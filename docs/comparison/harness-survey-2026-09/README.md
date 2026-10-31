# OSS エージェント・ハーネス調査（2026-09）と DAK への取り込み

2026-08 に OpenAI が Codex のハーネス本体（CLI / app-server / SDK）を「open agent harness」として再定義したのを機に、
主要なコーディングエージェント・ハーネスを**実装レベル**で調査し、DAK 憲章（`docs/CHARTER.md`）に照らして
取り込むべき機構をバックログ化した。追跡 Epic は **#119**。

| ファイル | 対象 |
|---|---|
| [codex.md](codex.md) | OpenAI Codex CLI（Rust, `codex-rs/`）。core loop / compaction / unified_exec / apply_patch / sandbox+execpolicy / hooks / multi-agent / app-server |
| [opencode.md](opencode.md) | OpenCode（TypeScript）。server/client 分離 / permission ruleset / compaction+prune / edit matcher / task / plan mode / plugin |
| [gemini-cli-and-goose.md](gemini-cli-and-goose.md) | Gemini CLI（TypeScript, ADK と同じ Google 系）と Goose（Rust, MCP ネイティブ） |
| [claude-code-and-others.md](claude-code-and-others.md) | Claude Code の公開範囲（hooks / 権限モード / サブエージェント / 圧縮）、「Fusion」の正体、Pi / Deep Agents / OpenHands / mini-SWE-agent / Crush / Hermes / Forge / Cline、横断 15 原則、標準（ACP / Agent Skills / MCP 2026-07 / A2A 1.0 / AGENTS.md） |

調査対象のクローンは `/tmp/harness-research/<name>`（2026-09-14 時点の main）。各ファイルの末尾に「DAK が設計を参考にすべき候補」の表がある。

## 0. 帰属とライセンスの方針

本調査の目的は**設計思想を参考にして DAK で独自に実装する**ことであり、他プロジェクトのコードを取り込むことではない。

- **コードは写さない。** Issue の「実装スケッチ」は考え方の説明であり、実装は DAK（Apache-2.0）の Python コードとして一から書く。
- **やむを得ず特定実装を翻訳・転記する場合**は派生物として扱い、元プロジェクトの著作権表示とライセンス文を保持し、`NOTICE` に出典を記載する（MIT / Apache-2.0 の要件）。PR の説明にも明記する。
- **Crush（FSL-1.1-MIT）はコード流用の対象外。** 設計の記述のみ参照する。
- **Claude Code は公開ドキュメント・OSS の Agent SDK / sandbox-runtime・Anthropic の公開記事のみ**を根拠にする。
- 本ドキュメント群の短いコード引用（各 3〜11 行）は、いずれも Apache-2.0 / MIT のプロジェクトから出典（ファイルパス）付きで技術解説のために引用したもの。
- 引用元の文章（ブログ・ドキュメント）は要約・言い換えで記述し、URL を併記する。

### 参照したプロジェクトとライセンス

| プロジェクト | ライセンス | URL |
|---|---|---|
| OpenAI Codex CLI | Apache-2.0 | https://github.com/openai/codex |
| OpenCode | MIT | https://github.com/anomalyco/opencode |
| Gemini CLI | Apache-2.0 | https://github.com/google-gemini/gemini-cli |
| Goose | Apache-2.0 | https://github.com/block/goose |
| Claude Agent SDK / sandbox-runtime | MIT / Apache-2.0 | https://github.com/anthropics/claude-agent-sdk-python , https://github.com/anthropics/sandbox-runtime |
| Pi | MIT | https://github.com/badlogic/pi-mono |
| Deep Agents | MIT | https://github.com/langchain-ai/deepagents |
| OpenHands agent-sdk | MIT | https://github.com/OpenHands/agent-sdk |
| mini-SWE-agent | MIT | https://github.com/SWE-agent/mini-swe-agent |
| Hermes Agent | MIT | https://github.com/NousResearch/hermes-agent |
| Crush | FSL-1.1-MIT（コード流用対象外） | https://github.com/charmbracelet/crush |
| Forge | Apache-2.0 | https://github.com/antinomyhq/forgecode |
| Cline | Apache-2.0 | https://github.com/cline/cline |

## 1. 「Codex のハーネスがオープンになった」の中身

- 2026-02 の OpenAI「Harness engineering」は、モデルとタスクの間に座る実行系（文脈収集・ツール実行・境界強制・ストリーミング・多ターン継続）を「ハーネス」と呼び、AGENTS.md を目次にした `docs/` 知識ベース、依存方向を lint で機械的に強制、エージェントが読める観測性、古い文書の GC、を実践として挙げた。
- 2026-08-19「Codex as a platform: build on the open agent harness」で、`codex exec`（非対話・構造化出力）/ SDK / `app-server`（JSON-RPC でスレッド・ターン・承認までフル制御）の 3 層を組み込み用として公開。コードは以前から Apache-2.0 で `openai/codex` にある。
- 注意点: ワイヤは **Responses API のみ**（Chat Completions は削除）。DAK の LiteLLM/chat 形式とは根本的に異なるため、「コードを流用する」のではなく「設計思想を参考に独自実装する」対象。

「Fusion?」は Cognition の **Fusion**（2026-09-11、Devin CLI の lead/sidekick 二重モデルハーネス、プロプライエタリ）が最有力。詳細は [claude-code-and-others.md](claude-code-and-others.md) §2.1。

## 2. 横断比較（DAK に関係する機構だけ）

| 機構 | Codex | OpenCode | Gemini CLI | Goose | Claude Code | DAK（現状） |
|---|---|---|---|---|---|---|
| 圧縮トリガ | 窓の 90%（ハード 95%）、MidTurn/PreTurn/`new_context` | `usable = context − min(output,32K)`、step-finish と loop 先頭で判定 | 50%、直近 30% 保持、要約前に事前トランケート、失敗/インフレ検出 | 80%、要約は可視性フラグで非表示化、ツールペア要約をバックグラウンドで | 自動（micro-compact → 要約）、スラッシング停止 | 60%（ADK token threshold）+ 85% ガード |
| 要約の保持 | 直近ユーザ発話 20K tok 原文 + 要約 + 初期コンテキスト再注入 | tail 25%（2K〜15K）原文 + 固定セクション要約 + prior-summary 更新 + continue ターン | `<state_snapshot>` XML（goal/constraints/knowledge/artifact_trail/fs_state/task_state） | 構造化 JSON（intent/concepts/files/errors_and_fixes/pending/next）、テンプレート上書き可 | CLAUDE.md 再注入 | 直近 4 イベント + 自由文要約 |
| 無要約の剪定 | — | `prune`（直近 2 turn 保護、40K 超分を cleared） | — | ツールペア 1 行要約（`compute_tool_call_cutoff`） | micro-compact | **なし** → #102 |
| ツール出力上限 | token 10K、middle-cut、`Warning: truncated (original N)` 見出し | 2000 行 / 50KB、ファイル退避、委譲ヒント | 2000 行 / 2000 文字・行、shell 16MB buffer | shell 2000 行超で head + 末尾 50 行、全文は一時ファイル | — | 窓の 15%、head 70/tail 30、artifact + paging |
| 権限モデル | `SandboxPolicy` × `AskForApproval`、execpolicy prefix_rule、拒否→昇格再要求 | `tool × pattern → allow/ask/deny` 後勝ち、`always` 永続化、`"*": deny` は非表示 | `default/autoEdit/yolo/plan` + TOML 多軸ルール（tier 優先度） | `Auto/Approve/SmartApprove/Chat`、`readOnlyHint` 即許可 → LLM 分類、引数ハッシュで永続化 | 6 モード + ルール構文 + auto 分類器 | `require_confirmation` 一律 + denylist → #100/#101 |
| 承認の経路 | app-server `requestApproval` | `GET /permission` + `reply` + SSE | confirmation bus（`AwaitingApproval` 状態） | ACP `session/request_permission` | `PermissionRequest` hook | CLI のみ（#21） → #100 |
| ループ/上限ガード | — | doom_loop（3 回同一）、`steps` | loopDetectionService（周期 1〜5 ×5、内容反復 ×10、LLM 二重確認）、`MAX_TURNS=100` | `goal`/`grind` 継続、`empty_turn_retries` | スラッシング停止 | **なし** → #99 |
| サブエージェント | spawn/wait/close、履歴 fork、FINAL_ANSWER 封筒 | 独立セッション、親の deny のみ継承、最終テキストのみ | `LocalAgentExecutor`（独立レジストリ、再帰禁止をコード化） | `delegate`（working_dir 制限、max_turns 25、分担方針を説明文に） | Explore/Plan/general、深さ 3/同時 20 | A2A ピアのみ（#85） |
| 計画/TODO | `update_plan`、Plan collaboration mode | `todowrite` + plan モード reminder + `plan_exit` | `plan` 承認モード、承認済みプランを要約で保持強制 | recipes（宣言的サブワークフロー） | TodoWrite、plan モード | `planner`（状態に残らない） → #87/#106 |
| Hooks | 12 イベント、Command/Prompt/Agent | plugin API（`tool.execute.before/after`, `permission.ask`） | hooks | Stop hook（Deny で継続） | 33 イベント、exit 0/2 JSON 契約 | ADK callback のみ → #107 |
| スキル | SKILL.md（agentskills 準拠）、`$skill` 明示/暗黙 | `skill` ツール | extensions、GEMINI.md 階層 | extensions（MCP）、`.goosehints` 遅延ロード、Code Mode | Skills/plugins | 独自 `SkillRegistry`（#90） |
| プレフィックス安定 | world-state 差分注入、request 同一性検査、先頭から削る | system 1 本、synthetic user 介入 | — | `manages_own_context()` で圧縮を委譲 | MCP ツール定義の遅延ロード | モード切替がツール集合を変える → #105/#92 |
| モデル差の吸収 | `models.json` の `model_messages` | モデル別 prompt（Qwen 等は default.txt） | 429 でモデルダウングレード（pro→flash→flash-lite） | `CanonicalModelRegistry`、`ProviderFeatures` | — | なし → #110 |
| テスト | モック Responses サーバ + リクエスト検査ヘルパ + snapshot | fake provider + ツールスキーマ snapshot + HTTP 録画 | `FakeContentGenerator`（台本、strict/nonStrict） | wiremock + `ProviderFeatures`、MCP 録画再生、超過シナリオ録画 | — | fake-LLM は応答台本のみ → #111 |

## 3. DAK 憲章との整合

- **System ENABLES, Agent DECIDES** と最も同型なのは Codex の「モデルが `sandbox_permissions=require_escalated` + `justification` で昇格を**要求**し、ハーネス/ユーザが決める」ループと、MCP 2026-07-28 の **MRTR**（`input_required` → 再呼び出し）。DAK の Observation-Driven をそのまま標準に載せられる。
- **疎結合コンテナ**の観点では、OS サンドボックス（Seatbelt/Landlock）や git スナップショット undo、LSP 同梱は参考にしない。DAK はツールを別コンテナで実行しており Codex の `ExternalSandbox` 相当。
- **Multi-LLM 中立**の観点では、Responses-only ワイヤ、remote compaction、`apply_patch` の constrained-decoding 文法、Guardian（承認をモデルに委ねる）は不採用。
- 唯一衝突するのは「安定プレフィックス（ツールはマスク）」対 DAK の Meta-LLM モード切替。#92 の評価で決める。

横断 15 原則と DAK の状態（済/部分/ギャップ/衝突）は [claude-code-and-others.md](claude-code-and-others.md) §3。

## 4. バックログ（Epic #119）

| 優先 | Issue | 由来 | 規模 |
|---|---|---|---|
| P1 | #99 実行ガード（反復検知・ステップ/時間上限・スラッシング停止） | Crush / OpenCode doom_loop / mini-swe / Claude Code | S |
| P1 | #100 承認/質問の保留キュー + reply API + イベント（MRTR 互換） | OpenCode permission / Codex app-server / MCP MRTR | M |
| P1 | #101 宣言的な権限ルール（allow/ask/deny 後勝ち）と承認の永続化・昇格再要求 | OpenCode ruleset / Codex execpolicy+orchestrator / OpenHands SecurityRisk | M |
| P1 | #102 古いツール出力の無要約剪定（prune） | OpenCode prune / Claude Code micro-compact / Hermes | S |
| P1 | #103 圧縮の保持構造（構造化要約・tail 原文・指示再注入・continue・警告） | OpenCode / Codex / Pi / Deep Agents | M |
| P2 | #104 切り詰めの middle-cut + メタ見出し + 委譲ヒント | Codex / OpenCode | S |
| P2 | #105 安定プレフィックス規律（マスク・system 1 本・差分注入・計測） | Manus / Codex world-state / Deep Agents | M |
| P2 | #106 plan モード（非変異のみ + reminder + plan_exit） | OpenCode / Codex / Claude Code | S |
| P2 | #107 hooks 契約（Claude Code 互換 JSON） | Claude Code / Codex / OpenHands / Crush | M |
| P2 | #108 引数スキーマ違反を Observation に | OpenCode | S |
| P2 | #109 保護パス・外部ディレクトリ確認（mcp） | Codex / OpenCode | S |
| P2 | #110 モデル別ハーネスプロファイル | Deep Agents / OpenCode / mini-swe / Fusion | M |
| P2 | #111 fake-LLM リクエスト検査 + snapshot（eval） | Codex / OpenCode | S |
| P2 | #112 MCP 2026-07-28 追随（tech-watch） | MCP | — |
| P3 | #113 get_context_remaining / new_context | Codex | S |
| P3 | #114 ハンドオフ成果物とリセット再開 | Anthropic 2026-03 / OpenHands | M |
| P3 | #115 AGENTS.md 探索規則 | Codex / OpenCode / Claude Code | S |
| P3 | #116 永続メモリ | Claude Code / Codex / Gemini CLI / Goose | S–M |
| P3 | #117 ACP アダプタ（tech-watch） | Zed/JetBrains | M–L |
| P3 | #118 sandbox-runtime で mcp-server を包む（tech-watch） | Anthropic | S–M |

既存 Issue への設計参照コメント: #85, #86, #87, #88, #89, #21, #81, #92, #94。

**推奨する着手順**: #99 → #102 → #87 → #103 → #100/#101（Epic B #16/#20/#21 と統合） → #105/#92 の評価 → 残り。各段で #93 の長時間タスク eval（窓超過率・圧縮回数・キャッシュヒット率）で効果を測る。

## 5. 追跡する標準

| 標準 | 2026-09 の状態 | DAK での扱い |
|---|---|---|
| MCP 2026-07-28 | ステートレスコア、MRTR、Tasks 拡張、Apps | #112。MRTR は憲章の実装形 |
| Agent Client Protocol | Zed/JetBrains Registry、50+ エージェント | #117 |
| Agent Skills（agentskills.io） | Claude Code / Codex / OpenCode / ADK `SkillToolset` | #90 |
| A2A 1.0（2026-04）→ AAIF 移管（2026-08） | 署名付き Agent Card、AP2 併設 | `a2a_peer_manager.py` の互換確認（#47） |
| AGENTS.md（AAIF 創設プロジェクト） | Codex / Gemini CLI / Cursor / Pi / OpenHands | #115 |
