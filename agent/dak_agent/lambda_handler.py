"""Lambda entry point: one turn per invocation, no HTTP server.

Event: {"message": "<text>", "parts": [<genai Part: text | inline_data>]?,
        "state_delta": {"dak:...": ...}, "job_id": "<id>"?, "session_id": "<id>"?, "user_id": "<id>"?}
(`parts` are attachments, sent after the message, as /run_sse's new_message.parts.)
"mcp_servers": [{"url", "type"?, "headers"?: {"Authorization": ...}}] (also on a
reply) are the caller's MCP servers for this call: `dak:tools` gets the url and
type (the operator's DAK_ALLOWED_MCP_URLS decides), the headers are held for
this turn only (`call_config.CALLER_MCP_HEADERS`): not in the state, the table,
the logs or a result.
Result: {"status": "succeeded", "output": "<final text>"}
     (a turn that ends with `attempt_answer` returns its `answer` as the output)
     or {"status": "failed", "error": "<class name | invalid_event | ...>"}

With a `job_id` the call is a job: its state and result are kept in the DynamoDB
table `DAK_TABLE` (pk `J#<job_id>`, sk `JOB`, expires after a day), so an async
(Event) caller can poll with {"op": "get", "job_id": "<id>"}. The status is one of
running | succeeded | waiting | failed | timed_out | not_found.

Without a `session_id` each call runs in a throwaway InMemory session and writes
nothing. With one, the session (history, state, pending approvals and questions)
is kept in `DAK_TABLE` by `DynamoDbSessionService` and the next call with the same
id goes on from it; only one turn of a session runs at a time (`session_busy`).
A turn that stops on a confirmation or `ask_question` returns
{"status": "waiting", "session_id", "pending": [...]}, answered with
{"op": "reply", "session_id", "approval_id", "mode"? | "answer"?, "reason"?},
judged as `POST /approvals/{id}/reply` does (server.py).
With "stream": true (`stream()`, served by `lambda_runtime` for
InvokeWithResponseStream) the turn is written as NDJSON while it runs: one
{"event": <ADK Event, as /run_sse sends it>} line per event, partial text
included, then the result above as the last line. Not with a `job_id`.
If `DAK_API_KEY_PARAMETER` names an SSM parameter, its value is read once into
`ANTHROPIC_API_KEY` (the key itself is in no file, image or log).
Neither the message, the parts nor the state_delta values are logged or returned in errors.
Only the standard library is imported at module level: `dak_agent.agent` (telemetry,
Langfuse auth check, wallets) loads on the first call, not in Lambda's 10 s Init.
"""
import asyncio
import json
import logging
import os
import time
import uuid

logger = logging.getLogger(__name__)

_USER_ID = "lambda"
_app_cache = None
JOB_TTL_SECONDS = 24 * 3600
MAX_OUTPUT_BYTES = 350 * 1024  # DynamoDB's item limit is 400 KB
_loop = None  # one loop per container: the cached App may hold loop-bound async clients


def _ssm():
    """The SSM client. Tests replace this."""
    import boto3
    return boto3.client("ssm")


def _ensure_api_key() -> None:
    """Read the model API key from Parameter Store once per container.

    `DAK_API_KEY_PARAMETER` is the parameter's *name*; the value goes only into
    `ANTHROPIC_API_KEY` and is never logged or returned."""
    name = os.environ.get("DAK_API_KEY_PARAMETER")
    if not name or os.environ.get("ANTHROPIC_API_KEY"):
        return
    value = _ssm().get_parameter(Name=name, WithDecryption=True)["Parameter"]["Value"]
    os.environ["ANTHROPIC_API_KEY"] = value


def _app():
    global _app_cache
    if _app_cache is None:
        from .agent import app
        _app_cache = app
    return _app_cache


async def _run_turn(sessions, session, new_message: dict, state_delta: dict, emit=None) -> str:
    """Run the turn; `emit`, when given, gets each event as /run_sse sends it,
    partial text included."""
    from google.adk.agents.run_config import RunConfig, StreamingMode
    from google.adk.artifacts import InMemoryArtifactService
    from google.adk.runners import Runner
    from google.genai import types

    runner = Runner(app=_app(), session_service=sessions, artifact_service=InMemoryArtifactService())
    # No MCP server is deployed with the Lambda; do not wait for one that is
    # unreachable. A kept session already holds the caller's earlier choice.
    if "dak:tools" not in session.state:
        state_delta = {"dak:tools": [], **state_delta}
    output = ""
    answers = {}  # attempt_answer call id -> its `answer` argument
    async for event in runner.run_async(
        user_id=session.user_id,
        session_id=session.id,
        new_message=types.Content.model_validate({"role": "user", **new_message}),
        state_delta=state_delta or None,
        run_config=RunConfig(streaming_mode=StreamingMode.SSE) if emit else None,
    ):
        if emit:
            emit(event.model_dump(mode="json", by_alias=True, exclude_none=True))
        for call in event.get_function_calls():
            if call.name == "attempt_answer":
                answers[call.id] = (call.args or {}).get("answer")
        # Only a call that ran: ADK wraps its returned text as {"result": ...}. A call
        # that was refused or blocked ({"error"} / {"observation"}) did not answer.
        for resp in event.get_function_responses():
            if (resp.name == "attempt_answer" and "result" in (resp.response or {})
                    and isinstance(answers.get(resp.id), str)):
                output = answers[resp.id]
        if event.is_final_response() and event.content and event.content.parts:
            text = "".join(p.text for p in event.content.parts if p.text)
            if text:
                output = text
    return output


def _table():
    """The job table, or None when `DAK_TABLE` is not set. Tests replace this."""
    name = os.environ.get("DAK_TABLE")
    if not name:
        return None
    import boto3
    return boto3.resource("dynamodb").Table(name)


def _job_key(job_id: str) -> dict:
    return {"pk": f"J#{job_id}", "sk": "JOB"}


def _get_job(job_id) -> dict:
    if not isinstance(job_id, str) or not job_id:
        return {"status": "failed", "error": "invalid_event"}
    table = _table()
    if table is None:
        return {"status": "failed", "error": "table_not_configured"}
    item = table.get_item(Key=_job_key(job_id), ConsistentRead=True).get("Item")
    now = time.time()
    if not item or item.get("expires_at", now + 1) <= now:
        return {"job_id": job_id, "status": "not_found"}
    status = item["status"]
    if status == "running" and item.get("deadline", now + 1) < now:
        status = "timed_out"  # the Lambda was stopped by its timeout
    result = {"job_id": job_id, "status": status}
    for key in ("output", "error", "session_id", "observation"):
        if key in item:
            result[key] = item[key]
    if "pending" in item:
        result["pending"] = json.loads(item["pending"])
    return result


def _start_job(table, job_id: str, context) -> bool:
    from botocore.exceptions import ClientError
    now = time.time()
    remaining_ms = context.get_remaining_time_in_millis() if context else 15 * 60 * 1000
    try:
        table.put_item(
            Item={**_job_key(job_id), "status": "running", "started_at": int(now),
                  "deadline": int(now + remaining_ms / 1000), "expires_at": int(now + JOB_TTL_SECONDS)},
            ConditionExpression="attribute_not_exists(pk)",
        )
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") == "ConditionalCheckFailedException":
            return False
        raise
    return True


def _finish_job(table, job_id: str, result: dict) -> None:
    fields = {k: result[k] for k in ("status", "output", "error", "session_id", "observation") if k in result}
    if "pending" in result:  # floats are not DynamoDB numbers: keep the list as JSON
        fields["pending"] = json.dumps(result["pending"])
    if sum(len(fields[k].encode()) for k in ("output", "pending") if k in fields) > MAX_OUTPUT_BYTES:
        fields = {"status": "failed", "error": "output_too_large",
                  **{k: result[k] for k in ("session_id", "observation") if k in result}}
    table.update_item(
        Key=_job_key(job_id),
        UpdateExpression="SET " + ", ".join(f"#{k} = :{k}" for k in fields),
        ExpressionAttributeNames={f"#{k}": k for k in fields},
        ExpressionAttributeValues={f":{k}": v for k, v in fields.items()},
    )


async def run(event, context=None, emit=None) -> dict:
    if isinstance(event, dict) and event.get("op") == "get":
        return _get_job(event.get("job_id"))
    job_id = event.get("job_id") if isinstance(event, dict) else None
    if job_id is not None and (not isinstance(job_id, str) or not job_id):
        return {"status": "failed", "error": "invalid_event"}
    if job_id is None:
        return await _turn(event, context, emit)
    table = _table()
    if table is None:
        return {"status": "failed", "error": "table_not_configured"}
    if event.get("op") != "reply" and not isinstance(event.get("message"), str):
        return {"status": "failed", "error": "invalid_event"}
    try:
        started = _start_job(table, job_id, context)
    except Exception as exc:
        logger.error("job start failed: %s", type(exc).__name__)
        return {"status": "failed", "error": type(exc).__name__}
    if not started:
        return {"status": "failed", "error": "job_exists"}
    result = await _turn(event, context)
    try:
        _finish_job(table, job_id, result)
    except Exception as exc:
        logger.error("job update failed: %s", type(exc).__name__)
        return {"status": "failed", "error": type(exc).__name__}
    return result


async def _turn(event, context=None, emit=None) -> dict:
    if not isinstance(event, dict):
        return {"status": "failed", "error": "invalid_event"}
    session_id, user_id = event.get("session_id"), event.get("user_id", _USER_ID)
    if session_id is not None or event.get("op") == "reply":
        if not isinstance(session_id, str) or not session_id.strip() \
                or not isinstance(user_id, str) or not user_id:
            return {"status": "failed", "error": "invalid_event"}
    parts = _attachments(event.get("parts", []))
    if parts is None:
        return {"status": "failed", "error": "invalid_event"}
    if event.get("op") == "reply":
        if not _valid_reply(event):
            return {"status": "failed", "error": "invalid_event"}
        state_delta = {}
    else:
        message, state_delta = event.get("message"), event.get("state_delta", {})
        if not isinstance(message, str) or not isinstance(state_delta, dict):
            return {"status": "failed", "error": "invalid_event"}
        from .permission import owned_state_keys  # same refusal as server.py: no pre-approval via state_delta
        if owned_state_keys(state_delta):
            return {"status": "failed", "error": "invalid_event"}
    servers = _caller_mcp_servers(event.get("mcp_servers"))
    if servers is None or (isinstance(event.get("mcp_servers"), list) and "dak:tools" in state_delta):
        return {"status": "failed", "error": "invalid_event"}
    headers = {}
    if isinstance(event.get("mcp_servers"), list) and not servers and "dak:tools" not in state_delta:
        state_delta = {**state_delta, "dak:tools": []}  # an explicit [] drops the servers a kept session held
    if servers:
        state_delta = {**state_delta, "dak:tools": {"mcp_servers": [
            {"url": s["url"], "type": s["type"]} for s in servers]}}
        headers = {s["url"]: s["headers"] for s in servers if s["headers"]}
    from .call_config import CALLER_MCP_HEADERS
    held = agent = None
    try:
        _ensure_api_key()
        held = CALLER_MCP_HEADERS.set(headers)
        if servers:
            agent = _app().root_agent
            agent.hold_caller_toolsets([s["url"] for s in servers])
        if session_id is None:
            return await _throwaway_turn(_with(parts, {"parts": [{"text": message}]}), state_delta, emit)
        return await _session_turn(event, parts, user_id, session_id.strip(), state_delta, context, emit)
    except Exception as exc:  # the message may contain the request text: log the class only
        logger.error("turn failed: %s", type(exc).__name__)
        if isinstance(exc, ValueError) and str(exc) == "event_too_large":  # a kept event is one table item
            return {"status": "failed", "error": "event_too_large"}
        return {"status": "failed", "error": type(exc).__name__}
    finally:
        if held is not None:
            CALLER_MCP_HEADERS.reset(held)
        if agent is not None:  # do not keep the call's connections (and its headers) in the warm container
            try:  # a server another running call still uses stays open until that call ends
                await agent.close_caller_toolsets(agent.release_caller_toolsets([s["url"] for s in servers]))
            except Exception as exc:
                logger.error("closing the caller's MCP connections failed: %s", type(exc).__name__)


def _caller_mcp_servers(entries) -> list | None:
    """The event's `mcp_servers` as [{"url", "type", "headers"}] ([] when there
    are none), or None when one is malformed. Only `Authorization` may be sent."""
    if entries is None:
        return []
    from .adaptive_agent import CALLER_MCP_SERVERS_MAX

    if not isinstance(entries, list) or len(entries) > CALLER_MCP_SERVERS_MAX:
        return None
    servers = []
    for entry in entries:
        if not isinstance(entry, dict) or not set(entry) <= {"url", "type", "headers"}:
            return None
        url, conn_type, headers = entry.get("url"), entry.get("type", "http"), entry.get("headers", {})
        if (not isinstance(url, str) or not url.strip() or conn_type not in ("http", "sse")
                or not isinstance(headers, dict)
                or not all(k == "Authorization" and isinstance(v, str) and v.isascii() and v.isprintable()
                           and v == v.strip()
                           for k, v in headers.items())):  # a bad value would be echoed in errors
            return None
        servers.append({"url": url.strip(), "type": conn_type, "headers": headers})
    return servers


def _attachments(parts) -> list | None:
    """The `parts` of the event as genai Parts, or None when one is not a
    single `text` or `inline_data` (the values are not logged)."""
    from google.genai import types
    from pydantic import ValidationError

    if not isinstance(parts, list):
        return None
    out = []
    for item in parts:
        try:
            part = types.Part.model_validate(item)
        except ValidationError:
            return None
        if list(part.model_dump(exclude_none=True)) not in (["text"], ["inline_data"]):
            return None
        if part.inline_data and not (part.inline_data.data and part.inline_data.mime_type):
            return None
        out.append(part)
    return out


def _with(parts: list, message: dict) -> dict:
    """`message` with the attachments after its own parts."""
    return {**message, "parts": [*message["parts"], *parts]}


async def _throwaway_turn(message: dict, state_delta: dict, emit=None) -> dict:
    from google.adk.sessions import InMemorySessionService

    sessions = InMemorySessionService()
    session = await sessions.create_session(app_name=_app().name, user_id=_USER_ID,
                                            session_id=str(uuid.uuid4()))
    output = await _run_turn(sessions, session, message, state_delta, emit)
    return {"status": "succeeded", "output": output}


def _valid_reply(event: dict) -> bool:
    return (isinstance(event.get("approval_id"), str) and bool(event["approval_id"])
            and event.get("mode") in (None, "once", "always", "reject")
            # null is the same as leaving it out (server.py's `Reply` takes `answer: null`)
            and all(event.get(k) is None or isinstance(event[k], str) for k in ("reason", "answer")))


def _pending(session) -> list[dict]:
    """The session's pending items, as `GET /approvals` lists them (server.py)."""
    from . import approvals

    events = [e.model_dump(mode="json", by_alias=True, exclude_none=True) for e in session.events]
    return [{**p, "session_id": session.id,
             "status": "timed_out" if approvals.is_expired(p["requested_at"]) else "pending"}
            for p in approvals.list_pending(events)]


def _reply_message(event: dict, pending: list[dict]):
    """The new message that answers `approval_id`, judged as server.py's
    `reply`: (message, timed_out) or an error result."""
    from . import approvals

    by_id = {p["id"]: p for p in pending}
    item = by_id.get(event["approval_id"])
    if item is None:
        return {"status": "failed", "error": "not_found"}
    if item["kind"] == "question":
        if event.get("answer") is None:
            return {"status": "failed", "error": "invalid_event"}
        return approvals.build_question_reply(event["answer"]), False
    if event.get("mode") is None or event.get("parts"):  # ADK refuses text next to a confirmation
        return {"status": "failed", "error": "invalid_event"}
    timed_out = item["status"] == "timed_out"
    unanswered = [(pid, p["status"]) for pid, p in by_id.items()
                  if pid != item["id"] and p["kind"] == "approval"]
    return approvals.build_reply_function_response(
        item["id"], "timed_out" if timed_out else event["mode"],
        "" if timed_out else event.get("reason") or "", unanswered), timed_out


def _lock_key(app_name: str, user_id: str, session_id: str) -> dict:
    from .dynamodb_sessions import _session_pk
    return {"pk": _session_pk(app_name, user_id, session_id), "sk": "LOCK"}


def _lock(table, key: dict, context) -> str | None:
    """Take the session's lock until this invocation's deadline (a stopped
    Lambda cannot release it). The owner token, or None when it is held."""
    from botocore.exceptions import ClientError
    now = time.time()
    remaining_ms = context.get_remaining_time_in_millis() if context else 15 * 60 * 1000
    owner = str(uuid.uuid4())
    try:
        table.put_item(
            Item={**key, "owner": owner, "lock_until": int(now + remaining_ms / 1000) + 1,
                  "expires_at": int(now + JOB_TTL_SECONDS)},
            ConditionExpression="attribute_not_exists(pk) OR lock_until < :now",
            ExpressionAttributeValues={":now": int(now)},
        )
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") == "ConditionalCheckFailedException":
            return None
        raise
    return owner


def _unlock(table, key: dict, owner: str) -> None:
    from botocore.exceptions import ClientError
    try:
        table.delete_item(Key=key, ConditionExpression="#o = :o",
                          ExpressionAttributeNames={"#o": "owner"},
                          ExpressionAttributeValues={":o": owner})
    except ClientError as exc:  # expired and taken by a later turn: theirs now
        if exc.response.get("Error", {}).get("Code") != "ConditionalCheckFailedException":
            raise


async def _session_turn(event: dict, parts: list, user_id: str, session_id: str, state_delta: dict,
                        context, emit=None) -> dict:
    from .dynamodb_sessions import DynamoDbSessionService

    table = _table()
    if table is None:
        return {"status": "failed", "error": "table_not_configured"}
    app_name = _app().name
    key = _lock_key(app_name, user_id, session_id)
    owner = _lock(table, key, context)
    if owner is None:
        return {"status": "failed", "error": "session_busy"}
    try:
        sessions = DynamoDbSessionService(table)
        ids = dict(app_name=app_name, user_id=user_id, session_id=session_id)
        session = await sessions.get_session(**ids)
        timed_out = False
        if event.get("op") == "reply":
            if session is None:
                return {"status": "failed", "error": "not_found"}
            answer = _reply_message(event, _pending(session))
            if isinstance(answer, dict):
                return answer
            message, timed_out = answer
        else:
            session = session or await sessions.create_session(**ids)
            message = {"parts": [{"text": event["message"]}]}
        output = await _run_turn(sessions, session, _with(parts, message), state_delta, emit)
        pending = _pending(await sessions.get_session(**ids))
    finally:
        try:
            _unlock(table, key, owner)
        except Exception as exc:  # the turn is kept: report it; the lock expires at lock_until
            logger.error("session unlock failed: %s", type(exc).__name__)
    result = {"status": "waiting" if pending else "succeeded", "session_id": session_id, "output": output}
    if pending:
        result["pending"] = pending
    if timed_out:  # resumed with a `timed_out` answer, as server.py's 409: do not answer again
        result["observation"] = "timed_out"
    return result


def _line(obj: dict) -> bytes:
    return json.dumps(obj).encode() + b"\n"


async def stream(event, context, write) -> None:
    """The turn as NDJSON: `write(bytes)` gets an {"event": ...} line per event,
    then the result of `run()` as the last line."""
    if (not isinstance(event, dict) or event.get("stream") is not True
            or event.get("job_id") is not None):  # an Event call's response is dropped
        write(_line({"status": "failed", "error": "invalid_event"}))
        return
    write(_line(await run(event, context, emit=lambda e: write(_line({"event": e})))))


def run_sync(coro):
    """Run `coro` on the container's one event loop."""
    global _loop
    if _loop is None or _loop.is_closed():
        _loop = asyncio.new_event_loop()
    return _loop.run_until_complete(coro)


def handler(event, context=None):
    return run_sync(run(event, context))
