"""The Lambda image's entry: Lambda's Runtime API, read with the standard library.

Python's managed runtime (`awslambdaric`) cannot stream a response, so this loop
takes its place (agent/Dockerfile.lambda). An event with "stream" (other than
false or null; any other non-boolean gets `stream()`'s invalid_event line) is answered with a streamed response, InvokeWithResponseStream's
`Lambda-Runtime-Function-Response-Mode: streaming` with chunked encoding: one
chunk per line of `lambda_handler.stream()`. Any other event is answered with
`lambda_handler.handler()`'s result as one JSON, as before.

An exception from `handler()` is posted to the invocation's /error with its
class name only (the event may hold the request text). A streamed turn that
fails says so in its last line (`failed`), not as an error.
"""
import http.client
import json
import logging
import os
import time

from . import lambda_handler

logger = logging.getLogger(__name__)

_BASE = "/2018-06-01/runtime/invocation"


class _Context:
    """The part of Lambda's context object the handler reads."""

    def __init__(self, request_id: str, deadline_ms: int):
        self.aws_request_id = request_id
        self._deadline_ms = deadline_ms

    def get_remaining_time_in_millis(self) -> int:
        return max(0, self._deadline_ms - int(time.time() * 1000))


def _post(api: str, path: str, body: bytes, headers: dict | None = None) -> None:
    conn = http.client.HTTPConnection(api)
    try:
        conn.request("POST", path, body=body, headers=headers or {})
        conn.getresponse().read()
    finally:
        conn.close()


def _stream(api: str, request_id: str, event: dict, context: _Context) -> None:
    conn = http.client.HTTPConnection(api)
    try:
        conn.putrequest("POST", f"{_BASE}/{request_id}/response")
        conn.putheader("Lambda-Runtime-Function-Response-Mode", "streaming")
        conn.putheader("Transfer-Encoding", "chunked")
        conn.putheader("Content-Type", "application/x-ndjson")
        conn.endheaders()

        def write(data: bytes) -> None:
            conn.send(b"%X\r\n%s\r\n" % (len(data), data))

        lambda_handler.run_sync(lambda_handler.stream(event, context, write))
        conn.send(b"0\r\n\r\n")
        conn.getresponse().read()
    finally:
        conn.close()


def serve_one(api: str) -> None:
    """Take the next invocation and answer it."""
    conn = http.client.HTTPConnection(api)
    try:
        conn.request("GET", f"{_BASE}/next")
        resp = conn.getresponse()
        body = resp.read()
        request_id = resp.getheader("Lambda-Runtime-Aws-Request-Id")
        context = _Context(request_id, int(resp.getheader("Lambda-Runtime-Deadline-Ms") or 0))
    finally:
        conn.close()
    try:
        event = json.loads(body)
        streaming = isinstance(event, dict) and event.get("stream") is not None and event.get("stream") is not False
        if not streaming:
            payload = json.dumps(lambda_handler.handler(event, context)).encode()
    except Exception as exc:  # the event may hold the request text: the class only
        name = type(exc).__name__
        logger.error("invocation failed: %s", name)
        _post(api, f"{_BASE}/{request_id}/error",
              json.dumps({"errorType": name, "errorMessage": name}).encode(),
              {"Lambda-Runtime-Function-Error-Type": name})
        return
    if not streaming:
        _post(api, f"{_BASE}/{request_id}/response", payload)
        return
    try:
        _stream(api, request_id, event, context)
    except Exception as exc:  # the response has started (or the caller left): nothing to post
        logger.error("stream failed: %s", type(exc).__name__)


def main() -> None:
    api = os.environ["AWS_LAMBDA_RUNTIME_API"]
    while True:
        serve_one(api)


if __name__ == "__main__":
    main()
