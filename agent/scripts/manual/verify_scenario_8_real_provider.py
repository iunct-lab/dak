import requests
import json
import sys

PROVIDER_URL = "http://localhost:8002/mcp" # Agent Provider MCP endpoint

def test_premium_service_payment_required():
    print("Testing Premium Service Payment Requirement...")
    
    # Construct JSON-RPC request for 'premium_service' tool
    # Note: The tool name might be namespaced or just 'perform_premium_analysis'
    # We need to list tools first to be sure
    
    # 1. List Tools
    list_req = {
        "jsonrpc": "2.0",
        "method": "tools/list",
        "id": 1
    }
    try:
        res = requests.post(PROVIDER_URL, json=list_req).json()
        tools = res.get('result', {}).get('tools', [])
        tool_name = next((t['name'] for t in tools if 'premium' in t['name']), None)
        
        if not tool_name:
            print("ERROR: Premium service tool not found!")
            sys.exit(1)
            
        print(f"Found tool: {tool_name}")
        
        # 2. Call Tool WITHOUT Payment
        call_req = {
            "jsonrpc": "2.0",
            "method": "tools/call",
            "params": {
                "name": tool_name,
                "arguments": {
                    "topic": "AI Future"
                }
            },
            "id": 2
        }
        
        print(f"Calling {tool_name} without payment...")
        res = requests.post(PROVIDER_URL, json=call_req).json()
        
        if 'error' in res:
            print(f"SUCCESS: Received expected error: {res['error']}")
            # Check if it's a PaymentRequiredError (custom error might be wrapped)
            # The MCP spec returns application errors in a specific way
            if "Payment of 10.0 SOL required" in str(res['error']):
                 print("Verified: Error message contains payment requirement.")
            else:
                 print(f"WARNING: Error message might not be specific: {res['error']}")
        else:
            # If result is successful, it FAILED to enforce payment
            print(f"FAILURE: Tool execution succeeded without payment! Result: {res.get('result')}")
            sys.exit(1)
            
    except Exception as e:
        print(f"Exception during test: {e}")
        sys.exit(1)

if __name__ == "__main__":
    test_premium_service_payment_required()
