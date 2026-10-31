"""Dependency-maintenance tools for the DAK agent (dogfooding requirement 2/5).

Self-contained by design (the agent runs as an independent container that may not
mount `maintenance/`). If the `dak_maintenance` package IS importable it is used
directly so behaviour stays identical to CI; otherwise a minimal inline copy of
the same policy is used. Keep the two in sync — the CI package is the source of truth.
"""
import logging

logger = logging.getLogger(__name__)

try:  # Prefer the real toolkit when available (identical to CI behaviour).
    from dak_maintenance import classify_update, assess_risk, decide  # type: ignore

    _HAVE_TOOLKIT = True
except Exception:  # pragma: no cover - fallback path
    _HAVE_TOOLKIT = False

    import re
    from dataclasses import dataclass

    _VRE = re.compile(r"^\s*v?(\d+)(?:\.(\d+))?(?:\.(\d+))?")
    _BREAK = [r"\bbreaking change", r"\bbackwards?[- ]incompat", r"\bremoved?\b",
              r"\bdropped? support", r"\bno longer\b", r"\bmigrat"]
    _RISKY = [r"\bdeprecat", r"\bchanged? default", r"\brenamed?\b"]

    def _parse(v):
        m = _VRE.match(v.strip()) if v else None
        return (int(m.group(1)), int(m.group(2) or 0), int(m.group(3) or 0)) if m else None

    def classify_update(a, b):  # returns a str
        pa, pb = _parse(a), _parse(b)
        if pa is None or pb is None:
            return "unknown"
        if pa == pb:
            return "none"
        if pb < pa:
            return "unknown"
        # 0.x も 1.x+ と同じ規則（major成分の変化のみ major）。CI 側の semver.py と同期。
        if pa[0] != pb[0]:
            return "major"
        if pa[1] != pb[1]:
            return "minor"
        return "patch"

    @dataclass
    class _R:
        level: str
        summary: str
        tier: str = "heuristic"

    def assess_risk(pkg, a, b, changelog, assessor=None):
        t = (changelog or "").lower()
        if not t.strip():
            return _R("unknown", "changelog なし")
        if any(re.search(p, t) for p in _BREAK):
            return _R("breaking", "破壊的変更キーワードを検出")
        if any(re.search(p, t) for p in _RISKY):
            return _R("risky", "挙動変化キーワードを検出")
        return _R("safe", "破壊的キーワードなし")

    @dataclass
    class _D:
        action: str
        reason: str

    def decide(bump, ci_passed, risk):
        bump = getattr(bump, "value", bump)
        level = getattr(risk, "level", None)
        level = getattr(level, "value", level)
        if not ci_passed:
            return _D("needs-human-review", "CI が green でない")
        if bump in ("major", "unknown", "none"):
            return _D("needs-human-review", f"bump={bump} は要レビュー")
        if level == "safe":
            return _D("auto-merge", f"bump={bump}, CI green, SAFE")
        return _D("needs-human-review", f"bump={bump} だが risk={level}")


def classify_bump(from_version: str, to_version: str) -> str:
    """Classify the semver bump between two versions (major/minor/patch/none/unknown)."""
    level = classify_update(from_version, to_version)
    return getattr(level, "value", str(level))


def triage_dependency(
    package: str,
    from_version: str,
    to_version: str,
    ci_passed: bool = False,
    changelog: str = "",
) -> str:
    """Triage a dependency update per the repo's maintenance policy.

    Args:
        package: dependency name (e.g. "litellm").
        from_version / to_version: e.g. "1.51.0" / "1.52.3".
        ci_passed: whether CI is currently green for the update.
        changelog: changelog/release-notes text (empty if unknown).

    Returns:
        A human-readable triage report with the recommended action.
    """
    bump = classify_update(from_version, to_version)
    bump_str = getattr(bump, "value", str(bump))
    risk = assess_risk(package, from_version, to_version, changelog)
    decision = decide(bump, bool(ci_passed), risk)
    logger.info("triage_dependency %s %s->%s toolkit=%s -> %s",
                package, from_version, to_version, _HAVE_TOOLKIT, decision.action)
    return (
        f"## Dependency triage: {package} {from_version} -> {to_version}\n"
        f"- bump: **{bump_str}**\n"
        f"- risk: **{getattr(risk.level, 'value', risk.level)}** ({risk.tier}) — {risk.summary}\n"
        f"- CI passed: {bool(ci_passed)}\n"
        f"- **decision: {decision.action}**\n"
        f"- reason: {decision.reason}\n"
    )
