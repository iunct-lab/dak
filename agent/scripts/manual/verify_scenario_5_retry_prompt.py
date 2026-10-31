import os
import sys
import asyncio
import logging
from unittest.mock import MagicMock

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Mock environment
os.environ['SOLANA_USE_MOCK'] = 'true'
os.environ['ENABLE_AP2_PROTOCOL'] = 'true'
os.environ['GOOGLE_API_KEY'] = "fake_key" # Mocking, won't be used for real calls if we mock the client

# Add agent directory to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../../..")))

# from dak_agent.adaptive_agent import AdaptiveAgent
# from google.adk.models.llm_response import LlmResponse

async def run_retry_verification():
    print("=== Scenario 5: Retry Logic Verification ===")
    
    # 1. Setup Mock Agent
    # We need to mock the GenAI client to avoid real API calls, 
    # but we want to test the PROMPT influence. 
    # Actually, testing the LLM's reaction to a prompt requires a real LLM or a very sophisticated mock.
    # Since we can't easily mock the "Intelligence" to prove it *understands* the prompt without calling the API,
    # we might have to rely on the fact that we CHANGED the prompt.
    
    # However, we can verify that the TOOL returns the correct string.
    
    from skills.solana_wallet.tools import send_sol_payment
    
    print("\n[Step 1] Verifying send_sol_payment output format...")
    output = send_sol_payment("MockRecipient", 10.0)
    print(f"Tool Output:\n{output}")
    
    if "**NEXT STEP REQUIRED**" in output and "MUST retry" in output:
        print("✅ SUCCESS: Tool output contains strong retry directive.")
    else:
        print("❌ FAILED: Tool output missing directive.")
        return

    print("\n[Step 2] (Manual Verification) The prompt is now:")
    print("-" * 40)
    print(output)
    print("-" * 40)
    print("This prompt is designed to force the LLM to retry.")

if __name__ == "__main__":
    asyncio.run(run_retry_verification())
