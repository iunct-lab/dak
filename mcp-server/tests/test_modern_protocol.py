"""2026-07-28 版の MCP クライアントが、セッションなしでこのサーバを使えること（#322, #324）。

mcp 2.x の `Client` を `mode="2026-07-28"` に固定し（旧仕様の `initialize` に切り替えない）、
httpx2 の ASGI トランスポートで `create_app()` のアプリにつなぐ。
"""
import asyncio
import contextlib
import os
import sys
import tempfile
import unittest

import httpx2
from mcp import Client
from mcp.client.streamable_http import streamable_http_client

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import main

MODERN = "2026-07-28"
URL = "http://localhost:8001/mcp"


@contextlib.asynccontextmanager
async def _modern_client(app, seen: list):
    """A pinned 2026-07-28 client on `app`; `seen` gets (Mcp-Method, status, Mcp-Session-Id) per response."""
    async def record(resp):
        seen.append((resp.request.headers.get("mcp-method"), resp.status_code, resp.headers.get("mcp-session-id")))

    http = httpx2.AsyncClient(
        transport=httpx2.ASGITransport(app=app), base_url="http://localhost:8001", event_hooks={"response": [record]}
    )
    async with http, Client(streamable_http_client(URL, http_client=http), mode=MODERN) as client:
        yield client


class TestModernProtocol(unittest.TestCase):
    def setUp(self):
        fd, self.path = tempfile.mkstemp(suffix=".txt")
        with os.fdopen(fd, "w") as f:
            f.write("hello 2026-07-28")
        self.addCleanup(os.remove, self.path)

    def test_stateless_discover_list_call(self):
        seen = []

        async def run():
            app = main.create_app()
            async with app.router.lifespan_context(app), _modern_client(app, seen) as client:
                discover = await client.session.send_discover(MODERN)
                tools = await client.list_tools()
                result = await client.call_tool("read_file", {"path": self.path})
            return discover, tools, result

        discover, tools, result = asyncio.run(run())
        self.assertIn(MODERN, discover["supportedVersions"])
        self.assertIn("read_file", [t.name for t in tools.tools])
        self.assertFalse(result.is_error)
        self.assertEqual(result.content[0].text, "hello 2026-07-28")
        self.assertEqual([m for m, _, _ in seen], ["server/discover", "tools/list", "tools/call"])
        self.assertTrue(all(status == 200 and sid is None for _, status, sid in seen), seen)

    def test_two_instances(self):
        """List on one app, call on another: no state is shared, as behind a load balancer."""
        seen_first, seen_second = [], []

        async def run():
            first, second = main.create_app(), main.create_app()
            async with first.router.lifespan_context(first), second.router.lifespan_context(second):
                async with _modern_client(first, seen_first) as client:
                    tools = await client.list_tools()
                async with _modern_client(second, seen_second) as client:
                    result = await client.call_tool("read_file", {"path": self.path})
            return tools, result

        tools, result = asyncio.run(run())
        self.assertIn("read_file", [t.name for t in tools.tools])
        self.assertFalse(result.is_error)
        self.assertEqual(result.content[0].text, "hello 2026-07-28")
        self.assertEqual([m for m, _, _ in seen_first], ["tools/list"])
        # The second app gets the call before any listing (the SDK may list afterwards).
        self.assertEqual(seen_second[0][0], "tools/call")
        seen = seen_first + seen_second
        self.assertTrue(all(status == 200 and sid is None for _, status, sid in seen), seen)


if __name__ == "__main__":
    unittest.main()
