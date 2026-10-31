"""Best-effort changelog retrieval from PyPI project metadata + GitHub Releases.

All functions fail soft: on any error they return "" so the caller's assessor
reports UNKNOWN (safe side) rather than crashing the workflow.
"""

from __future__ import annotations

import re

import httpx

_GITHUB_REPO_RE = re.compile(r"github\.com[/:]([^/]+)/([^/#?]+)", re.IGNORECASE)


def find_github_repo(package: str, *, timeout: float = 10.0) -> str | None:
    """Resolve a PyPI package to an 'owner/repo' slug via its project URLs."""
    try:
        r = httpx.get(f"https://pypi.org/pypi/{package}/json", timeout=timeout)
        r.raise_for_status()
        info = r.json().get("info", {})
    except Exception:
        return None
    urls = list((info.get("project_urls") or {}).values())
    if info.get("home_page"):
        urls.append(info["home_page"])
    for url in urls:
        m = _GITHUB_REPO_RE.search(url or "")
        if m:
            return f"{m.group(1)}/{m.group(2).removesuffix('.git')}"
    return None


def fetch_release_notes(repo: str, *, limit: int = 20, timeout: float = 10.0) -> str:
    """Concatenate recent GitHub release bodies for a repo ('owner/repo')."""
    try:
        r = httpx.get(
            f"https://api.github.com/repos/{repo}/releases",
            params={"per_page": limit},
            headers={"Accept": "application/vnd.github+json"},
            timeout=timeout,
        )
        r.raise_for_status()
        releases = r.json()
    except Exception:
        return ""
    parts = []
    for rel in releases:
        tag = rel.get("tag_name", "")
        body = (rel.get("body") or "").strip()
        if body:
            parts.append(f"## {tag}\n{body}")
    return "\n\n".join(parts)


def get_changelog(package: str, from_version: str, to_version: str) -> str:
    """Convenience: resolve repo then fetch notes. Returns '' if unavailable."""
    repo = find_github_repo(package)
    if not repo:
        return ""
    return fetch_release_notes(repo)
