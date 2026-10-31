import dak_maintenance.search as search_mod
from dak_maintenance.search import web_search


def test_no_key_returns_empty_and_does_not_scrape(monkeypatch):
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    called = {"n": 0}

    def fake_post(*a, **k):
        called["n"] += 1
        raise AssertionError("must not make any HTTP call without a Tavily key")

    monkeypatch.setattr(search_mod.httpx, "post", fake_post)
    assert web_search("anything") == []
    assert called["n"] == 0  # no network at all -> no scraping


def test_tavily_parses_results(monkeypatch):
    monkeypatch.setenv("TAVILY_API_KEY", "tvly-test")

    class FakeResp:
        def raise_for_status(self):
            pass

        def json(self):
            return {"results": [
                {"title": "MCP spec", "url": "http://mcp", "content": "new transport"},
                {"title": "A2A", "url": "http://a2a", "content": "agent2agent"},
            ]}

    def fake_post(url, json, timeout):
        assert url == search_mod.TAVILY_ENDPOINT
        assert json["api_key"] == "tvly-test"
        assert json["query"] == "mcp"
        return FakeResp()

    monkeypatch.setattr(search_mod.httpx, "post", fake_post)
    results = web_search("mcp", k=5)
    assert [r.url for r in results] == ["http://mcp", "http://a2a"]
    assert results[0].snippet == "new transport"


def test_tavily_failure_fails_soft(monkeypatch):
    monkeypatch.setenv("TAVILY_API_KEY", "tvly-test")

    def boom(*a, **k):
        raise RuntimeError("503")

    monkeypatch.setattr(search_mod.httpx, "post", boom)
    assert web_search("mcp") == []
