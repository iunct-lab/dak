# Golden replay corpus（育つテスト資産）

各 `*.json` は、一度観測した「エージェントのツール呼び出し系列」を**決定論的に凍結**した
回帰テストケース。fake-LLM にこの系列をスクリプトとして流し込み、エージェントが同じツールを
呼ぶことを PR CI（実LLM不要・高速）で検証する。

実LLMスモークで成功したセッションを `tools/capture_golden.py` で凍結すると、
**使うほど決定論スイートが増えていく**（要件6）。

## フォーマット

```json
{
  "name": "一意な名前（テストID）",
  "prompt": "ユーザ入力",
  "model": "fake-default",
  "script": [
    {"tool_call": {"name": "list_skills", "args": {}}},
    {"text": "最終応答テキスト"}
  ],
  "expect": { "function_calls": ["list_skills"] }
}
```

- `script`: fake-LLM に順に返させる応答（tool_call → ... → text）。
- `expect.function_calls`: エージェントの出力イベントに現れるべきツール名（部分集合でOK）。

## 追加方法

1. 実LLMスタックを起動（`scripts/smoke_local_llm.sh --keep`）。
2. `uv run python tools/capture_golden.py --name my_case --prompt "..."` で新規 golden を出力。
3. 生成された JSON を確認し、PR として提案（`capture-golden` ワークフローは #822 でやめた。手元で回す）。
