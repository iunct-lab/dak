"""A 2026-07-28 MCP client and an agent on the older MCP session use the same mcp-server at once (#322, #325).

The 2026-07-28 client is plain httpx (no mcp dependency here): no `initialize`, each request
describes itself in `params._meta`, and the POST carries `Mcp-Method` / `Mcp-Name`.
The agent is `agent-legacy-mcp` (compose/test/mcp-legacy.yml): ADK with MCP_MODERN_PROTOCOL off,
so it connects with `initialize` and an `Mcp-Session-Id`."""
import os
import re
import subprocess
import threading
from pathlib import Path

import httpx

from conftest import MCP_URL, AgentClient, function_responses

AGENT_LEGACY_MCP_URL = os.getenv("DAK_AGENT_LEGACY_MCP_URL", "http://localhost:8019")
MODEL = "fake-legacy-mcp"
MODERN = "2026-07-28"
ROOT = Path(__file__).resolve().parents[2]
COMPOSE_FILE = subprocess.run([ROOT / "scripts" / "compose_files.sh", "test"], capture_output=True, text=True,
                              check=True).stdout.strip()
COMPOSE = ["env", f"COMPOSE_FILE={COMPOSE_FILE}", "docker", "compose"]
CONNECTED = re.compile(r"MCP connected: protocol=(\S+)")


def _modern_request(client: httpx.Client, method: str, params: dict | None = None, name: str | None = None) -> httpx.Response:
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
        "Mcp-Protocol-Version": MODERN,
        "Mcp-Method": method,
    }
    if name:
        headers["Mcp-Name"] = name
    meta = {
        "io.modelcontextprotocol/protocolVersion": MODERN,
        "io.modelcontextprotocol/clientInfo": {"name": "dak-integration", "version": "0"},
        "io.modelcontextprotocol/clientCapabilities": {},
    }
    payload = {"jsonrpc": "2.0", "id": 1, "method": method, "params": {**(params or {}), "_meta": meta}}
    return client.post(MCP_URL, json=payload, headers=headers, timeout=30.0)


def _modern_read_readme(client: httpx.Client) -> dict:
    resp = _modern_request(client, "tools/call", {"name": "read_file", "arguments": {"path": "README.md"}}, name="read_file")
    assert resp.status_code == 200, resp.text[:300]
    assert "mcp-session-id" not in resp.headers
    return resp.json()


def _connected_protocols() -> list:
    logs = subprocess.run([*COMPOSE, "logs", "--no-log-prefix", "agent-legacy-mcp"], cwd=ROOT, capture_output=True,
                          text=True, check=True)
    return CONNECTED.findall(logs.stdout + logs.stderr)


def test_modern_client_stateless_call():
    with httpx.Client() as client:
        discover = _modern_request(client, "server/discover")
        assert discover.status_code == 200, discover.text[:300]
        assert "mcp-session-id" not in discover.headers
        assert MODERN in discover.json()["result"]["supportedVersions"]

        result = _modern_read_readme(client)["result"]
    assert result["isError"] is False
    assert "Decentralized Agent Kit" in result["content"][0]["text"]


def test_legacy_agent_and_modern_client_together(fake_llm):
    """The agent's MCP session stays open across the 2026-07-28 calls and is used again after them.

    ADK keeps one MCP session per header set and reuses it, so the second turn (same ADK
    session) calls read_file on the session the first turn opened: no new `MCP connected`
    line. The 2026-07-28 calls are sent while that session is open (and also during the
    first turn, which may or may not overlap its MCP calls)."""
    agent = AgentClient(AGENT_LEGACY_MCP_URL)
    fake_llm.clear(MODEL)
    fake_llm.script(MODEL, [
        fake_llm.tool_call("enable_skill", skill_name="filesystem"),
        fake_llm.tool_call("read_file", path="README.md"),
        fake_llm.text("The README was read successfully."),
        fake_llm.tool_call("read_file", path="README.md"),
        fake_llm.text("Read it again."),
    ])
    session_id = agent.create_session()
    turn = {}

    def run_turn():
        turn["events"] = agent.run(session_id, "Enable the filesystem skill and read README.md")

    with httpx.Client() as client:
        modern = [_modern_read_readme(client)]  # before the first turn
        thread = threading.Thread(target=run_turn)
        thread.start()
        while thread.is_alive():  # during the first turn
            modern.append(_modern_read_readme(client))
            thread.join(timeout=0.2)
        opened = _connected_protocols()
        modern.append(_modern_read_readme(client))  # while the agent's session is open
        second = agent.run(session_id, "Read README.md again")
        modern.append(_modern_read_readme(client))  # after the second turn

    assert all(m["result"]["isError"] is False for m in modern)
    assert all("Decentralized Agent Kit" in m["result"]["content"][0]["text"] for m in modern)

    for events in (turn["events"], second):
        read_resp = next(r for r in function_responses(events) if r.get("name") == "read_file")
        assert "Decentralized Agent Kit" in str(read_resp.get("response", {}))

    assert opened, "agent-legacy-mcp logged no MCP connection"
    assert MODERN not in opened, opened
    # the second turn reused a session opened before the 2026-07-28 calls
    assert _connected_protocols() == opened
