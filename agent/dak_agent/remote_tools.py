"""Zero-config discovery of remote MCP tools (metadata only)."""
import logging
from typing import Dict

from google.adk.tools.mcp_tool import McpToolset, StreamableHTTPConnectionParams

logger = logging.getLogger(__name__)


async def discover_remote_tools(mcp_url: str) -> Dict[str, str]:
    """Fetch tool names and descriptions from an MCP server.

    Returns an empty dict if the URL is unset or the server is unreachable.
    """
    if not mcp_url:
        return {}

    try:
        logger.info(f"Connecting to MCP server at: {mcp_url}")
        toolset = McpToolset(
            connection_params=StreamableHTTPConnectionParams(url=mcp_url),
            require_confirmation=False,
        )
        tools = await toolset.get_tools()
    except Exception as e:
        logger.warning(f"Failed to discover remote tools: {e}")
        return {}

    discovered = {}
    for tool in tools:
        name = getattr(tool, "name", None)
        if name:
            discovered[name] = getattr(tool, "description", "No description")
    logger.info(f"Discovered {len(discovered)} remote tools.")
    return discovered
