"""analyze_langfuse.py reads Langfuse credentials only from the environment (#287)."""

import runpy
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "analyze_langfuse.py"


def test_missing_key_exits_with_message(monkeypatch):
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "dummy-public-key")
    monkeypatch.delenv("LANGFUSE_SECRET_KEY", raising=False)

    with pytest.raises(SystemExit) as exc:
        runpy.run_path(str(SCRIPT))

    assert "LANGFUSE_SECRET_KEY" in str(exc.value.code)


def test_script_contains_no_key_literal():
    source = SCRIPT.read_text()

    assert "pk-lf-" not in source
    assert "sk-lf-" not in source
