import sys
import os
import requests
import time
import json

# Add project root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from cli.src.client import AgentClient

def test_tool_discovery():
    print("=== Tool Discovery Integration Test ===")
    
    # AgentClient reads config from env or file. Ensure it points to localhost:8000
    # We can set env var if needed, but default is usually fine for local dev.
    client = AgentClient()
    # Manually override base_url because ConfigManager ignores env vars
    client.base_url = "http://127.0.0.1:8002"
    # Manually set username for testing
    client.username = "test_user_discovery"
    client.session_id = f"session_{client.username}_discovery_test"
    
    print(f"\nUsing session: {client.session_id}")
    
    # 1. Switch to a restricted mode first
    print("\n[Step 1] Force switch to 'File Operations' mode...")
    try:
        response = client.run_task(
            prompt="Please switch mode to 'File Operations' so I can read files. I only want file tools."
        )
        print(f"Agent Response: {response}")
    except Exception as e:
        print(f"Error in Step 1: {e}")

    # 2. Ask for tool list (should trigger switch_mode(request_tool_list=True))
    print("\n[Step 2] Asking for all available tools...")
    try:
        response = client.run_task(
            prompt="Actually, I changed my mind. Please use `switch_mode(request_tool_list=True)` to see what OTHER tools are available, then list them for me."
        )
        print(f"Agent Response: {response}")
        
        # Check response text
        # response is a dict or list of events. We need to extract text.
        response_text = str(response)
        
        if "deep_think" in response_text or "run_command" in response_text:
            print("SUCCESS: Agent successfully discovered and listed tools.")
        else:
            print("FAILURE: Agent did not list expected tools.")
            if "switch_mode" in response_text:
                 print("(It might have tried to switch, but failed to get the list)")
                 
    except Exception as e:
        print(f"Error in Step 2: {e}")

if __name__ == "__main__":
    try:
        test_tool_discovery()
    except Exception as e:
        print(f"Test failed with error: {e}")
        sys.exit(1)
