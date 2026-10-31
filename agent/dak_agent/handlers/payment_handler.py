import logging
from typing import Dict, Optional, Any

logger = logging.getLogger(__name__)

class PaymentHandler:
    """
    Handles payment-related errors and interactions.
    Instead of auto-paying, it formats the error into a structured observation
    that allows the LLM to make an autonomous decision.
    """

    def __init__(self):
        pass

    def format_payment_error(self, tool_name: str, error: Any) -> Dict[str, str]:
        """
        Formats a PaymentRequiredError into a structured message for the LLM.
        
        Args:
            tool_name: Name of the tool that raised the error.
            error: The PaymentRequiredError exception (must have price, address, message attributes).
            
        Returns:
            Dict with "error" key containing the formatted message.
        """
        price = getattr(error, 'price', 'Unknown')
        address = getattr(error, 'address', 'Unknown')
        reason = getattr(error, 'message', 'Service fee')
        currency = getattr(error, 'currency', 'SOL')

        # Construct the observation
        # We deliberately do NOT check the balance here. The LLM should decide if it needs to check.
        payment_info = f"""
## Payment Required

The tool `{tool_name}` requires payment before execution.

**Payment Details:**
- **Amount**: {price} {currency}
- **Recipient**: {address}
- **Reason**: {reason}

**Action Required:**
This tool cannot be executed without payment.
If you wish to proceed, you must:
1. (Optional) Check your balance using `check_solana_balance` if you are unsure.
2. Pay the required amount using `send_sol_payment(recipient="{address}", amount={price})`.
3. Retry the original tool call with the `payment_hash` argument returned by the payment tool.

**Decision**:
You CANNOT pay this yourself. You must request payment from the user (or calling agent).
Return the following message EXACTLY to the user:
"Payment Required: {price} {currency} to {address}. Reason: {reason}"
"""
        logger.info(f"Formatted payment request for {tool_name}: {price} {currency}")
        return {"error": payment_info}
