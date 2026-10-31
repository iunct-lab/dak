# DAK ハーネスギャップ分析（Claude Code 基準）と P1 実装記録

目的: 「ハーネスエンジニアリングが Claude Code 等に比べて十分でない」という感を構造化し、
既存の調査 Epic **#119**（`docs/comparison/harness-survey-2026-09/`）との整合性を保ちつつ、
実装済み項目と次着手順を記録する。

## 1. 現状の全体像（実測ベース）

- **エージェント側ハーネス**（`agent/dak_agent/`）
  - `planner`, `switch_mode`, `ask_question`, `attempt_answer`（`builtin_tools.py`）— in-process FunctionTool
  - `mode_manager.py`（モード切替）、`enforcer.py`（境界強制）、`harness.py`（3層コンテキスト制御・compaction）
- **リモートツール**（MCP server, `mcp-server/main.py`）— サブエージェント / 外部ハーネスが MCP 経由で呼ぶもの
  - `deep_think`, `read_file`, `write_file`, `list_files`, `run_command`, `search_files`（従来）
  - **新規: `grep`, `edit_file`（実装・単体テスト済み。#159）**

## 2. 今回のギャップを埋めたもの（P1 実装済み）

Claude Code / Codex / OpenCode はいずれも `grep`・`edit` をコアツールとして持つ。
DAK の MCP 側にはそれが欠けていた。これを埋めた。

- `grep(pattern, path=".", glob_pattern="*", ignore_case=False)`
  - 行番号付きマッチング。上限は `MCP_MAX_GREP_MATCHES`（既定 100）。
  - 出力は `_cap_text` / `_cap_entries` でキャップ（`MCP_MAX_OUTPUT_CHARS` / `MCP_MAX_LIST_ENTRIES` と同一の仕組み）。
- `edit_file(path, old_string, new_string, replace_all=False)`
  - 一意置き換えを強制：`replace_all=False` かつ複数マッチ時は拒否 → 誤置換を防止。
  - OpenCode の edit matcher / Codex の `apply_patch` と同趣旨。
- テスト: `mcp-server/tests/test_grep_edit.py`（`TestGrep` / `TestEditFile`, `IsolatedAsyncioTestCase`, temp-dir ベース）。
- 結果: `uv run pytest` → **34 passed**（新規 14 + 既存 20）。
- 統合テスト: `tests/integration/test_mcp_server.py` は `EXPECTED_TOOLS <= tools` の**部分集合**判定なので、
  新ツール追加で破損しない。

## 3. まだ開いているギャップ（Epic #119 参照）

| ギャップ | 状態 | 参照 |
|---|---|---|
| `grep` / `edit_file` | ✅ 実装・単体テスト済み（統合テスト・golden は未） | #159 |
| planner の永続化（`write_todos` 同等） | 未着手 (P1) | #99 系 |
| 調査サブエージェント | 未着手 (P1) | #102 系 |
| 溢れ回復 / ウィンドウ自動検出 | 未着手 (P2) | #87 / #113 |
| SkillToolset 移行（agentskills.io） | 未着手 (P2) | #90 |
| 引数スキーマ違反を Observation / ReflectAndRetry | 未着手 (P2) | #108 |
| `deep_think` の修正 | 未着手 (P2) | — |
| sandbox-runtime で mcp-server を包む | tech-watch (P3) | #118 |

## 4. 推奨次の着手順

1. **planner の永続化**（`write_todos` 同等）→ 計画をセッション間・コンテキスト圧縮後も残す。
2. **調査サブエージェント** → 大規模探索を主ループのコンテキストから分離。
3. 各段で **#93 長時間タスク eval**（窓超過率・圧縮回数・キャッシュヒット率）で効果測定。

## 5. 品質の指針（CLAUDE.md / AGENTS.md 準拠）

- 変更は必ずテストを伴う。
- 既存テスト（`agent/tests/`, `mcp-server/tests/`, `tests/integration/`）を壊さない。
- `COMPOSE_FILE=$(./scripts/compose_files.sh) docker compose up` で起動確認。統合テストは
  `COMPOSE_FILE=$(./scripts/compose_files.sh test) docker compose up -d --build --wait`
  の後に `cd tests/integration && uv run pytest`。
