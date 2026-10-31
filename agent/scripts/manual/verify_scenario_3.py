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
    print("=== Scenario 3: Payment Verification Logic ===")
    
    # 1. Try calling premium tool with INVALID hash
    print("\n[Step 1] Calling perform_premium_analysis with INVALID hash...")
    try:
        perform_premium_analysis(topic="Invalid Hash Test", payment_hash="invalid_hash_123")
        print("❌ FAILED: Expected PaymentRequiredError (Verification Failed), but got success.")
    except PaymentRequiredError as e:
        if "verification failed" in str(e):
            print(f"✅ SUCCESS: Caught PaymentRequiredError as expected: {e}")
        else:
            print(f"❌ FAILED: Caught unexpected error message: {e}")

    # 2. Try calling premium tool with VALID hash (Mock)
    print("\n[Step 2] Calling perform_premium_analysis with VALID hash...")
    
    # Generate a valid mock hash by sending payment
    # Note: In mock mode, verify_transaction always returns True for any hash if use_mock is True.
    # However, verify_transaction checks if client is available if not mock.
    # Since we set SOLANA_USE_MOCK=true, verify_transaction should return True.
    # Wait, step 1 failed? If mock returns True always, step 1 should have succeeded?
    # Let's check SolanaWalletManager.verify_transaction implementation.
    # It says: if self.use_mock: return True.
    # So Step 1 might actually SUCCEED in mock mode if we don't simulate failure.
    # But wait, verify_transaction takes tx_hash.
    
    # Let's run and see. If Step 1 succeeds, it means Mock Verification is too loose.
    # We might need to adjust Mock Verification to fail for specific "invalid" strings if we want to test it.
    # But for now, let's see behavior.
    
    try:
        # We use a hash that looks like a mock hash
        valid_hash = "MockTx_12345_Valid" 
        result = perform_premium_analysis(topic="Valid Hash Test", payment_hash=valid_hash)
        print("✅ SUCCESS: Tool executed successfully with valid hash.")
    except Exception as e:
        print(f"❌ FAILED: Tool failed with valid hash: {e}")

if __name__ == "__main__":
    run_verification()
