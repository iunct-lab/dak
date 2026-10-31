"""Provider-neutral web search via the Tavily API, decoupled from the LLM provider.

Tavily only. We deliberately do NOT scrape DuckDuckGo/Google HTML — that violates
their terms of service. If TAVILY_API_KEY is unset, search returns [] (so the
pipeline simply yields no proposals) instead of falling back to scraping.

The search key is independent of the LLM key, so the LLM stays swappable
(Gemini / Ollama / OpenAI / …) while web search remains ToS-compliant.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass

import httpx

logger = logging.getLogger(__name__)

TAVILY_ENDPOINT = "https://api.tavily.com/search"


@dataclass
class SearchResult:
    title: str
    url: str
    snippet: str


def web_search(query: str, k: int = 5, timeout: float = 15.0) -> list[SearchResult]:
    """Search the web via Tavily. Fails soft (returns []) with no key or on error."""
    key = os.getenv("TAVILY_API_KEY")
    if not key:
        logger.warning("TAVILY_API_KEY 未設定のため Web 検索をスキップ（提案は 0 件になります）。")
        return []
    try:
        r = httpx.post(
            TAVILY_ENDPOINT,
            json={"api_key": key, "query": query, "max_results": k, "search_depth": "basic"},
            timeout=timeout,
        )
        r.raise_for_status()
        results = r.json().get("results", [])
    except Exception as e:  # noqa: BLE001 - search failure must not crash the workflow
        logger.warning("Tavily 検索に失敗: %s", e)
        return []
    return [
        SearchResult(
            title=item.get("title", ""),
            url=item.get("url", ""),
            snippet=item.get("content", ""),
        )
        for item in results[:k]
    ]
