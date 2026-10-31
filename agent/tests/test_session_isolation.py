"""End-to-end regression tests for PBI #133: one AdaptiveAgent instance is
shared by every session in the process. These drive a real ADK `Runner`
(not mocks) to confirm that:

1. A skill enabled in session A's turn does not leak into session B's turn,
   even though both run on the very same AdaptiveAgent/App instance.
2. A skill enabled in one turn of a session is restored at the very start of
   that session's NEXT turn (a fresh `before_agent_callback` invocation),
   even from a brand-new AdaptiveAgent instance (simulating a redeployed
   process) that only shares the session's persisted `state`.
"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from google.genai import types

from dak_agent.skill_registry import SkillRegistry


@pytest.fixture(autouse=True)
def no_remote_mcp_discovery():
    """`enable_skill`/`list_skills` lazily probe the default MCP server; avoid
    a real (slow, failing) network attempt in these tests."""
    with patch("dak_agent.remote_tools.discover_remote_tools", AsyncMock(return_value={})):
        yield


def _make_scripted_llm(steps):
    """`steps`: a list of "enable" | "switch" | "<literal text>", consumed one
    per model call across every invocation this LLM instance is used for.
    Returns (llm, requests) where `requests` records every `LlmRequest` sent."""
    from google.adk.models.base_llm import BaseLlm
    from google.adk.models.llm_response import LlmResponse

    remaining = list(steps)
    requests = []

    class ScriptedLlm(BaseLlm):
        async def generate_content_async(self, llm_request, stream=False):
            requests.append(llm_request)
            step = remaining.pop(0)
            if step == "enable":
                part = types.Part(function_call=types.FunctionCall(
                    id=f"fc-{len(requests)}", name="enable_skill", args={"skill_name": "demo"}))
            elif step == "switch":
                part = types.Part(function_call=types.FunctionCall(
                    id=f"fc-{len(requests)}", name="switch_mode",
                    args={"reason": "new phase", "new_focus": "debugging"}))
            else:
                part = types.Part(text=step)
            yield LlmResponse(content=types.Content(role="model", parts=[part]))

    return ScriptedLlm(model="scripted"), requests


def _make_agent(llm, with_switch_mode: bool = False):
    from google.adk.tools import FunctionTool

    from dak_agent.adaptive_agent import AdaptiveAgent
    from dak_agent.builtin_tools import switch_mode

    tools = [FunctionTool(switch_mode, require_confirmation=False)] if with_switch_mode else []
    agent = AdaptiveAgent(model=llm, name="dak_agent", instruction="Base instruction.", tools=tools)
    agent.skill_registry = MagicMock(spec=SkillRegistry)
    agent.skill_registry.find_skill_dir.return_value = "/tmp/nonexistent-demo-skill-dir"
    agent.skill_registry.get_skill.side_effect = lambda name: {
        "name": "demo", "instructions": "Use the demo skill.", "tools": [],
    } if name == "demo" else None
    agent.skill_registry.list_skills.return_value = []
    return agent


async def _run_turn(app, sessions, artifacts, session_id, user_id, text):
    from google.adk.runners import Runner

    runner = Runner(app=app, session_service=sessions, artifact_service=artifacts)
    async for _ in runner.run_async(
        user_id=user_id, session_id=session_id,
        new_message=types.Content(role="user", parts=[types.Part(text=text)]),
    ):
        pass


def _instructions(llm_request) -> str:
    return llm_request.config.system_instruction or ""


@pytest.mark.asyncio
async def test_enabling_a_skill_in_one_session_does_not_leak_into_another():
    from google.adk.apps import App
    from google.adk.artifacts import InMemoryArtifactService
    from google.adk.sessions import InMemorySessionService

    llm, requests = _make_scripted_llm(["enable", "done", "done"])
    agent = _make_agent(llm)
    app = App(name="dak_agent", root_agent=agent)
    sessions = InMemorySessionService()
    artifacts = InMemoryArtifactService()

    session_a = await sessions.create_session(app_name="dak_agent", user_id="u")
    session_b = await sessions.create_session(app_name="dak_agent", user_id="u")

    # Session A enables the "demo" skill.
    await _run_turn(app, sessions, artifacts, session_a.id, "u", "enable demo")
    # Session B's own turn must not see it.
    await _run_turn(app, sessions, artifacts, session_b.id, "u", "hello")

    session_b_request = requests[-1]
    assert "Use the demo skill." not in _instructions(session_b_request)

    state_b = (await sessions.get_session(app_name="dak_agent", user_id="u", session_id=session_b.id)).state
    assert not state_b.get("dak_active_skills")


@pytest.mark.asyncio
async def test_skill_enabled_in_one_turn_is_restored_on_the_next_turn():
    from google.adk.apps import App
    from google.adk.artifacts import InMemoryArtifactService
    from google.adk.sessions import InMemorySessionService

    llm, requests = _make_scripted_llm(["enable", "done", "done"])
    agent = _make_agent(llm)
    app = App(name="dak_agent", root_agent=agent)
    sessions = InMemorySessionService()
    artifacts = InMemoryArtifactService()
    session = await sessions.create_session(app_name="dak_agent", user_id="u")

    # Turn 1: enable the skill mid-turn.
    await _run_turn(app, sessions, artifacts, session.id, "u", "enable demo")
    assert "Use the demo skill." in _instructions(requests[-1])

    # Turn 2: a brand-new invocation of the SAME session; its first model call
    # must already carry the skill. (On the old code this also passed via the
    # leaked root; the fresh-instance test below is what isolates the restore.)
    await _run_turn(app, sessions, artifacts, session.id, "u", "continue")
    assert "Use the demo skill." in _instructions(requests[-1])

    state = (await sessions.get_session(app_name="dak_agent", user_id="u", session_id=session.id)).state
    assert state.get("dak_active_skills") == ["demo"]


@pytest.mark.asyncio
async def test_skill_survives_a_brand_new_agent_instance_for_the_same_session():
    """Regression test for the PBI's second acceptance criterion: state must
    survive the AdaptiveAgent instance being recreated (e.g. a redeployed
    process), as long as the session (and its persisted `state`) continues."""
    from google.adk.apps import App
    from google.adk.artifacts import InMemoryArtifactService
    from google.adk.sessions import InMemorySessionService

    sessions = InMemorySessionService()
    artifacts = InMemoryArtifactService()
    session = await sessions.create_session(app_name="dak_agent", user_id="u")

    llm1, requests1 = _make_scripted_llm(["enable", "done"])
    app1 = App(name="dak_agent", root_agent=_make_agent(llm1))
    await _run_turn(app1, sessions, artifacts, session.id, "u", "enable demo")
    assert "Use the demo skill." in _instructions(requests1[-1])

    # A brand-new AdaptiveAgent/App (fresh process), same session store.
    llm2, requests2 = _make_scripted_llm(["done"])
    app2 = App(name="dak_agent", root_agent=_make_agent(llm2))
    await _run_turn(app2, sessions, artifacts, session.id, "u", "continue")

    assert "Use the demo skill." in _instructions(requests2[-1])


@pytest.mark.asyncio
async def test_switch_mode_in_one_session_does_not_leak_into_another():
    """Same regression as `enable_skill`, but for the `switch_mode` path
    (ModeManager's first-turn/switch-request flags and the resulting mode
    instruction), which is the other half of PBI #133's acceptance criteria."""
    from google.adk.apps import App
    from google.adk.artifacts import InMemoryArtifactService
    from google.adk.sessions import InMemorySessionService

    with patch(
        "dak_agent.mode_manager.ModeManager.generate_mode_config",
        return_value=("Mode instruction for debugging.", [], []),
    ):
        # "done" first so each session's first turn is spent (switch_mode is
        # never honored on a session's first turn), then "switch".
        llm, requests = _make_scripted_llm(["done", "done", "switch", "done", "done"])
        agent = _make_agent(llm, with_switch_mode=True)
        app = App(name="dak_agent", root_agent=agent)
        sessions = InMemorySessionService()
        artifacts = InMemoryArtifactService()

        session_a = await sessions.create_session(app_name="dak_agent", user_id="u")
        session_b = await sessions.create_session(app_name="dak_agent", user_id="u")

        await _run_turn(app, sessions, artifacts, session_a.id, "u", "first turn")
        await _run_turn(app, sessions, artifacts, session_b.id, "u", "first turn")
        # Session A's second turn triggers the switch.
        await _run_turn(app, sessions, artifacts, session_a.id, "u", "switch please")
        assert "Mode instruction for debugging." in _instructions(requests[-1])
        # Session B's next turn must not see session A's mode.
        await _run_turn(app, sessions, artifacts, session_b.id, "u", "hello again")
        assert "Mode instruction for debugging." not in _instructions(requests[-1])

        state_a = (await sessions.get_session(app_name="dak_agent", user_id="u", session_id=session_a.id)).state
        state_b = (await sessions.get_session(app_name="dak_agent", user_id="u", session_id=session_b.id)).state

        assert state_a.get("dak_mode_instruction") == "Mode instruction for debugging."
        assert "dak_mode_instruction" not in state_b
