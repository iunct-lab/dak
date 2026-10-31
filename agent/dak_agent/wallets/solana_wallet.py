"""
Solana Wallet Manager for AP2/x402 protocol.
Handles Solana keypair management, wSOL wrapping, and transactions.
"""
import os
import logging
from typing import Optional
from .base_wallet import BaseWalletManager

logger = logging.getLogger(__name__)

# Check if Solana dependencies are available
try:
    from solana.rpc.api import Client as SolanaClient
    from solana.rpc.commitment import Confirmed
    from solders.keypair import Keypair
    from solders.pubkey import Pubkey
    from solders.system_program import TransferParams, transfer
    from solders.transaction import Transaction
    from solders.message import Message
    from solders.hash import Hash
    SOLANA_AVAILABLE = True
except ImportError:
    SOLANA_AVAILABLE = False
    logger.warning("Solana SDK not available. Install with: pip install solana solders")


def keypair_from_secret(value: str) -> "Keypair":
    """SOLANA_PRIVATE_KEY の値（JSON 配列か base58）から Keypair を作る。"""
    if value.startswith("["):
        import json
        return Keypair.from_bytes(bytes(json.loads(value)))
    return Keypair.from_base58_string(value)


class SolanaWalletManager(BaseWalletManager):
    """
    Manages the agent's Solana wallet for AP2/x402 payments.
    Supports SOL and wSOL (wrapped SOL) transactions.
    """
    
    
    # Network RPC URLs
    DEVNET_RPC = "https://api.devnet.solana.com"
    MAINNET_RPC = "https://api.mainnet-beta.solana.com"
    
    def __init__(self, network: str = "devnet"):
        """
        Initialize Solana wallet manager.
        
        Args:
            network: "devnet", "mainnet", or custom RPC URL
        """
        self.network = network
        # FORCE MOCK MODE for demo stability if env var not set
        self.use_mock = os.getenv("SOLANA_USE_MOCK", "true").lower() == "true"
        
        if self.use_mock:
            logger.info("SolanaWalletManager running in MOCK MODE")
            self.client = None
            self.keypair = None
            self._mock_balance = 1000.0  # 1000 SOL mock balance for demo
            logger.info(f"Mock balance set to {self._mock_balance} SOL")
            return
            
        if not SOLANA_AVAILABLE:
            raise ImportError("Solana SDK not installed. Run: pip install solana solders")
        
        # Set RPC URL
        if network == "devnet":
            self.rpc_url = os.getenv("SOLANA_RPC_URL", self.DEVNET_RPC)
        elif network == "mainnet":
            self.rpc_url = os.getenv("SOLANA_RPC_URL", self.MAINNET_RPC)
        else:
            self.rpc_url = network
            
        self.client = SolanaClient(self.rpc_url)
        
        # Load or generate keypair
        private_key_str = os.getenv("SOLANA_PRIVATE_KEY")
        if private_key_str:
            try:
                self.keypair = keypair_from_secret(private_key_str)
                logger.info(f"Solana wallet initialized. Address: {self.get_address()}")
            except Exception as e:
                logger.error(f"Failed to load Solana private key: {e}")
                self.keypair = None
        else:
            logger.warning("SOLANA_PRIVATE_KEY not set. Wallet functionality limited.")
            self.keypair = None
    
    def get_address(self) -> str:
        """Get the wallet's public address."""
        if self.use_mock:
            return "MockSoLAddress1111111111111111111111111111111"
        if self.keypair:
            return str(self.keypair.pubkey())
        return "Unknown"
    
    def get_balance(self) -> float:
        """Get SOL balance in the wallet."""
        if self.use_mock:
            return self._mock_balance
            
        if not self.keypair or not self.client:
            return 0.0
            
        try:
            response = self.client.get_balance(self.keypair.pubkey(), commitment=Confirmed)
            if response.value is not None:
                # Convert lamports to SOL (1 SOL = 1e9 lamports)
                return response.value / 1e9
            return 0.0
        except Exception as e:
            logger.error(f"Error fetching Solana balance: {e}")
            return 0.0
    
    def send_transaction(self, recipient_address: str, amount: float, message: str = "") -> str:
        """
        Send SOL to a recipient.
        
        Args:
            recipient_address: Recipient's public key (base58)
            amount: Amount in SOL
            message: Optional memo (not fully implemented in this simplified version)
            
        Returns:
            Transaction signature (hash) or error message
        """
        if self.use_mock:
            self._mock_balance -= amount
            tx_hash = f"MockTx_{int(amount * 1e9)}_{recipient_address[:8]}"
            logger.info(f"[MOCK] Sent {amount} SOL to {recipient_address}. TxHash: {tx_hash}")
            return tx_hash
            
        if not self.keypair or not self.client:
            return "Error: Wallet not initialized"
            
        try:
            recipient_pubkey = Pubkey.from_string(recipient_address)
            lamports = int(amount * 1e9)
            
            # Get recent blockhash
            blockhash_response = self.client.get_latest_blockhash(commitment=Confirmed)
            recent_blockhash = blockhash_response.value.blockhash
            
            # Create transfer instruction
            transfer_ix = transfer(
                TransferParams(
                    from_pubkey=self.keypair.pubkey(),
                    to_pubkey=recipient_pubkey,
                    lamports=lamports
                )
            )
            
            # Create and sign transaction
            msg = Message.new_with_blockhash(
                [transfer_ix],
                self.keypair.pubkey(),
                recent_blockhash
            )
            tx = Transaction.new_unsigned(msg)
            tx.sign([self.keypair], recent_blockhash)
            
            # Send transaction
            response = self.client.send_transaction(tx)
            tx_signature = str(response.value)
            
            logger.info(f"Sent {amount} SOL to {recipient_address}. TxHash: {tx_signature}")
            return tx_signature
            
        except Exception as e:
            error_msg = f"Transaction failed: {e}"
            logger.error(error_msg)
            return f"Error: {e}"
    
    def verify_transaction(self, tx_hash: str, expected_recipient: str, expected_amount: float) -> bool:
        """
        Verify a transaction was confirmed and matches expected details.
        """
        if self.use_mock:
            # In mock mode, we only accept hashes starting with "MockTx"
            if not tx_hash.startswith("MockTx"):
                logger.warning(f"[MOCK] Verification failed for invalid hash: {tx_hash}")
                return False
            logger.info(f"[MOCK] Verified transaction {tx_hash}")
            return True
            
        if not self.client:
            return False
            
        try:
            from solders.signature import Signature
            sig = Signature.from_string(tx_hash)
            
            response = self.client.get_transaction(
                sig, encoding="json", commitment=Confirmed, max_supported_transaction_version=0
            )
            if response.value is None:
                logger.warning(f"Transaction not found: {tx_hash}")
                return False

            received = _received_lamports(response.value, expected_recipient)
            if received is None or received <= 0:
                logger.warning(f"Transaction {tx_hash} failed or did not credit {expected_recipient}")
                return False
            expected_lamports = int(expected_amount * 1e9)
            if received < expected_lamports:
                logger.warning(f"Transaction {tx_hash} paid {received} lamports, expected {expected_lamports}")
                return False

            logger.info(f"Transaction {tx_hash} confirmed")
            return True
            
        except Exception as e:
            logger.error(f"Error verifying transaction: {e}")
            return False

def _received_lamports(tx, recipient: str) -> Optional[int]:
    """
    Lamports the recipient's balance grew by in a confirmed transaction
    (``get_transaction(...).value``). None if the transaction failed or
    the recipient is not one of its accounts.
    """
    meta = tx.transaction.meta
    if meta is None or meta.err is not None:
        return None
    keys = [str(getattr(key, "pubkey", key)) for key in tx.transaction.transaction.message.account_keys]
    if recipient not in keys:
        return None
    i = keys.index(recipient)
    return meta.post_balances[i] - meta.pre_balances[i]

def get_solana_wallet_manager() -> SolanaWalletManager:
    """Factory function to get a SolanaWalletManager instance."""
    network = os.getenv("SOLANA_NETWORK", "devnet")
    return SolanaWalletManager(network=network)
