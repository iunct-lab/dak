import pytest
from unittest.mock import MagicMock, patch
from dak_agent.adaptive_agent import AdaptiveAgent
from dak_agent.errors import PaymentRequiredError

class TestAp2Protocol:
    @pytest.fixture
    def agent(self):
        # Mock dependencies to avoid full initialization
        with patch('dak_agent.adaptive_agent.ModeManager'), \
             patch('dak_agent.adaptive_agent.SkillRegistry'):

            agent = AdaptiveAgent(model="test-model", name="test_agent", instruction="test-instruction", tools=[])
            # Manually set private attributes that would be set in __init__
            agent._enable_ap2 = True
            agent.tools = []
            
            # Initialize PaymentHandler mock
            agent._payment_handler = MagicMock()
            agent._payment_handler.format_payment_error.return_value = {
                "error": "**Payment Required**\nAmount**: 10.0\nRecipient**: TestAddress\nCurrent Wallet Status: Mock Balance: 1000.0 SOL"
            }
            
            return agent

    def test_payment_required_handling(self, agent):
        """Test that PaymentRequiredError triggers PaymentHandler."""
        # Setup the error
        error = PaymentRequiredError(price=10.0, address="TestAddress", message="Service fee")
        
        # Call _on_tool_error
        result = agent._on_tool_error(tool=MagicMock(), args={}, tool_context=None, error=error)
        
        # Verify result
        assert "error" in result
        error_msg = result["error"]
        
        # Check that payment details are present (as formatted by mock PaymentHandler)
        assert "Amount**: 10.0" in error_msg
        assert "Recipient**: TestAddress" in error_msg
        
        # Verify PaymentHandler was called
        agent._payment_handler.format_payment_error.assert_called_once()

    def test_payment_required_handler_missing(self, agent):
        """Test handling when PaymentHandler is missing (AP2 disabled or init failed)."""
        error = PaymentRequiredError(price=10.0, address="TestAddress", message="Payment required")
        agent._payment_handler = None # Simulate missing handler
        
        result = agent._on_tool_error(tool=MagicMock(), args={}, tool_context=None, error=error)
        
        assert "error" in result
        error_msg = result["error"]
        
        # Should fallback to standard error message
        assert "Tool '<MagicMock name='mock.name' id=" in error_msg or "Tool 'unknown' failed" in error_msg
