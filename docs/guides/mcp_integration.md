# MCP Integration Guide

## What is MCP?

The Model Context Protocol (MCP) is an open protocol that standardizes how applications provide context to LLMs. In the Decentralized Agent Kit (DAK), MCP is used to provide **tools** that the agent can discover and execute dynamically.

## Why MCP?

- **Standardized Protocol**: Industry-standard way to expose tools to LLMs
- **Dynamic Discovery**: Agent discovers available tools at runtime
- **Decoupled Architecture**: Tools are separated from the agent, allowing independent development
- **Extensibility**: Easy to add new tools without modifying agent code

## Architecture

```
┌─────────────┐         MCP Protocol          ┌─────────────┐
│  DAK Agent  │ ──────────────────────────▶  │ MCP Server  │
│             │  (streamable-http)            │             │
│ MCP Client  │ ◀──────────────────────────   │   Tools:    │
│             │                                │ • deep_think│
└─────────────┘                                └─────────────┘
      │                                              │
      │ Uses tools via LLM                          │
      ▼                                              ▼
  User Query ──▶ LLM decides ──▶ Tool Call ──▶ Tool Execution
```

## Components

### MCP Server (`mcp-server/`)

- **Purpose**: Exposes tools via MCP protocol
- **Framework**: FastMCP with streamable HTTP transport
- **Port**: 8000 (Docker: `mcp-server:8000`)
- **Tools**: Defined using `@mcp.tool()` decorator

### MCP Client (`agent/src/mcp_client.py`)

- **Purpose**: Connects to MCP Server and executes tools
- **Transport**: `streamablehttp_client` from `mcp` library
- **Discovery**: Calls `list_tools()` to get available tools
- **Execution**: Calls `call_tool(name, arguments)` to run tools

### LLM Integration (`agent/src/llm.py`)

- **Tool Awareness**: Tool definitions are passed to LLM
- **Tool Calling**: LLM generates tool calls based on user queries
- **Response Handling**: Agent executes tool and feeds result back to LLM

## How It Works

1. **User Query**: User sends a message like "Use deep_think to analyze consciousness"

2. **Tool Discovery**: Agent's MCP Client connects to MCP Server and lists available tools

3. **LLM Decision**: Agent passes tools to LLM along with the query. LLM decides to use `deep_think`

4. **Tool Execution**: Agent calls `mcp_client.call_tool("deep_think", {"thought": "consciousness"})`

5. **Result Processing**: MCP Server executes the tool and returns the result

6. **Final Response**: Agent feeds the result back to LLM for final answer generation

## Adding a Custom Tool

### Step 1: Define Tool in MCP Server

Edit `mcp-server/main.py`:

```python
@mcp.tool()
async def my_custom_tool(input_param: str) -> str:
    """
    Description of what this tool does.
    
    Args:
        input_param: Description of the parameter
    
    Returns:
        Description of the return value
    """
    # Your logic here
    result = f"Processed: {input_param}"
    return result
```

### Step 2: Rebuild MCP Server

```bash
export COMPOSE_FILE=$(./scripts/compose_files.sh)   # the default stack (docs/getting-started/docker_deployment.md)
docker compose up --build -d mcp-server
```

### Step 3: Test the Tool

```bash
cd cli
uv run dak-cli run "Use my_custom_tool to process 'hello world'"
```

The agent will automatically discover and use your new tool!

## Configuration

### MCP Server

File: `mcp-server/main.py`

```python
# Initialize FastMCP
mcp = FastMCP("dak-agent-mcp", json_response=True)

# Run with Uvicorn
app = Starlette(
    routes=[Mount("/", app=mcp.streamable_http_app())],
    lifespan=lifespan
)
uvicorn.run(app, host="0.0.0.0", port=8000)
```

**Key Settings**:
- `json_response=True`: Use JSON instead of SSE for responses
- `host="0.0.0.0"`: Allow Docker network access
- `stateless_http`: Disabled for clean session lifecycle

### MCP Client

File: `agent/src/mcp_client.py`

```python
class MCPClient:
    def __init__(self):
        self.server_url = os.getenv("MCP_SERVER_URL", "http://mcp-server:8000/mcp")
```

**Environment Variable**:
- `MCP_SERVER_URL`: Override default MCP Server URL (default: `http://mcp-server:8000/mcp`)

## Troubleshooting

### "MCPClient Error listing tools"

**Symptom**: Agent logs show `MCPClient Error listing tools: unhandled errors in a TaskGroup`

**Cause**: MCP Server is not reachable or not running

**Solution**:
```bash
# Check if mcp-server is running
docker compose ps mcp-server

# Check mcp-server logs
docker compose logs mcp-server --tail 50

# Restart mcp-server
docker compose restart mcp-server
```

### "Processing request of type CallToolRequest" but tool doesn't execute

**Symptom**: Logs show tool request but no execution

**Cause**: Tool function has errors or wrong arguments

**Solution**:
1. Check mcp-server logs for Python exceptions
2. Verify tool parameter types match the call
3. Add debug logging to your tool function

### Session Termination Errors

**Symptom**: Logs show `anyio.ClosedResourceError`

**Cause**: `stateless_http=True` causes premature session cleanup

**Solution**:
Remove `stateless_http=True` from FastMCP initialization (current default)

## Best Practices

### Tool Design

1. **Clear Descriptions**: Write detailed docstrings for LLM understanding
2. **Type Hints**: Always use type hints for parameters
3. **Error Handling**: Return meaningful error messages
4. **Idempotency**: Tools should be safe to call multiple times

### Example:

```python
@mcp.tool()
async def fetch_data(source: str, query: str) -> str:
    """
    Fetches data from a specified source based on a query.
    
    This tool is useful when the user needs to retrieve information
    from external sources like databases or APIs.
    
    Args:
        source: The data source to query (e.g., "database", "api")
        query: The search query or filter criteria
    
    Returns:
        JSON string containing the fetched data, or an error message
    """
    try:
        # Your implementation
        data = await fetch_from_source(source, query)
        return json.dumps(data)
    except Exception as e:
        return f"Error fetching data: {str(e)}"
```

### Testing

1. **Unit Tests**: Test tool functions independently
2. **Integration Tests**: Test via MCP Inspector
3. **End-to-End**: Test with actual agent queries

### Security

1. **Input Validation**: Always validate tool parameters
2. **Access Control**: Limit what tools can access
3. **Rate Limiting**: Prevent abuse of expensive operations
4. **Logging**: Log all tool executions for audit

## References

- [MCP Specification](https://modelcontextprotocol.io/specification)
- [FastMCP Documentation](https://github.com/modelcontextprotocol/python-sdk)
- [Python SDK Examples](https://github.com/modelcontextprotocol/python-sdk/tree/main/examples)
