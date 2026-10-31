# MCP のツール結果: litellm の共通変換を取り込むか

PBI #671（要望 #657）。litellm の「MCP のツール結果の互換を考えた共通変換」（PR #43089、v1.105.0）を、
DAK がモデルに渡すツール結果に通すべきかを記録する。

## 結論

**C（取り込まない）に決めた**（2026-10-26、利用者の回答。#671 の決定ログ）。実装の PBI は起こさない。

- 共通変換は「MCP の結果 → MCP の結果」の変換で、litellm の proxy が MCP の版（wire の規則）に合わせて下流のクライアントに返す形を揃えるもの。モデル向けの Observation の形を整える変換ではない
- DAK の MCP の結果の経路からは呼ばれない。依存は既に 1.105.1 だが（#925）、DAK がモデルに渡す中身は変わっていない
- DAK の経路に通しても、テキスト・テキスト + 構造化・`isError` の 3 種で中身もトークン数も同じ（恒等）
- 関数は `litellm.proxy._experimental` の内部で、DAK から呼ぶと他コンポーネントの内部実装に依存する（CLAUDE.md の規約）

## 経路

版: google-adk 2.12.0、litellm 1.105.0（wheel を展開して読んだ。DAK の `agent/uv.lock` は 1.105.1 で、下に挙げる litellm の 8 ファイルは 1.105.0 とバイト単位で同じ）、mcp 2.3.0。
ADK と litellm の行は `agent/.venv/lib/python3.12/site-packages/` からの相対パス。

### DAK の MCP の結果が通る関数

| 順 | 関数 | 場所 | すること |
|---|---|---|---|
| 1 | `PatchedMcpToolset` | `agent/dak_agent/agent.py:43`（生成は `:51`） | ADK の `McpToolset` をそのまま使う（`model_config` だけ足す）。`skill_tools.py:143`・`remote_tools.py:20` も `McpToolset` |
| 2 | `McpTool._run_async_impl` | `google/adk/tools/mcp_tool/mcp_tool.py:644` | `session.call_tool(...)` の `CallToolResult` を受け、`:736` で dict にし、`:742` で mcp 2.x だけの `resultType` を落とす |
| 3 | `_dump_mcp_model` | `google/adk/tools/mcp_tool/mcp_tool.py:129` | 1.x と同じ camelCase の鍵（`isError`・`structuredContent`）で dump する |
| 4 | （ADK）`function_response.response` | — | 3 の dict がそのままツールの応答になる |
| 5 | `_elide_part` | `agent/dak_agent/harness.py:827`（呼ぶのは `:967`） | 古いツール結果を、200 字を超えたら省略の印に置き換える。中身の形は変えない |
| 6 | `_content_to_message_param` | `google/adk/models/lite_llm.py:1573` | `response` を `_safe_json_serialize`（`:1226`、`json.dumps(ensure_ascii=False)`）で文字列にし（`:1614`）、role `tool` のメッセージにする（Gemma 4 のモデルでは role `tool_responses`。OpenAI 互換の口を除く） |
| 7 | `LiteLLMClient.acompletion` → `litellm.acompletion` | `google/adk/models/lite_llm.py:1168`, `:1188` | 出来上がったメッセージを渡すだけ。litellm の MCP の処理は通らない |

### litellm 1.105.0 の共通変換

| 関数 | 場所 | 入出力 |
|---|---|---|
| `to_call_tool_result(outcome, compat)` | `litellm/proxy/_experimental/mcp_server/result_conversion.py:67` | `TextResult \| JsonResult \| CallToolResult \| InputRequiredResult \| Exception` → `CallToolResult \| InputRequiredResult` |
| `complete_call_tool_result(outcome, compat)` | 同 `:95` | 上と同じで、interim の結果を `isError` のテキストにする |
| `error_text_result(exc)` | 同 `:60` | 例外 → `isError` のテキスト 1 件 |
| `_downgrade_structured_content(result)` | 同 `:106` | `structuredContent` が dict でなければ、JSON のテキストにして `content` の末尾に足し、`structuredContent` を消す |
| `WireCompat` / `wire_compat_for(protocol_version)` | `litellm/proxy/_experimental/mcp_server/tool_outcome.py:20`, `:25` | `LEGACY`（`2024-11-05` .. `2025-11-25`）/ `MODERN`（`2026-07-28`） |

`CallToolResult` を渡したときに変わるのは、`LEGACY` で `structuredContent` が dict でない結果だけ（テキストが増える方向）。それ以外はそのまま返す。

公開範囲: `litellm/__init__.py` から出ていない。proxy / experimental の内部（モジュールの `__all__` はある）。
依存: litellm の extra の `mcp` / `proxy` が `mcp>=2.2.0,<3` を要る。DAK の環境（mcp 2.3.0）からは import できた。

### 共通変換を呼ぶ litellm の面

| 面 | 場所 | 共通変換を呼ぶか |
|---|---|---|
| proxy の MCP サーバ | `litellm/proxy/_experimental/mcp_server/operations.py:2190`, `:2646`、`mcp_server_manager.py:5777`、`rest_endpoints.py:1293`、`tool_search.py:649` | 呼ぶ |
| `experimental_mcp_client` | `litellm/experimental_mcp_client/client.py:876` | `error_text_result` だけ |
| Responses API の MCP | `litellm/responses/mcp/litellm_proxy_mcp_handler.py:651`（`_parse_mcp_result`） | 呼ばない。1.105.0 でも独自に `TextContent` を空白でつなぐ |
| DAK の経路（上の 1〜7） | — | 呼ばない |

上の行番号は 1.105.0 で読んだ。DAK の 1.105.1 でも、ここで挙げた litellm の 8 ファイル（`result_conversion.py`・`tool_outcome.py`・`operations.py`・`mcp_server_manager.py`・`rest_endpoints.py`・`tool_search.py`・`experimental_mcp_client/client.py`・`responses/mcp/litellm_proxy_mcp_handler.py`）は 1.105.0 と同じ（`cmp`）。

## 変換の前後

テスト: `agent/tests/test_mcp_result_conversion_probe.py`（#674、PR #964）。1.105.0 の出力は
`agent/tests/fixtures/litellm_1_105_mcp_result_conversion.json`（一時の環境で `to_call_tool_result` を `LEGACY` / `MODERN` の両方で呼んだ）。
変換の前後の結果を、上の 3 と 6 の関数に通して tool メッセージの `content` を比べる（2 の `resultType` を落とす処理は手で写した。5 のハーネスの省略は通していない。省略は 200 字を超えた古い結果を印に置き換えるだけで、前後で同じに効く）。トークン数は `dak_agent.harness.estimate_tokens`。

| 種類 | 今の `content` | 変換後（`LEGACY` / `MODERN`） | トークン数 今 → 後 |
|---|---|---|---|
| テキスト 1 件 | `{"content": [{"type": "text", "text": …}], "isError": false}` | 同じ | 22 → 22 |
| テキスト + 構造化 | 上に `"structuredContent": {…}` が付く（同じ値がテキストと構造化の 2 回入る） | 同じ（dict なので落とさない） | 55 → 55 |
| `isError` | `{"content": [...], "isError": true}` | 同じ | 33 → 33 |

小型のローカルモデルに効きそうな差（例: テキストと `structuredContent` の重複を 1 つにする、JSON の包みを外してテキストだけにする）は、共通変換には無い。

## 案の比較

| 案 | DAK の経路に効くか | 他コンポーネント・外部ライブラリの内部実装に依存するか | 暗黙の副作用を足すか | 変える場所 | 小型ローカルモデルでの確認に要るもの |
|---|---|---|---|---|---|
| A: DAK 側で変換する（ADK の `after_tool_callback` かプラグインで `to_call_tool_result` を呼ぶ） | 効くが、3 種では恒等。変わるのは `structuredContent` が dict でない結果だけで、テキストが増える | する（`litellm.proxy._experimental` の内部。litellm の版ごとに場所・引数が変わりうる） | 足す（ツール結果の書き換えが、利用者もモデルも知らないうちに入る。`dict` を `CallToolResult` に戻す往復も要る） | `agent/dak_agent/` に新しいプラグインかコールバック、`agent/agent_config.yaml` か `agent.py` の配線 | 変換の前後で同じ評価（`docs/eval/` の実 LLM スモーク）を回す。3 種では中身が同じなので差は出ない見込み |
| B: 依存を上げるだけ | 効かない（既に 1.105.1。上の経路からは呼ばれない） | しない | 足さない | 無し（#925 で済んでいる） | 無し |
| C: 取り込まない | — | しない | 足さない | 無し（この文書と #674 のテストだけ） | 無し |

**推奨: C**。共通変換は litellm の proxy が下流の MCP クライアントに返す形を MCP の版に合わせるためのもので、
モデルに渡す Observation を整えるものではない。DAK の経路に通しても 3 種とも中身が変わらず、
変わる唯一の場合も小型モデルに有利な方向（短くする）ではない。それでいて A は proxy の内部の関数に依存し、
ツール結果を黙って書き換える層を足す。小型モデル向けにツール結果を整えたいなら、
litellm の変換ではなく DAK のハーネス（`agent/dak_agent/harness.py`）の側で、何をどう縮めるかを別の要望として決める方が筋がよい
（例: テキストと `structuredContent` の重複）。B は既に済んでおり、効かないことを #674 のテストで確かめた。
