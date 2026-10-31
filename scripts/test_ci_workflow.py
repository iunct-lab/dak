"""ci.yml's steps run as local-ci.ts runs them: only `run:`, from the repository root, without the job's or step's
`env:` and `${{ }}` (run: `uv run --no-project --with pytest pytest scripts -q`)."""
import re
from pathlib import Path

CI = Path(__file__).resolve().parents[1] / ".github/workflows/ci.yml"
GUARD = '[ -n "${GITHUB_ACTIONS:-}" ] || { echo "skip: Actions の外"; exit 0; }'


def _runs(text: str) -> list[str]:
    """The script of every `run:` step: the rest of the line, or the indented block under `run: |`."""
    runs, lines = [], text.splitlines()
    for i, line in enumerate(lines):
        m = re.match(r"^(\s*)(?:- )?run:\s*(.*)$", line)
        if not m:
            continue
        if m.group(2) not in ("|", ">"):
            runs.append(m.group(2))
            continue
        indent, block = len(m.group(1)), []
        for nxt in lines[i + 1:]:
            if nxt.strip() and len(nxt) - len(nxt.lstrip()) <= indent:
                break
            block.append(nxt.strip())
        runs.append("\n".join(block).strip())
    return runs


def test_runs_are_found():
    assert len(_runs(CI.read_text())) >= 8


def test_no_step_depends_on_working_directory():
    assert "working-directory:" not in CI.read_text()


def test_no_run_has_an_expression():
    for run in _runs(CI.read_text()):
        assert "${{" not in run, run


def _env_names(text: str) -> set[str]:
    """Every name set under an `env:` (job or step): local-ci.ts passes none of them."""
    names, lines = set(), text.splitlines()
    for i, line in enumerate(lines):
        if line.strip() != "env:":
            continue
        indent = len(line) - len(line.lstrip())
        for nxt in lines[i + 1:]:
            if nxt.strip() and len(nxt) - len(nxt.lstrip()) <= indent:
                break
            if m := re.match(r"^\s*([A-Z_][A-Z0-9_]*):", nxt):
                names.add(m.group(1))
    return names


def test_an_env_name_is_read_only_with_a_default_or_behind_the_guard():
    text = CI.read_text()
    names = _env_names(text)
    assert "A2A_TCK_REF" in names
    for run in _runs(text):
        if run.splitlines()[0] == GUARD:
            continue
        for name in names:
            # ${NAME:-default} is fine: the step runs without it
            assert not re.search(rf"\$\{{?{name}(?![:A-Z0-9_])", run), (name, run)


def test_the_stack_and_a2a_tck_run_only_on_actions_and_a_loop_stops_at_a_failure():
    heavy = [r for r in _runs(CI.read_text()) if "docker compose" in r or "tests/integration" in r or "run_tck.py" in r]
    assert len(heavy) == 5
    for run in heavy:
        assert run.splitlines()[0] == GUARD, run
    for run in _runs(CI.read_text()):
        if run.startswith("for c in"):
            assert "|| exit 1; done" in run, run
