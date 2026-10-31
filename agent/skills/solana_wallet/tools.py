"""
Solana Wallet Tools for AP2/x402 protocol.
Provides tools for agents to check balance and send SOL payments.
"""
import logging
import os
from typing import Optional
from dak_agent.wallets.solana_wallet import get_solana_wallet_manager, SolanaWalletManager

logger = logging.getLogger(__name__)

# Singleton wallet manager
_wallet_manager: Optional[SolanaWalletManager] = None


def _get_wallet() -> SolanaWalletManager:
    """Get or create the wallet manager singleton."""
    global _wallet_manager
    if _wallet_manager is None:
        _wallet_manager = get_solana_wallet_manager()
    return _wallet_manager


def check_solana_balance() -> str:
    """
    Check the current SOL balance in the agent's Solana wallet.
    
    Returns:
        A string describing the current balance.
    """
    wallet = _get_wallet()
    balance = wallet.get_balance()
    address = wallet.get_address()
    
    logger.info(f"check_solana_balance called: mock={wallet.use_mock}, balance={balance}")
    
    return f"""
## Solana Wallet Balance

**Address**: `{address}`
**Balance**: {balance:.6f} SOL
**Network**: {wallet.network}
"""


def get_solana_address() -> str:
    """
    Get the agent's Solana wallet public address.
    
    Returns:
        The wallet's public address (base58 format).
    """
    wallet = _get_wallet()
    return wallet.get_address()


def send_sol_payment(recipient: str, amount: float, memo: str = "") -> str:
    """
    Send SOL to a recipient address.
    
    IMPORTANT: This tool should only be used when the LLM has decided to make a payment
    based on user consent or a valid Intent Mandate. Do NOT auto-pay without authorization.
    
    Args:
        recipient: The recipient's Solana public address (base58 format).
        amount: The amount of SOL to send.
        memo: Optional memo for the transaction.
        
    Returns:
        Transaction result with signature/hash or error message.
    """
    wallet = _get_wallet()
    
    # Check balance first
    balance = wallet.get_balance()
    if balance < amount:
        return f"Error: Insufficient balance. Current: {balance:.6f} SOL, Required: {amount:.6f} SOL"
    
    # Execute transfer
    result = wallet.send_transaction(recipient, amount, memo)
    
    if result.startswith("Error"):
        return result
    
    # Get updated balance
    new_balance = wallet.get_balance()
    
    return f"""
## SOL Payment Sent

**Recipient**: `{recipient}`
**Amount**: {amount:.6f} SOL
**Transaction**: `{result}`
**Remaining Balance**: {new_balance:.6f} SOL

**NEXT STEP REQUIRED**:
You have successfully paid. Now you MUST retry the original tool call that required this payment.
Include the argument `payment_hash="{result}"` in your retry.
DO NOT STOP HERE. COMPLETE THE ORIGINAL TASK.
"""


def verify_sol_payment(tx_signature: str, expected_recipient: str, expected_amount: float) -> str:
    """
    Verify that a SOL payment was successfully confirmed.
    
    Args:
        tx_signature: The transaction signature to verify.
        expected_recipient: The expected recipient address.
        expected_amount: The expected payment amount in SOL.
        
    Returns:
        Verification result.
    """
    wallet = _get_wallet()
    is_valid = wallet.verify_transaction(tx_signature, expected_recipient, expected_amount)
    
    if is_valid:
        return f"✅ Transaction `{tx_signature}` verified and confirmed."
    else:
        return f"❌ Transaction `{tx_signature}` could not be verified."


# List of tools to export
SOLANA_WALLET_TOOLS = [
    check_solana_balance,
    get_solana_address,
    send_sol_payment,
    verify_sol_payment,
]
