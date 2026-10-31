"""Tier 0: semver bump classification. No network, no LLM — fully deterministic."""

from __future__ import annotations

import re
from enum import Enum


class BumpLevel(str, Enum):
    MAJOR = "major"
    MINOR = "minor"
    PATCH = "patch"
    NONE = "none"
    UNKNOWN = "unknown"  # 非パース可能 / 比較不能 → 安全側で扱う


_VERSION_RE = re.compile(r"^\s*v?(\d+)(?:\.(\d+))?(?:\.(\d+))?")


def _parse(version: str) -> tuple[int, int, int] | None:
    """Extract (major, minor, patch) from a version string.

    Tolerant: strips a leading 'v', ignores pre-release/build suffixes
    (e.g. '1.2.3rc1', '1.2.3+local'). Missing components default to 0.
    """
    if not version:
        return None
    m = _VERSION_RE.match(version.strip())
    if not m:
        return None
    major = int(m.group(1))
    minor = int(m.group(2) or 0)
    patch = int(m.group(3) or 0)
    return (major, minor, patch)


# 0.x の minor の上げを破壊的（MAJOR）として扱うパッケージ。
ZERO_MINOR_BREAKING = frozenset({"ghcr.io/astral-sh/uv"})


def classify_update(from_version: str, to_version: str, package: str = "") -> BumpLevel:
    """Classify the semver bump between two versions.

    0.x releases are classified the same as 1.x+ (major/minor/patch component
    changed). We used to escalate any 0.x minor-position change straight to
    MAJOR on the theory that pre-1.0 packages can break at any time, but this
    repo's actual dependency stack (fastapi, uvicorn, anthropic-sdk, langfuse,
    litellm, ...) lives almost entirely on 0.x and releases routine, well
    documented minor versions — the blanket escalation meant *every* routine
    update got flagged MAJOR and no dependency PR ever qualified for
    auto-merge. Real breaking changes are now caught by the changelog-based
    risk assessor (see risk.py) instead of a blunt version-number heuristic.

    Exception: packages in ZERO_MINOR_BREAKING get the old escalation — a 0.x
    minor-position change is MAJOR. uv ships breaking changes in 0.x minors
    (0.13.0 changed `--require-hashes`, requirement-file parsing and the default
    Python), so its container image must not qualify for auto-merge (#766).
    """
    a = _parse(from_version)
    b = _parse(to_version)
    if a is None or b is None:
        return BumpLevel.UNKNOWN
    if a == b:
        return BumpLevel.NONE

    a_major, a_minor, a_patch = a
    b_major, b_minor, b_patch = b

    # ダウングレードは通常起きない（起きたら人間判断へ）
    if b < a:
        return BumpLevel.UNKNOWN

    if a_major != b_major:
        return BumpLevel.MAJOR
    if a_minor != b_minor:
        if a_major == 0 and package in ZERO_MINOR_BREAKING:
            return BumpLevel.MAJOR
        return BumpLevel.MINOR
    if a_patch != b_patch:
        return BumpLevel.PATCH
    return BumpLevel.NONE


_BUMP_SEVERITY = {
    BumpLevel.PATCH: 0,
    BumpLevel.MINOR: 1,
    BumpLevel.UNKNOWN: 2,
    BumpLevel.MAJOR: 3,
}


def combine_bump(bumps: list[BumpLevel]) -> BumpLevel:
    """Reduce per-dependency bumps from a grouped Dependabot PR to one verdict.

    NONE entries (no detected version diff for that dependency — e.g. a
    transitive-only lockfile refresh) carry no signal and are ignored unless
    they're the only entries. Otherwise the most conservative bump wins:
    MAJOR > UNKNOWN > MINOR > PATCH.
    """
    informative = [b for b in bumps if b is not BumpLevel.NONE]
    if not informative:
        return BumpLevel.NONE
    return max(informative, key=lambda b: _BUMP_SEVERITY[b])
