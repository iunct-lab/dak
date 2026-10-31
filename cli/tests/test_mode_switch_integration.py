import os
import sys
import pytest

# Add cli directory to path (parent of tests)
sys.path.append(os.path.join(os.path.dirname(__file__), ".."))

try:
    # Try importing as part of src package
    from src.client import AgentClient
    from src.config import ConfigManager
except ImportError:
    # Fallback if running from different context
    print("Could not import src.client. Checking path...")
    print(sys.path)
    raise

@pytest.mark.integration
@pytest.mark.skipif(
    not os.getenv("DAK_AGENT_URL"),
    reason="integration test: set DAK_AGENT_URL to a running agent to enable",
)
def test_mode_switch_integration():
    """
    Integration test to verify mode switching.
    Requires a running agent (set DAK_AGENT_URL, e.g. http://localhost:8000).
    """
    # Ensure user is logged in
    cm = ConfigManager()
    if not cm.get_user():
        print("No user found. Setting temporary test user.")
        cm.set_user("test_user")

    client = AgentClient()
    
    print("\n--- Starting Mode Switch Integration Test ---")
    
    # Message 1
    print("\nSending Message 1...")
    try:
        response1 = client.run_task("Hello, who are you?")
        print(f"Response 1: {str(response1)[:100]}...")
    except Exception as e:
        pytest.fail(f"Error sending message 1: {e}")
    
    # Message 2
    print("\nSending Message 2...")
    try:
        response2 = client.run_task("What tools do you have?")
        print(f"Response 2: {str(response2)[:100]}...")
    except Exception as e:
        pytest.fail(f"Error sending message 2: {e}")
    
    # Message 3 (Should trigger switch before or during this)
    print("\nSending Message 3 (Should trigger switch)...")
    try:
        response3 = client.run_task("Tell me a joke.")
        print(f"Response 3: {str(response3)[:100]}...")
    except Exception as e:
        pytest.fail(f"Error sending message 3: {e}")

    print("\n--- Test Complete ---")

if __name__ == "__main__":
    # Allow running as a script
    test_mode_switch_integration()
