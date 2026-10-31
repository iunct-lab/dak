import requests
import uuid
import json
import time
import sys

BASE_URL = "http://127.0.0.1:8001"
USERNAME = "test_user"
SESSION_ID = f"session_{uuid.uuid4()}"

HEADERS = {
    "Content-Type": "application/json",
    "X-User-ID": USERNAME,
    "X-Session-ID": SESSION_ID
}

def create_session():
    print(f"Creating session {SESSION_ID}...")
    url = f"{BASE_URL}/apps/dak_agent/users/{USERNAME}/sessions"
    try:
        resp = requests.post(url, json={}, headers=HEADERS, timeout=10)
        resp.raise_for_status()
        print("Session created.")
    except Exception as e:
        print(f"Failed to create session: {e}")
        if hasattr(e, 'response') and e.response:
            print(f"Response: {e.response.text}")
        sys.exit(1)

def send_message(text):
    print(f"\nSending message: '{text}'")
    url = f"{BASE_URL}/run"
    payload = {
        "app_name": "dak_agent",
        "user_id": USERNAME,
        "session_id": SESSION_ID,
        "new_message": {
            "parts": [{"text": text}]
        }
    }
    
    try:
        resp = requests.post(url, json=payload, headers=HEADERS, timeout=300)
        resp.raise_for_status()
        data = resp.json()
        
        response_text = ""
        # Parse response
        if isinstance(data, list):
            for event in data:
                parts = event.get("content", {}).get("parts", [])
                for part in parts:
                    if "text" in part:
                        print(f"Agent Response: {part['text']}")
                        response_text += part["text"]
        return response_text
    except Exception as e:
        print(f"Failed to send message: {e}")
        if hasattr(e, 'response') and e.response:
            print(f"Response: {e.response.text}")
        return ""

def main():
    create_session()
    
    # 1. Initial Request
    response = send_message("Ask agent_provider to perform premium analysis on AI technology. Pay if required.")
    
    # 2. Check for payment confirmation request or success
    if "PREMIUM ANALYSIS REPORT" in response:
        print("\nSUCCESS: Premium analysis received autonomously!")
    elif "authorize" in response.lower() or "confirm" in response.lower() or "payment required" in response.lower():
        print("\nAgent asked for authorization. Sending 'Yes'...")
        # Send authorization
        response = send_message("Yes, I authorize the payment of 10 SOL.")
        
        if "PREMIUM ANALYSIS REPORT" in response:
             print("\nSUCCESS: Premium analysis received after authorization!")
        else:
             print("\nFAILED: Did not receive premium analysis after authorization.")
    else:
        print("\nUnknown state. Checking logs might be needed.")
