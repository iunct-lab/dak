"""`dak-maint collect-deps`: merged Dependabot PR bodies (JSON on stdin) → deps list.
Inputs are the three real body shapes (group update, single update, range-only)."""
import io
import json

from dak_maintenance.cli import main
from dak_maintenance.feature import deps_from_prs

GROUP = """Bumps the agent-minor-patch group with 3 updates in the /agent directory: [anthropic](https://github.com/anthropics/anthropic-sdk-python), [litellm](https://github.com/BerriAI/litellm) and [a2a-sdk](https://github.com/a2aproject/a2a-python).
Updates `anthropic` from 1.6.0 to 1.7.0
- [Release notes](https://github.com/anthropics/anthropic-sdk-python/releases)
Updates `litellm` from 1.101.0 to 1.102.0
Updates `a2a-sdk` from 0.3.19 to 0.3.26
"""
SINGLE = "Bumps [mcp](https://github.com/modelcontextprotocol/python-sdk) from 1.22.0 to 2.2.0.\n<details>...</details>"
SINGLE_EXTRAS = "Bumps [google-adk[a2a,db,mcp]](https://github.com/google/adk-python) from 2.8.0 to 2.9.0.\n"
RANGE_ONLY = ("Updates the requirements on [google-adk[a2a,db,mcp]](https://github.com/google/adk-python) "
              "to permit the latest version.\n")


def test_deps_from_prs_reads_group_single_and_extras_and_skips_range_only():
    deps, skipped = deps_from_prs([{"body": GROUP}, {"body": SINGLE}, {"body": SINGLE_EXTRAS},
                                   {"body": RANGE_ONLY}, {"body": None}])

    assert deps == [
        {"package": "anthropic", "from": "1.6.0", "to": "1.7.0"},
        {"package": "litellm", "from": "1.101.0", "to": "1.102.0"},
        {"package": "a2a-sdk", "from": "0.3.19", "to": "0.3.26"},
        {"package": "mcp", "from": "1.22.0", "to": "2.2.0"},
        {"package": "google-adk[a2a,db,mcp]", "from": "2.8.0", "to": "2.9.0"},
    ]
    assert skipped == 2


def test_deps_from_prs_keeps_the_first_seen_update_of_a_package():
    newer = "Updates `litellm` from 1.102.0 to 1.103.0\n"
    deps, _ = deps_from_prs([{"body": newer}, {"body": GROUP}])
    assert [d for d in deps if d["package"] == "litellm"] == [
        {"package": "litellm", "from": "1.102.0", "to": "1.103.0"}]


def test_collect_deps_cli_reads_pr_json_from_stdin(monkeypatch, capsys):
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps([{"body": SINGLE}, {"body": RANGE_ONLY}])))

    assert main(["collect-deps"]) == 0

    out = capsys.readouterr()
    assert json.loads(out.out) == [{"package": "mcp", "from": "1.22.0", "to": "2.2.0"}]
    assert "note: 1 件の deps-labeled PR" in out.err  # one PR skipped, reported on stderr


def test_collect_deps_cli_caps_the_list(monkeypatch, capsys):
    bodies = [{"body": f"Updates `p{i}` from 1.0.0 to 1.0.1\n"} for i in range(15)]
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(bodies)))

    main(["collect-deps", "--max-items", "10"])

    assert len(json.loads(capsys.readouterr().out)) == 10


def test_collect_deps_cli_empty_input_is_an_empty_list(monkeypatch, capsys):
    monkeypatch.setattr("sys.stdin", io.StringIO("[]"))
    assert main(["collect-deps"]) == 0
    assert json.loads(capsys.readouterr().out) == []


def test_collect_deps_cli_explains_empty_or_broken_input(monkeypatch, capsys):
    """An upstream `gh pr list` failure leaves stdin empty; say so instead of a
    bare JSONDecodeError traceback (the #157 symptom)."""
    for text in ("", "not json"):
        monkeypatch.setattr("sys.stdin", io.StringIO(text))
        assert main(["collect-deps"]) == 2
        assert "error:" in capsys.readouterr().err


def test_collect_deps_cli_rejects_a_negative_max_items():
    import pytest

    with pytest.raises(SystemExit):
        main(["collect-deps", "--max-items", "-1"])
