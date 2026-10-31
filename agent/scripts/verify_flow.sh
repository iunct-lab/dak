#!/bin/bash

BASE_URL="http://127.0.0.1:8001"
USERNAME="test_user"
SESSION_ID="session_$(uuidgen)"

echo "Creating session $SESSION_ID..."
curl -s -X POST "$BASE_URL/apps/dak_agent/users/$USERNAME/sessions" \
  -H "Content-Type: application/json" \
  -H "X-User-ID: $USERNAME" \
  -H "X-Session-ID: $SESSION_ID" \
  -d '{}' > /dev/null

echo "Session created."

echo "Sending initial request..."
RESPONSE=$(curl -s -X POST "$BASE_URL/run" \
  -H "Content-Type: application/json" \
  -H "X-User-ID: $USERNAME" \
  -H "X-Session-ID: $SESSION_ID" \
  -d '{
    "app_name": "dak_agent",
    "user_id": "'"$USERNAME"'",
    "session_id": "'"$SESSION_ID"'",
    "new_message": {
        "parts": [{"text": "Ask agent_provider to perform premium analysis on AI technology. Pay if required."}]
    }
  }')

echo "Response received."
echo "$RESPONSE" | grep -o '"text": "[^"]*"' | cut -d'"' -f4

# Check for success or auth request
if echo "$RESPONSE" | grep -q "PREMIUM ANALYSIS REPORT"; then
    echo "SUCCESS: Premium analysis received autonomously!"
    exit 0
fi

if echo "$RESPONSE" | grep -q -i "authorize\|confirm\|payment required"; then
    echo "Agent asked for authorization. Sending 'Yes'..."
    RESPONSE_2=$(curl -s -X POST "$BASE_URL/run" \
      -H "Content-Type: application/json" \
      -H "X-User-ID: $USERNAME" \
      -H "X-Session-ID: $SESSION_ID" \
      -d '{
        "app_name": "dak_agent",
        "user_id": "'"$USERNAME"'",
        "session_id": "'"$SESSION_ID"'",
        "new_message": {
            "parts": [{"text": "Yes, I authorize the payment of 10 SOL."}]
        }
      }')
      
    echo "Follow-up Response:"
    echo "$RESPONSE_2" | grep -o '"text": "[^"]*"' | cut -d'"' -f4
    
    if echo "$RESPONSE_2" | grep -q "PREMIUM ANALYSIS REPORT"; then
        echo "SUCCESS: Premium analysis received after authorization!"
    else
        echo "FAILED: Did not receive premium analysis."
    fi
else
    echo "Unknown state."
fi
