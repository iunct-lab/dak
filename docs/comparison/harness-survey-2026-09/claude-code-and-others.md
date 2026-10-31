# Claude Code の公開範囲、その他 OSS ハーネス群、横断的設計原則、標準（2026-09 時点）

対象外（別ファイル）: Codex CLI / OpenCode / Gemini CLI / Goose は位置づけの言及のみ。
ローカル検証: `/tmp/harness-research/` に pi, deepagents, openhands-sdk, mini-swe-agent, crush, hermes-agent, claude-agent-sdk-python, sandbox-runtime を shallow clone（2026-09-14 時点の main）。

---

## 1. Claude Code は何が公開で何が非公開か

### 1.1 結論表

| 成果物 | ライセンス/公開状態 | 根拠 |
|---|---|---|
| `@anthropic-ai/claude-code`（npm CLI 本体） | **非公開**。minify されたバンドルのみ配布。ソースは GitHub `anthropics/claude-code` に無い（Issue と docs のみ） | https://github.com/anthropics/claude-code |
| Claude Agent SDK（`claude-agent-sdk-python` / `-typescript`） | **MIT**。ただし SDK は CLI バイナリを `_bundled/` に同梱し、それを子プロセスとして駆動する薄いラッパ。ハーネス本体は依然ブラックボックス | `claude-agent-sdk-python/src/claude_agent_sdk/_bundled` |
| `anthropics/sandbox-runtime`（srt） | **Apache-2.0**。macOS `sandbox-exec` / Linux `bubblewrap` + プロキシによるネットワーク許可リスト。MCP サーバやエージェントプロセスを包める | `sandbox-runtime/README.md` |
| 公開ドキュメント（`code.claude.com/docs`） | 仕様レベルで公開。hooks の I/O 契約、権限モード、サブエージェント隔離モデル、チェックポイント、headless プロトコルなど | 各節で URL を引用 |
| Agent Skills 仕様（agentskills.io） | オープン仕様（skills-ref 検証ライブラリ付き） | https://agentskills.io/specification |

### 1.2 公開されているハーネス機構（実装レベル）

**(a) Hooks — イベント一覧と JSON 契約**（https://code.claude.com/docs/en/hooks）

- イベント（33）: `SessionStart|Setup|SessionEnd`、`UserPromptSubmit|UserPromptExpansion|Stop|StopFailure`、`PreToolUse|PostToolUse|PostToolUseFailure|PermissionRequest|PermissionDenied|PostToolBatch`、`SubagentStart|SubagentStop|TaskCreated|TaskCompleted`、`PreModelSwitch|PostModelSwitch`、`InstructionsLoaded|ConfigChange|CwdChanged|FileChanged|DirectoryAdded|WorktreeCreate|WorktreeRemove`、`PreCompact|PostCompact`、`Notification|MessageDisplay|TeammateIdle`、`Elicitation|ElicitationResult`。
- 共通入力: `session_id, prompt_id, transcript_path, cwd, permission_mode, effort.level, hook_event_name, agent_id/agent_type`。ツール系は `tool_name, tool_input, tool_use_id`。
- 出力契約: **exit 0** = stdout の JSON を読む（無ければプレーンテキストをコンテキストに追加）、**exit 2** = ブロック（stderr がブロック理由）、その他 = 非ブロッキングエラー。JSON は `hookSpecificOutput{permissionDecision: allow|deny|ask, permissionDecisionReason, updatedInput, additionalContext, continue, retry, stopReason, suppressOutput}` + `systemMessage`。SDK では `defer` 判定と `PostToolUse.updatedToolOutput`（モデルに渡す前にツール出力を差し替え）も追加。
- フック種別: `command`、`http`（POST、許可 URL リスト）、`mcp_tool`、`prompt`（高速モデルが JSON で判定）、`agent`（実験的）。
- タイムアウト: 既定 600 秒。同一イベントのフックは**並列**に発火。`if: "Bash(rm *)"` で権限ルール構文によるフィルタ。

**(b) 権限モード**（https://code.claude.com/docs/en/permission-modes）
`default` / `acceptEdits` / `plan`（読み取り専用） / `auto`（分類器が各ツール呼び出しを審査、2026-08-14 から Pro/Max/Team の既定） / `dontAsk`（未許可は**拒否して続行**、CI 向け） / `bypassPermissions`。加えて `--permission-prompts none`。判定順: 権限ルール → `PermissionRequest` フック → モード → プロンプト。

**(c) サブエージェント隔離モデル**（https://code.claude.com/docs/en/sub-agents）
- Markdown + frontmatter（`name, description, tools, disallowedTools, model, permissionMode, maxTurns, skills, mcpServers, hooks, memory, background, isolation: worktree, effort`）。
- 非 fork サブエージェントが受け取るもの: 自分のシステムプロンプト + 委譲プロンプト + CLAUDE.md 階層 + git status。**会話履歴は渡らない**。親に返るのは**最終要約だけ**。
- 制限: ネスト深さ既定 3、同時 20。
- 組み込み: `Explore`（読み取り専用、CLAUDE.md/git status を読み込まず軽量）、`Plan`、`general-purpose`。
- **Agent teams**（実験的）: 共有タスクリスト、JSON メールボックス、他エージェントからのメッセージは「ユーザーではない」と明示され、承認の代理はできない。

**(d) 圧縮・メモリ・チェックポイント**
- 自動圧縮は「古いツール出力を先に消す（micro-compact）→ それでも足りなければ要約」。同じ巨大出力で圧縮直後に再び溢れる場合は**スラッシング検出で自動圧縮を停止**。プロジェクト直下 CLAUDE.md は圧縮後に再注入される。MCP ツール定義は既定で遅延ロード（tool search）。
- Context editing API（`clear_tool_uses_20250919`）と Memory tool: Anthropic 内部ベンチで context editing 単独 +29%、memory 併用 +39%、100 ターン検索タスクで 84% トークン削減。
- CLAUDE.md: managed → user → project → local の順、`@path` import は 4 段まで、`.claude/rules/*.md` は `paths:` glob で遅延ロード、**CLAUDE.md はシステムプロンプトではなくユーザーメッセージとして投入**（強制力なし、強制はフックで）。
- チェックポイント: ターン開始ごとにファイルスナップショット、`/rewind` で「コード/会話/両方」を復元。

**(e) Headless / SDK プロトコル**（https://code.claude.com/docs/en/headless）
`-p` + `--bare`、`--output-format json|stream-json`、`--json-schema` で `structured_output`、`system/init` に `capabilities` 配列。SDK 側の制御プロトコルは `can_use_tool / initialize / set_permission_mode / hook_callback / interrupt`。`ClaudeAgentOptions` には `agents`, `skills`, `sandbox`, `plugins`, `session_store`, `fork_session`, `enable_file_checkpointing`, `task_budget`, `output_format`。

### 1.3 Anthropic エンジニアリング記事の要点（ハーネス関連）

| 記事 | 日付 | ハーネス設計上の主張 |
|---|---|---|
| [Building effective agents](https://www.anthropic.com/research/building-effective-agents) | 2024-12 | ワークフロー（固定）と エージェント（動的）を区別、まず単純な構成から |
| [Writing effective tools for agents](https://www.anthropic.com/engineering/writing-tools-for-agents) | 2025-09 | ツールは少数・高解像度・戻り値はトークン効率重視・ページング/フィルタ引数 |
| [Effective context engineering](https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents) | 2025-09-29 | 「最小の高信号トークン集合」、just-in-time 取得、圧縮・構造化ノート・サブエージェントの 3 手法 |
| [Effective harnesses for long-running agents](https://www.anthropic.com/engineering/effective-harnesses-for-long-running-agents) | 2025-11-26 | Initializer agent と Coding agent の 2 段。feature list JSON、`claude-progress.txt`、機能ごとに git commit、セッション冒頭で git log + progress を読む |
| [Harness design for long-running apps](https://www.anthropic.com/engineering/harness-design-long-running-apps) | 2026-03-24 | Planner / Generator / Evaluator の 3 エージェント。**圧縮ではなくコンテキストリセット + 構造化ハンドオフ**。「ハーネスの各部品はモデルにできないことの仮定を符号化している。モデルが更新されるたびに足場を外せるか検証せよ」 |
| [Managed Agents](https://www.anthropic.com/engineering/managed-agents) | 2026-04-08 | Session（追記専用イベントログ）/ Harness（ステートレスな「脳」）/ Sandbox（「手」）を分離。インターフェースは実装より長生きさせる |

---

## 2. 「Fusion?」の正体と、その他 OSS ハーネスのプロファイル

### 2.1 「Fusion」の最有力候補

**Cognition の「Fusion」**（Devin Desktop / Devin CLI、2026-09-11 発表）がほぼ確実。フロンティア「lead」モデルが計画・曖昧性解釈・レビューを持ち、安価な「sidekick」（SWE-2）に各タスクの brief を渡して実行させる二重モデルハーネスで、36〜39% のコスト削減を主張（https://cognition.com/blog/local-fusion）。**プロプライエタリで OSS ではない**。
次点: `jackulau/fusionHarness`（OSS の mixture-of-agents サーバ）。
DAK への含意: Fusion の lead/sidekick 分割は DAK の Meta-LLM（`meta_llm.py`）+ ModeManager の延長線上にあり、「大きいクラウドモデルが計画、8K〜32K のローカルモデルが実行」という構成の商用実証例として参照価値が高い。

### 2.2 OSS ハーネス 8 本のプロファイル

#### Pi（badlogic/pi-mono）
- TypeScript / **MIT**。`pi-ai`（マルチプロバイダ）、`pi-agent-core`（ループ）、`pi-coding-agent`（CLI）。
- `packages/agent/src/agent-loop.ts` は steering と follow-up を一次要素として持ち、`transformContext` でモデル送信直前に変換。ツールは `bash/edit/find/grep/ls/read/write` の最小セット、それ以外は**拡張**で足す思想。
- 特徴的機構:
  1. **拡張イベント API**（`core/extensions/types.ts`）: `before_agent_start / turn_start / tool_call(block 可) / tool_result / context / before_provider_request / session_compact / model_select`。
  2. **圧縮**（`docs/compaction.md`）: `contextTokens > contextWindow - reserveTokens(16384)` で発火、`keepRecentTokens(20000)` だけ残す。**ツール結果追記直後・同一 run 内で圧縮**して続行。圧縮用プロンプトはキャッシュ書き込みを無効化。
  3. 権限機構を**意図的に持たない** — micro-VM / Docker で外側から隔離。`docs/llama-cpp.md` で llama.cpp を一級サポート。
- DAK 関連度: **高**。ローカル LLM 前提の圧縮パラメータ設計、権限を外殻に任せる思想は DAK の疎結合コンテナ構成と一致。

#### Deep Agents（langchain-ai/deepagents）
- Python / **MIT**。LangGraph → LangChain `create_agent()` → Deep Agents（ミドルウェア束）の 3 層。
- 特徴的機構（`middleware/`）:
  1. **要約ミドルウェア** `summarization.py`: トリガ `("fraction", 0.85)`、保持 `("fraction", 0.10)`。`truncate_args` で古い `tool_calls.args` だけ先に切る二段構え。
  2. **溢れ時の読み側クリップ** `_overflow_clip.py`: `ContextOverflowError` を捕まえたら、`read_file` 結果は先頭だけ残して「元パスを再読せよ」の注記、その他は `/large_tool_results/{tool_call_id}` にオフロードしてスタブ化。
  3. `_tool_exclusion.py` + `profiles/`: モデル/プロバイダ**プロファイルでツールを request 時に隠す**（削除ではなく非表示）。`write_todos`、`task`、`skills.py`、`memory.py`、`libs/acp` に ACP サーバ実装。
- DAK 関連度: **高**。overflow_clip の「読み直せる場所へのポインタを残す」設計と、プロファイルによるツール非表示。

#### OpenHands agent-sdk
- Python / **MIT**。イベントソーシングが中心。
- 特徴的機構:
  1. **Condenser**（`context/condenser/`）: `LLMSummarizingCondenser(max_size=240 events, keep_first=2)`。要約は `Condensation` **イベントとして履歴に追記**され、`View.from_events` が LLM に見せる射影を再構成する（履歴は不変）。`agent/agent.py` L776-804: モデルが context-window-exceeded を投げたら**強制 condensation してリトライ**、`hard_context_reset` も用意。
  2. **リスク注釈付き権限**（`security/`）: `llm_security_analyzer=True` が既定で、ツール呼び出しに `SecurityRisk(LOW|MEDIUM|HIGH|UNKNOWN)` をモデル自身が注釈、`ConfirmationPolicy`（`AlwaysConfirm / NeverConfirm / ConfirmRisky(threshold=HIGH)`）で確認要否を決める。
  3. **Claude Code 互換フック**（`hooks/`）: `PreToolUse/PostToolUse/UserPromptSubmit/SessionStart/SessionEnd/Stop`、stdin JSON、`HookDecision allow|deny`。**Critic**（`critic/`）で完了判定を別視点から評価。ツールは `ToolDefinition[Action, Observation]` の型付き Observation。
- DAK 関連度: **非常に高**。同じ Python、Observation 型。Condenser のイベント追記モデルは ADK の `EventsCompactionConfig` と思想が近く、overflow リトライは DAK #88 そのもの。

#### mini-SWE-agent
- Python / **MIT**。`agents/default.py` は **190 行**。
- 1. **単一 bash アクション + テキスト応答**: function calling を使わないので小型/ローカルモデルでも動く。LiteLLM 経由。
- 2. **限界を例外で制御フロー化**: `step_limit / cost_limit / wall_time_limit_seconds / max_consecutive_format_errors` を超えると `LimitsExceeded / TimeExceeded / RepeatedFormatError` を "exit" ロールのメッセージとして記録し終了。
- 3. **トラジェクトリを毎ステップ保存**。圧縮は無い。
- DAK 関連度: **中〜高**。「小型モデルでの決定論的ガード」「予算超過を Observation として返す」の最小実装。

#### Crush（charmbracelet/crush）
- Go / **FSL-1.1-MIT**。
- 1. **ループ検出** `internal/agent/loop_detection.go`: 直近 10 ステップで「ツール呼び出し+結果」の SHA-256 署名が 5 回超で停止。
- 2. `internal/hooks/`（Claude Code 互換名）と `hooked_tool.go`（全ツールをフックでラップ）。
- DAK 関連度: **中**。ループ検出とフック名の互換性が参考。

#### Hermes Agent（NousResearch）+ OpenClaw
- Python / **MIT**。「self-improving agent」: タスク後に**スキルを自動生成し使いながら改善**。
- 1. `agent/context_engine.py` の `ContextEngine` ABC: `threshold_percent=0.75`、**プリフライトと応答 usage の両方で判定**、`prune_tool_results_only`（低い閾値で古いツール結果だけ先に落とす）。`context_compressor.py` は要約失敗を分類して圧縮を中止・再試行。
- 2. `agent/curator.py`: アイドル時にスキルの stale 判定・アーカイブ・統合。
- DAK 関連度: **中**（常駐・自己改善スキルは DAK の maintenance/tech-watch 系と相性がよい）。

#### Forge（antinomyhq/forgecode）
- Rust / **Apache-2.0**。restricted shell mode、ポリシー/権限エンジン、エージェント定義は `.forge/agents/*.md`。DAK 関連度: **低〜中**。

#### Cline
- TypeScript / **Apache-2.0**。Plan/Act の明示モード、書き込みごとの承認、チェックポイント（shadow git）、ACP 対応。DAK 関連度: **低〜中**。

---

## 3. 横断的な設計原則（15）と DAK への写像

出典略号: CC=Claude Code docs、A-Nov=Anthropic 2025-11、A-Mar=Anthropic 2026-03、MA=Managed Agents、OAI=[OpenAI Harness engineering](https://openai.com/index/harness-engineering/)、Manus=[Manus Context Engineering](https://manus.im/blog/Context-Engineering-for-AI-Agents-Lessons-from-Building-Manus)、Cog=[Cognition "Don't build multi-agents"](https://cognition.ai/blog/dont-build-multi-agents)。

| # | 原則 | 体現しているハーネス（証拠） | DAK での状態 |
|---|---|---|---|
| 1 | **ツール出力は予算化し、全文はファイルへ退避してポインタを返す** | Manus; Deep Agents `_overflow_clip.py`; CC micro-compact; Codex/OpenCode 切り詰め | **済**（`harness.py` Artifact + `read_tool_output`） |
| 2 | **圧縮は run 内で、直近窓は保持、要約はスキーマ化** | Pi `reserveTokens/keepRecentTokens`; Deep Agents 0.85/0.10; OpenHands `keep_first`; OpenCode tail 25%; Codex user 20K | **済**（60%/直近 4 イベント）。要約の**構造化スキーマ**は部分的 |
| 3 | **長時間タスクは圧縮よりリセット + ハンドオフ成果物** | A-Mar; A-Nov（progress file）; OpenHands `hard_context_reset` | **ギャップ**。session state に progress artifact を持ち「リセットして再開」経路が無い |
| 4 | **KV キャッシュ安定プレフィックス（追記専用・決定論的直列化）** | Manus（キャッシュ 10 倍差）; Codex world-state 差分注入; OpenCode system 1 本; Pi 圧縮時のキャッシュ書込抑止 | **ギャップ**。ModeManager が**ツールリストを切り替える**設計はプレフィックスを壊す → 原則 5 と併せて要再設計（#92, #81） |
| 5 | **ツールは削除せず「マスク」する** | Manus; Deep Agents `_tool_exclusion`; CC MCP 遅延ロード; Codex `tool_search` | **衝突**: `switch_mode` はツール集合を変更。ADK なら `before_model_callback` で `llm_request.config.tools` を絞る＝マスクに寄せられる |
| 6 | **計画を状態に持ち、末尾で再唱（recitation）** | Manus todo.md; CC TodoWrite; Deep Agents `write_todos`; OpenCode todowrite + plan reminder; Codex update_plan | **ギャップ**（#87）。`planner` は状態に残らない |
| 7 | **失敗を消さず Observation として残す** | Manus; mini-swe `FormatError`; OpenHands; Codex `success:false` function_call_output; OpenCode `DeniedError`/`CorrectedError` | **済（憲章そのもの）** |
| 8 | **決定論的ポリシー層（フック）をモデル外に置き、JSON 契約で外部プロセスに委ねる** | CC hooks; OpenHands `hooks/`; Crush; Pi `tool_call` block; Codex hooks crate; OpenCode plugin | **部分**: ADK Plugin callback + mcp-server 側ポリシー。**外部プロセス/HTTP で差し替え可能な契約**は無い |
| 9 | **権限は段階モード + ルール構文 + リスク分類** | CC 6 モード + `Bash(git *)`; OpenHands `SecurityRisk`; OpenCode ruleset; Codex execpolicy | **ギャップ**（#20/#21/#16）。「確認要」は**ブロックではなく `PermissionRequired` Observation** として返し、BFF/CLI が承認 UI を出す |
| 10 | **サブエージェントはコンテキスト隔離し要約だけ返す。深さ・並列数を制限。並列に「決定」させない** | CC（深さ 3/同時 20）; Deep Agents `task`; OpenCode task（親の deny のみ継承）; Codex FINAL_ANSWER 封筒; **Cog** | **ギャップ**（#85）。書き込みを伴う並列化は避ける |
| 11 | **段階的開示**（メタデータ → 本文 → リソース） | agentskills.io; CC `.claude/rules` `paths:`; Codex skills; OpenCode skill ツール | **部分**（`SkillRegistry`）。ADK `SkillToolset` へ移行で仕様準拠（#90） |
| 12 | **安価なガード: ステップ/コスト/時間上限、反復呼び出し検出、フォーマットエラー計数、圧縮スラッシング停止** | mini-swe; Crush; CC; OpenCode doom_loop; OpenCode `agent.steps` | **ギャップ**（実装コスト最小） |
| 13 | **生成者と評価者を分ける** | A-Mar（Evaluator）; OpenHands `critic/`; Codex review mode; OAI | **部分**: nightly-eval/golden はオフライン。実行時の critic は無い |
| 14 | **追記専用イベントログ + ステートレスなハーネス再起動** | MA; OpenHands; CC JSONL + `/rewind`; Codex rollout jsonl + fork | **部分**: ADK Session events は追記型。`ResumabilityConfig` 未使用 |
| 15 | **散文より機械的強制、ドキュメントはエージェントの知識ベース、古い文書は GC。モデル更新ごとに足場を外す** | OAI; A-Mar; CC `/doctor` | **部分**: `charter-review` が「足場の撤去」を定期議題にできる |

補足: 原則 4/5 は DAK の adaptive mode（Meta-LLM によるモード切替）と**直接衝突**する唯一の項目。#92 の判断材料として、「マスク」方式へ寄せることを推奨する。

---

## 4. 追跡すべき標準

| 標準 | 状態（2026-09） | 採用者 | DAK が得るもの |
|---|---|---|---|
| **Agent Client Protocol (ACP)** — https://agentclientprotocol.com | Zed が 2025-08 公開。JSON-RPC over stdio。`initialize → session/new|load → session/prompt`、`session/update` 通知、クライアント側メソッド `session/request_permission`, `fs/read_text_file`, `fs/write_text_file`, `terminal/*`。**2026-01-28 に Zed+JetBrains が ACP Registry を公開**、2026-06 時点で 50+ エージェント | Claude Agent, Gemini CLI, Codex CLI, Copilot, Cursor, Cline, OpenCode, Goose, Deep Agents, OpenHands, Hermes | **Zed/JetBrains を無料の UI にできる**。`session/request_permission` は DAK の「障壁 = Observation → 人が判断」に自然に写像 |
| **Agent Skills** — https://agentskills.io/specification | `SKILL.md` frontmatter（`name` ≤64、`description` ≤1024、`license`, `compatibility`, `metadata`, `allowed-tools`(実験)）、`scripts/ references/ assets/`、3 段の段階的開示 | Claude Code、Codex、OpenCode、Hermes、OpenHands、Deep Agents、ADK `SkillToolset` | 独自 `SkillRegistry` を仕様準拠に置き換えると他ハーネスのスキルをそのまま取り込める（#90） |
| **MCP** | **2025-11-25**: Tasks（実験）、URL モード elicitation、sampling with tools。**2026-07-28**: **ステートレスコア**（`Mcp-Session-Id` 廃止）、**MRTR**（SEP-2322: サーバが `resultType: "input_required"` と `requestState` を返し、クライアントが `inputResponses` を付けて再呼び出し。sampling/elicitation を置換）、Tasks は拡張へ、**MCP Apps**、Roots/Sampling/Logging は非推奨（https://blog.modelcontextprotocol.io/posts/2026-07-28/） | 全主要ハーネス | **MRTR は DAK 憲章の実装形そのもの**: mcp-server が決済や危険操作で `input_required` を返し、エージェントが判断してから再呼び出しする流れが標準化される。FastMCP と ADK の MCP アダプタの対応版追跡が必要 |
| **A2A** | **v1.0 2026-04-09**（署名付き Agent Card、AP2 併設）、**2026-08-17 に AAIF へ移管** | Google/Microsoft/AWS ほか | `a2a_peer_manager.py` の v1.0 互換確認、署名付き Agent Card の検証 |
| **AGENTS.md** | 2025-12 に MCP / goose と共に **AAIF の創設プロジェクト** | Codex, Cursor, Gemini CLI, Copilot, Pi, Crush, Hermes, OpenHands | OAI 流に AGENTS.md を「目次」、`docs/` を真実にし、重複をリンタで検出 |

---

## DAK が設計を参考にすべき候補（本パートのランキング）

| 順位 | 候補 | 出典 | DAK にとっての理由 | DAK/ADK でのスケッチ | 規模 | 衝突 |
|---|---|---|---|---|---|---|
| 1 | **安価な実行ガード**: 反復ツール呼び出し検出 + ステップ/コスト/時間上限 + 圧縮スラッシング停止 | Crush `loop_detection.go`; mini-swe `AgentConfig`; CC | 小型モデルは同じ呼び出しを繰り返しやすい。最小コストで最大の事故削減 | `before_tool_callback` で `sha256(tool_name+args)` の直近窓を state に保持、閾値超で**ツールを実行せず** Observation を返す。`DAK_MAX_TOOL_CALLS/DAK_MAX_WALL_SECONDS` | S | なし |
| 2 | **TODO/計画を session state に保存し、モデル呼び出し前に再唱** | Manus todo.md; Deep Agents `write_todos`; CC TodoWrite | 圧縮後に計画が消える問題（#87）。recitation は小型モデルほど効く | `write_todos(items)` → `state["dak:todos"]`; `before_model_callback` で末尾に注入 | S | `planner` と役割重複 → 置換 |
| 3 | **読み取り専用の調査サブエージェント（Explore 相当）** | CC Explore; Deep Agents `task`; Cog の警告 | #85。**読み取り専用に限定**して決定の分散を避ける | ADK `AgentTool(LlmAgent(name="explore", tools=[read_file, list_files, search_files, grep]))`。深さカウンタで再帰禁止 | M | 書き込み系を含めない |
| 4 | **フック契約（PreToolUse/PostToolUse/Stop）を外部プロセス/HTTP に委ねる** | CC hooks の JSON 契約; OpenHands `hooks/`; Crush | ポリシーをエージェントコンテナの外に置け、疎結合を保ったまま「決定論的な強制層」を得る | `DAK_HOOKS` 設定（command/http）を ADK Plugin から起動、CC 互換 JSON。`deny` は Observation | M | hooks 設定は明示 opt-in、既定は空 |
| 5 | **リスク注釈 + 段階権限を Observation として返す（MRTR 互換）** | OpenHands `SecurityRisk` + `ConfirmRisky`; CC 6 モード; MCP MRTR | 「確認が必要」を**構造化 Observation**にすると BFF/CLI/ACP 全てが同じ承認 UI を作れる | `security_risk` 自己申告 + `DAK_PERMISSION_MODE` + mcp-server ポリシー。要確認なら `{"resultType":"input_required"}` 相当 | M | 憲章と整合 |
| 6 | **安定プレフィックス（KV キャッシュ）規律 + ツールはマスク** | Manus; CC; Deep Agents `_tool_exclusion`; Pi | llama.cpp の prompt cache は先頭が同一である限り効く。ModeManager の動的ツール切替はこれを毎回壊す | `before_model_callback` で `llm_request.config.tools` を**フィルタ**。`switch_mode` はフィルタ集合の切替に縮退。llama-server `/metrics` の `prompt_tokens_cached` を記録 | M | #92, #81 と衝突。評価で決める |
| 7 | **窓超過からの回復 + 構造化要約 + ハンドオフ成果物** | OpenHands `agent.py`; A-Mar; Pi | #88 の実装指針 | `on_model_error_callback` で検知→強制圧縮→再試行→無理なら handoff 成果物を state に書いて履歴を切る | M | なし |
| 8 | **モデル別ハーネスプロファイル** | Deep Agents `profiles/`; Pi llama.cpp; mini-swe テキストアクション | 「Qwen 27B/32K ではツール 6 個 + テキストアクション、Claude では全部」 | `HarnessProfile`（compaction 比率、ツール出力予算、allowlist、`text_actions`）を `profiles/*.yaml` でモデル名 glob 解決 | M | なし |
| 9 | **sandbox-runtime で mcp-server プロセスを包む** | anthropics/sandbox-runtime | `run_command(shell=True)` の P3 サンドボックスを**コード変更なし**で前進 | Dockerfile で `srt --settings sandbox.json -- python main.py` | S〜M | コンテナ内 bubblewrap の検証要 |
| 10 | **ACP アダプタ** | Zed/JetBrains ACP、Deep Agents `libs/acp`、OpenHands | 50+ エージェントが載る Registry に DAK を出せ、IDE UI が無償で付く | 新コンテナ `acp/`: stdio JSON-RPC ↔ agent の A2A/HTTP | M〜L | 「ACP=人が使う IDE 面、A2A=エージェント間」と整理 |

---

### 参照 URL
Claude Code docs: https://code.claude.com/docs/en/hooks, /sub-agents, /memory, /checkpointing, /headless, /how-claude-code-works, /agent-teams ・ SDK: https://github.com/anthropics/claude-agent-sdk-python ・ sandbox: https://github.com/anthropics/sandbox-runtime  ・ Anthropic: https://www.anthropic.com/engineering/effective-harnesses-for-long-running-agents, https://www.anthropic.com/engineering/harness-design-long-running-apps, https://www.anthropic.com/engineering/managed-agents ・ Fusion: https://cognition.com/blog/local-fusion ・ OpenAI: https://openai.com/index/harness-engineering/ ・ Manus: https://manus.im/blog/Context-Engineering-for-AI-Agents-Lessons-from-Building-Manus ・ Cognition: https://cognition.ai/blog/dont-build-multi-agents ・ ACP: https://agentclientprotocol.com/protocol/overview ・ Skills: https://agentskills.io/specification ・ MCP: https://blog.modelcontextprotocol.io/posts/2026-07-28/ ・ リポジトリ: https://github.com/badlogic/pi-mono, https://github.com/langchain-ai/deepagents, https://github.com/OpenHands/agent-sdk, https://github.com/SWE-agent/mini-swe-agent, https://github.com/charmbracelet/crush, https://github.com/NousResearch/hermes-agent
