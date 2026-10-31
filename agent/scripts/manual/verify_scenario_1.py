import os
import sys
import logging

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
from skills.premium_service.tools import perform_premium_analysis
from skills.solana_wallet.tools import send_sol_payment

def run_verification():
    print("=== Scenario 1: CLI/Script Verification ===")
    
    # 1. Try calling premium tool without payment
    print("\n[Step 1] Calling perform_premium_analysis without payment...")
    try:
        perform_premium_analysis(topic="Decentralized Agents")
        print("❌ FAILED: Expected PaymentRequiredError, but got success.")
    except PaymentRequiredError as e:
        print(f"✅ SUCCESS: Caught PaymentRequiredError: {e}")
        print(f"   Price: {e.price} {e.currency}")
        print(f"   Address: {e.address}")
        
        # 2. Make payment
        print("\n[Step 2] Making payment...")
        payment_result = send_sol_payment(recipient=e.address, amount=e.price)
        print(f"   Payment Result: {payment_result}")
        
        # Extract fake hash (simple parsing for mock)
        # Mock result format: ... Transaction: `MockTx_...` ...
        import re
        match = re.search(r"Transaction\*\*: `([^`]+)`", payment_result)
        if match:
            tx_hash = match.group(1)
            print(f"   Tx Hash: {tx_hash}")
            
            # 3. Retry with payment hash
            print("\n[Step 3] Retrying tool with payment_hash...")
            try:
                result = perform_premium_analysis(topic="Decentralized Agents", payment_hash=tx_hash)
                print("✅ SUCCESS: Tool executed successfully.")
                print("   Result Summary:")
                print("\n".join(result.split("\n")[:5])) # Print first few lines
            except Exception as retry_e:
                print(f"❌ FAILED: Retry failed: {retry_e}")
        else:
            print("❌ FAILED: Could not extract transaction hash from payment result.")

if __name__ == "__main__":
    run_verification()
