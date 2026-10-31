import os
import sys

# Add cli root to path
sys.path.append(os.path.join(os.path.dirname(__file__), ".."))

from src.client import AgentClient

def test_mode_switch():
    client = AgentClient()
    
    print("--- Starting Mode Switch Test ---")
    
    # Message 1
    print("\nSending Message 1...")
    try:
        response1 = client.run_task("Hello, who are you?")
        print(f"Response 1: {str(response1)[:100]}...")
    except Exception as e:
        print(f"Error sending message 1: {e}")
    
    # Message 2
    print("\nSending Message 2...")
    try:
        response2 = client.run_task("What tools do you have?")
        print(f"Response 2: {str(response2)[:100]}...")
    except Exception as e:
        print(f"Error sending message 2: {e}")
    
    # Message 3 (Should trigger switch before or during this)
    print("\nSending Message 3 (Should trigger switch)...")
    try:
        response3 = client.run_task("Tell me a joke.")
        print(f"Response 3: {str(response3)[:100]}...")
    except Exception as e:
        print(f"Error sending message 3: {e}")

    print("\n--- Test Complete ---")

if __name__ == "__main__":
    test_mode_switch()
