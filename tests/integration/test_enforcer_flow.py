"""Enforcer Mode (Ulysses Pact) E2E against the agent-enforcer instance."""
from conftest import event_texts, function_responses

MODEL = "fake-enforcer"
BLOCKED = "[ENFORCER_BLOCKED]"


def test_bare_text_is_blocked(agent_enforcer, fake_llm):
    fake_llm.clear(MODEL)
    fake_llm.script(MODEL, [fake_llm.text("I will just chat instead of using tools.")])

    session_id = agent_enforcer.create_session()
    events = agent_enforcer.run(session_id, "Hello")

    assert any(BLOCKED in t for t in event_texts(events)), f"events: {events}"


def test_pact_blocks_out_of_plan_tool_and_allows_planned_tool(agent_enforcer, fake_llm):
    fake_llm.clear(MODEL)
    session_id = agent_enforcer.create_session()

    # Turn 1: set a pact allowing only read_file
    fake_llm.script(MODEL, [
        fake_llm.tool_call(
            "planner",
            task_description="read a file",
            plan_steps=["read the file"],
            allowed_tools=["read_file"],
        ),
    ])
    agent_enforcer.run(session_id, "Plan to read a file")

    # Turn 2: an out-of-plan tool is blocked
    fake_llm.script(MODEL, [fake_llm.tool_call("run_command", command="ls")])
    events = agent_enforcer.run(session_id, "Now list the directory")
    assert any(BLOCKED in t and "run_command" in t for t in event_texts(events)), f"events: {events}"

    # Turn 3: list_skills (always allowed) is NOT blocked even mid-pact
    fake_llm.script(MODEL, [
        fake_llm.tool_call("list_skills"),
        fake_llm.tool_call(
            "attempt_answer",
            answer="done",
            confidence="high",
            sources_used=["list_skills"],
        ),
    ])
    events = agent_enforcer.run(session_id, "What skills do you have?")
    texts = event_texts(events)
    assert not any(BLOCKED in t for t in texts), f"events: {events}"
    assert any(r.get("name") == "list_skills" for r in function_responses(events))


def test_pact_does_not_leak_across_sessions(agent_enforcer, fake_llm):
    """Regression test: plans used to live in a process-global and leaked
    into every other session of the same agent process."""
    fake_llm.clear(MODEL)

    # Session A sets a very restrictive pact
    session_a = agent_enforcer.create_session()
    fake_llm.script(MODEL, [
        fake_llm.tool_call(
            "planner",
            task_description="restricted",
            plan_steps=["only read"],
            allowed_tools=["read_file"],
        ),
    ])
    agent_enforcer.run(session_a, "Restrict yourself")

    # Session B (fresh): a tool outside session A's pact must NOT be blocked
    session_b = agent_enforcer.create_session()
    fake_llm.script(MODEL, [
        fake_llm.tool_call("list_skills"),
        fake_llm.tool_call(
            "attempt_answer",
            answer="independent session",
            confidence="high",
            sources_used=[],
        ),
    ])
    events = agent_enforcer.run(session_b, "What can you do?")
    assert not any(BLOCKED in t for t in event_texts(events)), f"events: {events}"

    # Session A still has its pact: run_command is blocked there
    fake_llm.script(MODEL, [fake_llm.tool_call("run_command", command="ls")])
    events = agent_enforcer.run(session_a, "List files")
    assert any(BLOCKED in t for t in event_texts(events)), f"events: {events}"
