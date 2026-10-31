"""charter-review pipeline: propose revisions to the purpose charter (quarterly)."""

from __future__ import annotations

from typing import Callable

from .jsonutil import extract_json
from .proposals import Proposal, dedupe
from .search import SearchResult, web_search
from .watch import gather_candidates

CompleteFn = Callable[[str], str]
SearchFn = Callable[[str, int], list[SearchResult]]

_QUERIES = [
    "agent framework 2026 new",
    "A2A agent-to-agent protocol update",
    "Model Context Protocol MCP new spec",
    "multi-LLM routing framework",
    "AI agent sandbox security",
]

_PROMPT = """You perform a quarterly review of a project's purpose charter.
Current charter:
---
{charter}
---
Recent landscape signals (web search):
{signals}

Propose concrete revisions to the charter's in-scope domains, out-of-scope list,
and adoption criteria, respecting its design principles. Return ONE issue.

Respond with ONLY a JSON object:
{{"title": "Charter review <YYYY-Qn>",
  "landscape": "<summary of shifts>",
  "revisions": "<specific proposed edits as a diff-like list>",
  "domains": "<domains to add/remove from watch>"}}
"""


def review_charter(
    charter: str,
    complete: CompleteFn,
    search: SearchFn = web_search,
    quarter: str = "",
    existing_titles: list[str] | None = None,
) -> list[Proposal]:
    candidates = gather_candidates(_QUERIES, search, k=3)
    signals = "\n".join(f"- {c.title}: {c.snippet}" for c in candidates) or "(none)"
    data = extract_json(complete(_PROMPT.format(charter=charter[:6000], signals=signals)))
    if not isinstance(data, dict) or not data.get("title"):
        return []
    title = str(data["title"]).strip()
    if quarter and quarter not in title:
        title = f"Charter review {quarter}"
    body = (
        f"## Landscape の変化\n{data.get('landscape', '')}\n\n"
        f"## 憲章改訂の提案\n{data.get('revisions', '')}\n\n"
        f"## ウォッチ対象ドメインの見直し\n{data.get('domains', '')}\n\n"
        f"_自動生成 (charter-review)。docs/CHARTER.md の PR として反映するか人間が判断する。_"
    )
    proposals = [Proposal(title=title, body=body, labels=["charter", "automation"])]
    return dedupe(proposals, existing_titles or [], max_items=1)
