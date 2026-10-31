"""scripts/setup/install_hooks.sh and .githooks/pre-push (#291).
A fake gitleaks on PATH (see test_check.py) stands in for the real one.
Run: `uv run --no-project --with pytest pytest scripts -q`."""
import shutil
import subprocess

import pytest

from test_check import FAKE_GITLEAKS, MARK, _write_exec
from test_checklist import ROOT

FILES = ("scripts/security/check.sh", "scripts/setup/install_hooks.sh", ".githooks/pre-commit", ".githooks/pre-push",
         "docs/security/review-checklist.md", ".gitleaks.toml", ".gitleaksignore")


@pytest.fixture
def env(tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "git").symlink_to(shutil.which("git"))
    _write_exec(bin_dir / "gitleaks", FAKE_GITLEAKS)
    return {"PATH": f"{bin_dir}:/usr/bin:/bin", "HOME": str(tmp_path),
            "FAKE_GITLEAKS_LOG": str(tmp_path / "gitleaks.log"),
            "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.com",
            "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.com", "_bin": str(bin_dir)}


@pytest.fixture
def clone(tmp_path, env):
    """A bare 'remote' with one clean commit, and a fresh clone of it whose
    hooks are NOT enabled (as after `git clone` on a new machine)."""
    env = {k: v for k, v in env.items() if not k.startswith("_")}
    run = lambda *a, cwd=None: subprocess.run(a, cwd=cwd, env=env, check=True, capture_output=True, text=True)  # noqa: E731
    seed = tmp_path / "seed"
    seed.mkdir()
    run("git", "init", "-q", "-b", "main", cwd=seed)
    for rel in FILES:
        (seed / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / rel, seed / rel)
    (seed / "a.txt").write_text("hello\n")
    run("git", "add", ".", cwd=seed)
    run("git", "commit", "-q", "-m", "init", cwd=seed)
    remote = tmp_path / "remote.git"
    run("git", "clone", "-q", "--bare", str(seed), str(remote))
    work = tmp_path / "work"
    run("git", "clone", "-q", str(remote), str(work))
    return {"dir": work, "env": env, "run": lambda *a: subprocess.run(a, cwd=work, env=env, capture_output=True, text=True)}


def test_install_hooks_enables_the_hooks_on_a_fresh_clone(clone):
    assert clone["run"]("git", "config", "core.hooksPath").stdout.strip() == ""
    result = clone["run"]("sh", "scripts/setup/install_hooks.sh")
    assert result.returncode == 0, result.stdout + result.stderr
    assert clone["run"]("git", "config", "core.hooksPath").stdout.strip() == ".githooks"
    assert "pre-push" in result.stdout


def test_install_hooks_fails_without_gitleaks_and_says_how_to_install_it(clone, env):
    import os

    os.unlink(os.path.join(env["_bin"], "gitleaks"))
    result = clone["run"]("sh", "scripts/setup/install_hooks.sh")
    assert result.returncode != 0
    assert "brew install gitleaks" in result.stdout + result.stderr


def test_after_install_a_leak_cannot_be_committed(clone):
    clone["run"]("sh", "scripts/setup/install_hooks.sh")
    (clone["dir"] / "a.txt").write_text(f"token={MARK}\n")
    clone["run"]("git", "add", "a.txt")
    assert clone["run"]("git", "commit", "-q", "-m", "leak").returncode != 0


def test_pre_push_stops_a_leak_committed_with_no_verify(clone):
    clone["run"]("sh", "scripts/setup/install_hooks.sh")
    (clone["dir"] / "a.txt").write_text(f"token={MARK}\n")
    clone["run"]("git", "commit", "-q", "--no-verify", "-am", "leak")
    result = clone["run"]("git", "push", "-q", "origin", "main")
    assert result.returncode != 0, result.stdout + result.stderr
    assert "gitleaks found secrets" in result.stdout + result.stderr


def test_pre_push_stops_a_leak_on_a_new_branch(clone):
    clone["run"]("sh", "scripts/setup/install_hooks.sh")
    clone["run"]("git", "checkout", "-q", "-b", "feature")
    (clone["dir"] / "b.txt").write_text(f"token={MARK}\n")
    clone["run"]("git", "add", "b.txt")
    clone["run"]("git", "commit", "-q", "--no-verify", "-m", "leak")
    result = clone["run"]("git", "push", "-q", "origin", "feature")
    assert result.returncode != 0
    assert "gitleaks found secrets" in result.stdout + result.stderr


def test_pre_push_lets_clean_commits_and_branch_deletions_through(clone):
    clone["run"]("sh", "scripts/setup/install_hooks.sh")
    (clone["dir"] / "a.txt").write_text("clean\n")
    clone["run"]("git", "commit", "-q", "-am", "clean")
    result = clone["run"]("git", "push", "-q", "origin", "main")
    assert result.returncode == 0, result.stdout + result.stderr
    clone["run"]("git", "push", "-q", "origin", "main:tmp")
    assert clone["run"]("git", "push", "-q", "origin", ":tmp").returncode == 0


@pytest.mark.skipif(not shutil.which("gitleaks"), reason="real gitleaks not installed")
@pytest.mark.parametrize("branch", ["main", "feature"])
def test_real_gitleaks_in_pre_push_stops_a_langfuse_key(clone, env, branch):
    import os

    os.unlink(os.path.join(env["_bin"], "gitleaks"))
    os.symlink(shutil.which("gitleaks"), os.path.join(env["_bin"], "gitleaks"))
    clone["run"]("sh", "scripts/setup/install_hooks.sh")
    if branch != "main":
        clone["run"]("git", "checkout", "-q", "-b", branch)
    key = "sk" + "-lf-" + "0f3a9c2e-7b41-4d8a-9e6f-1c2b3d4e5f60"  # built at run time, never committed here
    (clone["dir"] / "k.txt").write_text(f"LANGFUSE_SECRET_KEY={key}\n")
    clone["run"]("git", "add", "k.txt")
    clone["run"]("git", "commit", "-q", "--no-verify", "-m", "leak")
    result = clone["run"]("git", "push", "-q", "origin", branch)
    assert result.returncode != 0, result.stdout + result.stderr


def test_pre_push_stops_a_force_push_over_a_remote_commit_this_clone_never_fetched(clone, tmp_path):
    """Machine A pushed; machine B did not fetch and force-pushes a leak. The
    remote sha is unknown here, so its range cannot be resolved: scan what the
    remote-tracking refs do not have instead of passing."""
    clone["run"]("sh", "scripts/setup/install_hooks.sh")
    other = tmp_path / "other"
    env = clone["env"]
    subprocess.run(["git", "clone", "-q", str(tmp_path / "remote.git"), str(other)], env=env, check=True)
    (other / "a.txt").write_text("from machine A\n")
    subprocess.run(["git", "commit", "-q", "-am", "A"], cwd=other, env=env, check=True)
    subprocess.run(["git", "push", "-q", "--no-verify", "origin", "main"], cwd=other, env=env, check=True)

    (clone["dir"] / "a.txt").write_text(f"token={MARK}\n")
    clone["run"]("git", "commit", "-q", "--no-verify", "-am", "leak")
    result = clone["run"]("git", "push", "-q", "--force", "origin", "main")
    assert result.returncode != 0, result.stdout + result.stderr
    assert "gitleaks found secrets" in result.stdout + result.stderr


def test_pre_push_to_a_path_instead_of_a_remote_name_still_scans(clone, tmp_path):
    clone["run"]("sh", "scripts/setup/install_hooks.sh")
    target = tmp_path / "remote with space.git"
    subprocess.run(["git", "clone", "-q", "--bare", str(tmp_path / "remote.git"), str(target)],
                   env=clone["env"], check=True)
    clone["run"]("git", "checkout", "-q", "-b", "feat")
    (clone["dir"] / "b.txt").write_text(f"token={MARK}\n")
    clone["run"]("git", "add", "b.txt")
    clone["run"]("git", "commit", "-q", "--no-verify", "-m", "leak")
    result = clone["run"]("git", "push", "-q", str(target), "feat")
    assert result.returncode != 0, result.stdout + result.stderr
    assert "gitleaks found secrets" in result.stdout + result.stderr
