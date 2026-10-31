import unittest
from unittest.mock import MagicMock
import sys
import os

# Add parent directory to path to import modules
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dak_agent.handlers.payment_handler import PaymentHandler
from dak_agent.errors import PaymentRequiredError

class TestPaymentHandler(unittest.TestCase):
    def setUp(self):
        self.handler = PaymentHandler()

    def test_format_payment_error(self):
        # Create a mock PaymentRequiredError
        error = PaymentRequiredError(
            price=1.5,
            address="RecipientAddress123",
            message="Test Service Fee",
            currency="SOL"
        )
        
        result = self.handler.format_payment_error("test_tool", error)
        
        self.assertIn("error", result)
        error_msg = result["error"]
        
        # Verify key information is present
        self.assertIn("1.5 SOL", error_msg)
        self.assertIn("RecipientAddress123", error_msg)
        self.assertIn("Test Service Fee", error_msg)
        self.assertIn("send_sol_payment", error_msg)
        
        # Verify NO auto-payment logic (no balance check in output unless requested)
        # The handler itself shouldn't check balance, so we don't expect "Current Wallet Status" 
        # unless we mocked the wallet to return it, but the handler logic we wrote 
        # explicitly DOES NOT check balance.
        self.assertNotIn("Current Wallet Status", error_msg)

if __name__ == '__main__':
    unittest.main()
