"""nightly-eval の結果の記録（リリース eval-history の asset history.jsonl）と、経路ごとの月の実行回数の上限。

`provider` は経路（ollama / bedrock …）、`runner` は実行環境。`provider` の無い古い行は ollama とみなす。
`profile` は DAK_HARNESS_PROFILE に渡した名前（空なら未指定 = モデル名の pattern で解決）。
`small_model` は DAK_SMALL_MODEL に渡した Meta-Agent のモデル（空なら未指定 = メインのモデル）。
`context` は実 LLM スモークのテストが record_property で残した長いツールループの指標（`context_*` の property）。
"""

from __future__ import annotations

import datetime
import json
import os
import xml.etree.ElementTree as ET


def summarize_junit(path: str) -> dict:
    total = failures = errors = skipped = 0
    if os.path.exists(path):
        root = ET.parse(path).getroot()
        for s in root.findall("testsuite") or [root]:
            total += int(s.get("tests", 0))
            failures += int(s.get("failures", 0))
            errors += int(s.get("errors", 0))
            skipped += int(s.get("skipped", 0))
    passed = total - failures - errors - skipped
    return {
        "total": total, "passed": passed, "failed": failures + errors, "skipped": skipped,
        "pass_rate": round(passed / total, 3) if total else 0.0,
    }


CONTEXT_COUNTS = ("model_calls", "overflow_calls", "compactions", "total_tokens")


def context_metrics(path: str) -> dict:
    """JUnit XML の testcase の property `context_<名前>` の和（CONTEXT_COUNTS）と、和から計算した
    `overflow_rate`（窓超過の呼び出し / モデルの呼び出し）。property が 1 つも無ければ {}。"""
    if not os.path.exists(path):
        return {}
    found = {}
    for prop in ET.parse(path).getroot().iter("property"):
        name = prop.get("name") or ""
        if name.startswith("context_") and (name := name.removeprefix("context_")) in CONTEXT_COUNTS:
            found[name] = found.get(name, 0) + int(float(prop.get("value", 0)))
    if not found:
        return {}
    metrics = {name: found.get(name, 0) for name in CONTEXT_COUNTS}
    calls = metrics["model_calls"]
    metrics["overflow_rate"] = round(metrics["overflow_calls"] / calls, 3) if calls else 0.0
    return metrics


def make_record(summary: dict, *, model: str, provider: str, runner: str, profile: str,
                small_model: str, today: datetime.date, vulnerabilities: dict | None = None,
                context: dict | None = None) -> dict:
    """`vulnerabilities` は lock ごとの {"ids": [...], "error": 文字列 or None}（無ければ {}）。
    `context` は context_metrics の結果（無ければ {}）。"""
    return {"date": today.isoformat(), "model": model, **summary, "provider": provider, "runner": runner,
            "profile": profile, "small_model": small_model,
            "vulnerabilities": vulnerabilities or {}, "context": context or {}}


def count_runs(history_path: str, *, provider: str, year_month: str) -> int:
    if not os.path.exists(history_path):
        return 0
    with open(history_path, encoding="utf-8") as f:
        rows = [json.loads(line) for line in f if line.strip()]
    return sum(
        1 for r in rows
        if r.get("provider", "ollama") == provider and str(r.get("date", "")).startswith(year_month + "-")
    )


def check_budget(count: int, limit: int, *, provider: str) -> tuple[bool, str]:
    if count >= limit:
        return False, f"今月の {provider} の実行は {count} 回で、上限 {limit} 回に達した"
    return True, f"今月の {provider} の実行は {count} 回（上限 {limit} 回）"
