"""Tier 0: the merge decision. Combines bump level x CI status x risk verdict.

Policy (approved): auto-merge only patch/minor updates that pass CI and are
assessed SAFE. Everything else escalates to a human with a labelled reason.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .semver import BumpLevel
from .risk import RiskLevel, RiskVerdict


class Action(str):
    AUTO_MERGE = "auto-merge"
    NEEDS_REVIEW = "needs-human-review"


@dataclass
class Decision:
    action: str
    reason: str
    labels: list[str] = field(default_factory=list)

    @property
    def is_auto_merge(self) -> bool:
        return self.action == Action.AUTO_MERGE


def decide(bump: BumpLevel, ci_passed: bool, risk: RiskVerdict) -> Decision:
    # 1. CI が通っていなければ無条件でレビュー
    if not ci_passed:
        return Decision(
            Action.NEEDS_REVIEW,
            "CI が green ではないため自動マージしない。",
            ["needs-human-review"],
        )

    # 2. major / unknown bump はレビュー
    if bump in (BumpLevel.MAJOR, BumpLevel.UNKNOWN):
        return Decision(
            Action.NEEDS_REVIEW,
            f"bump={bump.value} は破壊的変更の可能性が高いため人間レビューが必要。",
            ["needs-human-review"],
        )

    # 3. none bump は何もしない（実質レビュー扱い＝安全側）
    if bump is BumpLevel.NONE:
        return Decision(
            Action.NEEDS_REVIEW,
            "バージョン差分を検出できなかった。人間が確認する。",
            ["needs-human-review"],
        )

    # 4. patch/minor: リスク評価に従う
    if risk.level is RiskLevel.SAFE:
        return Decision(
            Action.AUTO_MERGE,
            f"bump={bump.value} かつ CI green かつ SAFE 判定（{risk.tier}）。自動マージ可。 {risk.summary}",
            ["auto-merge-candidate"],
        )

    return Decision(
        Action.NEEDS_REVIEW,
        f"bump={bump.value} だがリスク判定={risk.level.value}（{risk.tier}）: {risk.summary}",
        ["needs-human-review"],
    )
