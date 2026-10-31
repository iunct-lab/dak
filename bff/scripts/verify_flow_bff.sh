#!/bin/bash

BFF_URL="http://localhost:3000/chat"
SESSION_ID="session_bff_test_$(uuidgen)"

echo "Sending initial request to BFF..."
RESPONSE=$(curl -s -X POST "$BFF_URL" \
  -F "prompt=Ask agent_provider to perform premium analysis on AI technology. Pay if required." \
  -F "session_id=$SESSION_ID")

echo "Response received."
echo "$RESPONSE"
# Extract the message content from the HTML
echo "$RESPONSE" | grep "message-content"

# Check for success or auth request
if echo "$RESPONSE" | grep -q "PREMIUM ANALYSIS REPORT"; then
    echo "SUCCESS: Premium analysis received autonomously!"
    exit 0
fi

if echo "$RESPONSE" | grep -q -i "authorize\|confirm\|payment required\|requires a payment"; then
    echo "Agent asked for authorization or reported payment required. Sending 'Yes'..."
    RESPONSE_2=$(curl -s -X POST "$BFF_URL" \
      -F "prompt=Yes, I authorize the payment of 10 SOL to DemoRecipientAddress123." \
      -F "session_id=$SESSION_ID")
      
    echo "Follow-up Response:"
    echo "$RESPONSE_2" | grep "message-content"
    
    if echo "$RESPONSE_2" | grep -q "PREMIUM ANALYSIS REPORT"; then
        echo "SUCCESS: Premium analysis received after authorization!"
    else
        echo "FAILED: Did not receive premium analysis."
    fi
else
    echo "Unknown state."
fi
