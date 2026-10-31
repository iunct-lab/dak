"""Integration regression test for the context-window guard of agent/dak_agent/harness.py
(docs/architecture/harness_engineering.md P3): large tool results repeated in one long tool loop.

`agent-harness-eval` has MODEL_CONTEXT_WINDOW=4000, so every request it sends the
model must stay within request_token_budget = 4000 * 0.85. Each read is under the
tool-output budget (2,000 chars at this window), and together they exceed the
request budget. The reads all happen in one invocation: across invocations
compaction and the pruning of old tool results act first, and the request guard
(fit_request_to_budget) would not be exercised.
"""
from conftest import function_responses

MODEL = "fake-harness"
# 40 lines, 1,840 chars: under the tool-output budget, so every read reaches the model whole.
FIXTURE = "tests/integration/fixtures/harness_stress.txt"
ORIGINAL_REQUEST = f"Investigate the repository by reading {FIXTURE} repeatedly, then summarize it."
REQUEST_TOKEN_BUDGET = int(4000 * 0.85)
READS = 10


def _estimate_tokens(text: str) -> int:
    """agent/dak_agent/harness.py estimate_tokens, copied (tests do not import the agent)."""
    ascii_chars = sum(1 for ch in text if ord(ch) < 128)
    return ascii_chars // 4 + (len(text) - ascii_chars)


def _strings(value, key: str = ""):
    if isinstance(value, str):
        if key not in ("role", "type", "id", "tool_call_id"):
            yield value
    elif isinstance(value, dict):
        for k, v in value.items():
            yield from _strings(v, k)
    elif isinstance(value, list):
        for v in value:
            yield from _strings(v, key)


def _estimate_request_tokens(entry: dict) -> int:
    """The messages of a request as the model received them (system, texts, tool calls and
    results): the part the guard trims. The tool declarations are left out; how they and the
    elided placeholders add up in a long loop is #1009."""
    return sum(_estimate_tokens(s) for s in _strings(entry["messages"]))


def test_repeated_large_tool_results_stay_within_request_budget(agent_harness_eval, fake_llm):
    fake_llm.clear(MODEL)
    fake_llm.script(MODEL, [
        fake_llm.tool_call("enable_skill", skill_name="filesystem"),
        # a different (still whole-file) limit each time: the tool guard blocks a call repeated more than 3 times in a row
        *[fake_llm.tool_call("read_file", path=FIXTURE, limit=100 + i) for i in range(READS)],
        fake_llm.text("summary done"),
    ])
    session_id = agent_harness_eval.create_session()
    events = agent_harness_eval.run(session_id, ORIGINAL_REQUEST)

    reads = [r for r in function_responses(events) if r.get("name") == "read_file"]
    assert len(reads) == READS, f"expected {READS} read_file results, got {len(reads)}"
    read_tokens = sum(_estimate_tokens(s) for s in _strings(reads))
    # Without the guard the last request would carry all of them: the scenario must need it.
    assert read_tokens > REQUEST_TOKEN_BUDGET, f"the reads ({read_tokens}) do not exceed the budget"

    requests = [entry for entry in fake_llm.requests(MODEL) if entry["tools"]]
    assert len(requests) == READS + 2
    sizes = [_estimate_request_tokens(entry) for entry in requests]
    assert max(sizes) <= REQUEST_TOKEN_BUDGET, f"a request exceeded the budget {REQUEST_TOKEN_BUDGET}: {sizes}"

    assert any(ORIGINAL_REQUEST in s for s in _strings(requests[-1]["messages"])), "the original request was lost"
