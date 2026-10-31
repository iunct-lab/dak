import os
import sys
import logging
from unittest.mock import MagicMock

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Mock environment
os.environ['SOLANA_USE_MOCK'] = 'true'
os.environ['ENABLE_AP2_PROTOCOL'] = 'true'

# Add agent directory to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../../..")))

from dak_agent.decorators import PaidToolWrapper
from dak_agent.errors import PaymentRequiredError
from dak_agent.handlers.payment_handler import PaymentHandler
from skills.premium_service.tools import perform_premium_analysis

def run_a2a_simulation():
    print("=== Scenario 4: A2A Payment Flow Simulation ===")
    
    payment_handler = PaymentHandler()
    
    # 1. Provider receives request (No Payment)
    print("\n[Step 1] Provider receives request (No Payment)...")
    try:
        perform_premium_analysis(topic="A2A Test")
        print("❌ FAILED: Expected PaymentRequiredError.")
        return
    except PaymentRequiredError as e:
        print(f"✅ SUCCESS: Caught PaymentRequiredError: {e}")
        
        # 2. Provider formats error for Consumer
        print("\n[Step 2] Provider formats error for Consumer...")
        formatted_error = payment_handler.format_payment_error("perform_premium_analysis", e)
        error_msg = formatted_error["error"]
        print(f"--- Formatted Message ---\n{error_msg}\n-------------------------")
        
        # Verify the message contains the instruction to request payment from user
        if "You CANNOT pay this yourself" in error_msg and "Payment Required:" in error_msg:
            print("✅ SUCCESS: Error message contains correct A2A instructions.")
        else:
            print("❌ FAILED: Error message missing A2A instructions.")
            return

    # 3. Consumer pays (Simulated)
    print("\n[Step 3] Consumer pays (Simulated)...")
    payment_hash = "MockTx_A2A_Payment_123"
    print(f"Consumer obtained payment hash: {payment_hash}")
    
    # 4. Consumer retries with hash
    print("\n[Step 4] Consumer retries with hash...")
    try:
        result = perform_premium_analysis(topic="A2A Test", payment_hash=payment_hash)
        print(f"✅ SUCCESS: Provider accepted payment and returned result:\n{result}")
    except Exception as e:
        print(f"❌ FAILED: Provider rejected valid payment: {e}")

if __name__ == "__main__":
    run_a2a_simulation()
