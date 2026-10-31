import unittest
from unittest.mock import MagicMock, patch
import os
import sys

# Add parent directory to path to import modules
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dak_agent.wallets.solana_wallet import SolanaWalletManager, keypair_from_secret

class TestSolanaWalletManager(unittest.TestCase):
    def setUp(self):
        # Force mock mode for testing
        self.patcher = patch.dict(os.environ, {"SOLANA_USE_MOCK": "true"})
        self.patcher.start()
        self.wallet = SolanaWalletManager()

    def tearDown(self):
        self.patcher.stop()

    def test_initialization_mock(self):
        self.assertTrue(self.wallet.use_mock)
        self.assertEqual(self.wallet.get_balance(), 1000.0)

    def test_get_address(self):
        address = self.wallet.get_address()
        self.assertTrue(address.startswith("MockSoL"))

    def test_send_transaction_mock(self):
        initial_balance = self.wallet.get_balance()
        recipient = "RecipientAddress123"
        amount = 10.0
        
        tx_hash = self.wallet.send_transaction(recipient, amount)
        
        self.assertTrue(tx_hash.startswith("MockTx_"))
        self.assertEqual(self.wallet.get_balance(), initial_balance - amount)

    def test_verify_transaction_mock(self):
        tx_hash = "MockTx_123"
        self.assertTrue(self.wallet.verify_transaction(tx_hash, "any", 1.0))


class TestKeypairFromSecret(unittest.TestCase):
    def test_base58_and_json_array(self):
        import json
        from solders.keypair import Keypair

        keypair = Keypair()  # テストの実行時に作る使い捨ての鍵
        self.assertEqual(keypair_from_secret(str(keypair)).pubkey(), keypair.pubkey())
        self.assertEqual(keypair_from_secret(json.dumps(list(bytes(keypair)))).pubkey(), keypair.pubkey())


def _tx(err=None, keys=None, pre=None, post=None):
    """偽の get_transaction の応答。RPC の json を solders に読ませ、本物と同じ型にする。"""
    import json
    from solders.rpc.responses import GetTransactionResp

    system = "11111111111111111111111111111111"
    keys = keys if keys is not None else [PAYER, RECIPIENT, system]
    raw = {
        "jsonrpc": "2.0",
        "id": 1,
        "result": {
            "slot": 1,
            "blockTime": None,
            "transaction": {
                "signatures": [SIG],
                "message": {
                    "accountKeys": keys,
                    "header": {"numRequiredSignatures": 1, "numReadonlySignedAccounts": 0, "numReadonlyUnsignedAccounts": 1},
                    "recentBlockhash": system,
                    "instructions": [],
                },
            },
            "meta": {
                "err": err,
                "status": {"Err": err} if err else {"Ok": None},
                "fee": 5000,
                "preBalances": pre if pre is not None else [2_000_000_000, 0, 1],
                "postBalances": post if post is not None else [999_995_000, 1_000_000_000, 1],
                "innerInstructions": [],
                "logMessages": [],
                "preTokenBalances": [],
                "postTokenBalances": [],
                "rewards": [],
                "loadedAddresses": {"writable": [], "readonly": []},
            },
        },
    }
    return GetTransactionResp.from_json(json.dumps(raw))


def _pubkey():
    from solders.pubkey import Pubkey

    return str(Pubkey.new_unique())


PAYER = _pubkey()
RECIPIENT = _pubkey()
SIG = "1" * 64  # Signature.from_string に通る署名（Signature.default()）


class TestVerifyTransactionReal(unittest.TestCase):
    """実モードの verify_transaction。実モードの wallet は __init__ を通さずに作り、RPC を偽物にする。"""

    def setUp(self):
        self.wallet = SolanaWalletManager.__new__(SolanaWalletManager)
        self.wallet.use_mock = False
        self.wallet.client = MagicMock()

    def verify(self, resp, amount=1.0):
        self.wallet.client.get_transaction.return_value = resp
        return self.wallet.verify_transaction(SIG, RECIPIENT, amount)

    def test_accepts_successful_transfer(self):
        self.assertTrue(self.verify(_tx()))

    def test_rejects_failed_transaction(self):
        self.assertFalse(self.verify(_tx(err={"InstructionError": [0, {"Custom": 1}]})))

    def test_rejects_when_recipient_missing(self):
        self.assertFalse(self.verify(_tx(keys=[PAYER, _pubkey(), "11111111111111111111111111111111"])))

    def test_rejects_when_recipient_not_credited(self):
        self.assertFalse(self.verify(_tx(pre=[2_000_000_000, 5, 1], post=[1_999_995_000, 5, 1]), amount=0))

    def test_amount_exact_short_and_over(self):
        def credited(lamports):
            return _tx(pre=[2_000_000_000, 0, 1], post=[1_000_000_000, lamports, 1])

        self.assertTrue(self.verify(credited(1_000_000_000)))
        self.assertFalse(self.verify(credited(999_999_999)))
        self.assertTrue(self.verify(credited(1_000_000_001)))

    def test_rejects_when_not_found(self):
        self.assertFalse(self.verify(MagicMock(value=None)))

    def test_rejects_on_rpc_error(self):
        self.wallet.client.get_transaction.side_effect = RuntimeError("rpc down")
        self.assertFalse(self.wallet.verify_transaction(SIG, RECIPIENT, 1.0))


if __name__ == '__main__':
    unittest.main()
