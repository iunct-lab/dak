import google.adk.tools
print(f"google.adk.tools contents: {dir(google.adk.tools)}")

try:
    from google.adk.tools.mcp_tool import McpToolset
    print(f"McpToolset bases: {McpToolset.__bases__}")
    for base in McpToolset.__bases__:
        print(f"Base: {base.__module__}.{base.__name__}")
except ImportError as e:
    print(f"Could not import McpToolset: {e}")
