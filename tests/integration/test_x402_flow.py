"""x402 on the real stack (PBI #416): 402 → Observation → the user approves the payment →
one signed resend → 200, against fake-x402 (the paid resource, its facilitator and the Solana
RPC; compose/test/x402.yml). agent-x402's key is made when it starts. Nothing reaches a
testnet or a public facilitator."""
import json

import httpx
import pytest

from conftest import AGENT_RUN_TIMEOUT, AGENT_X402_URL, FAKE_X402_URL, AgentClient, function_responses

MODEL = "fake-x402"
PAID_URL = "http://paid.x402.test:8080/paid"
# What fake-x402 asks for (tests/integration/fake_x402/app.py), fixed here so a change there fails the test.
# Only payTo and feePayer are made at its startup and read from /stats.
NETWORK = "solana:EtWTRABZaYq6iMfeYKouRu166VU2xqa1"
ASSET = "4zMMC9srt5Ri5X14GAgXhaHii3GnPAEERYPJgZJDncDU"
AMOUNT = "10000"


def _pending(user_id, session_id):
    resp = httpx.get(f"{AGENT_X402_URL}/approvals", params={"user_id": user_id, "session_id": session_id}, timeout=30.0)
    resp.raise_for_status()
    return resp.json()


def _reply(approval_id, user_id, session_id, **body):
    resp = httpx.post(f"{AGENT_X402_URL}/approvals/{approval_id}/reply",
                      json={"user_id": user_id, "session_id": session_id, **body}, timeout=AGENT_RUN_TIMEOUT)
    assert resp.status_code == 200, resp.text
    return resp


def _session_events(user_id, session_id):
    resp = httpx.get(f"{AGENT_X402_URL}/apps/dak_agent/users/{user_id}/sessions/{session_id}", timeout=30.0)
    resp.raise_for_status()
    return resp.json()["events"]


def _counts():
    return httpx.get(f"{FAKE_X402_URL}/stats", timeout=10.0).json()["counts"]


@pytest.fixture
def paid(fake_llm):
    """Reset fake-x402 and script the model: enable x402 → fetch_url → pay_x402 with the 402's values → text.
    A call waiting for confirmation goes back to the model as an error, so each one is followed by a text
    that ends the turn (otherwise pay_x402 would be asked for before fetch_url is answered)."""
    httpx.post(f"{FAKE_X402_URL}/reset", timeout=10.0).raise_for_status()
    req = httpx.get(f"{FAKE_X402_URL}/stats", timeout=10.0).json()["requirement"]
    assert (req["scheme"], req["network"], req["asset"], req["amount"]) == ("exact", NETWORK, ASSET, AMOUNT)
    fake_llm.clear(MODEL)
    fake_llm.script(MODEL, [
        fake_llm.tool_call("enable_skill", skill_name="x402"),
        fake_llm.tool_call("fetch_url", url=PAID_URL),
        fake_llm.text("Waiting for the approval to fetch."),
        fake_llm.tool_call("pay_x402", url=PAID_URL, network=NETWORK, asset=ASSET, amount=AMOUNT,
                           pay_to=req["payTo"]),
        fake_llm.text("Waiting for the approval to pay."),
        fake_llm.text("Done."),
    ])
    agent = AgentClient(AGENT_X402_URL)
    session_id = agent.create_session()
    agent.run(session_id, "Get the premium data")
    # fetch_url asks first (#728): approve it, and the 402 comes back as an Observation
    [fetch] = _pending(agent.user_id, session_id)
    assert fetch["tool_name"] == "fetch_url" and fetch["tool_args"]["url"] == PAID_URL
    _reply(fetch["id"], agent.user_id, session_id, mode="once")
    # The model got the payment requirement as fetch_url's result, and nothing was paid
    [observation] = [json.dumps(r["response"]) for r in function_responses(_session_events(agent.user_id, session_id))
                     if r["name"] == "fetch_url" and "Payment Required" in json.dumps(r["response"])]
    for fact in (f"amount={AMOUNT}", f"asset={ASSET}", f"network={NETWORK}", f"payTo={req['payTo']}",
                 "expires_in=60s", "Nothing has been paid"):
        assert fact in observation, observation
    return agent, session_id, req


def _pay_x402_responses(events):
    return [r["response"] for r in function_responses(events) if r["name"] == "pay_x402"]


def test_approved_payment_reaches_200(paid):
    agent, session_id, req = paid
    [pay] = _pending(agent.user_id, session_id)
    assert pay["tool_name"] == "pay_x402"
    assert pay["tool_args"]["amount"] == AMOUNT and pay["tool_args"]["pay_to"] == req["payTo"]
    # Waiting for the user: only the unsigned GET reached the paid resource
    assert _counts() == {"/paid": 1}

    _reply(pay["id"], agent.user_id, session_id, mode="once")

    counts = _counts()
    assert counts["/paid"] == 2 and counts["/paid:signed"] == 1
    assert counts["/verify"] == 1 and counts["/settle"] == 1
    assert counts["/rpc:getAccountInfo"] == 1 and counts["/rpc:getLatestBlockhash"] == 1
    result = json.dumps(_pay_x402_responses(_session_events(agent.user_id, session_id))[-1])
    assert "HTTP 200" in result and "premium" in result
    assert _pending(agent.user_id, session_id) == []


def test_rejected_payment_sends_nothing(paid):
    agent, session_id, _ = paid
    [pay] = _pending(agent.user_id, session_id)
    assert pay["tool_name"] == "pay_x402"

    _reply(pay["id"], agent.user_id, session_id, mode="reject", reason="too expensive")

    counts = _counts()
    assert counts == {"/paid": 1}  # no signed resend, no /verify, no RPC (nothing was signed)
    assert not any("HTTP 200" in json.dumps(r) for r in _pay_x402_responses(_session_events(agent.user_id, session_id)))
