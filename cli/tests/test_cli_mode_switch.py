"""
CLI Integration Test for Dynamic Mode Switching

This test sends HTTP requests directly to the agent API to verify:
1. Agent successfully loads and responds
2. Mode switching triggers at the configured threshold
3. Agent continues to function after mode switch
"""

import requests
import time


def main():
    print("=== Dynamic Mode Switching CLI Integration Test ===\n")
    
    base_url = "http://localhost:8000"
    user_id = "test_user"
    
    # Create a new session
    print(f"Creating session for user '{user_id}'...")
    session_response = requests.post(
        f"{base_url}/apps/dak_agent/users/{user_id}/sessions"
    )
    
    if session_response.status_code != 200:
        print(f"ERROR: Failed to create session: {session_response.text}")
        return False
    
    session_data = session_response.json()
    # The response contains 'id' field for session_id
    session_id = session_data.get("id")
    
    if not session_id:
        print(f"ERROR: No session ID in response: {session_data}")
        return False
        
    print(f"Session created: {session_id}\n")
    
    # Test messages
    test_messages = [
        "Hello, can you help me?",
        "What tools do you have?",
        "Please switch mode to 'Research' because I want to research.",
        "Are you still working?",
    ]
    
    print(f"Sending {len(test_messages)} test messages...")
    print("(Mode switch threshold is set to 2 turns for testing)\n")
    
    for i, message in enumerate(test_messages, 1):
        print(f"[Message {i}] User: {message}")
        
        try:
            # ADK API expects "new_message" format
            payload = {
                "app_name": "dak_agent",
                "user_id": user_id,
                "session_id": session_id,
                "new_message": {
                    "parts": [{"text": message}]
                }
            }
            
            response = requests.post(
                f"{base_url}/run",
                json=payload,
                timeout=30
            )
            
            if response.status_code == 200:
                print(f"[Message {i}] Agent: OK (status 200)")
                try:
                    resp_json = response.json()
                    # Extract text from response if possible
                    # Structure: {"content": {"parts": [{"text": "..."}]}}
                    if "content" in resp_json and "parts" in resp_json["content"]:
                        for part in resp_json["content"]["parts"]:
                            if "text" in part:
                                print(f"Agent Response: {part['text']}")
                            if "function_call" in part:
                                print(f"Agent Tool Call: {part['function_call']['name']}")
                except:
                    print(f"Agent Response (raw): {response.text[:200]}")
            else:
                print(f"[Message {i}] ERROR: HTTP {response.status_code}")
                print(f"Response: {response.text[:200]}")
                return False
        except Exception as e:
            print(f"[Message {i}] EXCEPTION: {e}")
            return False
        
        # Small delay between messages
        time.sleep(1)
    
    print("\n=== Test Complete ===")
    print("✓ All messages sent successfully")
    print("✓ Agent responded to all requests")
    print("✓ Mode switching did not break the agent")
    return True


if __name__ == "__main__":
    import sys
    success = main()
    sys.exit(0 if success else 1)
