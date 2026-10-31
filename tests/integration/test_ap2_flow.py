"""AP2 payment protocol E2E against the agent-ap2 instance (mock wallet).

Flow: enable the paid skill -> paid tool fails with Payment Required ->
check balance -> pay -> retry with payment_hash -> success.
"""
from conftest import event_texts, function_responses

MODEL = "fake-ap2"
MOCK_ADDRESS = "MockSoLAddress1111111111111111111111111111111"


def _response_str(events, tool_name):
    matches = [r for r in function_responses(events) if r.get("name") == tool_name]
    assert matches, f"no functionResponse for {tool_name} in {events}"
    return str(matches[-1].get("response", {}))


def test_full_payment_flow(agent_ap2, fake_llm):
    fake_llm.clear(MODEL)
    session_id = agent_ap2.create_session()

    # Turn 1: enable the paid skill, then call the paid tool without payment
    fake_llm.script(MODEL, [
        fake_llm.tool_call("enable_skill", skill_name="premium_service"),
        fake_llm.tool_call("perform_premium_analysis", topic="AI"),
        fake_llm.text("Payment is required: 10 SOL."),
    ])
    events = agent_ap2.run(session_id, "Run a premium analysis on AI")

    # "already active" can occur when the long-lived agent kept state from a previous run
    enable_resp = _response_str(events, "enable_skill")
    assert "enabled" in enable_resp or "already active" in enable_resp
    paid_resp = _response_str(events, "perform_premium_analysis")
    assert "Payment Required" in paid_resp
    assert MOCK_ADDRESS in paid_resp

    # Turn 2: the agent checks its balance and pays (mock wallet)
    fake_llm.script(MODEL, [
        fake_llm.tool_call("check_solana_balance"),
        fake_llm.tool_call("send_sol_payment", recipient=MOCK_ADDRESS, amount=10.0),
        fake_llm.text("Paid 10 SOL."),
    ])
    events = agent_ap2.run(session_id, "Check balance and pay")

    assert "SOL" in _response_str(events, "check_solana_balance")
    payment_resp = _response_str(events, "send_sol_payment")
    assert "MockTx_" in payment_resp

    # Extract the mock transaction hash from the tool output
    tx_hash = "MockTx_" + payment_resp.split("MockTx_", 1)[1].split("`", 1)[0].split("'", 1)[0].split('"', 1)[0].split("\\n", 1)[0].strip()

    # Turn 3: retry the paid tool with the payment proof
    fake_llm.script(MODEL, [
        fake_llm.tool_call("perform_premium_analysis", topic="AI", payment_hash=tx_hash),
        fake_llm.text("Here is your premium analysis."),
    ])
    events = agent_ap2.run(session_id, "Retry the analysis with the payment hash")

    final_resp = _response_str(events, "perform_premium_analysis")
    assert "PREMIUM ANALYSIS REPORT" in final_resp
    assert any("premium analysis" in t.lower() for t in event_texts(events))


def test_invalid_payment_hash_is_rejected(agent_ap2, fake_llm):
    fake_llm.clear(MODEL)
    session_id = agent_ap2.create_session()

    fake_llm.script(MODEL, [
        fake_llm.tool_call("enable_skill", skill_name="premium_service"),
        fake_llm.tool_call("perform_premium_analysis", topic="AI", payment_hash="FakeHash123"),
        fake_llm.text("The payment hash was rejected."),
    ])
    events = agent_ap2.run(session_id, "Run an analysis with a forged payment hash")

    paid_resp = _response_str(events, "perform_premium_analysis")
    assert "Payment Required" in paid_resp or "verification failed" in paid_resp
