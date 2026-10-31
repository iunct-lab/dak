"""PBI #135 acceptance criteria 1 and 7 (code side): the Lambda entry runs one
turn in a throwaway in-memory session, without a database, and keeps the
request text out of logs. Recording `BaseLlm` as in
`test_call_scoped_output_schema.py`."""
import json
import logging
import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from google.genai import types

from dak_agent import lambda_handler
from dak_agent.skill_registry import SkillRegistry


@pytest.fixture(autouse=True)
def no_remote_mcp_discovery():
    with patch("dak_agent.remote_tools.discover_remote_tools", AsyncMock(return_value={})):
        yield


def _llm(reply="hello back", error=None):
    from google.adk.models._capabilities import LlmCapabilities
    from google.adk.models.base_llm import BaseLlm
    from google.adk.models.llm_response import LlmResponse

    requests = []

    class RecordingLlm(BaseLlm):
        @property
        def capabilities(self) -> LlmCapabilities:
            return LlmCapabilities(output_schema_and_tools=True)

        async def generate_content_async(self, llm_request, stream=False):
            requests.append(llm_request)
            if error:
                raise error
            yield LlmResponse(content=types.Content(
                role="model", parts=[types.Part(text=reply)]))

    return RecordingLlm(model="recording"), requests


def _install(monkeypatch, llm, tools=()):
    from google.adk.apps import App

    from dak_agent.adaptive_agent import AdaptiveAgent

    agent = AdaptiveAgent(model=llm, name="dak_agent", instruction="Base.", tools=list(tools))
    agent.skill_registry = MagicMock(spec=SkillRegistry)
    agent.skill_registry.get_skill.return_value = None
    agent.skill_registry.list_skills.return_value = []
    monkeypatch.setattr(lambda_handler, "_app_cache", App(name="dak_agent", root_agent=agent))


def _text(request) -> str:
    return "\n".join(p.text for c in request.contents for p in c.parts or [] if p.text)


@pytest.mark.asyncio
async def test_reply_is_returned_as_output(monkeypatch):
    llm, _ = _llm("hello back")
    _install(monkeypatch, llm)
    assert await lambda_handler.run({"message": "hi"}) == {"status": "succeeded", "output": "hello back"}


@pytest.mark.asyncio
async def test_works_without_session_database(monkeypatch):
    monkeypatch.delenv("SESSION_SERVICE_URI", raising=False)
    llm, requests = _llm()
    _install(monkeypatch, llm)
    assert (await lambda_handler.run({"message": "hi"}))["status"] == "succeeded"
    assert len(requests) == 1


@pytest.mark.asyncio
async def test_no_tools_declared_when_dak_tools_omitted(monkeypatch):
    llm, requests = _llm()
    _install(monkeypatch, llm)
    await lambda_handler.run({"message": "hi"})
    assert not (requests[0].config.tools or [])


@pytest.mark.asyncio
async def test_tools_are_not_offered_when_dak_tools_omitted_but_agent_has_one(monkeypatch):
    def lookup(q: str) -> str:
        """Look something up."""
        return q

    llm, requests = _llm()
    _install(monkeypatch, llm, tools=[lookup])
    await lambda_handler.run({"message": "hi"})
    await lambda_handler.run({"message": "hi", "state_delta": {"dak:tools": ["lookup"]}})
    offered = lambda r: [d.name for t in (r.config.tools or []) for d in (t.function_declarations or [])]
    assert "lookup" not in offered(requests[0])


@pytest.mark.asyncio
async def test_owned_state_keys_are_refused_like_run(monkeypatch):
    llm, requests = _llm()
    _install(monkeypatch, llm)
    event = {"message": "hi", "state_delta": {"dak_permission_always_rules": ["*"]}}
    assert await lambda_handler.run(event) == {"status": "failed", "error": "invalid_event"}
    assert requests == []


def test_handler_survives_repeated_calls_on_one_loop(monkeypatch):
    llm, _ = _llm("ok")
    _install(monkeypatch, llm)
    assert [lambda_handler.handler({"message": "hi"})["output"] for _ in range(3)] == ["ok"] * 3


@pytest.mark.asyncio
async def test_two_calls_do_not_share_conversation(monkeypatch):
    llm, requests = _llm()
    _install(monkeypatch, llm)
    await lambda_handler.run({"message": "first-secret"})
    await lambda_handler.run({"message": "second"})
    assert "first-secret" not in _text(requests[1])


@pytest.mark.asyncio
async def test_message_and_state_values_are_not_logged(monkeypatch, caplog):
    llm, _ = _llm(error=RuntimeError("boom"))
    _install(monkeypatch, llm)
    with caplog.at_level(logging.DEBUG):
        result = await lambda_handler.run(
            {"message": "my-message", "state_delta": {"dak:instruction": "my-instruction"}})
    assert result == {"status": "failed", "error": "RuntimeError"}
    assert "my-message" not in caplog.text
    assert "my-instruction" not in caplog.text


@pytest.mark.asyncio
@pytest.mark.parametrize("event", [
    {}, {"message": 1}, {"message": "hi", "state_delta": []}, None, "hi"])
async def test_invalid_event_does_not_call_the_llm(monkeypatch, event):
    llm, requests = _llm()
    _install(monkeypatch, llm)
    assert await lambda_handler.run(event) == {"status": "failed", "error": "invalid_event"}
    assert requests == []


def test_handler_is_a_sync_wrapper(monkeypatch):
    llm, _ = _llm("ok")
    _install(monkeypatch, llm)
    assert lambda_handler.handler({"message": "hi"}, None)["output"] == "ok"


def test_importing_the_module_does_not_load_the_agent():
    import subprocess
    import sys
    code = ("import sys, dak_agent.lambda_handler; "
            "sys.exit(1 if 'dak_agent.agent' in sys.modules else 0)")
    assert subprocess.run([sys.executable, "-c", code]).returncode == 0


class _FakeTable:
    """A dict-backed stand-in for the boto3 Table: the calls the job, lock and
    session code make, with the condition expressions they send."""

    def __init__(self):
        self.items = {}
        self.writes = 0

    def get_item(self, Key, ConsistentRead=False):
        item = self.items.get((Key["pk"], Key["sk"]))
        return {"Item": dict(item)} if item else {}

    def put_item(self, Item, ConditionExpression=None, ExpressionAttributeValues=None):
        from botocore.exceptions import ClientError
        key = (Item["pk"], Item["sk"])
        cur = self.items.get(key)
        v = ExpressionAttributeValues or {}
        ok = {
            None: lambda: True,
            "attribute_not_exists(pk)": lambda: cur is None,
            "attribute_not_exists(pk) OR ver = :ver": lambda: cur is None or cur["ver"] == v[":ver"],
            "attribute_not_exists(pk) OR lock_until < :now":
                lambda: cur is None or cur["lock_until"] < v[":now"],
        }[ConditionExpression]()
        if not ok:
            raise ClientError({"Error": {"Code": "ConditionalCheckFailedException"}}, "PutItem")
        self.writes += 1
        self.items[key] = dict(Item)

    def update_item(self, Key, ExpressionAttributeNames, ExpressionAttributeValues, UpdateExpression=None):
        self.writes += 1
        item = self.items[(Key["pk"], Key["sk"])]
        for placeholder, name in ExpressionAttributeNames.items():
            item[name] = ExpressionAttributeValues[":" + placeholder[1:]]

    def delete_item(self, Key, ConditionExpression=None, ExpressionAttributeNames=None,
                    ExpressionAttributeValues=None):
        from botocore.exceptions import ClientError
        key = (Key["pk"], Key["sk"])
        if ConditionExpression:
            assert ConditionExpression == "#o = :o"
            if self.items.get(key, {}).get("owner") != ExpressionAttributeValues[":o"]:
                raise ClientError({"Error": {"Code": "ConditionalCheckFailedException"}}, "DeleteItem")
        self.writes += 1
        self.items.pop(key, None)

    def query(self, KeyConditionExpression, ExpressionAttributeValues, ScanIndexForward=True,
              Limit=None, ExclusiveStartKey=None, ConsistentRead=False):
        assert KeyConditionExpression == "pk = :pk AND sk BETWEEN :lo AND :hi"
        v = ExpressionAttributeValues
        rows = sorted((i for (pk, sk), i in self.items.items()
                       if pk == v[":pk"] and v[":lo"] <= sk <= v[":hi"]),
                      key=lambda i: i["sk"], reverse=not ScanIndexForward)
        return {"Items": [dict(r) for r in (rows[:Limit] if Limit else rows)]}


class _Context:
    def get_remaining_time_in_millis(self):
        return 60_000


@pytest.fixture
def table(monkeypatch):
    fake = _FakeTable()
    monkeypatch.setattr(lambda_handler, "_table", lambda: fake)
    return fake


@pytest.mark.asyncio
async def test_job_result_is_polled_with_get(monkeypatch, table):
    llm, _ = _llm("done")
    _install(monkeypatch, llm)
    event = {"message": "hi", "job_id": "j1"}
    assert await lambda_handler.run(event, _Context()) == {"status": "succeeded", "output": "done"}
    got = await lambda_handler.run({"op": "get", "job_id": "j1"})
    assert got == {"job_id": "j1", "status": "succeeded", "output": "done"}
    assert table.items[("J#j1", "JOB")]["expires_at"] > 0


@pytest.mark.asyncio
async def test_same_job_id_twice_does_not_call_the_llm_again(monkeypatch, table):
    llm, requests = _llm()
    _install(monkeypatch, llm)
    await lambda_handler.run({"message": "hi", "job_id": "j1"}, _Context())
    again = await lambda_handler.run({"message": "hi", "job_id": "j1"}, _Context())
    assert again == {"status": "failed", "error": "job_exists"}
    assert len(requests) == 1


@pytest.mark.asyncio
async def test_running_job_past_its_deadline_is_timed_out(table):
    table.items[("J#j1", "JOB")] = {"pk": "J#j1", "sk": "JOB", "status": "running", "deadline": 1}
    assert (await lambda_handler.run({"op": "get", "job_id": "j1"}))["status"] == "timed_out"
    table.items[("J#j2", "JOB")] = {"pk": "J#j2", "sk": "JOB", "status": "running",
                                    "deadline": 9_999_999_999}
    assert (await lambda_handler.run({"op": "get", "job_id": "j2"}))["status"] == "running"


@pytest.mark.asyncio
async def test_unknown_job_is_not_found(table):
    assert await lambda_handler.run({"op": "get", "job_id": "nope"}) == {
        "job_id": "nope", "status": "not_found"}


@pytest.mark.asyncio
async def test_job_without_table_is_not_configured(monkeypatch):
    monkeypatch.delenv("DAK_TABLE", raising=False)
    llm, requests = _llm()
    _install(monkeypatch, llm)
    expected = {"status": "failed", "error": "table_not_configured"}
    assert await lambda_handler.run({"message": "hi", "job_id": "j1"}, _Context()) == expected
    assert await lambda_handler.run({"op": "get", "job_id": "j1"}) == expected
    assert requests == []


@pytest.mark.asyncio
async def test_failed_turn_and_oversized_output_are_recorded(monkeypatch, table):
    llm, _ = _llm(error=RuntimeError("boom"))
    _install(monkeypatch, llm)
    await lambda_handler.run({"message": "hi", "job_id": "bad"}, _Context())
    assert await lambda_handler.run({"op": "get", "job_id": "bad"}) == {
        "job_id": "bad", "status": "failed", "error": "RuntimeError"}

    llm, _ = _llm("x" * (lambda_handler.MAX_OUTPUT_BYTES + 1))
    _install(monkeypatch, llm)
    await lambda_handler.run({"message": "hi", "job_id": "big"}, _Context())
    got = await lambda_handler.run({"op": "get", "job_id": "big"})
    assert got["status"] == "failed" and got["error"] == "output_too_large" and "output" not in got


@pytest.mark.asyncio
async def test_expired_job_row_is_not_found(table):
    table.items[("J#old", "JOB")] = {"pk": "J#old", "sk": "JOB", "status": "succeeded",
                                     "output": "x", "expires_at": 1}
    assert (await lambda_handler.run({"op": "get", "job_id": "old"}))["status"] == "not_found"


@pytest.mark.asyncio
async def test_start_error_other_than_exists_is_a_failed_result(monkeypatch, table):
    from botocore.exceptions import ClientError

    def throttled(**kwargs):
        raise ClientError({"Error": {"Code": "ProvisionedThroughputExceededException"}}, "PutItem")

    monkeypatch.setattr(table, "put_item", throttled)
    llm, requests = _llm()
    _install(monkeypatch, llm)
    result = await lambda_handler.run({"message": "hi", "job_id": "j1"}, _Context())
    assert result == {"status": "failed", "error": "ClientError"}
    assert requests == []


@pytest.mark.asyncio
async def test_finish_error_is_a_failed_result_and_the_row_stays_running(monkeypatch, table):
    def broken(**kwargs):
        raise RuntimeError("down")

    monkeypatch.setattr(table, "update_item", broken)
    llm, _ = _llm()
    _install(monkeypatch, llm)
    result = await lambda_handler.run({"message": "hi", "job_id": "j1"}, _Context())
    assert result == {"status": "failed", "error": "RuntimeError"}
    assert table.items[("J#j1", "JOB")]["status"] == "running"


# PBI #721 / Task #722: `session_id` keeps the session in the table.

def _scripted(*turns):
    """A recording `BaseLlm` that answers each call with the next item of
    `turns`: a text, or a (tool name, args) call."""
    from google.adk.models._capabilities import LlmCapabilities
    from google.adk.models.base_llm import BaseLlm
    from google.adk.models.llm_response import LlmResponse

    requests = []
    script = list(turns)

    class ScriptedLlm(BaseLlm):
        @property
        def capabilities(self) -> LlmCapabilities:
            return LlmCapabilities(output_schema_and_tools=True)

        async def generate_content_async(self, llm_request, stream=False):
            requests.append(llm_request)
            turn = script.pop(0)
            part = (types.Part(text=turn) if isinstance(turn, str)
                    else types.Part(function_call=types.FunctionCall(name=turn[0], args=turn[1])))
            yield LlmResponse(content=types.Content(role="model", parts=[part]))

    return ScriptedLlm(model="scripted"), requests


def _tool_results(table, name):
    """The tool's results kept in the table (not ADK's "requires confirmation" error)."""
    from google.adk.events.event import Event
    events = [Event.model_validate_json(i["event"]) for (_, sk), i in table.items.items() if sk.startswith("E#")]
    return [r for e in events for r in e.get_function_responses()
            if r.name == name and "error" not in (r.response or {})]


@pytest.mark.asyncio
async def test_second_turn_with_session_id_carries_the_first(monkeypatch, table):
    llm, requests = _llm("noted")
    _install(monkeypatch, llm)
    first = await lambda_handler.run({"message": "my name is Zorblat", "session_id": "s1"}, _Context())
    assert first == {"status": "succeeded", "session_id": "s1", "output": "noted"}
    await lambda_handler.run({"message": "what is my name?", "session_id": "s1"}, _Context())
    assert "Zorblat" in _text(requests[1]) and "noted" in _text(requests[1])
    assert not any(sk == "LOCK" for _, sk in table.items)  # released after each turn


@pytest.mark.asyncio
async def test_kept_session_keeps_the_callers_tools(monkeypatch, table):
    from google.adk.tools import FunctionTool

    def lookup(q: str) -> str:
        """Look something up."""
        return q

    llm, requests = _llm()
    _install(monkeypatch, llm, tools=[FunctionTool(lookup)])
    await lambda_handler.run({"message": "hi", "session_id": "s1",
                              "state_delta": {"dak:tools": ["lookup"]}}, _Context())
    await lambda_handler.run({"message": "again", "session_id": "s1"}, _Context())
    offered = [d.name for t in (requests[1].config.tools or []) for d in (t.function_declarations or [])]
    assert offered == ["lookup"]


@pytest.mark.asyncio
async def test_confirmation_waits_and_once_runs_the_tool(monkeypatch, table):
    from dak_agent.builtin_tools import make_builtin_tools

    monkeypatch.setenv("DAK_PLANNER_REQUIRE_CONFIRMATION", "true")  # as tests/integration/test_approvals.py
    llm, _ = _scripted(("planner", {"task_description": "tidy", "plan_steps": ["tidy"], "allowed_tools": []}),
                       "planned")
    _install(monkeypatch, llm, tools=make_builtin_tools())
    waiting = await lambda_handler.run({"message": "tidy up", "session_id": "s1",
                                        "state_delta": {"dak:tools": ["planner"]}}, _Context())
    assert (waiting["status"], waiting["session_id"]) == ("waiting", "s1")
    [item] = waiting["pending"]
    assert (item["kind"], item["tool_name"], item["status"], item["session_id"]) == (
        "approval", "planner", "pending", "s1")
    assert _tool_results(table, "planner") == []

    done = await lambda_handler.run({"op": "reply", "session_id": "s1", "approval_id": item["id"],
                                     "mode": "once"}, _Context())
    assert done == {"status": "succeeded", "session_id": "s1", "output": "planned"}
    assert len(_tool_results(table, "planner")) == 1


@pytest.mark.asyncio
async def test_question_waits_and_the_answer_resumes(monkeypatch, table):
    from google.adk.tools import FunctionTool

    from dak_agent.builtin_tools import ask_question

    llm, requests = _scripted(("ask_question", {"questions": ["Which branch?"], "context": "Two match"}),
                              "deploying main")
    _install(monkeypatch, llm, tools=[FunctionTool(ask_question)])
    waiting = await lambda_handler.run({"message": "deploy", "session_id": "s1",
                                        "state_delta": {"dak:tools": ["ask_question"]}}, _Context())
    [item] = waiting["pending"]
    assert (waiting["status"], item["kind"], item["questions"]) == ("waiting", "question", ["Which branch?"])

    done = await lambda_handler.run({"op": "reply", "session_id": "s1", "approval_id": item["id"],
                                     "answer": "the main branch"}, _Context())
    assert done["status"] == "succeeded" and done["output"] == "deploying main"
    assert "the main branch" in _text(requests[-1])


@pytest.mark.asyncio
@pytest.mark.parametrize("reply, error", [
    ({"approval_id": "nope", "mode": "once"}, "not_found"),
    ({"approval_id": "ID"}, "invalid_event"),  # an approval needs a mode
    ({"approval_id": "ID", "mode": "sometimes"}, "invalid_event"),
])
async def test_reply_is_judged_like_the_server(monkeypatch, table, reply, error):
    from google.adk.tools import FunctionTool

    from dak_agent.builtin_tools import planner

    llm, requests = _scripted(("planner", {"task_description": "t", "plan_steps": ["t"], "allowed_tools": []}))
    _install(monkeypatch, llm, tools=[FunctionTool(planner, require_confirmation=True)])
    waiting = await lambda_handler.run({"message": "go", "session_id": "s1",
                                        "state_delta": {"dak:tools": ["planner"]}}, _Context())
    reply = {k: waiting["pending"][0]["id"] if v == "ID" else v for k, v in reply.items()}
    result = await lambda_handler.run({"op": "reply", "session_id": "s1", **reply}, _Context())
    assert result == {"status": "failed", "error": error}
    assert len(requests) == 1


@pytest.mark.asyncio
async def test_reply_to_an_unknown_session_is_not_found(monkeypatch, table):
    llm, requests = _llm()
    _install(monkeypatch, llm)
    result = await lambda_handler.run({"op": "reply", "session_id": "nope", "approval_id": "a",
                                       "mode": "once"}, _Context())
    assert result == {"status": "failed", "error": "not_found"}
    assert requests == [] and not any(pk.startswith("S#") and sk != "LOCK" for pk, sk in table.items)


@pytest.mark.asyncio
async def test_held_lock_refuses_a_second_turn_without_calling_the_llm(monkeypatch, table):
    import time

    llm, requests = _llm()
    _install(monkeypatch, llm)
    key = lambda_handler._lock_key("dak_agent", "lambda", "s1")
    table.items[(key["pk"], key["sk"])] = {**key, "owner": "other", "lock_until": int(time.time()) + 60}
    assert await lambda_handler.run({"message": "hi", "session_id": "s1"}, _Context()) == {
        "status": "failed", "error": "session_busy"}
    assert requests == []
    assert table.items[(key["pk"], key["sk"])]["owner"] == "other"

    table.items[(key["pk"], key["sk"])]["lock_until"] = 1  # its Lambda was stopped: taken over
    assert (await lambda_handler.run({"message": "hi", "session_id": "s1"}, _Context()))["status"] == "succeeded"


@pytest.mark.asyncio
async def test_without_session_id_nothing_is_written(monkeypatch, table):
    llm, _ = _llm()
    _install(monkeypatch, llm)
    assert (await lambda_handler.run({"message": "hi"}, _Context()))["status"] == "succeeded"
    assert table.writes == 0


@pytest.mark.asyncio
async def test_waiting_job_is_polled_with_its_pending_list(monkeypatch, table):
    from google.adk.tools import FunctionTool

    from dak_agent.builtin_tools import ask_question

    llm, _ = _scripted(("ask_question", {"questions": ["Which?"], "context": "c"}))
    _install(monkeypatch, llm, tools=[FunctionTool(ask_question)])
    await lambda_handler.run({"message": "go", "session_id": "s1", "job_id": "j1",
                              "state_delta": {"dak:tools": ["ask_question"]}}, _Context())
    got = await lambda_handler.run({"op": "get", "job_id": "j1"})
    assert (got["status"], got["session_id"], got["pending"][0]["questions"]) == ("waiting", "s1", ["Which?"])


@pytest.mark.asyncio
@pytest.mark.parametrize("event", [
    {"message": "hi", "session_id": ""}, {"message": "hi", "session_id": 1},
    {"message": "hi", "session_id": "s1", "user_id": ""},
    {"op": "reply", "approval_id": "a", "mode": "once"},
    {"op": "reply", "session_id": "s1", "mode": "once"}])
async def test_invalid_session_event_does_not_touch_the_table(monkeypatch, table, event):
    llm, requests = _llm()
    _install(monkeypatch, llm)
    assert await lambda_handler.run(event, _Context()) == {"status": "failed", "error": "invalid_event"}
    assert requests == [] and table.writes == 0


@pytest.mark.asyncio
async def test_session_id_without_table_is_not_configured(monkeypatch):
    monkeypatch.delenv("DAK_TABLE", raising=False)
    llm, requests = _llm()
    _install(monkeypatch, llm)
    assert await lambda_handler.run({"message": "hi", "session_id": "s1"}) == {
        "status": "failed", "error": "table_not_configured"}
    assert requests == []


@pytest.mark.asyncio
async def test_waiting_job_over_the_size_limit_counts_the_pending_list(monkeypatch, table):
    from google.adk.tools import FunctionTool

    from dak_agent.builtin_tools import ask_question

    big = "q" * (lambda_handler.MAX_OUTPUT_BYTES // 2 + 1)  # the list is stored next to the output
    llm, _ = _scripted(("ask_question", {"questions": [big], "context": big}))
    _install(monkeypatch, llm, tools=[FunctionTool(ask_question)])
    await lambda_handler.run({"message": "go", "session_id": "s1", "job_id": "j1",
                              "state_delta": {"dak:tools": ["ask_question"]}}, _Context())
    assert await lambda_handler.run({"op": "get", "job_id": "j1"}) == {
        "job_id": "j1", "status": "failed", "error": "output_too_large", "session_id": "s1"}


@pytest.mark.asyncio
async def test_failed_unlock_keeps_the_turns_result(monkeypatch, table):
    def no_delete(**kwargs):
        raise RuntimeError("AccessDenied")

    monkeypatch.setattr(table, "delete_item", no_delete)
    llm, _ = _llm("done")
    _install(monkeypatch, llm)
    assert await lambda_handler.run({"message": "hi", "session_id": "s1"}, _Context()) == {
        "status": "succeeded", "session_id": "s1", "output": "done"}


@pytest.mark.asyncio
async def test_expired_approval_is_answered_timed_out_and_the_job_says_so(monkeypatch, table):
    from dak_agent import approvals
    from dak_agent.builtin_tools import make_builtin_tools

    monkeypatch.setenv("DAK_PLANNER_REQUIRE_CONFIRMATION", "true")
    llm, _ = _scripted(("planner", {"task_description": "t", "plan_steps": ["t"], "allowed_tools": []}),
                       "moved on")
    _install(monkeypatch, llm, tools=make_builtin_tools())
    waiting = await lambda_handler.run({"message": "go", "session_id": "s1",
                                        "state_delta": {"dak:tools": ["planner"]}}, _Context())
    monkeypatch.setattr(approvals, "PENDING_TIMEOUT_SECONDS", -1)  # every pending item has expired
    result = await lambda_handler.run({"op": "reply", "session_id": "s1", "job_id": "j1", "mode": "once",
                                       "approval_id": waiting["pending"][0]["id"]}, _Context())
    assert (result["status"], result["observation"]) == ("succeeded", "timed_out")
    # planner did not run: its only result is the timed_out observation
    assert [r.response for r in _tool_results(table, "planner")] == [{"observation": "timed_out"}]
    got = await lambda_handler.run({"op": "get", "job_id": "j1"})
    assert (got["status"], got["observation"]) == ("succeeded", "timed_out")


@pytest.mark.asyncio
async def test_null_reason_and_answer_are_the_same_as_leaving_them_out(monkeypatch, table):
    from dak_agent.builtin_tools import make_builtin_tools

    monkeypatch.setenv("DAK_PLANNER_REQUIRE_CONFIRMATION", "true")
    llm, _ = _scripted(("planner", {"task_description": "t", "plan_steps": ["t"], "allowed_tools": []}), "ok")
    _install(monkeypatch, llm, tools=make_builtin_tools())
    waiting = await lambda_handler.run({"message": "go", "session_id": "s1",
                                        "state_delta": {"dak:tools": ["planner"]}}, _Context())
    done = await lambda_handler.run({"op": "reply", "session_id": "s1", "mode": "once", "answer": None,
                                     "reason": None, "approval_id": waiting["pending"][0]["id"]}, _Context())
    assert done["status"] == "succeeded"
    assert len(_tool_results(table, "planner")) == 1


def test_output_too_large_keeps_the_timed_out_observation(table):
    table.items[("J#j1", "JOB")] = {"pk": "J#j1", "sk": "JOB", "status": "running"}
    lambda_handler._finish_job(table, "j1", {
        "status": "succeeded", "session_id": "s1", "observation": "timed_out",
        "output": "x" * (lambda_handler.MAX_OUTPUT_BYTES + 1)})
    item = table.items[("J#j1", "JOB")]
    assert (item["status"], item["error"], item["session_id"], item["observation"]) == (
        "failed", "output_too_large", "s1", "timed_out")
    assert "output" not in item


# PBI #879 / Task #880: a turn that ends with `attempt_answer` (Enforcer Mode)
# returns its `answer` as the output.

def _attempt(answer):
    return ("attempt_answer", {"answer": answer, "confidence": "high", "sources_used": []})


@pytest.mark.asyncio
async def test_attempt_answer_is_returned_as_output(monkeypatch):
    from google.adk.tools import FunctionTool

    from dak_agent.builtin_tools import attempt_answer

    llm, _ = _scripted(_attempt("42"))
    _install(monkeypatch, llm, tools=[FunctionTool(attempt_answer)])
    result = await lambda_handler.run({"message": "the answer?", "state_delta": {"dak:tools": ["attempt_answer"]}})
    assert result == {"status": "succeeded", "output": "42"}


@pytest.mark.asyncio
async def test_job_output_is_the_attempt_answer(monkeypatch, table):
    from google.adk.tools import FunctionTool

    from dak_agent.builtin_tools import attempt_answer

    llm, _ = _scripted(_attempt("42"))
    _install(monkeypatch, llm, tools=[FunctionTool(attempt_answer)])
    await lambda_handler.run({"message": "the answer?", "job_id": "j1",
                              "state_delta": {"dak:tools": ["attempt_answer"]}}, _Context())
    got = await lambda_handler.run({"op": "get", "job_id": "j1"})
    assert (got["status"], got["output"]) == ("succeeded", "42")


@pytest.mark.asyncio
async def test_question_then_attempt_answer_returns_the_answer(monkeypatch, table):
    from google.adk.tools import FunctionTool

    from dak_agent.builtin_tools import ask_question, attempt_answer

    llm, _ = _scripted(("ask_question", {"questions": ["Which branch?"], "context": "Two match"}),
                       _attempt("deploying main"))
    _install(monkeypatch, llm, tools=[FunctionTool(ask_question), FunctionTool(attempt_answer)])
    waiting = await lambda_handler.run({"message": "deploy", "session_id": "s1",
                                        "state_delta": {"dak:tools": ["ask_question", "attempt_answer"]}},
                                       _Context())
    [item] = waiting["pending"]
    done = await lambda_handler.run({"op": "reply", "session_id": "s1", "approval_id": item["id"],
                                     "answer": "the main branch"}, _Context())
    assert done == {"status": "succeeded", "session_id": "s1", "output": "deploying main"}


@pytest.mark.asyncio
async def test_blocked_attempt_answer_is_not_the_output(monkeypatch, table):
    """The harness answers a call with missing arguments with an observation (no
    `error`); the tool did not run, so its `answer` is not the output."""
    from google.adk.apps import App
    from google.adk.tools import FunctionTool

    from dak_agent.builtin_tools import ask_question, attempt_answer
    from dak_agent.harness import ContextHarnessPlugin, HarnessSettings

    llm, _ = _scripted(("attempt_answer", {"answer": "42"}),
                       ("ask_question", {"questions": ["Which one?"], "context": "c"}))
    _install(monkeypatch, llm, tools=[FunctionTool(ask_question), FunctionTool(attempt_answer)])
    monkeypatch.setattr(lambda_handler, "_app_cache", App(
        name="dak_agent", root_agent=lambda_handler._app_cache.root_agent,
        plugins=[ContextHarnessPlugin(HarnessSettings(context_window=8192), "scripted")]))
    waiting = await lambda_handler.run({"message": "go", "session_id": "s1",
                                        "state_delta": {"dak:tools": ["ask_question", "attempt_answer"]}},
                                       _Context())
    assert (waiting["status"], waiting["output"]) == ("waiting", "")


# PBI #837 / Task #838: "stream": true writes the turn as NDJSON while it runs.

async def _stream(event, context=None):
    lines = []
    await lambda_handler.stream(event, context, lambda data: lines.append(json.loads(data)))
    return lines


@pytest.mark.asyncio
async def test_stream_writes_events_while_the_turn_runs_then_the_result(monkeypatch):
    from google.adk.tools import FunctionTool

    def lookup(q: str) -> str:
        """Look something up."""
        return "found " + q

    lines = []
    llm, _ = _scripted(("lookup", {"q": "x"}), "found it")
    written_before_call = []
    real = llm.__class__.generate_content_async

    async def counting(self, llm_request, stream=False):
        written_before_call.append(len(lines))
        async for r in real(self, llm_request, stream):
            yield r

    monkeypatch.setattr(llm.__class__, "generate_content_async", counting)
    _install(monkeypatch, llm, tools=[FunctionTool(lookup)])
    await lambda_handler.stream({"message": "find x", "stream": True,
                                 "state_delta": {"dak:tools": ["lookup"]}},
                                None, lambda data: lines.append(json.loads(data)))

    assert lines[-1] == {"status": "succeeded", "output": "found it"}
    events = [line["event"] for line in lines[:-1]]
    calls = [p["functionCall"]["name"] for e in events for p in e.get("content", {}).get("parts", [])
             if "functionCall" in p]
    assert calls == ["lookup"] and events[-1]["content"]["parts"][0]["text"] == "found it"
    assert written_before_call[1] >= 2  # the call and its result went out before the second LLM call


@pytest.mark.asyncio
async def test_stream_waits_on_a_confirmation_and_the_reply_streams_too(monkeypatch, table):
    from dak_agent.builtin_tools import make_builtin_tools

    monkeypatch.setenv("DAK_PLANNER_REQUIRE_CONFIRMATION", "true")
    llm, _ = _scripted(("planner", {"task_description": "tidy", "plan_steps": ["tidy"], "allowed_tools": []}),
                       "planned")
    _install(monkeypatch, llm, tools=make_builtin_tools())
    first = await _stream({"message": "tidy up", "session_id": "s1", "stream": True,
                           "state_delta": {"dak:tools": ["planner"]}}, _Context())
    waiting = first[-1]
    assert (waiting["status"], waiting["session_id"]) == ("waiting", "s1")
    [item] = waiting["pending"]
    assert all("event" in line for line in first[:-1]) and len(first) > 1

    second = await _stream({"op": "reply", "session_id": "s1", "approval_id": item["id"],
                            "mode": "once", "stream": True}, _Context())
    assert second[-1] == {"status": "succeeded", "session_id": "s1", "output": "planned"}
    assert all("event" in line for line in second[:-1]) and len(second) > 1
    assert len(_tool_results(table, "planner")) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("event", [
    {"message": "hi", "stream": True, "job_id": "j1"},
    {"message": "hi", "stream": "yes"},
    {"message": "hi", "stream": False}, {"message": "hi", "stream": 0},
    {"op": "get", "job_id": "j1", "stream": True},
    "hi"])
async def test_stream_refuses_a_job_and_a_non_boolean_without_calling_the_llm(monkeypatch, table, event):
    llm, requests = _llm()
    _install(monkeypatch, llm)
    assert await _stream(event, _Context()) == [{"status": "failed", "error": "invalid_event"}]
    assert requests == [] and table.writes == 0


@pytest.mark.asyncio
async def test_stream_asks_the_model_to_stream_and_writes_partial_text(monkeypatch):
    from google.adk.models._capabilities import LlmCapabilities
    from google.adk.models.base_llm import BaseLlm
    from google.adk.models.llm_response import LlmResponse

    asked = []

    class PartialLlm(BaseLlm):
        @property
        def capabilities(self) -> LlmCapabilities:
            return LlmCapabilities(output_schema_and_tools=True)

        async def generate_content_async(self, llm_request, stream=False):
            asked.append(stream)
            if stream:
                yield LlmResponse(content=types.Content(role="model", parts=[types.Part(text="hel")]), partial=True)
            yield LlmResponse(content=types.Content(role="model", parts=[types.Part(text="hello")]))

    _install(monkeypatch, PartialLlm(model="partial"))
    lines = await _stream({"message": "hi", "stream": True})
    assert asked == [True]
    texts = [(e["event"].get("partial", False), e["event"]["content"]["parts"][0]["text"])
             for e in lines[:-1] if "content" in e["event"]]
    assert texts == [(True, "hel"), (False, "hello")]
    assert lines[-1] == {"status": "succeeded", "output": "hello"}
    assert (await lambda_handler.run({"message": "hi"}))["output"] == "hello" and asked[-1] is False


# PBI #837 / Task #839: `parts` are attachments after the message.

_PNG = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
_ATTACHMENTS = [{"text": "notes.txt says hello"}, {"inlineData": {"mimeType": "image/png", "data": _PNG}}]


@pytest.mark.asyncio
async def test_attachments_follow_the_message_in_order(monkeypatch):
    import base64

    llm, requests = _llm()
    _install(monkeypatch, llm)
    assert (await lambda_handler.run({"message": "look", "parts": _ATTACHMENTS}))["status"] == "succeeded"
    parts = requests[0].contents[-1].parts
    assert [p.text for p in parts[:2]] == ["look", "notes.txt says hello"]
    assert (parts[2].inline_data.mime_type, parts[2].inline_data.data) == ("image/png", base64.b64decode(_PNG))


@pytest.mark.asyncio
async def test_an_answer_to_a_question_carries_attachments(monkeypatch, table):
    from google.adk.tools import FunctionTool

    from dak_agent.builtin_tools import ask_question

    llm, requests = _scripted(("ask_question", {"questions": ["Which file?"], "context": "c"}), "read it")
    _install(monkeypatch, llm, tools=[FunctionTool(ask_question)])
    waiting = await lambda_handler.run({"message": "go", "session_id": "s1",
                                        "state_delta": {"dak:tools": ["ask_question"]}}, _Context())
    done = await lambda_handler.run({"op": "reply", "session_id": "s1", "approval_id": waiting["pending"][0]["id"],
                                     "answer": "this one", "parts": _ATTACHMENTS[:1]}, _Context())
    assert done["status"] == "succeeded"
    assert "this one\nnotes.txt says hello" in _text(requests[-1])


@pytest.mark.asyncio
@pytest.mark.parametrize("parts", [
    [{"fileData": {"fileUri": "gs://bucket/x.png", "mimeType": "image/png"}}],
    [{"text": "a", "inlineData": {"mimeType": "image/png", "data": _PNG}}],
    [{"functionCall": {"name": "lookup", "args": {}}}],
    [{"inlineData": {"mimeType": "image/png"}}], [{"inlineData": {"data": _PNG}}],
    [{"text": 1}], [{}], {"text": "not a list"}, "text"])
async def test_attachment_other_than_text_or_inline_data_is_refused(monkeypatch, parts):
    llm, requests = _llm()
    _install(monkeypatch, llm)
    assert await lambda_handler.run({"message": "hi", "parts": parts}) == {
        "status": "failed", "error": "invalid_event"}
    assert requests == []


@pytest.mark.asyncio
async def test_attachment_values_are_not_logged(monkeypatch, caplog):
    llm, _ = _llm(error=RuntimeError("boom"))
    _install(monkeypatch, llm)
    with caplog.at_level(logging.DEBUG):
        result = await lambda_handler.run({"message": "hi", "parts": [{"text": "my-attachment"}]})
        refused = await lambda_handler.run({"message": "hi", "parts": [{"text": "my-other", "x": 1}]})
    assert result == {"status": "failed", "error": "RuntimeError"}
    assert refused == {"status": "failed", "error": "invalid_event"}
    assert "my-attachment" not in caplog.text and "my-other" not in caplog.text


@pytest.mark.asyncio
async def test_a_confirmation_reply_with_attachments_is_refused(monkeypatch, table):
    from dak_agent.builtin_tools import make_builtin_tools

    monkeypatch.setenv("DAK_PLANNER_REQUIRE_CONFIRMATION", "true")
    llm, requests = _scripted(("planner", {"task_description": "t", "plan_steps": ["t"], "allowed_tools": []}), "ok")
    _install(monkeypatch, llm, tools=make_builtin_tools())
    waiting = await lambda_handler.run({"message": "go", "session_id": "s1",
                                        "state_delta": {"dak:tools": ["planner"]}}, _Context())
    reply = {"op": "reply", "session_id": "s1", "mode": "once", "approval_id": waiting["pending"][0]["id"]}
    assert await lambda_handler.run({**reply, "parts": _ATTACHMENTS[:1]}, _Context()) == {
        "status": "failed", "error": "invalid_event"}
    assert len(requests) == 1 and _tool_results(table, "planner") == []
    assert (await lambda_handler.run(reply, _Context()))["status"] == "succeeded"  # still pending


@pytest.mark.asyncio
async def test_an_attachment_too_large_for_the_session_table_is_named(monkeypatch, table):
    import base64

    llm, requests = _llm()
    _install(monkeypatch, llm)
    big = base64.b64encode(b"x" * 400_000).decode()
    result = await lambda_handler.run({"message": "hi", "session_id": "s1",
                                       "parts": [{"inlineData": {"mimeType": "image/png", "data": big}}]}, _Context())
    assert result == {"status": "failed", "error": "event_too_large"}
    assert requests == []


# PBI #837 / Task #875: the caller's MCP servers, with an Authorization header
# held for the turn only.

_TOKEN = "Bearer test-token"


@pytest.fixture
def caller_mcp(monkeypatch):
    """A small MCP server (as in test_mcp_trace_context.py) that records the
    Authorization header of each request. The allow-list names its root with a
    trailing `/`, so its `/mcp` is allowed by prefix."""
    import socket
    import threading
    import time

    import uvicorn
    from mcp.server.mcpserver import MCPServer

    mcp = MCPServer("echo")

    @mcp.tool()
    async def echo(text: str) -> str:
        return "echoed " + text

    seen = []
    app = mcp.streamable_http_app(json_response=True)

    async def recording(scope, receive, send):
        if scope["type"] == "http":
            seen.append(dict(scope["headers"]).get(b"authorization", b"").decode())
        await app(scope, receive, send)

    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(recording, host="127.0.0.1", port=port, log_level="error"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while not server.started:
        assert time.monotonic() < deadline, "MCP server did not start"
        time.sleep(0.05)
    monkeypatch.setenv("DAK_ALLOWED_MCP_URLS", f"http://127.0.0.1:{port}/")
    yield f"http://127.0.0.1:{port}/mcp", seen
    server.should_exit = True
    thread.join(timeout=10)


@pytest.mark.asyncio
async def test_caller_mcp_gets_the_authorization_header_and_nothing_keeps_it(monkeypatch, table, caplog, caller_mcp):
    url, seen = caller_mcp
    llm, _ = _scripted(("echo", {"text": "hi"}), "done")
    _install(monkeypatch, llm)
    with caplog.at_level(logging.DEBUG):
        result = await lambda_handler.run({"message": "echo hi", "session_id": "s1",
                                           "mcp_servers": [{"url": url, "headers": {"Authorization": _TOKEN}}]},
                                          _Context())
    assert result == {"status": "succeeded", "session_id": "s1", "output": "done"}
    assert len(_tool_results(table, "echo")) == 1
    assert seen and set(seen) == {_TOKEN}  # the probe and the tool call
    assert "test-token" not in json.dumps(list(table.items.values()), default=str)
    assert "test-token" not in caplog.text


@pytest.mark.asyncio
async def test_a_later_call_without_headers_does_not_get_the_earlier_ones(monkeypatch, caller_mcp):
    url, seen = caller_mcp
    llm, _ = _scripted(("echo", {"text": "a"}), "one", ("echo", {"text": "b"}), "two")
    _install(monkeypatch, llm)
    first = await lambda_handler.run({"message": "1", "mcp_servers": [{"url": url, "headers": {"Authorization": _TOKEN}}]})
    count = len(seen)
    second = await lambda_handler.run({"message": "2", "mcp_servers": [{"url": url}]})
    assert (first["output"], second["output"]) == ("one", "two")
    assert set(seen[:count]) == {_TOKEN} and seen[count:] and set(seen[count:]) == {""}


@pytest.mark.asyncio
async def test_an_explicit_empty_mcp_servers_drops_the_servers_a_session_held(monkeypatch, table, caller_mcp):
    url, seen = caller_mcp
    llm, _ = _scripted(("echo", {"text": "a"}), "one", "two")
    _install(monkeypatch, llm)
    first = await lambda_handler.run({"message": "1", "session_id": "s1",
                                      "mcp_servers": [{"url": url, "headers": {"Authorization": _TOKEN}}]}, _Context())
    count = len(seen)
    second = await lambda_handler.run({"message": "2", "session_id": "s1", "mcp_servers": []}, _Context())
    assert (first["output"], second["output"]) == ("one", "two")
    assert len(seen) == count  # the second turn did not contact the earlier server


@pytest.mark.asyncio
async def test_caller_mcp_outside_the_allow_list_does_not_call_the_llm(monkeypatch, caller_mcp):
    _, seen = caller_mcp
    llm, requests = _llm()
    _install(monkeypatch, llm)
    result = await lambda_handler.run({"message": "hi", "mcp_servers": [{"url": "http://elsewhere:9000/mcp"}]})
    assert "mcp_server_not_allowed" in result["output"]
    assert requests == [] and seen == []


@pytest.mark.asyncio
@pytest.mark.parametrize("extra", [
    {"mcp_servers": {"url": "http://127.0.0.1/mcp"}},
    {"mcp_servers": [{"url": 1}]},
    {"mcp_servers": [{"url": "http://127.0.0.1/mcp", "type": "ws"}]},
    {"mcp_servers": [{"url": "http://127.0.0.1/mcp", "headers": {"Cookie": "x"}}]},
    {"mcp_servers": [{"url": "http://127.0.0.1/mcp", "headers": {"Authorization": 1}}]},
    {"mcp_servers": [{"url": "http://127.0.0.1/mcp", "headers": {"Authorization": "Bearer t\nX: y"}}]},
    {"mcp_servers": [{"url": "http://127.0.0.1/mcp", "headers": {"Authorization": "Bearer ｔ"}}]},
    {"mcp_servers": [{"url": "http://127.0.0.1/mcp", "headers": {"Authorization": "Bearer secret "}}]},  # h11 would echo it
    {"mcp_servers": [{"url": "http://127.0.0.1/mcp", "headers": {"Authorization": " Bearer secret"}}]},
    {"mcp_servers": [{"url": "http://127.0.0.1/mcp", "names": ["echo"]}]},
    {"mcp_servers": [{"url": f"http://127.0.0.1/mcp/{i}"} for i in range(9)]},  # more than CALLER_MCP_SERVERS_MAX
    {"mcp_servers": [{"url": "http://127.0.0.1/mcp"}], "state_delta": {"dak:tools": []}},
    {"mcp_servers": [], "state_delta": {"dak:tools": {"mcp_servers": [{"url": "http://127.0.0.1/mcp"}]}}}])
async def test_malformed_mcp_servers_are_an_invalid_event(monkeypatch, extra):
    llm, requests = _llm()
    _install(monkeypatch, llm)
    assert await lambda_handler.run({"message": "hi", **extra}) == {"status": "failed", "error": "invalid_event"}
    assert requests == []


@pytest.mark.asyncio
async def test_the_answer_to_a_question_carries_the_header_and_the_connections_are_closed(
        monkeypatch, table, caller_mcp):
    from google.adk.tools import FunctionTool

    from dak_agent.builtin_tools import ask_question

    url, seen = caller_mcp
    llm, _ = _scripted(("ask_question", {"questions": ["Which?"], "context": "c"}), ("echo", {"text": "a"}), "done")
    _install(monkeypatch, llm, tools=[FunctionTool(ask_question)])
    servers = [{"url": url, "headers": {"Authorization": _TOKEN}}]
    waiting = await lambda_handler.run({"message": "go", "session_id": "s1",
                                        "state_delta": {"dak:tools": ["ask_question"]}}, _Context())
    assert waiting["status"] == "waiting" and seen == []
    done = await lambda_handler.run({"op": "reply", "session_id": "s1", "approval_id": waiting["pending"][0]["id"],
                                     "answer": "this", "mcp_servers": servers}, _Context())
    assert done["output"] == "done" and len(_tool_results(table, "echo")) == 1
    assert seen and set(seen) == {_TOKEN}
    assert lambda_handler._app_cache.root_agent._caller_toolset_keys() == []  # closed after the turn


def test_caller_toolsets_are_bounded(monkeypatch):
    from dak_agent import adaptive_agent
    from dak_agent.adaptive_agent import AdaptiveAgent

    monkeypatch.setattr(adaptive_agent, "CALLER_MCP_TOOLSETS_MAX", 2)
    agent = AdaptiveAgent(model="m", name="dak_agent", instruction="Base.", tools=[])
    for task in range(3):
        url = f"https://caller.example/mcp/{task}"
        agent.hold_caller_toolsets([url])  # the Lambda path owns what it holds
        agent._cached_mcp_toolset(url, "http", (), follow_redirects=False)
        agent.release_caller_toolsets([url])
    agent._cached_mcp_toolset(agent.mcp_url, "http", set())  # the default server is not counted
    assert [k[0] for k in agent._caller_toolset_keys()] == [
        "https://caller.example/mcp/1", "https://caller.example/mcp/2"]
    assert any(k[0] == agent.mcp_url for k in agent._mcp_toolset_cache)


def test_a_toolset_a_running_call_uses_is_not_evicted(monkeypatch):
    from dak_agent import adaptive_agent
    from dak_agent.adaptive_agent import AdaptiveAgent

    monkeypatch.setattr(adaptive_agent, "CALLER_MCP_TOOLSETS_MAX", 1)
    agent = AdaptiveAgent(model="m", name="dak_agent", instruction="Base.", tools=[])
    busy = "https://caller.example/mcp/busy"
    agent.hold_caller_toolsets([busy])
    agent._cached_mcp_toolset(busy, "http", (), follow_redirects=False)
    for task in range(2):
        agent._cached_mcp_toolset(f"https://caller.example/mcp/{task}", "http", (), follow_redirects=False)
    assert busy in [k[0] for k in agent._caller_toolset_keys()]
    agent.release_caller_toolsets([busy])
    assert agent._caller_in_use == {}


def test_only_the_last_running_call_of_a_server_closes_it_and_the_dockers_toolsets_are_not_evicted(monkeypatch):
    from dak_agent import adaptive_agent
    from dak_agent.adaptive_agent import AdaptiveAgent

    monkeypatch.setattr(adaptive_agent, "CALLER_MCP_TOOLSETS_MAX", 1)
    agent = AdaptiveAgent(model="m", name="dak_agent", instruction="Base.", tools=[])
    url = "https://caller.example/mcp/shared"
    agent.hold_caller_toolsets([url])
    agent.hold_caller_toolsets([url])
    assert agent.release_caller_toolsets([url]) == []  # another call still runs
    assert agent.release_caller_toolsets([url]) == [url]
    for task in range(3):  # toolsets the Lambda path never held (the Docker server's) stay
        agent._cached_mcp_toolset(f"https://docker.example/mcp/{task}", "http", (), follow_redirects=False)
    assert len(agent._caller_toolset_keys()) == 3


@pytest.mark.asyncio
async def test_a_failing_app_start_is_a_structured_failure_and_leaves_no_header_context(monkeypatch):
    from dak_agent.call_config import CALLER_MCP_HEADERS

    def boom():
        raise RuntimeError("start failed")

    monkeypatch.setattr(lambda_handler, "_app", boom)
    result = await lambda_handler.run({"message": "hi", "mcp_servers": [
        {"url": "http://127.0.0.1/mcp", "headers": {"Authorization": _TOKEN}}]})
    assert result == {"status": "failed", "error": "RuntimeError"}
    assert CALLER_MCP_HEADERS.get() == {}


@pytest.mark.asyncio
async def test_closing_leaves_a_server_another_call_holds_and_forgets_the_urls_it_closed(monkeypatch):
    from dak_agent.adaptive_agent import AdaptiveAgent

    agent = AdaptiveAgent(model="m", name="dak_agent", instruction="Base.", tools=[])
    a, b = "https://caller.example/mcp/a", "https://caller.example/mcp/b"
    for url in (a, b):
        agent.hold_caller_toolsets([url])
        agent._cached_mcp_toolset(url, "http", (), follow_redirects=False)
    agent.hold_caller_toolsets([b])  # another call joins b
    await agent.close_caller_toolsets(agent.release_caller_toolsets([a, b]))
    assert [k[0] for k in agent._caller_toolset_keys()] == [b]  # b stays: that call has not ended
    assert agent._caller_owned == {b}
    await agent.close_caller_toolsets(agent.release_caller_toolsets([b]))
    assert agent._caller_toolset_keys() == [] and agent._caller_owned == set()


class _FakeSsm:
    def __init__(self, value="the-key-value", error=None):
        self.calls, self.value, self.error = [], value, error

    def get_parameter(self, Name, WithDecryption):
        self.calls.append((Name, WithDecryption))
        if self.error:
            raise self.error
        return {"Parameter": {"Value": self.value}}


@pytest.fixture
def ssm(monkeypatch):
    fake = _FakeSsm()
    monkeypatch.setattr(lambda_handler, "_ssm", lambda: fake)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    yield fake
    os.environ.pop("ANTHROPIC_API_KEY", None)  # set by the code under test, not by monkeypatch


@pytest.mark.asyncio
async def test_api_key_is_read_from_the_parameter_once(monkeypatch, ssm):
    monkeypatch.setenv("DAK_API_KEY_PARAMETER", "/some/parameter")
    llm, _ = _llm()
    _install(monkeypatch, llm)
    await lambda_handler.run({"message": "hi"})
    await lambda_handler.run({"message": "hi"})
    assert os.environ["ANTHROPIC_API_KEY"] == "the-key-value"
    assert ssm.calls == [("/some/parameter", True)]


@pytest.mark.asyncio
async def test_no_parameter_name_reads_nothing(monkeypatch, ssm):
    monkeypatch.delenv("DAK_API_KEY_PARAMETER", raising=False)
    llm, _ = _llm()
    _install(monkeypatch, llm)
    assert (await lambda_handler.run({"message": "hi"}))["status"] == "succeeded"
    assert ssm.calls == []


@pytest.mark.asyncio
async def test_unreadable_parameter_fails_without_calling_the_llm(monkeypatch, caplog, ssm):
    monkeypatch.setenv("DAK_API_KEY_PARAMETER", "/some/parameter")
    ssm.error = RuntimeError("denied")
    llm, requests = _llm()
    _install(monkeypatch, llm)
    with caplog.at_level(logging.DEBUG):
        result = await lambda_handler.run({"message": "hi"})
    assert result == {"status": "failed", "error": "RuntimeError"}
    assert requests == []


@pytest.mark.asyncio
async def test_key_value_is_not_logged(monkeypatch, caplog, ssm):
    monkeypatch.setenv("DAK_API_KEY_PARAMETER", "/some/parameter")
    llm, _ = _llm()
    _install(monkeypatch, llm)
    with caplog.at_level(logging.DEBUG):
        await lambda_handler.run({"message": "hi"})
    assert "the-key-value" not in caplog.text
