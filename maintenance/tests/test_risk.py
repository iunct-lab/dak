from dak_maintenance.risk import (
    HeuristicAssessor,
    LLMAssessor,
    RiskLevel,
    RiskVerdict,
    assess_risk,
    combine_risk,
    extract_json,
)


def test_heuristic_detects_breaking():
    v = HeuristicAssessor().assess("pkg", "1.0.0", "2.0.0", "This release removed the old API.")
    assert v.level is RiskLevel.BREAKING
    assert v.tier == "heuristic"


def test_heuristic_detects_risky_deprecation():
    v = HeuristicAssessor().assess("pkg", "1.0.0", "1.1.0", "Deprecated the foo() helper.")
    assert v.level is RiskLevel.RISKY


def test_heuristic_safe_when_only_fixes():
    v = HeuristicAssessor().assess("pkg", "1.0.0", "1.0.1", "Fixed a typo and improved docs.")
    assert v.level is RiskLevel.SAFE


def test_heuristic_unknown_when_empty():
    v = HeuristicAssessor().assess("pkg", "1.0.0", "1.0.1", "")
    assert v.level is RiskLevel.UNKNOWN


def test_assess_risk_defaults_to_heuristic():
    v = assess_risk("pkg", "1.0.0", "1.0.1", "just a bugfix")
    assert v.level is RiskLevel.SAFE


def test_extract_json_from_fence():
    assert extract_json('```json\n{"level": "safe"}\n```') == {"level": "safe"}


def test_extract_json_from_prose():
    assert extract_json('Sure! {"level": "risky", "summary": "x"} done') == {
        "level": "risky",
        "summary": "x",
    }


def test_extract_json_garbage_returns_empty():
    assert extract_json("no json here") == {}


def test_llm_assessor_parses_verdict():
    def fake_complete(prompt: str) -> str:
        return '{"level": "breaking", "summary": "removed X"}'

    v = LLMAssessor(fake_complete, tier="llm").assess("pkg", "1.0.0", "2.0.0", "some changelog")
    assert v.level is RiskLevel.BREAKING
    assert v.summary == "removed X"
    assert v.tier == "llm"


def test_llm_assessor_falls_back_on_bad_json():
    def fake_complete(prompt: str) -> str:
        return "I cannot answer"

    # changelog にキーワードがあれば heuristic フォールバックが breaking を返す
    v = LLMAssessor(fake_complete).assess("pkg", "1.0.0", "2.0.0", "This removed the API.")
    assert v.level is RiskLevel.BREAKING
    assert v.tier == "heuristic"


def test_llm_assessor_falls_back_on_exception():
    def boom(prompt: str) -> str:
        raise RuntimeError("network down")

    v = LLMAssessor(boom).assess("pkg", "1.0.0", "1.0.1", "just a fix")
    assert v.level is RiskLevel.SAFE
    assert v.tier == "heuristic"


def test_llm_assessor_empty_changelog_is_unknown():
    v = LLMAssessor(lambda p: '{"level":"safe"}').assess("pkg", "1.0.0", "1.0.1", "  ")
    assert v.level is RiskLevel.UNKNOWN


def test_combine_risk_picks_worst_and_keeps_its_summary():
    safe = RiskVerdict(RiskLevel.SAFE, "ok", "heuristic")
    breaking = RiskVerdict(RiskLevel.BREAKING, "removed X", "heuristic")
    v = combine_risk([safe, breaking])
    assert v.level is RiskLevel.BREAKING
    assert "removed X" in v.summary


def test_combine_risk_single_passthrough():
    only = RiskVerdict(RiskLevel.SAFE, "ok", "heuristic")
    assert combine_risk([only]) is only


def test_combine_risk_empty_is_unknown():
    v = combine_risk([])
    assert v.level is RiskLevel.UNKNOWN
