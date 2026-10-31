"""確認を MRTR（SEP-2322 の入力要求の往復）で聞く試作ツール `confirm_probe`（#327、PBI #326）。

`MCP_EXPERIMENTAL_MRTR=true` のときだけ登録される。2026-07-28 版のクライアントには
`input_required` を返し、`inputResponses` の答えで実行/中止に分かれること、旧仕様の
セッションでは SDK が `elicitation/create` に切り替えること（SSE で応答するときだけ届き、
DAK の `json_response=True` では届かない）を確かめる。
"""
import asyncio
import contextlib
import os
import socket
import sys
import tempfile
import unittest
from unittest import mock

import httpx2
import pytest
import uvicorn
from mcp import Client
from mcp.client.streamable_http import streamable_http_client
from mcp.server.mcpserver import MCPServer
from mcp_types import ElicitResult, InputRequiredResult
from starlette.applications import Starlette
from starlette.routing import Mount

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import main

MODERN = "2026-07-28"
URL = "http://localhost:8001/mcp"


@contextlib.asynccontextmanager
async def _client(app, mode, elicitation_callback=None):
    http = httpx2.AsyncClient(transport=httpx2.ASGITransport(app=app), base_url="http://localhost:8001")
    async with http, Client(
        streamable_http_client(URL, http_client=http), mode=mode, elicitation_callback=elicitation_callback
    ) as client:
        yield client


async def _unused_callback(context, params):
    raise AssertionError("the 2026-07-28 client is driven by hand here; the callback must not run")


def _run(coro_fn, enabled=True):
    async def run():
        with mock.patch.dict(os.environ):
            os.environ.pop("MCP_EXPERIMENTAL_MRTR", None)
            if enabled:
                os.environ["MCP_EXPERIMENTAL_MRTR"] = "true"
            app = main.create_app()
        async with app.router.lifespan_context(app):
            return await coro_fn(app)

    return asyncio.run(run())


class TestMrtrProbe(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.target = os.path.join(tmp.name, "probe.txt")
        patcher = mock.patch.object(tempfile, "tempdir", os.path.realpath(tmp.name))  # the probe's temp directory
        patcher.start()
        self.addCleanup(patcher.stop)

    async def _first_round(self, client):
        return await client.session.call_tool("confirm_probe", {"path": self.target}, allow_input_required=True)

    async def _answer(self, client, first, content):
        key = next(iter(first.input_requests))
        return await client.session.call_tool(
            "confirm_probe",
            {"path": self.target},
            input_responses={key: ElicitResult(action="accept", content=content)},
            request_state=first.request_state,
        )

    def test_probe_hidden_by_default(self):
        async def body(app):
            async with _client(app, MODERN) as client:
                return await client.list_tools()

        tools = _run(body, enabled=False)
        names = [t.name for t in tools.tools]
        self.assertIn("read_file", names)
        self.assertNotIn("confirm_probe", names)

    def test_probe_refuses_path_outside_tmp(self):
        allowed = os.path.join(os.path.dirname(self.target), "allowed")
        os.mkdir(allowed)

        async def body(app):
            async with _client(app, MODERN, _unused_callback) as client:
                first = await self._first_round(client)
                return await self._answer(client, first, {"proceed": True})

        with mock.patch.object(tempfile, "tempdir", allowed):  # the target is now outside the temp directory
            result = _run(body)
        self.assertTrue(result.content[0].text.startswith("Error: path must be a file directly in "), result)
        self.assertFalse(os.path.exists(self.target))

    def test_probe_refuses_subdirectory(self):
        """Only a file directly in the temp directory: a parent below it could be swapped for a link."""
        sub = os.path.join(os.path.dirname(self.target), "sub")
        os.mkdir(sub)
        self.target = os.path.join(sub, "probe.txt")

        async def body(app):
            async with _client(app, MODERN, _unused_callback) as client:
                first = await self._first_round(client)
                return await self._answer(client, first, {"proceed": True})

        result = _run(body)
        self.assertTrue(result.content[0].text.startswith("Error: path must be a file directly in "), result)
        self.assertFalse(os.path.exists(self.target))

    def test_probe_does_not_overwrite(self):
        """An existing file (or a hard link to one) is never truncated."""
        outside = os.path.join(os.path.dirname(self.target), "outside.txt")
        with open(outside, "w") as f:
            f.write("keep\n")
        os.link(outside, self.target)

        async def body(app):
            async with _client(app, MODERN, _unused_callback) as client:
                first = await self._first_round(client)
                return await self._answer(client, first, {"proceed": True})

        result = _run(body)
        self.assertEqual(result.content[0].text, f"Error: {self.target} already exists.")
        with open(outside) as f:
            self.assertEqual(f.read(), "keep\n")

    def test_probe_input_required(self):
        async def body(app):
            async with _client(app, MODERN, _unused_callback) as client:
                self.assertIn("confirm_probe", [t.name for t in (await client.list_tools()).tools])
                return await self._first_round(client)

        first = _run(body)
        self.assertIsInstance(first, InputRequiredResult)
        self.assertTrue(first.request_state)
        (request,) = first.input_requests.values()
        self.assertEqual(request.method, "elicitation/create")
        self.assertIn(self.target, request.params.message)
        self.assertIn("proceed", request.params.requested_schema["properties"])
        self.assertFalse(os.path.exists(self.target))

    def test_probe_proceed(self):
        async def body(app):
            async with _client(app, MODERN, _unused_callback) as client:
                first = await self._first_round(client)
                return await self._answer(client, first, {"proceed": True})

        result = _run(body)
        self.assertFalse(result.is_error)
        self.assertEqual(result.content[0].text, f"Executed: wrote {self.target}")
        with open(self.target) as f:
            self.assertEqual(f.read(), "confirm_probe\n")

    def test_probe_decline(self):
        async def body(app):
            async with _client(app, MODERN, _unused_callback) as client:
                first = await self._first_round(client)
                return await self._answer(client, first, {"proceed": False, "reason": "not now"})

        result = _run(body)
        self.assertFalse(result.is_error)
        self.assertEqual(result.content[0].text, "Not executed: not now")
        self.assertFalse(os.path.exists(self.target))

    def test_probe_answer_is_bound_to_the_path(self):
        """A "yes" for one path does not authorize another: the SDK rejects the old requestState."""
        other = os.path.join(os.path.dirname(self.target), "other.txt")

        async def body(app):
            async with _client(app, MODERN, _unused_callback) as client:
                first = await self._first_round(client)
                key = next(iter(first.input_requests))
                with self.assertRaisesRegex(Exception, "Invalid or expired requestState"):
                    await client.session.call_tool(
                        "confirm_probe",
                        {"path": other},
                        input_responses={key: ElicitResult(action="accept", content={"proceed": True})},
                        request_state=first.request_state,
                    )

        _run(body)
        self.assertFalse(os.path.exists(other))
        self.assertFalse(os.path.exists(self.target))

    def test_probe_rejected_question(self):
        """A declined question (the user refuses to answer) does not run the tool either."""
        async def body(app):
            async with _client(app, MODERN, _unused_callback) as client:
                first = await self._first_round(client)
                key = next(iter(first.input_requests))
                return await client.session.call_tool(
                    "confirm_probe",
                    {"path": self.target},
                    input_responses={key: ElicitResult(action="decline")},
                    request_state=first.request_state,
                )

        result = _run(body)
        self.assertFalse(result.is_error)
        self.assertEqual(result.content[0].text, "Not executed: decline")
        self.assertFalse(os.path.exists(self.target))

    @pytest.mark.xfail(
        strict=True,
        reason="The SDK does switch to `elicitation/create` (no -32603), but this server answers with "
        "json_response=True (no SSE stream), so the request has no back-channel: 'this transport context "
        "has no back-channel for server-initiated requests'. Same finding as #328 on the agent side.",
    )
    def test_probe_legacy_session(self):
        """On a pre-2026 session the SDK asks with a standalone `elicitation/create` (no -32603)."""
        asked = []

        async def answer(context, params):
            asked.append(params.message)
            return ElicitResult(action="accept", content={"proceed": True})

        async def body(app):
            async with _client(app, "legacy", answer) as client:
                return await client.call_tool("confirm_probe", {"path": self.target})

        result = _run(body)
        self.assertFalse(result.is_error, result)
        self.assertEqual(len(asked), 1)
        self.assertIn(self.target, asked[0])
        self.assertTrue(os.path.exists(self.target))

    def test_probe_legacy_session_over_sse(self):
        """With SSE responses (json_response=False) the legacy `elicitation/create` reaches the client.

        A real uvicorn: httpx2's ASGITransport does not stream an SSE response mid-call.
        """
        asked = []

        async def answer(context, params):
            asked.append(params.message)
            return ElicitResult(action="accept", content={"proceed": True})

        async def run():
            server = MCPServer("probe")
            server.add_tool(main.confirm_probe)
            app = Starlette(
                routes=[Mount("/", app=server.streamable_http_app(json_response=False))],
                lifespan=lambda app: server.session_manager.run(),
            )
            sock = socket.socket()
            sock.bind(("127.0.0.1", 0))  # uvicorn serves on this socket: no window for another process
            port = sock.getsockname()[1]
            uv = uvicorn.Server(uvicorn.Config(app, log_level="warning"))
            serving = asyncio.create_task(uv.serve(sockets=[sock]))
            try:
                while not uv.started:
                    if serving.done():
                        serving.result()  # the startup error, not a timeout
                    await asyncio.sleep(0.05)
                async with Client(
                    streamable_http_client(f"http://127.0.0.1:{port}/mcp"), mode="legacy", elicitation_callback=answer
                ) as client:
                    return await client.call_tool("confirm_probe", {"path": self.target})
            finally:
                uv.should_exit = True
                await serving

        result = asyncio.run(asyncio.wait_for(run(), 30))
        self.assertFalse(result.is_error, result)
        self.assertEqual(result.content[0].text, f"Executed: wrote {self.target}")
        self.assertEqual(len(asked), 1)
        self.assertIn(self.target, asked[0])


if __name__ == "__main__":
    unittest.main()
