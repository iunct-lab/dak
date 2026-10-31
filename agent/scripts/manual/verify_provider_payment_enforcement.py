import requests
import json
import sys
import os

# Agent Provider URL (Direct A2A/MCP access)
# The provider is running on port 8002
PROVIDER_URL = "http://localhost:8002/mcp"

def test_provider_enforcement():
    print(f"Testing Provider Enforcement at {PROVIDER_URL}...")
    
    # 1. List Tools to find the premium service
    list_payload = {
        "jsonrpc": "2.0",
        "method": "tools/list",
        "id": 1
    }
    
    try:
        res = requests.post(PROVIDER_URL, json=list_payload)
        res.raise_for_status()
        data = res.json()
        
        tools = data.get('result', {}).get('tools', [])
        premium_tool = next((t for t in tools if 'premium' in t['name']), None)
        
        if not premium_tool:
            print("ERROR: Premium service tool not found in provider!")
            print(f"Available tools: {[t['name'] for t in tools]}")
            sys.exit(1)
            
        tool_name = premium_tool['name']
        print(f"Found premium tool: {tool_name}")
        
        # 2. Call Tool WITHOUT Payment Hash
        call_payload = {
            "jsonrpc": "2.0",
            "method": "tools/call",
            "params": {
                "name": tool_name,
                "arguments": {
                    "topic": "Testing Enforcement"
                }
            },
            "id": 2
        }
        
        print(f"Calling {tool_name} without payment hash...")
        call_res = requests.post(PROVIDER_URL, json=call_payload)
        call_data = call_res.json()
        
        # We EXPECT an error or a content that describes the error (depending on how MCP handles exceptions)
        # The ADK usually catches exceptions and returns them as tool errors or raises JSON-RPC errors.
        
        if 'error' in call_data:
            error_msg = str(call_data['error'])
            print(f"Received JSON-RPC Error: {error_msg}")
            if "Payment" in error_msg and "required" in error_msg:
                print("SUCCESS: Payment requirement enforced (JSON-RPC Error).")
                return
        
        # Check result for error message (if tool caught it and returned text)
        result = call_data.get('result', {})
        content = result.get('content', [])
        
        # In MCP, tool errors might be returned as isError: true
        if result.get('isError'):
            text_content = "".join([c.get('text', '') for c in content if c.get('type') == 'text'])
            print(f"Received Tool Error: {text_content}")
            if "Payment" in text_content and "required" in text_content:
                print("SUCCESS: Payment requirement enforced (Tool Error).")
                return
                
        # If we got here, it might have succeeded
        print(f"FAILURE: Tool execution seemed to succeed! Result: {result}")
        sys.exit(1)

    except Exception as e:
        print(f"Exception: {e}")
        sys.exit(1)

if __name__ == "__main__":
    test_provider_enforcement()
