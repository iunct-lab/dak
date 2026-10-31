"""MCP server integration tests (streamable HTTP, no LLM involved)."""
import json

import httpx

from conftest import MCP_URL

EXPECTED_TOOLS = {"deep_think", "read_file", "write_file", "list_files", "run_command", "search_files"}

MCP_HEADERS = {
    "Content-Type": "application/json",
    "Accept": "application/json, text/event-stream",
}


def _parse_mcp_body(resp: httpx.Response) -> dict:
    """FastMCP may answer JSON or a single-event SSE body."""
    content_type = resp.headers.get("content-type", "")
    if "text/event-stream" in content_type:
        for line in resp.text.splitlines():
            if line.startswith("data:"):
                return json.loads(line[len("data:"):].strip())
        raise AssertionError(f"No data line in SSE body: {resp.text[:200]}")
    return resp.json()


def _mcp_request(client: httpx.Client, headers: dict, payload: dict) -> httpx.Response:
    resp = client.post(MCP_URL, json=payload, headers=headers, timeout=30.0)
    resp.raise_for_status()
    return resp


def _initialize(client: httpx.Client) -> dict:
    """Run the MCP initialize handshake, returning headers with the session id."""
    headers = dict(MCP_HEADERS)
    resp = _mcp_request(client, headers, {
        "jsonrpc": "2.0",
        "id": 0,
        "method": "initialize",
        "params": {
            "protocolVersion": "2025-03-26",
            "capabilities": {},
            "clientInfo": {"name": "integration-test", "version": "0.0.1"},
        },
    })
    session_id = resp.headers.get("mcp-session-id")
    if session_id:
        headers["mcp-session-id"] = session_id
    # Complete the handshake
    client.post(MCP_URL, headers=headers, json={"jsonrpc": "2.0", "method": "notifications/initialized"}, timeout=30.0)
    return headers


def test_tools_list_exposes_builtin_tools():
    with httpx.Client() as client:
        headers = _initialize(client)
        resp = _mcp_request(client, headers, {"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
        body = _parse_mcp_body(resp)

    tools = {tool["name"] for tool in body["result"]["tools"]}
    assert EXPECTED_TOOLS <= tools


def test_read_file_round_trip():
    with httpx.Client() as client:
        headers = _initialize(client)
        resp = _mcp_request(client, headers, {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {"name": "read_file", "arguments": {"path": "README.md"}},
        })
        body = _parse_mcp_body(resp)

    content = body["result"]["content"][0]["text"]
    # The MCP server mounts the repo at /projects, so this is the repo README
    assert "Decentralized Agent Kit" in content
