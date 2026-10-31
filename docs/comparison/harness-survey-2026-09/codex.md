# Codex CLI ハーネス実装調査（DAK が設計を参考にする観点）

対象: `github.com/openai/codex` main @ `2f8603f0` (2026-09-14)。以下、ファイルパスは `codex-rs/` からの相対。`docs/` 配下の md は 2026 年中にほぼ全て `learn.chatgpt.com/docs/...` へのリンクだけになっており、仕様は Web 版と実コードから読んだ。

## 0. 2026 年に何が変わったか（要点）

- **2026-02 「Harness engineering」ブログ**: 5 ヶ月で約 100 万行を人手のソースコードなしで出荷した社内実験。ハーネス＝「モデルとタスクの間に座る実行系」。中身は AGENTS.md を目次にした `docs/` 知識ベース、依存方向（Types→Config→Repo→Service→Runtime→UI）を lint/構造テストで機械的に強制、ログ/メトリクス/スパンをエージェントが読める形にした観測性、「context engineering + architectural constraints + garbage collection」。
- **2026-08-19 「Codex as a platform: build on the open agent harness」**: ハーネス本体（CLI、`app-server`、公式 SDK）を OSS として "組み込み用の実行系" と再定義。統合層は 3 つ: `codex exec`（非対話・構造化出力）、SDK、`app-server`（スレッド/ターン/承認までフル制御）。
- コードで確認できる 2026 の主な追加: `hooks` crate、`memories`（バックグラウンド記憶抽出）、`guardian`（承認をモデルが自動審査）、multi-agent v1/v2（`spawn_agent` 等）、collaboration mode（Plan/Default）、remote compaction v2 / token budget、`tool_search`（遅延ロード）、`request_permissions`。
- **Chat Completions は削除済**。`model-provider-info/src/lib.rs:68` の `WireApi` は `Responses` のみ。Ollama も Responses API 対応版が前提。DAK が LiteLLM 経由で chat 形式に依存する点とは根本的に異なる。

## a. 全体アーキテクチャ

### crate 地図（抜粋）
`core`（エンジン）/ `protocol`（Op/Event と型）/ `app-server` + `app-server-protocol`（JSON-RPC 面）/ `exec`（非対話 CLI）/ `tui` / `tools` / `sandboxing` + `linux-sandbox` + `windows-sandbox-rs` / `execpolicy`（Starlark ルール）/ `apply-patch` / `rollout` + `history`（永続化）/ `hooks` / `skills` / `memories` / `models-manager` / `prompts` / `otel` / `rmcp-client`。core だけで 61k 行。

### SQ/EQ とターンのライフサイクル
- `protocol/src/protocol.rs:192` `Submission { id, op: Op, trace, parent_turn_id, root_turn_id }` と `Event { id, msg: EventMsg }`。`Op` は `Interrupt / TurnInput{mode} / ExecApproval / PatchApproval / ResolveElicitation / UserInputAnswer / RequestPermissionsResponse / Compact / Review / ...`。`EventMsg` は 100 超（`TokenCount`, `ContextCompacted`, `ExecCommandBegin/OutputDelta/End`, `ExecApprovalRequest`, `TurnDiff`, `PlanUpdate`, `HookStarted/Completed`, `CollabAgent*`...）。
- 実体: `core/src/codex_thread.rs`（スレッド）→ `session/session.rs` `Session` → `session/turn_context.rs` `TurnContext` → `session/step_context.rs` `StepContext`。タスクは `tasks/{regular,compact,review,user_shell}.rs` が `SessionTask` trait で並ぶ。
- `session/turn.rs:163 run_turn()`: `run_pre_sampling_compact` → hooks と入力記録 → MCP サーバ解決 → `try_run_sampling_request` でストリーム受信、ツール呼び出しを `ToolCallRuntime`（`tools/parallel.rs`）へ並列投入 → `TokenCount` 更新 → `context_window_token_status` 評価 → 必要なら `run_auto_compact` → `needs_follow_up` なら次サンプリング。
- **ステア**: `TurnInputMode { StartOrSteer, StartIfIdle, Steer{expected_turn_id} }`。実行中ターンへの追加入力は `session/input_queue.rs` の mailbox に積まれ、サンプリング境界で取り出される。

### コアと UI の分離
`app-server` は JSON-RPC 2.0（stdio JSONL / WebSocket / UDS）。`thread/start|resume|fork|archive`、`turn/start|steer|interrupt`、通知 `item/started|completed`、承認は `item/commandExecution/requestApproval` 等にクライアントが `accept | acceptForSession | decline | { acceptWithExecpolicyAmendment }` で応答。`codex app-server generate-ts / generate-json-schema` でスキーマを吐く。TUI も同じ Op/Event を消費する一クライアント。`codex exec --json` は EventMsg を JSONL に落とす。

### 「ハーネス」語彙
`history` crate の `CodexHarnessMetadata`（`ResponseItemEnvelope { item, metadata }`）として「この履歴アイテムはハーネスが書いたか」という出自を全アイテムに付与。`context_manager/history.rs:778 is_api_message()` は「生の system メッセージは決して保持しない。設定更新はハーネス出自が必須」と明記。

## b. コンテキスト管理

### 履歴と token 追跡
- `context_manager/history.rs:72 ContextManager`。`record_items(items, TruncationPolicy)` で記録時に切り詰め、`for_prompt()` で `normalize_history`。`replace_compacted`, `drop_last_n_user_turns`（ロールバック/フォーク用）。
- token は Responses API の `usage` を保持。加えてローカル推定 `estimate_item_token_count`（= 可視バイト数 / 4）。
- モデル窓: `models-manager/models.json`（サーバ配布）に `context_window`, `truncation_policy {mode: tokens, limit: 10000}`, `effective_context_window_percent`。未知モデルは `context_window 272_000`, `effective 95%`, `truncation bytes 10_000`。config で `model_context_window` / `model_auto_compact_token_limit` / `tool_output_token_limit` を上書き。

### 自動コンパクションの発火条件
`protocol/src/openai_models.rs:521`:
```rust
pub fn auto_compact_token_limit(&self) -> Option<i64> {
    let context_limit = self.resolved_context_window().map(|w| (w * 9) / 10);
    ... min(config_limit, context_limit)
}
```
`session/context_window.rs:52` で `token_limit_reached = scope_tokens >= (auto_compact_limit + fallback_buffer) || active_tokens >= window * effective_percent / 100`。**既定は窓の 90%（ハード上限は 95%）**。評価点は (1) 各サンプリング直後（MidTurn）、(2) ターン開始前（PreTurn）、(3) モデルが `new_context` ツールを呼んだ時、(4) ユーザ `Op::Compact`。`AutoCompactTokenLimitScope::BodyAfterPrefix` で「安定プレフィックス以降の増分」だけを閾値対象にできる。

### 3 種類の実装と「何を残すか」
`session/turn.rs:1397 run_auto_compact` が分岐: `Feature::TokenBudget` → `compact_token_budget.rs`、remote v2 → `compact_remote_v2.rs`（サーバ側要約）、それ以外 → ローカル `compact.rs`:
1. 履歴末尾に要約指示（`prompts/templates/compact/prompt.md`）を user メッセージとして追加し、通常の base_instructions のまま 1 回サンプリング。指示文は短い: 「CONTEXT CHECKPOINT COMPACTION。次の LLM が再開できる handoff summary を作れ: 進捗と決定、制約/好み、残タスク、必要なデータ/参照」。
2. `ContextWindowExceeded` なら **先頭から 1 件削除して再試行**（「Trim from the beginning to preserve cache (prefix-based)」）。
3. 新履歴 = `build_compacted_history()`: 直近の **ユーザメッセージを新しい順に合計 20,000 tokens まで**原文保持 + `SUMMARY_PREFIX` 付き要約（user ロール）。その後 `insert_initial_context_before_last_real_user_or_summary()` で環境コンテキスト/AGENTS.md 等を最後の実ユーザメッセージの直前に再注入。
4. `ContextCompacted` イベントと Warning「Long threads and multiple compactions can cause the model to be less accurate. Start a new thread when possible」を送出。`pre_compact`/`post_compact` hook も走る。

### ツール出力の切り詰め
- `TruncationPolicy::{Bytes, Tokens}`。`utils/string/src/truncate.rs` は **中央を落として先頭・末尾を保持**（50/50、UTF-8 境界維持）。`APPROX_BYTES_PER_TOKEN = 4`。
- `utils/output-truncation/src/lib.rs:20 formatted_truncate_text` は先頭に `Warning: truncated output (original token count: N)\nTotal output lines: L` を付ける。
- exec は二段: 生出力は `unified_exec/head_tail_buffer.rs` の `HeadTailBuffer<1 MiB>`（頭 512 KiB + 尾 512 KiB）、モデルに返す時は `min(要求 max_output_tokens (既定 10,000), モデルの truncation_policy)`。**ページング用の read_tool_output 相当は無い**（DAK の方が進んでいる）。

### プロンプトキャッシュ配慮
- `client.rs:497 prompt_cache_key()` はスレッド単位。`responses_request_properties_match` は model/instructions/tools 等が前回と同一かを比較し、WebSocket の増分送信を再利用。
- 文脈は「一度注入したら差分だけ」: `core/src/context/world_state/` の `WorldStateSection` trait（`snapshot()` と `render_diff()`）が環境・権限・AGENTS.md・collaboration mode・context window guidance などをセクション化し、前回スナップショットとの差分のみ developer メッセージとして追記。
- `context/memory.rs`: メモリ注入は `TruncationPolicy::Bytes(8_900)` で <10k tokens に固定。

## c. ツール

- **型**: `ToolSpec::{Function, Namespace, ToolSearch(遅延ロード), WebSearch, Freeform(文法)}`。`defer_loading` で MCP/プラグインのツールをプロンプトから外し、`tool_search(query, limit)` で必要時にだけ出す（`handlers/tool_search_spec.rs`）。
- **ディスパッチ**: `tools/registry.rs` `CoreToolRuntime` trait（`pre_tool_use_payload`/`post_tool_use_payload` で hooks 連携）→ `tools/router.rs` → `tools/parallel.rs`（並列、失敗は `success:false` の function_call_output に変換）→ `tools/orchestrator.rs`（承認とサンドボックス）。
- **unified_exec**（`handlers/shell_spec.rs`）: `exec_command(cmd, workdir, tty, yield_time_ms[既定 10000], max_output_tokens[既定 10000], shell, login, sandbox_permissions, justification, prefix_rule, ...)`。`yield_time` 内に終わらなければ session_id を返し、`write_stdin(session_id, chars, yield_time_ms)` で対話継続。上限 64 プロセス、バックグラウンド既定 300 秒。
- **apply_patch**: `*** Begin Patch` / `*** Add File:` / `*** Delete File:` / `*** Update File:` (+ `*** Move to:`) / `@@ context` / `*** End Patch`。行番号なし・文脈行で位置決め（`seek_sequence.rs` で緩い一致）。GPT-5 系には `ToolSpec::Freeform` + Lark 文法で constrained decoding。`safety.rs assess_patch_safety` で書込可能ルート内か判定、`turn_diff_tracker.rs` がターン単位の unified diff を `TurnDiff` イベントで流す。
- **その他**: `view_image`、`web_search`、`request_user_input`（質問＋選択肢）、`request_permissions`（権限プロファイルの追加要求）、`update_plan`（in_progress は 1 つ）、`get_context_remaining`、`new_context`、`mcp_resource`、dynamic tools。
- **MCP**: `rmcp-client`。名前空間は `mcp__<server>__<tool>`、説明文の上限 512 KiB。elicitation は `Op::ResolveElicitation`。
- **サブエージェント**: v2 は `spawn_agent / send_message / wait_agent / list_agents / close_agent / interrupt_agent / followup_task / resume_agent`。子は親の履歴をフォークして開始、`agent/role.rs` は「ロールは子の能力を縮小できるが親の権限を超えない」。深さ上限・同時数上限。子→親の返答は `Message Type: FINAL_ANSWER\nTask name: ..\nSender: ..\nPayload:` という固定封筒。委譲の積極性は `MultiAgentMode::{ExplicitRequestOnly, Proactive}` で切替。
- **スキル**: `skills/src/parser.rs` が `SKILL.md` frontmatter（`name`, `description`, `metadata.short-description`, `interface`, `dependencies`, `policy.allow_implicit_invocation`）を検証。`$skill` 明示メンションと暗黙起動。
- **Hooks**（`hooks/src/events/`）: `session_start / session_end / user_prompt_submit / pre_tool_use / post_tool_use / permission_request / pre_compact / post_compact / stop / interrupt / subagent_start / subagent_stop`。ハンドラ型は `Command | Prompt | Agent`、`hooks.json`。`pre_tool_use` は block と `updated_input`（引数書換え）が可能、`additional_context` 注入あり。
- **Plan mode**: `collaboration-mode-templates/templates/plan.md`。「Plan Mode は developer メッセージが明示的に終了するまで続く」「非変異アクションのみ許可」「3 フェーズ（環境で事実確認→意図→実装仕様）」「`update_plan` は Plan mode でエラーになる」。基本はプロンプト制御で、ツール側の拒否は `update_plan` のみ（ファイル書込みの機械的ブロックはサンドボックス側の責務）。
- **Review mode**: `tasks/review.rs` が別会話を `prompts/templates/review/rubric.md` で起動し、構造化 findings を親履歴へ記録して戻る。

## d. 安全性

- **ポリシー型**: `SandboxPolicy::{DangerFullAccess, ReadOnly{network_access}, ExternalSandbox{network_access}, WorkspaceWrite{writable_roots, network_access, ...}}`。`WritableRoot { root, read_only_subpaths, protected_metadata_names }`: 「`.codex`, `.git`（特に `.git/hooks`）は権限昇格に使えるので書込可能ルート下でも読み取り専用」。`PermissionProfile`（組込み `read_only / workspace / danger_full_access`）、プロジェクトが trusted なら既定 workspace、そうでなければ read_only。
- **承認**: `AskForApproval::{UnlessTrusted, OnRequest(alias "on-failure"), Granular{...}, Never}`。`ReviewDecision::{Approved, ApprovedExecpolicyAmendment, ApprovedForSession, Denied{rejection}, TimedOut, Abort}`。承認結果は `ApprovalStore` にキャッシュ。
- **拒否→再実行のループ**（`tools/orchestrator.rs:122 run()`）: (1) execpolicy から `ExecApprovalRequirement::{Skip, NeedsApproval, Forbidden}` を決定 → (2) サンドボックス下で初回実行 → (3) `SandboxErr::Denied` の判定は `sandboxing/src/denial.rs is_likely_sandbox_denied()`（exit code 2/126/127 は除外、seccomp は `128+SIGSYS`、それ以外は stderr の "operation not permitted", "read-only file system" 等。コメントで「決定論的には判定できない」と明記）→ (4) `escalate_on_failure()` かつポリシーが許す場合のみ、`retry_reason = "command failed; retry without sandbox?"` を付けて承認要求し、非サンドボックスで再実行。拒否はそのまま `success:false` の function_call_output としてモデルに返る。モデル側には `prompts/templates/permissions/approval_policy/on_request.md` で「サンドボックス起因で失敗したら `sandbox_permissions: "require_escalated"` + `justification` + 任意の `prefix_rule` で再実行せよ。ユーザに先に聞くな」「`rm` には prefix_rule を付けるな、`["python3"]` のような広い prefix は禁止」と教えている。
- **OS 実装**: macOS `seatbelt_base_policy.sbpl`（`(deny default)`）、Linux は bubblewrap + Landlock + seccomp、Windows は restricted token。ネットワークは `network-proxy` crate。既に別サンドボックス内なら `ExternalSandbox`。
- **execpolicy**: Starlark の `prefix_rule(pattern=[...], decision="allow|prompt|forbidden", justification, match, not_match)`。複数一致時は最も厳しい決定が勝つ。`bash -lc` は `&&`/`||`/`;`/`|` で分割して各セグメント評価、リダイレクト・置換・環境変数付きは評価しない。承認時の「以後許可」は `exec_policy.rs:464 append_amendment_and_update` が `.rules` に追記。
- **Guardian**（`core/src/guardian/`）: 承認を人でなくレビューモデルに判断させる仕組み。

## e. 指示と設定の階層

- **AGENTS.md**（`core/src/agents_md.rs`）: グローバル `~/.codex/AGENTS.override.md` → `AGENTS.md`、プロジェクトはルートから cwd へ降りながら各ディレクトリ 1 件、`--- project-doc ---` で連結、合計 `project_doc_max_bytes`（既定 32 KiB）で打ち切り。**untrusted プロジェクトでは読み込まない**。
- **基底プロンプト**: モデル毎に `core/gpt_5_2_prompt.md` 等。`models.json` の `model_messages`（`instructions_template`, `approvals`, `permissions`, `collaboration_modes`, `multi_agent`, `token_budget`）がサーバから来て、ローカル/未知モデルは `models-manager/prompt.md` にフォールバック。
- **ロール**: ハーネス注入文脈は `ContextualUserFragment` で `role()` を宣言（環境コンテキスト・権限・メモリ指示は `developer`、AGENTS.md や compaction summary は `user`）。system ロールは保持されない。
- **config**: `ConfigLayerStack`（system/managed → user → project（trusted 時）→ profile → CLI）。管理者制約は `configRequirements`。

## f. 観測性とテスト

- **Rollout**: `~/.codex/sessions/YYYY/MM/DD/rollout-<ts>-<thread_id>.jsonl`。行は `RolloutItem::{SessionMeta, ResponseItem(envelope), Compacted, TurnContext, TokenUsageRecord, WorldState, EventMsg, ...}`。SQLite の state DB が索引。`thread/fork` は履歴を切って新 thread_id。
- **OTel**: `otel` crate `SessionTelemetry`（`tool_decision`, `sandbox_outcome(denied|timed_out|signal)`, `record_turn_ttft`, `record_turn_cost`）。
- **テスト**: `core/tests/suite/*.rs`（100 超）。`core/tests/common/responses.rs` が wiremock ベースのモック Responses サーバと SSE ビルダ、`ResponsesRequest` に `instructions_text()`, `function_call_output_text(call_id)`, `message_input_texts(role)`, `tool_by_name()` など **リクエスト側を検査するヘルパ**を持つ。文脈描画は insta スナップショット。

## g. 設計思想の読み取り

1. **モデルが要求し、ハーネスが強制する**: 昇格は `sandbox_permissions` パラメータでモデルが明示要求、承認はユーザ/Guardian、ルール永続化はユーザ決定。DAK の「System ENABLES, Agent DECIDES」と同型。
2. **出自を型で持つ**: 全履歴に `CodexHarnessMetadata`、system ロール禁止、developer/user の使い分け。
3. **プレフィックス安定性を最優先**: 文脈は差分注入、compaction は先頭から削る、リクエスト同一性チェック。
4. **予算はバイト≒トークン/4 で十分**: 厳密な tokenizer を持たず全て近似。
5. **不確実性を認める**: サンドボックス拒否はヒューリスティック、compaction 後の精度低下を警告で明示。
6. **モードは指示で、境界は機構で**: Plan mode は developer メッセージ、書込み禁止はサンドボックス。
7. **全部スキーマ化・観測可能**: app-server の TS/JSON schema 生成、hook 入出力スキーマ、otel。

## DAK が設計を参考にすべき候補（優先順）

| # | 機構（Codex 参照） | DAK での価値 | 実装スケッチ | 規模 | 原則との衝突 |
|---|---|---|---|---|---|
| 1 | **拒否→昇格再要求ループの構造化**（`tools/orchestrator.rs`, `sandboxing/src/denial.rs`, `on_request.md`） | 「拒否理由 + 再要求の作法（`sandbox_permissions=require_escalated`, `justification`）」をツール引数として公開すると小型モデルでも再試行が定型化する | mcp-server `run_command` に `escalation: {requested, justification, prefix_rule}` を追加。拒否時 `{status:"denied_by_policy", reason, can_request_escalation, hint}` を返し、承認フローへ接続 | M | なし |
| 2 | **head+tail 切り詰めとメタ見出し**（`truncate.rs`, `output-truncation`, `HeadTailBuffer`） | 「元 token 数・総行数」の見出しと中央省略を足すだけで、8K モデルの失敗（末尾のエラーが見えない）が減る | `harness.py` の切り詰めを middle-cut に、見出し `Warning: truncated output (original token count: N) / Total output lines: L / artifact: <id>` を付与 | S | なし |
| 3 | **compaction の保持構造**（`build_compacted_history`, `insert_initial_context_before_last_real_user_or_summary`） | 「直近ユーザ発話を予算内で原文保持 + 固定プレフィックス要約 + 環境/指示の再注入」「溢れたら先頭から削って再試行」は小型モデルで効く | ADK compaction を差し替え: ユーザ発話予算を窓の 10–15%、要約プロンプトは 4 項目、`ContextCompacted` 相当の Observation とユーザ警告 | M | なし |
| 4 | **閾値の二段化と `get_context_remaining` / `new_context` ツール** | 90%/95% を窓サイズから導出し、モデルにも残量を問い合わせさせる。8K 窓ではモデル自身が節目で `new_context` を選べるのが重要 | 2 ツールを追加、`BodyAfterPrefix` 相当を設定可に | S | なし |
| 5 | **World-state 差分注入**（`WorldStateSection`） | 環境・権限・プランなどを毎ターン再注入せず差分だけにするとキャッシュと窓の両方に効く | `before_model_callback` でセクション毎に snapshot を session state に保存し、変化時のみ追記 | M | なし |
| 6 | **execpolicy 風プレフィックスルール + 承認時の永続化** | 安全層を宣言的に。「最も厳しい決定が勝つ」「`&&`/`|` 分割」「リダイレクト付きは評価しない」 | TOML/JSON の `[[prefix_rule]]`。決定 `allow/prompt/forbidden`。承認時にルール追記 | M | 永続化はユーザの明示決定に限定すれば整合 |
| 7 | **保護パス**（`read_only_subpaths`, `protected_metadata_names`） | `.git`, `.git/hooks`, skills 定義を書込み可能ルート下でも拒否 | mcp-server の `write_file` / `run_command` に追加 | S | なし |
| 8 | **AGENTS.md 探索規則**（`agents_md.rs`） | ルート→cwd の連結順、1 ディレクトリ 1 件、override、32 KiB 上限、untrusted では不読込 | `dak_agent` の指示ローダに同ロジック | S | なし |
| 9 | **Hooks** | ユーザ設定可能な `hooks.json`（command/prompt 型）に昇格させると監査・入力書換え・追加文脈が外部化できる | hooks ランナー（subprocess, JSON stdin/stdout, timeout）を ADK callback から呼ぶ | M | `updated_input` は暗黙の副作用になり得るので、書換え発生を Observation に残す |
| 10 | **Plan mode を collaboration mode として分離** | 「非変異のみ許可」「update_plan は plan mode で拒否」 | モード切替に `plan` を追加し、enforcer が変異ツールをブロック | S | なし |
| 11 | **リクエスト検査型テストヘルパとスナップショット** | fake-LLM は応答スクリプト中心。「モデルに何を送ったか」を検証するヘルパを足す | fake-LLM に受信リクエスト保存 API `/requests/{model}` を追加 | S | なし |
| 12 | **遅延ツールロード（`tool_search`）** | 8K 窓で MCP/スキルのツール定義が窓を食う問題への直接解 | コアツールのみ常時公開、他は `tool_search(query)` で定義を返して次ターンに有効化 | M | なし |

**参考にしないもの**: OS サンドボックス（Seatbelt/Landlock/bwrap）— DAK はツールを別コンテナで実行しており `ExternalSandbox` に相当、二重化は無駄。Responses-only ワイヤ・remote compaction・token budget — OpenAI サーバ依存。`apply_patch` の Freeform 文法 — constrained decoding 前提で小型モデル/LiteLLM では動かない（小型モデルには `str_replace` 型の方が失敗が少ない）。Guardian — 承認をモデルに任せるのはコストと原則の両面で時期尚早。multi-agent v2 — DAK は A2A ピアがあるので、封筒形式 `FINAL_ANSWER` と深さ/同時数上限だけ借りれば足りる。

Sources: [Codex as a platform: build on the open agent harness](https://developers.openai.com/blog/codex-as-a-platform), [InfoQ: OpenAI Introduces Harness Engineering](https://www.infoq.com/news/2026/02/openai-harness-engineering-codex/), [Codex app-server docs](https://learn.chatgpt.com/docs/app-server), [AGENTS.md guide](https://learn.chatgpt.com/docs/agent-configuration/agents-md), [Execution policy rules](https://learn.chatgpt.com/docs/agent-configuration/rules), [Codex changelog](https://developers.openai.com/codex/changelog)
