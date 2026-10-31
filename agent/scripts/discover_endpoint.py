import requests
import json
import uuid
import time

base_url = "http://localhost:8001"
user_id = "test-user"

# 1. Create Session
session_url = f"{base_url}/apps/dak_agent/users/{user_id}/sessions"
print(f"Creating session at {session_url}...")
try:
    session_res = requests.post(session_url, json={}, timeout=10)
    print(f"Session Create Status: {session_res.status_code}")
    if session_res.status_code not in [200, 201]:
        print(f"Failed to create session: {session_res.text}")
        exit(1)
    
    session_data = session_res.json()
    session_id = session_data.get("id")
    print(f"Created Session ID: {session_id}")

    # 2. Run Chat
    run_url = f"{base_url}/run"
    payload = {
        "appName": "dak_agent",
        "userId": user_id,
        "sessionId": session_id,
        "newMessage": {
            "role": "user",
            "parts": [{"text": "Perform a premium analysis on 'The Future of AI'."}]
        }
    }

    print(f"Sending message to {run_url}...")
    response = requests.post(run_url, json=payload, timeout=60)
    print(f"Run Status: {response.status_code}")
    print(f"Response: {response.text}")

except Exception as e:
    print(f"Error: {e}")
