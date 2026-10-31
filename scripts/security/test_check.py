"""scripts/security/check.sh: the one command skills call before push / PR.
A fake gitleaks on PATH stands in for the real one (CI's unit job has none);
a real-gitleaks test runs only when gitleaks is installed.
Run: `uv run --no-project --with pytest pytest scripts -q`."""
import os
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

from test_checklist import CHECKLIST, ROOT, checklist_items

CHECK = ROOT / "scripts" / "security" / "check.sh"
MARK = "FAKE-SECRET-MARK"  # what the fake gitleaks treats as a leak

FAKE_GITLEAKS = f"""#!/bin/sh
# Records its arguments; "finds a leak" when the scanned changes contain {MARK}.
echo "$@" >> "$FAKE_GITLEAKS_LOG"
case "$*" in
  *--staged*) git diff --cached | grep -q {MARK} && exit 1 ;;
  # Like gitleaks: the --log-opts value is split on spaces and given to git log.
  *--log-opts=*) opts=$(echo "$*" | sed 's/.*--log-opts=\\(.*\\) --config.*/\\1/'); git log -p $opts | grep -q {MARK} && exit 1 ;;
esac
exit 0
"""


def _write_exec(path: Path, text: str):
    path.write_text(text)
    path.chmod(path.stat().st_mode | stat.S_IEXEC)


@pytest.fixture
def repo(tmp_path):
    """A git repo with the files check.sh reads, and a bin dir with git and
    (unless removed) the fake gitleaks."""
    work = tmp_path / "repo"
    work.mkdir()
    run = lambda *a: subprocess.run(a, cwd=work, check=True, capture_output=True)  # noqa: E731
    run("git", "init", "-q", "-b", "main")
    run("git", "config", "user.email", "t@example.com")
    run("git", "config", "user.name", "t")
    for rel in ("scripts/security/check.sh", "docs/security/review-checklist.md", ".gitleaks.toml", ".gitleaksignore"):
        (work / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / rel, work / rel)
    (work / ".githooks").mkdir()
    _write_exec(work / ".githooks" / "pre-commit", "#!/bin/sh\nexit 0\n")  # a hook exists; it does nothing here
    (work / "a.txt").write_text("hello\n")
    run("git", "add", ".")
    run("git", "commit", "-q", "-m", "init")
    run("git", "config", "core.hooksPath", ".githooks")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "git").symlink_to(shutil.which("git"))
    _write_exec(bin_dir / "gitleaks", FAKE_GITLEAKS)
    log = tmp_path / "gitleaks.log"
    env = {"PATH": f"{bin_dir}:/usr/bin:/bin", "HOME": str(tmp_path), "FAKE_GITLEAKS_LOG": str(log)}
    return {"dir": work, "bin": bin_dir, "env": env, "log": log, "run": run}


def check(repo, *args):
    return subprocess.run(["sh", "scripts/security/check.sh", *args], cwd=repo["dir"], env=repo["env"],
                          capture_output=True, text=True)


def test_clean_staged_changes_pass(repo):
    (repo["dir"] / "a.txt").write_text("still clean\n")
    repo["run"]("git", "add", "a.txt")
    result = check(repo)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "--staged" in repo["log"].read_text()


def test_a_leak_in_staged_changes_fails(repo):
    (repo["dir"] / "a.txt").write_text(f"token={MARK}\n")
    repo["run"]("git", "add", "a.txt")
    result = check(repo)
    assert result.returncode != 0
    assert "NG  gitleaks found secrets" in result.stdout


def test_disabled_hooks_fail_and_say_how_to_enable_them(repo):
    repo["run"]("git", "config", "--unset", "core.hooksPath")
    result = check(repo)
    assert result.returncode != 0
    assert "scripts/setup/install_hooks.sh" in result.stdout + result.stderr


def test_missing_gitleaks_fails_and_says_how_to_install_it(repo):
    (repo["bin"] / "gitleaks").unlink()
    result = check(repo)
    assert result.returncode != 0
    assert "brew install gitleaks" in result.stdout + result.stderr


def test_range_is_passed_to_gitleaks_and_a_leak_in_it_fails(repo):
    base = repo["run"]("git", "rev-parse", "HEAD").stdout.decode().strip()
    (repo["dir"] / "a.txt").write_text(f"token={MARK}\n")
    repo["run"]("git", "commit", "-q", "-am", "leak")
    result = check(repo, "--range", f"{base}..HEAD")
    assert result.returncode != 0
    assert f"--log-opts={base}..HEAD" in repo["log"].read_text()
    assert check(repo, "--range", f"{base}..{base}").returncode == 0


def test_output_lists_exactly_the_checklist_items(repo):
    result = check(repo)
    listed = [line[2:].strip() for line in result.stdout.splitlines() if line.startswith("- ")]
    assert listed == checklist_items()
    assert "- " not in check(repo, "--no-checklist").stdout


@pytest.mark.skipif(not shutil.which("gitleaks"), reason="real gitleaks not installed")
def test_real_gitleaks_stops_a_langfuse_key(repo):
    (repo["bin"] / "gitleaks").unlink()
    (repo["bin"] / "gitleaks").symlink_to(shutil.which("gitleaks"))
    (repo["dir"] / "a.txt").write_text("still clean\n")
    repo["run"]("git", "add", "a.txt")
    assert check(repo).returncode == 0  # the real binary with our arguments: clean passes
    # Built at run time so no key-shaped string is committed to this repository.
    key = "sk" + "-lf-" + "0f3a9c2e-7b41-4d8a-9e6f-1c2b3d4e5f60"
    (repo["dir"] / "a.txt").write_text(f"LANGFUSE_SECRET_KEY={key}\n")
    repo["run"]("git", "add", "a.txt")
    result = check(repo)
    assert result.returncode != 0
    assert "NG  gitleaks found secrets" in result.stdout


@pytest.mark.parametrize("bad", ["nosuch..HEAD", "HEAD --output=x", "-p", "HEAD --all"])
def test_a_range_that_does_not_resolve_or_carries_options_fails(repo, bad):
    """gitleaks scans nothing (and says "no leaks") when git cannot resolve the
    range; the gate must not report OK then. Only revisions, --not and
    --remotes=<name> (what pre-push passes for a new branch) are allowed."""
    result = check(repo, "--range", bad, "--no-checklist")
    assert result.returncode != 0
    assert "NG  " in result.stdout
    assert not (repo["dir"] / "x").exists()


def test_the_new_branch_range_form_is_accepted(repo):
    head = repo["run"]("git", "rev-parse", "HEAD").stdout.decode().strip()
    assert check(repo, "--range", f"{head} --not --remotes=origin", "--no-checklist").returncode == 0


def test_a_missing_or_empty_checklist_fails(repo):
    doc = repo["dir"] / "docs" / "security" / "review-checklist.md"
    doc.write_text("# no items here\n")
    assert check(repo).returncode != 0
    doc.unlink()
    assert check(repo).returncode != 0


@pytest.mark.parametrize("value", ["./.githooks", ".githooks/"])
def test_equivalent_hooks_path_spellings_are_accepted(repo, value):
    repo["run"]("git", "config", "core.hooksPath", value)
    assert check(repo, "--no-checklist").returncode == 0


def test_hooks_path_without_the_hooks_fails(repo):
    (repo["dir"] / ".githooks" / "pre-commit").unlink()
    assert check(repo, "--no-checklist").returncode != 0
