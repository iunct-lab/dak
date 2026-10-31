# 小型ローカル LLM の比較（#690）

既定の `llama3.1:8b` と、tech-watch が挙げた候補を、同じ実LLMスモーク（`tests/integration/test_smoke_real_llm.py`）で比べた記録。
**測れたのは `qwen3:14b` の 2 回だけ**で、`gemma4:e4b`・`gemma4:12b` は測っていない。既定を替える根拠にはまだ足りない。

## 候補

| タグ | q4 のサイズ | 機能 | 測ったか |
|------|------|------|------|
| `qwen3:14b` | 9.3GB | tools / thinking | 2 回（予定は 3 回） |
| `gemma4:e4b` | 6.6GB | — | 測っていない |
| `gemma4:12b` | 8.0GB | tools / thinking | 測っていない |
| `mistral-small3.1:24b`, `gemma4:26b` | 15GB 以上 | — | 外した（無料ランナーの 16GB RAM に載らない。#684 の回答 A） |

出典: <https://ollama.com/library/qwen3/tags>、<https://ollama.com/library/gemma4/tags>、<https://ollama.com/library/mistral-small3.1/tags>（確認日 2026-10-13）。

`gemma4` の 2 つを測っていない理由: 比較は `nightly-eval.yml` の手動実行で回す計画だったが、#822 でこの workflow をやめた。残りは回せていない。

## 測り方

- GitHub ホストの無料ランナー（CPU）で `nightly-eval.yml` を `workflow_dispatch`（`model=qwen3:14b`）で実行した。
- 1 ターンのタイムアウトは `DAK_AGENT_RUN_TIMEOUT=600`（ログで確認）。
- スモーク 5 本の観点への対応:

| テスト | 見るもの |
|------|------|
| `test_basic_chat_responds` | 基本の応答 |
| `test_skill_discovery_and_use` | ツール選択（`list_skills` → `enable_skill`）、引数（`read_file` の `path`）、多ターン（3 ターン） |
| `test_enforcer_forces_tool_usage` | ツール選択（強制） |
| `test_ap2_payment_flow_with_real_llm` | ツール選択（支払い）、多ターン |
| `test_minimal_overhead_matches_direct_call` | モデル名が渡されないと skip（常に skip） |

## 結果

値は各実行のログ（pytest の要約行）から写した。artifact の `eval-report.xml` は期限切れで取れなかった。

| モデル | 通過 / 失敗 / skip | 失敗したテスト | 理由の種類 | 実行 |
|------|------|------|------|------|
| `qwen3:14b` | 2 / 2 / 1（pass_rate 0.4） | `test_skill_discovery_and_use`、`test_ap2_payment_flow_with_real_llm` | タイムアウト（`httpx.ReadTimeout`） | 2026-10 の実行 |
| `qwen3:14b` | 2 / 2 / 1（0.4） | 同上 | タイムアウト | 2026-10 の実行 |
| `llama3.1:8b` | 2 / 2 / 1（0.4） | `test_skill_discovery_and_use`、`test_ap2_payment_flow_with_real_llm` | `list_skills` を呼ばない（テキストで言う）/ 支払いツールに触れない（違うツールを呼ぶ） | 2026-10-14 夜間 |
| `llama3.1:8b` | 3 / 1 / 1（0.6） | `test_skill_discovery_and_use` | `list_skills` を呼ばない（テキストで言う） | 2026-10-15 夜間 |

## 読み方

- `qwen3:14b` は 2 回とも同じ 2 本がタイムアウトで落ちた。ツール選択・引数・多ターンのどれが悪いかは分からない（応答が返る前に時間切れになるため）。CPU で thinking のあるモデルは 1 ターンに時間がかかる。
- `llama3.1:8b` は応答は返り、失敗はツール選択の誤り。夜間の pass_rate は 0.25〜0.75 でぶれる。
- 2 回の差では `qwen3:14b` が優れるとも劣るとも言えない。この設定（無料の CPU ランナー、1 ターン 600 秒）では `qwen3:14b` が時間内に答えきれず、tool-calling 品質は測れなかった。タイムアウトを延ばした場合や別のハードウェアでの結果は分からない。
- 既定と推奨を替えるかは利用者が決める。
