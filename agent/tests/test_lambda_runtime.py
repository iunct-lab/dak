"""PBI #837 / Task #838: the image's Runtime API loop (`lambda_runtime`) against
a fake Runtime API on a thread. A streamed event goes out chunk by chunk while
the turn runs; any other event is one JSON, as `awslambdaric` sent it."""
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from dak_agent import lambda_handler, lambda_runtime


class _FakeRuntimeApi:
    """Hands out `events` on /next and records what is posted back."""

    def __init__(self, events):
        self.events = list(events)
        self.posts = []  # (path, headers, [chunks]) — one entry per POST
        self.chunk_seen = threading.Event()
        api = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *args):
                pass

            def do_GET(self):
                body = json.dumps(api.events.pop(0)).encode()
                self.send_response(200)
                self.send_header("Lambda-Runtime-Aws-Request-Id", "req-1")
                self.send_header("Lambda-Runtime-Deadline-Ms", str(int(time.time() * 1000) + 60_000))
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_POST(self):
                chunks = []
                api.posts.append((self.path, dict(self.headers), chunks))
                if self.headers.get("Transfer-Encoding") == "chunked":
                    while (size := int(self.rfile.readline().strip(), 16)):
                        chunks.append(self.rfile.read(size))
                        self.rfile.readline()
                        api.chunk_seen.set()
                    self.rfile.readline()
                else:
                    chunks.append(self.rfile.read(int(self.headers["Content-Length"])))
                self.send_response(202)
                self.send_header("Content-Length", "0")
                self.end_headers()

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.address = f"127.0.0.1:{self.server.server_address[1]}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()


@pytest.fixture
def runtime_api():
    servers = []

    def make(*events):
        servers.append(_FakeRuntimeApi(events))
        return servers[-1]

    yield make
    for s in servers:
        s.server.shutdown()


def test_streamed_event_is_sent_chunk_by_chunk_before_the_turn_ends(monkeypatch, runtime_api):
    api = runtime_api({"message": "hi", "stream": True})

    async def fake_stream(event, context, write):
        write(b'{"event": {"author": "dak_agent"}}\n')
        # the turn goes on only once the first line has reached the Runtime API
        assert api.chunk_seen.wait(5), "the first line was held back until the end"
        write(b'{"status": "succeeded", "output": "ok"}\n')

    monkeypatch.setattr(lambda_handler, "stream", fake_stream)
    lambda_runtime.serve_one(api.address)

    [(path, headers, chunks)] = api.posts
    assert path == "/2018-06-01/runtime/invocation/req-1/response"
    assert headers["Lambda-Runtime-Function-Response-Mode"] == "streaming"
    assert headers["Transfer-Encoding"] == "chunked"
    assert [json.loads(c) for c in chunks] == [
        {"event": {"author": "dak_agent"}}, {"status": "succeeded", "output": "ok"}]


def test_event_without_stream_is_one_json_as_before(monkeypatch, runtime_api):
    api = runtime_api({"message": "hi"}, {"message": "hi", "stream": False}, {"message": "hi", "stream": None})
    seen = []

    def fake_handler(event, context):
        seen.append((event, context.get_remaining_time_in_millis() > 0))
        return {"status": "succeeded", "output": "ok"}

    monkeypatch.setattr(lambda_handler, "handler", fake_handler)
    for _ in range(3):
        lambda_runtime.serve_one(api.address)

    assert [ok for _, ok in seen] == [True, True, True]
    for path, headers, chunks in api.posts:
        assert path == "/2018-06-01/runtime/invocation/req-1/response"
        assert "Lambda-Runtime-Function-Response-Mode" not in headers
        assert json.loads(b"".join(chunks)) == {"status": "succeeded", "output": "ok"}


def test_a_stream_value_that_is_not_a_boolean_is_judged_by_stream(monkeypatch, runtime_api):
    api = runtime_api({"message": "hi", "stream": 0}, {"message": "hi", "stream": "yes"})
    monkeypatch.setattr(lambda_handler, "handler", lambda e, c: pytest.fail("ran as a plain call"))
    lambda_runtime.serve_one(api.address)
    lambda_runtime.serve_one(api.address)
    for _, headers, chunks in api.posts:
        assert headers["Lambda-Runtime-Function-Response-Mode"] == "streaming"
        assert [json.loads(c) for c in chunks] == [{"status": "failed", "error": "invalid_event"}]


def test_handler_exception_is_posted_to_error_with_the_class_only(monkeypatch, runtime_api, caplog):
    api = runtime_api({"message": "my-message"})

    def broken(event, context):
        raise ValueError(f"cannot handle {event['message']}")

    monkeypatch.setattr(lambda_handler, "handler", broken)
    lambda_runtime.serve_one(api.address)

    [(path, headers, chunks)] = api.posts
    assert path == "/2018-06-01/runtime/invocation/req-1/error"
    assert headers["Lambda-Runtime-Function-Error-Type"] == "ValueError"
    assert json.loads(b"".join(chunks)) == {"errorType": "ValueError", "errorMessage": "ValueError"}
    assert "my-message" not in caplog.text
