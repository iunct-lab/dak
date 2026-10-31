"""Deterministic replay of the golden corpus (tests/integration/golden/*.json).

Each golden freezes a previously-observed tool-call sequence. We script the fake
LLM with that sequence and assert the agent still emits the expected tool calls.
Fast, no real model — runs in PR CI. The corpus grows via tools/capture_golden.py.
"""
import glob
import json
import os

import pytest

from conftest import function_calls

GOLDEN_DIR = os.path.join(os.path.dirname(__file__), "golden")
DEFAULT_MODEL = "fake-default"


def _load_cases():
    cases = []
    for path in sorted(glob.glob(os.path.join(GOLDEN_DIR, "*.json"))):
        with open(path, encoding="utf-8") as f:
            cases.append(json.load(f))
    return cases


_CASES = _load_cases()


@pytest.mark.skipif(not _CASES, reason="no golden cases yet")
@pytest.mark.parametrize("case", _CASES, ids=[c["name"] for c in _CASES])
def test_golden_replay(case, agent, fake_llm):
    model = case.get("model", DEFAULT_MODEL)
    fake_llm.clear(model)
    fake_llm.script(model, case["script"])

    session_id = agent.create_session()
    events = agent.run(session_id, case["prompt"])

    observed = [c["name"] for c in function_calls(events)]
    for expected in case.get("expect", {}).get("function_calls", []):
        assert expected in observed, (
            f"golden '{case['name']}': expected tool '{expected}' not called; observed {observed}"
        )
