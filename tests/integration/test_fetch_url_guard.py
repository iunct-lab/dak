"""fetch_url on the real stack (PBI #728): the x402 skill's fetch_url waits for the
user's approval before it goes out, and an approved call to an internal address
(a compose service name, the cloud metadata address) is refused without
connecting. Neither case leaves the stack, so no fake external server is needed."""
import httpx
import pytest

from conftest import AGENT_RUN_TIMEOUT, AGENT_URL, event_texts, function_calls, function_responses

MODEL = "fake-default"


def _pending(user_id, session_id):
    resp = httpx.get(f"{AGENT_URL}/approvals", params={"user_id": user_id, "session_id": session_id}, timeout=30.0)
    resp.raise_for_status()
    return resp.json()


def test_fetch_url_waits_for_approval(agent, fake_llm):
    url = "https://example.com/"
    fake_llm.clear(MODEL)
    fake_llm.script(MODEL, [
        fake_llm.tool_call("enable_skill", skill_name="x402"),
        fake_llm.tool_call("fetch_url", url=url),
        fake_llm.text("Waiting for approval."),
    ])
    session_id = agent.create_session()

    events = agent.run(session_id, "Fetch example.com")
    assert [c["name"] for c in function_calls(events)] == ["enable_skill", "fetch_url", "adk_request_confirmation"]
    # Not answered: the only fetch_url response is ADK's request for confirmation, so nothing went out
    fetched = [r for r in function_responses(events) if r.get("name") == "fetch_url"]
    assert all("requires confirmation" in str(r.get("response", {})) for r in fetched), fetched

    [item] = _pending(agent.user_id, session_id)
    assert item["tool_name"] == "fetch_url"
    assert item["tool_args"]["url"] == url


@pytest.mark.parametrize("url", ["http://mcp-server:8000/mcp", "http://169.254.169.254/latest/meta-data/"])
def test_fetch_url_to_internal_address_is_refused_after_approval(agent, fake_llm, url):
    fake_llm.clear(MODEL)
    fake_llm.script(MODEL, [
        fake_llm.tool_call("enable_skill", skill_name="x402"),
        fake_llm.tool_call("fetch_url", url=url),
        fake_llm.text("Waiting."),
        fake_llm.text("Done."),
    ])
    user_id = agent.user_id
    session_id = agent.create_session()
    agent.run(session_id, "Fetch an internal page")

    [item] = _pending(user_id, session_id)
    assert item["tool_name"] == "fetch_url"
    resp = httpx.post(f"{AGENT_URL}/approvals/{item['id']}/reply",
                      json={"user_id": user_id, "session_id": session_id, "mode": "once"}, timeout=AGENT_RUN_TIMEOUT)
    assert resp.status_code == 200, resp.text

    session = httpx.get(f"{AGENT_URL}/apps/dak_agent/users/{user_id}/sessions/{session_id}", timeout=30.0).json()
    assert "Done." in event_texts(session["events"])
    fetched = [r for r in function_responses(session["events"]) if r.get("name") == "fetch_url"]
    assert fetched, session["events"]
    assert "Not fetched: refused" in str(fetched[-1].get("response", {}))
