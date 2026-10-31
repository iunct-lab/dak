"""Skill system E2E: list skills, enable one, use its MCP-backed tool."""
import subprocess
from pathlib import Path

from conftest import event_texts, function_calls, function_responses

MODEL = "fake-default"
ROOT = Path(__file__).resolve().parents[2]
# the integration stack's files (scripts/compose_files.sh)
COMPOSE_FILE = subprocess.run([ROOT / "scripts" / "compose_files.sh", "test"], capture_output=True, text=True,
                              check=True).stdout.strip()
COMPOSE = ["env", f"COMPOSE_FILE={COMPOSE_FILE}", "docker", "compose"]


def _exec(service: str, *command: str) -> str:
    out = subprocess.run([*COMPOSE, "exec", "-T", service, *command], cwd=ROOT, capture_output=True,
                         text=True, check=True)
    return out.stdout.strip()


def test_agent_uses_modern_mcp_protocol():
    # MCP 2026-07-28 (#629): ADK tries server/discover first, so the skill flow below runs session-less
    assert _exec("agent", "printenv", "ADK_ENABLE_MCP_MODERN_PROTOCOL") == "1"


def test_mcp_server_speaks_mcp2():
    # the other end is the mcp 2.x mcp-server (#211); its image keeps mcp in /app/.venv
    version = _exec("mcp-server", ".venv/bin/python", "-c",
                    "import importlib.metadata as m; print(m.version('mcp'))")
    assert version.startswith("2."), version


def test_list_skills_shows_curated_and_remote(agent, fake_llm):
    fake_llm.clear(MODEL)
    fake_llm.script(MODEL, [
        fake_llm.tool_call("list_skills"),
        fake_llm.text("Here are the skills."),
    ])

    session_id = agent.create_session()
    events = agent.run(session_id, "What skills do you have?")

    responses = function_responses(events)
    list_resp = next(r for r in responses if r.get("name") == "list_skills")
    result = str(list_resp.get("response", {}))
    assert "filesystem" in result
    # Remote tools discovered from the MCP server (zero-config)
    assert "deep_think" in result


def test_enable_skill_and_use_mcp_tool(agent, fake_llm):
    fake_llm.clear(MODEL)
    fake_llm.script(MODEL, [
        fake_llm.tool_call("enable_skill", skill_name="filesystem"),
        fake_llm.tool_call("read_file", path="README.md"),
        fake_llm.text("The README was read successfully."),
    ])

    session_id = agent.create_session()
    events = agent.run(session_id, "Enable the filesystem skill and read README.md")

    calls = [c["name"] for c in function_calls(events)]
    assert "enable_skill" in calls
    assert "read_file" in calls

    responses = function_responses(events)
    enable_resp = next(r for r in responses if r.get("name") == "enable_skill")
    # "already active" can occur when the long-lived agent kept state from a previous run
    assert any(s in str(enable_resp.get("response", {})) for s in ("enabled", "already active"))

    read_resp = next(r for r in responses if r.get("name") == "read_file")
    assert "Decentralized Agent Kit" in str(read_resp.get("response", {}))

    assert any("README was read successfully" in t for t in event_texts(events))


def test_enable_unknown_skill_returns_error_observation(agent, fake_llm):
    fake_llm.clear(MODEL)
    fake_llm.script(MODEL, [
        fake_llm.tool_call("enable_skill", skill_name="no_such_skill"),
        fake_llm.text("That skill does not exist."),
    ])

    session_id = agent.create_session()
    events = agent.run(session_id, "Enable no_such_skill")

    responses = function_responses(events)
    enable_resp = next(r for r in responses if r.get("name") == "enable_skill")
    assert "not found" in str(enable_resp.get("response", {}))
