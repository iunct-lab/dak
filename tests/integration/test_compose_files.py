"""scripts/compose_files.sh: the compose files of the stack, for COMPOSE_FILE. Needs no stack."""
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "compose_files.sh"


@pytest.fixture(scope="session")
def stack_ready():
    """Overrides conftest's autouse wait: these tests need no stack."""


def _files(*args: str) -> list[str]:
    out = subprocess.run([str(SCRIPT), *args], capture_output=True, text=True, check=True)
    return out.stdout.strip().split(":")


def _in(directory: str) -> list[str]:
    return [str(p) for p in sorted((ROOT / directory).glob("*.yml"))]


def test_lists_base_test_and_feature_files_in_order():
    assert _files("test") == [
        str(ROOT / "docker-compose.yml"),
        *_in("compose/base"),
        str(ROOT / "docker-compose.test.yml"),
        *_in("compose/test"),
    ]
    assert str(ROOT / "compose/test/web-search.yml") in _files("test")


def test_default_lists_only_the_base_files():
    assert _files() == [str(ROOT / "docker-compose.yml"), *_in("compose/base")]


def test_base_feature_files_reach_the_agent():
    for name in ("bedrock.yml", "web-search.yml"):
        assert str(ROOT / "compose/base" / name) in _files()


def test_other_arguments_are_refused():
    out = subprocess.run([str(SCRIPT), "prod"], capture_output=True, text=True)
    assert out.returncode == 2
    assert out.stdout == ""
