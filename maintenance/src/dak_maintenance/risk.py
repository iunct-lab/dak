"""Tier 1/2: changelog risk assessment.

Two assessors share one interface (`Assessor.assess`):
  - HeuristicAssessor: deterministic keyword scan. No LLM. Always available (Tier 1 fallback).
  - LLMAssessor: delegates to an injected `complete(prompt) -> str` callable
    (an Ollama client for Tier 1, or a Claude client for Tier 2). Parses JSON.

Tests inject a fake `complete` so no network/model is needed.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import Callable, Protocol

from .jsonutil import extract_json


class RiskLevel(str, Enum):
    SAFE = "safe"          # 破壊的変更なし。自動マージ候補
    RISKY = "risky"        # 挙動変化の可能性。人間判断
    BREAKING = "breaking"  # 明確な破壊的変更
    UNKNOWN = "unknown"    # 判定不能（changelog なし等）→ 安全側


@dataclass
class RiskVerdict:
    level: RiskLevel
    summary: str
    tier: str  # "heuristic" | "llm"


class Assessor(Protocol):
    def assess(self, package: str, from_version: str, to_version: str, changelog: str) -> RiskVerdict: ...


# 破壊的変更を示唆するキーワード（大文字小文字無視）
_BREAKING_PATTERNS = [
    r"\bbreaking change", r"\bbackwards?[- ]incompat", r"\bincompatible\b",
    r"\bremoved?\b", r"\bdropped? support", r"\bno longer\b", r"\bmigrat",
]
_RISKY_PATTERNS = [
    r"\bdeprecat", r"\bchanged? default", r"\brenamed?\b", r"\bbehou?r? change",
    r"\bbehaviou?r change", r"\brequires?\b.*\bupgrade",
]


class HeuristicAssessor:
    """LLM を使わない決定論的評価。changelog のキーワードで判定する。"""

    def assess(self, package: str, from_version: str, to_version: str, changelog: str) -> RiskVerdict:
        text = (changelog or "").lower()
        if not text.strip():
            return RiskVerdict(RiskLevel.UNKNOWN, "changelog が空のため判定不能。", "heuristic")

        breaking_hits = [p for p in _BREAKING_PATTERNS if re.search(p, text)]
        if breaking_hits:
            return RiskVerdict(
                RiskLevel.BREAKING,
                f"破壊的変更の可能性を示すキーワードを検出: {', '.join(breaking_hits[:3])}",
                "heuristic",
            )
        risky_hits = [p for p in _RISKY_PATTERNS if re.search(p, text)]
        if risky_hits:
            return RiskVerdict(
                RiskLevel.RISKY,
                f"挙動変化の可能性を示すキーワードを検出: {', '.join(risky_hits[:3])}",
                "heuristic",
            )
        return RiskVerdict(RiskLevel.SAFE, "破壊的変更を示すキーワードは見つからなかった。", "heuristic")


_PROMPT = """You are a dependency-upgrade risk assessor for a Python project.
Given the changelog between two versions, decide whether upgrading is safe.

Package: {package}
From: {from_version}
To: {to_version}

Changelog:
---
{changelog}
---

Respond with ONLY a JSON object:
{{"level": "safe|risky|breaking", "summary": "<one concise sentence>"}}
- "safe": no breaking changes, only fixes / additive features.
- "risky": deprecations, changed defaults, or behavior that may affect us.
- "breaking": removed/renamed APIs or explicit breaking changes.
"""


class LLMAssessor:
    """`complete(prompt) -> str` に処理を委譲する評価器（Ollama=Tier1 / Claude=Tier2）。

    LLM が判定不能・不正応答の場合は HeuristicAssessor にフォールバックする。
    """

    def __init__(self, complete: Callable[[str], str], tier: str = "llm"):
        self._complete = complete
        self._tier = tier
        self._fallback = HeuristicAssessor()

    def assess(self, package: str, from_version: str, to_version: str, changelog: str) -> RiskVerdict:
        if not (changelog or "").strip():
            return RiskVerdict(RiskLevel.UNKNOWN, "changelog が空のため判定不能。", self._tier)
        prompt = _PROMPT.format(
            package=package, from_version=from_version, to_version=to_version,
            changelog=changelog[:8000],
        )
        try:
            raw = self._complete(prompt)
        except Exception as e:  # noqa: BLE001 - LLM 呼び出し失敗はフォールバック
            fb = self._fallback.assess(package, from_version, to_version, changelog)
            return RiskVerdict(fb.level, f"LLM 呼び出し失敗({e}) のためヒューリスティックに委譲: {fb.summary}", fb.tier)

        data = extract_json(raw)
        level_raw = str(data.get("level", "")).lower()
        try:
            level = RiskLevel(level_raw)
        except ValueError:
            fb = self._fallback.assess(package, from_version, to_version, changelog)
            return RiskVerdict(fb.level, f"LLM 応答が不正のためヒューリスティックに委譲: {fb.summary}", fb.tier)
        summary = str(data.get("summary", "")).strip() or "(要約なし)"
        return RiskVerdict(level, summary, self._tier)


def assess_risk(
    package: str,
    from_version: str,
    to_version: str,
    changelog: str,
    assessor: Assessor | None = None,
) -> RiskVerdict:
    """Convenience wrapper. Defaults to the deterministic HeuristicAssessor."""
    return (assessor or HeuristicAssessor()).assess(package, from_version, to_version, changelog)


_RISK_SEVERITY = {
    RiskLevel.SAFE: 0,
    RiskLevel.UNKNOWN: 1,
    RiskLevel.RISKY: 2,
    RiskLevel.BREAKING: 3,
}


def combine_risk(verdicts: list[RiskVerdict]) -> RiskVerdict:
    """Reduce per-dependency risk verdicts from a grouped Dependabot PR to the
    worst-case overall verdict, so one breaking/risky member doesn't get
    masked by the rest of the group being safe.
    """
    if not verdicts:
        return RiskVerdict(RiskLevel.UNKNOWN, "評価対象の依存が見つからなかった。", "heuristic")
    if len(verdicts) == 1:
        return verdicts[0]
    worst_level = max((v.level for v in verdicts), key=lambda level: _RISK_SEVERITY[level])
    matching = [v for v in verdicts if v.level is worst_level]
    return RiskVerdict(worst_level, "; ".join(v.summary for v in matching), matching[0].tier)
