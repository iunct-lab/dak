from dak_maintenance.decide import Action, decide
from dak_maintenance.semver import BumpLevel
from dak_maintenance.risk import RiskLevel, RiskVerdict


def _risk(level: RiskLevel) -> RiskVerdict:
    return RiskVerdict(level, "test", "heuristic")


def test_patch_safe_green_auto_merges():
    d = decide(BumpLevel.PATCH, True, _risk(RiskLevel.SAFE))
    assert d.action == Action.AUTO_MERGE
    assert d.is_auto_merge
    assert d.labels == ["auto-merge-candidate"]


def test_minor_safe_green_auto_merges():
    d = decide(BumpLevel.MINOR, True, _risk(RiskLevel.SAFE))
    assert d.action == Action.AUTO_MERGE


def test_ci_red_blocks_even_if_safe():
    d = decide(BumpLevel.PATCH, False, _risk(RiskLevel.SAFE))
    assert d.action == Action.NEEDS_REVIEW
    assert "needs-human-review" in d.labels


def test_major_always_reviews():
    d = decide(BumpLevel.MAJOR, True, _risk(RiskLevel.SAFE))
    assert d.action == Action.NEEDS_REVIEW


def test_unknown_bump_reviews():
    d = decide(BumpLevel.UNKNOWN, True, _risk(RiskLevel.SAFE))
    assert d.action == Action.NEEDS_REVIEW


def test_breaking_risk_blocks_minor():
    d = decide(BumpLevel.MINOR, True, _risk(RiskLevel.BREAKING))
    assert d.action == Action.NEEDS_REVIEW


def test_unknown_risk_blocks():
    d = decide(BumpLevel.PATCH, True, _risk(RiskLevel.UNKNOWN))
    assert d.action == Action.NEEDS_REVIEW


def test_none_bump_reviews():
    d = decide(BumpLevel.NONE, True, _risk(RiskLevel.SAFE))
    assert d.action == Action.NEEDS_REVIEW
