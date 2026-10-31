"""スキル x402 のツールのテスト。

有料サーバは httpx.MockTransport の偽物、Solana の RPC は tests/conftest.py の偽物で、実ネットワークには送らない。
鍵はテストの実行時に作る使い捨てのものだけ。
"""

import asyncio
import base64
import importlib.util
import ipaddress
import json
import os
import socket
from types import SimpleNamespace

import httpx
import pytest

from dak_agent import outbound_url
from dak_agent.permission import DEFAULT_RULES, PERSISTED_ALLOW_KEY, PermissionPlugin
from dak_agent.skill_registry import SkillRegistry

SKILLS_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "../..", "skills"))
_spec = importlib.util.spec_from_file_location(
    "x402_skill_tools", os.path.join(SKILLS_DIR, "x402", "tools.py")
)
tools = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(tools)

URL = "https://paid.example.com/data"
PAYMENT_REQUIRED = {
    "x402Version": 2,
    "resource": {"url": URL},
    "accepts": [
        {
            "scheme": "exact",
            "network": "solana:EtWTRABZaYq6iMfeYKouRu166VU2xqa1",
            "amount": "10000",
            "asset": "4zMMC9srt5Ri5X14GAgXhaHii3GnPAEERYPJgZJDncDU",
            "payTo": "2wKupLR9q6wXYppw8Gr2NvWxKBUqm4PPJKkQfoxHDBg4",
            "maxTimeoutSeconds": 60,
            "extra": {"feePayer": "EwWqGE4ZFKLofuestmU4LDdK7XM1N4ALgdZccwYugwGd"},
        }
    ],
}


@pytest.fixture
def paid_server(monkeypatch):
    """402 か 200 を返す偽の有料サーバ。受けた要求を requests に残す。"""
    requests: list[httpx.Request] = []
    state = {"status": 402}

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if "PAYMENT-SIGNATURE" in request.headers:
            settled = base64.b64encode(json.dumps({"success": True, "transaction": "tx1"}).encode()).decode()
            return httpx.Response(200, headers={"PAYMENT-RESPONSE": settled}, text="premium data")
        if state["status"] == 402:
            header = base64.b64encode(json.dumps(PAYMENT_REQUIRED).encode()).decode()
            return httpx.Response(402, headers={"PAYMENT-REQUIRED": header}, json={})
        return httpx.Response(200, text="premium data")

    class CheckedMock(httpx.MockTransport):
        """The real destination check, then the fake server (nothing leaves the process)."""

        def handle_request(self, request):
            outbound_url.check_outbound_url(str(request.url))
            return super().handle_request(request)

    dns = {}  # host -> address; any other host resolves to a public address

    def fake_getaddrinfo(host, port, *args, **kwargs):
        try:
            ipaddress.ip_address(host)
            addr = host  # a literal resolves to itself
        except ValueError:
            addr = dns.get(host, "93.184.216.34")
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (addr, port or 0))]

    monkeypatch.setattr(outbound_url.socket, "getaddrinfo", fake_getaddrinfo)
    monkeypatch.setattr(
        tools, "outbound_client",
        lambda **kw: httpx.Client(transport=CheckedMock(handler), follow_redirects=False, **kw),
    )
    return SimpleNamespace(requests=requests, state=state, dns=dns, handler=handler)


def _tool_context():
    return SimpleNamespace(state={})


def test_fetch_url_402_returns_observation_without_paying(paid_server):
    ctx = _tool_context()

    out = tools.fetch_url(URL, ctx)

    assert "Payment Required" in out
    for text in ("amount=10000", "asset=4zMMC9srt5Ri5X14GAgXhaHii3GnPAEERYPJgZJDncDU",
                 "network=solana:EtWTRABZaYq6iMfeYKouRu166VU2xqa1",
                 "payTo=2wKupLR9q6wXYppw8Gr2NvWxKBUqm4PPJKkQfoxHDBg4", "expires_in=60s"):
        assert text in out
    assert len(paid_server.requests) == 1
    assert not any("PAYMENT-SIGNATURE" in r.headers for r in paid_server.requests)
    [req] = ctx.state["dak_x402_requirements"][URL]
    assert req["amount"] == "10000" and req["pay_to"] == "2wKupLR9q6wXYppw8Gr2NvWxKBUqm4PPJKkQfoxHDBg4"


def test_fetch_url_402_keeps_other_urls_in_state(paid_server):
    ctx = _tool_context()
    ctx.state["dak_x402_requirements"] = {"https://other.example.com/": []}

    tools.fetch_url(URL, ctx)

    assert set(ctx.state["dak_x402_requirements"]) == {"https://other.example.com/", URL}


def test_fetch_url_200_returns_body(paid_server):
    paid_server.state["status"] = 200
    ctx = _tool_context()

    assert tools.fetch_url(URL, ctx) == "HTTP 200\npremium data"
    assert "dak_x402_requirements" not in ctx.state


def test_fetch_url_broken_402_reports_reason(monkeypatch):
    monkeypatch.setattr(
        tools, "outbound_client",
        lambda **kw: httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(402, text="pay")), **kw),
    )
    ctx = _tool_context()

    out = tools.fetch_url(URL, ctx)

    assert "could not be read" in out
    assert "dak_x402_requirements" not in ctx.state


def test_x402_skill_loads():
    registry = SkillRegistry([SKILLS_DIR])
    registry.load_skills()

    assert "fetch_url" in registry.skills["x402"]["tools"]


def test_fetch_url_does_not_follow_redirects(monkeypatch):
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(302, headers={"Location": "https://elsewhere.example.com/"})

    class CheckedMock(httpx.MockTransport):
        """The real destination check, then the fake server (nothing leaves the process)."""

        def handle_request(self, request):
            outbound_url.check_outbound_url(str(request.url))
            return super().handle_request(request)

    dns = {}  # host -> address; any other host resolves to a public address

    def fake_getaddrinfo(host, port, *args, **kwargs):
        addr = dns.get(host, "93.184.216.34")
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (addr, port or 0))]

    monkeypatch.setattr(outbound_url.socket, "getaddrinfo", fake_getaddrinfo)
    monkeypatch.setattr(
        tools, "outbound_client",
        lambda **kw: httpx.Client(transport=CheckedMock(handler), follow_redirects=False, **kw),
    )

    assert tools.fetch_url(URL, _tool_context()).startswith("HTTP 302")
    assert len(seen) == 1


@pytest.mark.parametrize("url", [
    "http://169.254.169.254/latest/meta-data/",
    "http://127.0.0.1:8001/mcp",
    "http://mcp-server:8000/mcp",
])
def test_fetch_url_refuses_internal_address_without_connecting(paid_server, url):
    out = tools.fetch_url(url, _tool_context())

    assert out.startswith("Not fetched:")
    assert paid_server.requests == []


def test_fetch_url_refuses_name_resolving_to_private(paid_server):
    paid_server.dns["internal.example.com"] = "10.0.0.5"

    out = tools.fetch_url("https://internal.example.com/data", _tool_context())

    assert out.startswith("Not fetched:") and "10.0.0.5" in out
    assert paid_server.requests == []


def test_fetch_url_refuses_non_http_scheme(paid_server):
    out = tools.fetch_url("file:///etc/passwd", _tool_context())

    assert out.startswith("Not fetched:")
    assert paid_server.requests == []


# --- pay_x402: PermissionPlugin's confirmation, then one signed resend ---

REQ = PAYMENT_REQUIRED["accepts"][0]
PAY_ARGS = {"url": URL, "network": REQ["network"], "asset": REQ["asset"], "amount": REQ["amount"], "pay_to": REQ["payTo"]}


@pytest.fixture
def wallet(monkeypatch, keypair, fake_solana_rpc):
    monkeypatch.setenv("SOLANA_PRIVATE_KEY", str(keypair))
    monkeypatch.setenv("SOLANA_RPC_URL", fake_solana_rpc["url"])
    return fake_solana_rpc


class _ConfirmContext(SimpleNamespace):
    """The parts of ADK's ToolContext that PermissionPlugin and the tools use."""

    def request_confirmation(self, hint=None, payload=None):
        self.requested = True


def _call_through_permission(ctx, confirmed):
    """PermissionPlugin's before_tool_callback, then pay_x402 only when it returns None (as ADK does)."""
    ctx.tool_confirmation = None if confirmed is None else SimpleNamespace(confirmed=confirmed, payload={"mode": "always"})
    plugin = PermissionPlugin(DEFAULT_RULES, "http://mcp-server:8000/mcp")
    blocked = asyncio.run(plugin.before_tool_callback(
        tool=SimpleNamespace(name="pay_x402"), tool_args=PAY_ARGS, tool_context=ctx,
    ))
    if blocked is not None:
        return blocked
    return tools.pay_x402(**PAY_ARGS, tool_context=ctx)


def _signed(paid_server):
    return [r for r in paid_server.requests if "PAYMENT-SIGNATURE" in r.headers]


@pytest.mark.parametrize("confirmed", [None, False], ids=["pending", "rejected"])
def test_pay_x402_not_approved_sends_nothing(paid_server, wallet, confirmed):
    ctx = _ConfirmContext(state={})
    tools.fetch_url(URL, ctx)

    out = _call_through_permission(ctx, confirmed)

    assert "error" in out
    assert len(paid_server.requests) == 1 and _signed(paid_server) == []
    assert wallet["calls"] == []  # nothing was signed (signing reads the RPC first)
    assert ctx.state["dak_x402_requirements"][URL]


def test_pay_x402_approved_resends_once_with_signature(paid_server, wallet):
    ctx = _ConfirmContext(state={})
    tools.fetch_url(URL, ctx)

    out = _call_through_permission(ctx, True)

    assert out.startswith("HTTP 200")
    assert '"transaction": "tx1"' in out and "premium data" in out
    [signed] = _signed(paid_server)
    assert len(paid_server.requests) == 2
    payload = json.loads(base64.b64decode(signed.headers["PAYMENT-SIGNATURE"]))
    assert payload["accepted"] == REQ
    assert set(payload["payload"]) == {"transaction"}
    # The requirement was used, and `always` was not remembered for a payment
    assert ctx.state["dak_x402_requirements"][URL] == []
    assert PERSISTED_ALLOW_KEY not in ctx.state


def test_pay_x402_does_not_pay_the_same_402_twice(paid_server, wallet):
    ctx = _ConfirmContext(state={})
    tools.fetch_url(URL, ctx)
    _call_through_permission(ctx, True)

    out = _call_through_permission(ctx, True)

    assert "Nothing was paid" in out
    assert len(_signed(paid_server)) == 1


@pytest.mark.parametrize("change", [{"amount": "1"}, {"pay_to": "Other1111111111111111111111111111111111111"},
                                    {"url": "https://paid.example.com/other"}])
def test_pay_x402_unknown_requirement_sends_nothing(paid_server, wallet, change):
    ctx = _ConfirmContext(state={})
    tools.fetch_url(URL, ctx)

    out = tools.pay_x402(**{**PAY_ARGS, **change}, tool_context=ctx)

    assert "Nothing was paid" in out
    assert len(paid_server.requests) == 1 and wallet["calls"] == []


def test_x402_requirements_are_dak_owned_state():
    from dak_agent.permission import owned_state_keys

    # server.py / lambda_handler.py refuse these keys from a caller, so no requirement can be planted
    assert owned_state_keys({tools.STATE_X402_REQUIREMENTS: {}}) == [tools.STATE_X402_REQUIREMENTS]


def test_pay_x402_timeout_still_uses_up_the_requirement(paid_server, wallet, monkeypatch):
    ctx = _ConfirmContext(state={})
    tools.fetch_url(URL, ctx)

    def timeout(*args, **kwargs):
        raise httpx.ReadTimeout("the server got the payment but did not answer")

    monkeypatch.setattr(tools, "retry_with_payment", timeout)
    with pytest.raises(httpx.ReadTimeout):
        tools.pay_x402(**PAY_ARGS, tool_context=ctx)

    assert ctx.state["dak_x402_requirements"][URL] == []
    assert "Nothing was paid" in tools.pay_x402(**PAY_ARGS, tool_context=ctx)


def test_pay_x402_unsignable_requirement_keeps_it(paid_server, wallet, monkeypatch):
    ctx = _ConfirmContext(state={})
    tools.fetch_url(URL, ctx)

    def refuse(*args, **kwargs):
        raise outbound_url.OutboundURLRefused("refused: resolves to 10.0.0.5")

    monkeypatch.setattr(tools, "retry_with_payment", refuse)
    out = tools.pay_x402(**PAY_ARGS, tool_context=ctx)

    assert out.startswith("Not paid: refused")
    assert len(ctx.state["dak_x402_requirements"][URL]) == 1
    assert _signed(paid_server) == []


def test_pay_x402_refuses_when_url_now_resolves_to_private(paid_server, wallet):
    ctx = _ConfirmContext(state={})
    tools.fetch_url(URL, ctx)  # paid.example.com resolves to a public address here
    paid_server.dns["paid.example.com"] = "10.0.0.5"  # and to a private one when paying

    out = tools.pay_x402(**PAY_ARGS, tool_context=ctx)

    assert out.startswith("Not paid: refused") and "10.0.0.5" in out
    assert wallet["calls"] == []  # nothing was signed (signing reads the RPC first)
    assert len(paid_server.requests) == 1 and _signed(paid_server) == []
    assert len(ctx.state["dak_x402_requirements"][URL]) == 1


def test_fetch_url_and_pay_x402_use_the_same_check(paid_server, wallet, monkeypatch):
    """Both tools go through the real outbound_client, whose transport calls check_outbound_url."""
    monkeypatch.setattr(tools, "outbound_client", outbound_url.outbound_client)
    checked = []
    real_check = outbound_url.check_outbound_url

    def counting_check(url):
        checked.append(url)
        return real_check(url)

    monkeypatch.setattr(outbound_url, "check_outbound_url", counting_check)
    # Below the pinned transport: answer with the fake server instead of connecting
    fake = httpx.MockTransport(paid_server.handler)
    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", lambda self, request: fake.handle_request(request))
    ctx = _ConfirmContext(state={})

    tools.fetch_url(URL, ctx)
    assert checked == [URL]
    out = tools.pay_x402(**PAY_ARGS, tool_context=ctx)

    assert out.startswith("HTTP 200")
    assert checked == [URL, URL, URL]  # pay_x402: before signing, then the pinned transport when sending
    # The connection went to the checked address, with the name kept for the server
    assert [r.url.host for r in paid_server.requests] == ["93.184.216.34", "93.184.216.34"]
    assert all(r.headers["host"] == "paid.example.com" for r in paid_server.requests)


def test_pay_x402_unreadable_key_sends_nothing(paid_server, wallet, monkeypatch):
    monkeypatch.setenv("SOLANA_PRIVATE_KEY", "not-a-key")
    ctx = _ConfirmContext(state={})
    tools.fetch_url(URL, ctx)

    out = tools.pay_x402(**PAY_ARGS, tool_context=ctx)

    assert out == "SOLANA_PRIVATE_KEY could not be read as a Solana key. Nothing was paid."
    assert "not-a-key" not in out
    assert len(paid_server.requests) == 1 and wallet["calls"] == []


def test_pay_x402_without_key_sends_nothing(paid_server, wallet, monkeypatch):
    monkeypatch.delenv("SOLANA_PRIVATE_KEY")
    ctx = _ConfirmContext(state={})
    tools.fetch_url(URL, ctx)

    out = tools.pay_x402(**PAY_ARGS, tool_context=ctx)

    assert out == "SOLANA_PRIVATE_KEY is not set. Nothing was paid."
    assert len(paid_server.requests) == 1 and wallet["calls"] == []


def test_x402_skill_lists_pay_x402():
    registry = SkillRegistry([SKILLS_DIR])
    registry.load_skills()

    assert "pay_x402" in registry.skills["x402"]["tools"]
