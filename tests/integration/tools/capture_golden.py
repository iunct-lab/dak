"""Freeze a real agent session into a deterministic golden replay case.

Run against a REAL-model stack (e.g. `scripts/smoke_local_llm.sh --keep`):

    cd tests/integration
    uv run python tools/capture_golden.py --name my_case --prompt "Enable filesystem and read README.md"

It sends the prompt to the live agent, records the tool-call sequence + final
text, and writes tests/integration/golden/<name>.json. That golden then replays
forever in fast PR CI (test_golden_replay.py) without a real model. Requirement 6:
the deterministic suite grows every time the agent succeeds at something new.
"""
from __future__ import annotations

import argparse
import json
import os
import sys

# tests/integration is the pytest root; make its modules importable when run directly.
_HERE = os.path.dirname(os.path.abspath(__file__))
_ITEST = os.path.dirname(_HERE)
sys.path.insert(0, _ITEST)

from conftest import AGENT_URL, AgentClient, event_texts, function_calls  # noqa: E402

GOLDEN_DIR = os.path.join(_ITEST, "golden")


def capture(name: str, prompt: str, model: str, agent_url: str) -> dict:
    client = AgentClient(agent_url)
    session_id = client.create_session()
    events = client.run(session_id, prompt)

    calls = function_calls(events)
    texts = event_texts(events)
    script = [{"tool_call": {"name": c["name"], "args": c.get("args", {})}} for c in calls]
    script.append({"text": texts[-1] if texts else "Done."})

    return {
        "name": name,
        "prompt": prompt,
        "model": model,
        "script": script,
        "expect": {"function_calls": [c["name"] for c in calls]},
    }


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Capture a golden replay case from a live agent")
    p.add_argument("--name", required=True, help="golden case name (also the test id)")
    p.add_argument("--prompt", required=True)
    p.add_argument("--model", default="fake-default", help="model name used at replay time")
    p.add_argument("--agent-url", default=AGENT_URL)
    p.add_argument("--out-dir", default=GOLDEN_DIR)
    args = p.parse_args(argv)

    golden = capture(args.name, args.prompt, args.model, args.agent_url)
    if not golden["expect"]["function_calls"]:
        print("warn: no tool calls observed — このセッションは golden 化に不向きかもしれません。", file=sys.stderr)

    os.makedirs(args.out_dir, exist_ok=True)
    out_path = os.path.join(args.out_dir, f"{args.name}.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(golden, f, ensure_ascii=False, indent=2)
        f.write("\n")
    print(f"wrote {out_path}")
    print(json.dumps(golden, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
