# Gemini CLI と Goose の実装調査（DAK が設計を参考にする観点）

対象コミット: gemini-cli 2026-09-11 HEAD (`/tmp/harness-research/gemini-cli`)、goose 2026-09-11 HEAD `50666ae0` (`/tmp/harness-research/goose`)。goose は Block 単独から Linux Foundation 傘下 "Agentic AI Foundation" 移行に伴い大幅リファクタ済みで、以前の `goose-server`（REST+SSE）/`goose-mcp/developer` は姿を変えている。

---

## パート A: Gemini CLI（TypeScript, `packages/core/src/`）

### (a) アーキテクチャ & コアループ

`GeminiClient`（`core/client.ts`）の `sendMessageStream()` がエントリポイントで、`processTurn()` が 1 ターンを処理する。**ツール実行を `Turn`（`core/turn.ts`）ではなく別レイヤーの `Scheduler`（`scheduler/scheduler.ts`）に完全分離**。`Turn.run()` はストリームを消費して `ToolCallRequestInfo` を作るだけ。ツール呼び出しは判別ユニオン型の状態機械（`scheduler/types.ts:26-33`）:

```ts
export enum CoreToolCallStatus {
  Validating, Scheduled, Error, Success, Executing, Cancelled, AwaitingApproval,
}
```

`Scheduler._processNextItem()`（`scheduler.ts:440`）は並列実行可能なツールをまとめてバッチ処理。`EDIT_TOOL_NAMES` と `update_topic` は強制逐次、それ以外は `args.wait_for_previous` が無ければ並列。`MAX_TURNS = 100`。ツール呼び出しが無く終了しても `checkNextSpeaker()` が「次の話者はモデルか」を判定し、"Please continue." を注入して継続する。

### (b) コンテキスト管理

- **圧縮**（`context/chatCompressionService.ts`）: `DEFAULT_COMPRESSION_TOKEN_THRESHOLD = 0.5`（上限の 50%）で発火、直近 `COMPRESSION_PRESERVE_THRESHOLD = 0.3`（30%）は保持しそれ以前を要約。**要約前に履歴全体を安全サイズへ事前トランケート**する二段構え、かつ「要約が失敗した / かえってトークンを増やした」場合を検出するガード（`COMPRESSION_FAILED_EMPTY_SUMMARY` / `COMPRESSION_FAILED_INFLATED_TOKEN_COUNT`）。要約プロンプトは `<state_snapshot>` XML 形式で `overall_goal / active_constraints / key_knowledge / artifact_trail / file_system_state / recent_actions / task_state(DONE/IN PROGRESS/TODO)` を持つ構造化フォーマット。プロンプトインジェクション対策（履歴内の指示を無視せよ）も明記。承認済みプランがある場合は専用セクションで保持を強制する。
- **ツール出力上限**: シェル `MAX_CHILD_PROCESS_BUFFER_SIZE = 16MB`、stderr は 20KB、ファイル読み込みは `DEFAULT_MAX_LINES_TEXT_FILE = 2000` 行 / `MAX_LINE_LENGTH_TEXT_FILE = 2000` 文字。
- **リトライ/フォールバック**（`utils/retry.ts`）: 指数バックオフ（`initialDelayMs=5000, maxDelayMs=30000, maxAttempts=10`）。429 継続時は `MAX_SILENT_CAPACITY_ATTEMPTS=3` 回静かにリトライ後、`onPersistent429` でモデルダウングレード（pro→flash→flash-lite、`config/models.ts`）。

### (c) ツール

`ToolRegistry`（`tools/tool-registry.ts`）が MCP ツールも統合管理。`discoverMcpTools()` は全 MCP サーバーを `Promise.all` で並列発見し、サードパーティのスキーマが AJV コンパイルに失敗しても **no-op バリデータにフォールバックしてツール自体は使わせる**。編集ツール（`tools/edit.ts`）は文字列置換が失敗すると `utils/llm-edit-fixer.ts` で **1 回だけ** LLM に修正させる（タイムアウト 40 秒、SHA256 キーで LRU キャッシュ 50 件）。プロンプトには "DO NOT GIVE ADVICE. Your only goal here is to do your best to perform the search and replace task!" と明記。grep は同梱 ripgrep バイナリ優先、失敗時は JS 実装にフォールバック。

### (d) 安全性/承認

`ApprovalMode` は `default / autoEdit / yolo / plan` の 4 値（`policy/types.ts`）。**TOML ベースのポリシールール**（`policy/toml-loader.ts`）が `toolName / subagent / mcpName / argsPattern / commandPrefix / commandRegex` の多軸マッチと 3 段階 tier 優先度（default[1.xxx] < user[2.xxx] < admin[3.xxx]）を持つ。ツール名のタイポには Levenshtein 距離で候補提示。シェルの拒否時は「セッション単位/恒久」で許可範囲を拡張するダイアログを出す。

### (e) サブエージェント

`agents/local-executor.ts` の `LocalAgentExecutor` が**エージェントごとに独立したツール/プロンプト/リソースレジストリを生成**し、定義された `toolConfig.tools` のみをクローン登録する。**「エージェントは他のエージェントを呼び出せない」を `registerToolInstance()` 内で明示的にコード化**（`Kind.Agent` のツールは登録スキップ）。A2A でプロセス外エージェントとも通信できる（`remote-invocation.ts`）。

### (f) メモリファイル

`GEMINI.md`（新方式は `MEMORY.md` インデックス）を `~/.gemini/` → プロジェクト → 拡張の `contextFiles` → git root までの親ディレクトリ階層、の順で収集し重複排除。注入時の優先順位「Sub-directories > Workspace Root > Extensions > Global」を明記しつつ「安全性に関わるコアマンデートは上書き不可」を区別。

### (g) ループ検出/リトライ

`services/loopDetectionService.ts` は 3 方式併用: ①ツール呼び出し反復（周期長 1〜5 の完全一致検出、`TOOL_CALL_LOOP_THRESHOLD=5`）、②コンテンツ反復（50 文字チャンクのハッシュ、`CONTENT_LOOP_THRESHOLD=10`、コードブロック等は除外）、③ **LLM ダブルチェック**（30 ターン経過後、軽量モデルで `unproductive_state_confidence≥0.9` なら別モデルで二重確認）。誤検知防止のため「何がループでないか」（クロスファイル一括編集、引数を変えたリトライ等）をプロンプトに明記。

### (h) テスト

Vitest + `vi.mock()` によるモジュール単位モック。`FakeContentGenerator`（DAK の fake-LLM に相当）は応答をスクリプト化でき、`nonStrict` で「順序厳密一致」/「メソッド一致で最初の応答」を切替可能。関心事ごとにテストファイルを分割（並列スケジューリング専用、フック専用、ネットワークリトライ専用など）。

### (i) 設計思想

`npm run preflight` は「PR の最後にのみ実行し、失敗したら個別の速いコマンドで直してから再実行」が明文化されており、DAK の 3 層テスト戦略と同じ「速い順」思想。サブエージェントは「メインのコンテキスト/ツールセットを汚さない専門家」。

**ADK が既にネイティブに持つもの**: ツール呼び出しの状態機械やターン実行ループは ADK の `LlmAgent` / イベントループが担っており Scheduler 相当の自作は不要。モデルフォールバックチェーンは LiteLLM の `fallbacks` で代替可能。GEMINI.md 階層探索は ADK にも Goose にも標準実装が無く、必要なら DAK 側で薄く自作（#115）。

---

## パート B: Goose（Rust, `crates/goose*/`）

### (a) アーキテクチャ & コアループ

`crates/goose/src/agents/agent.rs`（6000 行超）の `reply()` / `reply_impl()` が本体。**2 つの実装が並存**（移行中、`AGENTS.md` に明記）: レガシーの `async_stream::try_stream!` ループと、`GOOSE_STATE_MACHINE=1` で有効化される新しい `state_machine/` エンジン。**自律継続の仕組み**: ツール呼び出しが無いターンで即終了せず、①`final_output_tool` 未呼び出し、②`self.goal`、③`self.grind`（完全に終わるまで続けろ）が設定されていれば nudge を注入して継続。Stop hook が `Deny` を返すと `consecutive_stop_hook_blocks` の上限まで拒否コンテキストを注入してリトライ。ツール実行は `agents/tool_execution.rs` に分離。

### (b) コンテキスト管理

- **しきい値**: `DEFAULT_COMPACTION_THRESHOLD = 0.8`（`goose-context-management/src/lib.rs`）。`manages_own_context()` が true のプロバイダ（Claude Code / Gemini CLI を ACP 経由でラップする場合）は goose 側の圧縮を完全スキップする「メタ・プロバイダ」設計。
- **要約は削除ではなく可視性フラグで非表示化**。要約プロンプト（`crates/goose-context-management/src/prompts/compaction.md`）は `user_intent / technical_concepts / files[{path,summary,key_code}] / errors_and_fixes / pending_tasks / next_step` を持つ構造化 JSON で、「次のターンのエージェント自身が読む前提だから人間向け要約より長くて良い」と明記。レンダリングテンプレートはユーザーが `~/.config/goose/prompts/compaction_summary.md` に上書き配置できる。
- **ツールペア要約**（会話全体の圧縮とは別枠）: 個々の古いツール呼び出し/応答ペアだけを 1 行要約に置き換える軽量圧縮。`compute_tool_call_cutoff = (3 * context_limit / 20_000).clamp(10, 500)` で対象範囲を決め、直近分は保護し、メインループと並行して `tokio::task::JoinHandle` でバックグラウンド実行。DAK の artifact 退避 + paging とは異なる「古いツール結果を消さず縮める」アプローチ。
- プロバイダ抽象（`goose-provider-types/src/base.rs`）は `ModelInfo{context_limit, reasoning, ...}` を持ち、`CanonicalModelRegistry` でベンダー名→正規モデル名を解決。

### (c) ツール

developer 拡張（`agents/platform_extensions/developer/`）は `write / edit / shell / tree / read_image` の 5 ツールのみで、**旧来の `view/str_replace/insert/undo_edit` インターフェースや undo 履歴は現バージョンには存在しない**（意図的簡素化）。shell は `OUTPUT_LIMIT_LINES=2000` 行超で先頭一部 + 末尾 50 行プレビューに切り詰め全文を一時ファイル保存、バックグラウンドプロセスの出力ドレインにタイムアウトを設け待ち続けない。ツール名前空間は `extension__tool`。**多ツール環境の対策はベクトル検索ではなく「拡張の検索的発見」+ feature-gated な Code Mode**（ツールを TypeScript 関数として見せてコード実行させる progressive disclosure）で、専用のベクトルルータは存在しなかった。

### (d) 安全性/承認

`GooseMode` は `Auto / Approve / SmartApprove / Chat` の 4 値。**SmartApprove の判定は 2 段構え**: ①MCP アノテーション `read_only_hint=true` なら即 Allow（LLM 不要）、②それ以外は専用ツール `platform__tool_by_tool_permission` を軽量 LLM に投げて読み取り専用リクエスト ID を分類させる。**プロンプトインジェクション対策がテストで明示的に保証**されている（`permission_judge.rs`: ツール名/引数を「UNTRUSTED TOOL REQUEST DATA」として封入し、システムプロンプトに漏れないことを専用テストで検証）。永続許可は `~/.config/goose/permissions/tool_permissions.json` に「ツール名 + 引数の blake3 ハッシュ」をキーとして保存し、TTL 付き失効も可能。

### (e) サブエージェント/レシピ/拡張

`summon` 拡張の `delegate` ツールがサブエージェント委譲を担う。`extensions`（継承ツール制限）、`working_dir`（親 working_dir 配下に制限）、`async`、`max_turns`（既定 25）。ツール説明文に「Delegates cannot coordinate. Same-file work = conflicts. Research (read-only): parallelize freely」と**並列実行時の作業分割方針が自然文で教え込まれている**。サブエージェント用プロンプトにも「追加のサブエージェントは起動できない」と明記し再帰を防止。レシピ（`recipe/mod.rs`）は宣言的サブワークフローで `sub_recipes`、`response.json_schema`（構造化出力）、`retry` 設定を持つ。

### (f) 指示/ヒントファイル

`.goosehints` / `AGENTS.md` をグローバル + git root までのローカル階層から収集するが、**`SubdirectoryHintTracker`**（`hints/load_hints.rs`）が非自明: エージェントの**ツール呼び出し引数を監視**してアクセスしたディレクトリを推測し、working_dir 配下の未ロードディレクトリのヒントファイルを次のプロンプト構築時に遅延ロードする。セッション開始時に全階層を一括で読まない「必要になったら読む」設計。

### (g) ループ検出/エラー回復

専用のループ検出サービスは見当たらなかった。かわりに `goal` / `grind` による継続と `compaction_attempts` / `empty_turn_retries` カウンタでの回復制御がある。

### (h) テスト

レガシーループのテスト（`crates/goose/tests/agent.rs`）はテストごとに使い捨ての `impl Provider` を定義してストリームを手動スクリプト。新 state machine のテストは `wiremock` で HTTP API をモックし、`ProviderFeatures` 構造体でプロバイダごとの挙動差異（usage 報告有無、thinking 保持、context 管理有無）を再現。MCP 呼び出しの録画・再生（`tests/mcp_replays/`）やプロバイダ別のコンテキスト長超過シナリオ録画（`scenario_tests/recordings/`）もある。

### (i) 設計思想

「マルチプロバイダ・マルチインターフェース・MCP 標準準拠・他社 CLI エージェントを ACP 経由でラップ実行できる」ことを強調。**サーバー層は REST+SSE を廃止し ACP（Agent Client Protocol）に一本化**。`security/` 配下に `security_inspector.rs` / `egress_inspector.rs` / `adversary_inspector.rs` が別途存在。

---

## DAK が設計を参考にすべき候補（ランク付き）

1. **ツール呼び出し反復検出（Gemini CLI `loopDetectionService.ts`）** — S/M。周期長 1〜5 の完全一致検出（閾値 5）を ADK の `before_tool_callback` で。検出したら Observation として「同じ呼び出しを繰り返しています」を返す。LLM ダブルチェックは小型モデル運用ではコスト対効果が薄いため後回し。→ #99
2. **編集失敗時の LLM 自己修正（Gemini CLI `utils/llm-edit-fixer.ts`）** — M。文字列置換が曖昧一致・複数マッチで失敗した場合、1 回だけ小型 LLM で `old_string` を訂正。「1 回だけ」「ファイル未変更のハッシュ確認」の歯止めが必須。mcp-server の独立性を壊さないため agent 側で実装するのが筋。→ #86
3. **要約後のインフレ検出/失敗ガード（Gemini CLI `COMPRESSION_FAILED_*`）** — S。要約結果のトークン数が元より増えていないかを検証し、失敗時はトランケートのみにフォールバック。→ #103 / #88
4. **SmartApprove の read_only_hint 優先ショートカット（Goose `permission_inspector.rs`）** — S。MCP ツールのアノテーション（read_only_hint）がある読み取り系は確認をスキップし、書き込み系のみ確認。LLM ベースの分類は複雑さの割に効果が薄いため見送り。→ #101
5. **プロンプトインジェクション対策の「信頼できないデータ」明示パターン（Goose `permission_judge.rs`）** — S。`meta_llm.py` や `enforcer.py` で LLM 判定にツール引数/ファイル内容を渡す際に「UNTRUSTED」封入 + 漏洩なしテスト。→ #101 / #92
6. **サブエージェント間の作業分担を自然文で明記（Goose `summon.rs`）** — S。「Delegates cannot coordinate. Same-file work = conflicts. Research: parallelize freely」を A2A ピア/サブエージェントの description に。→ #85
7. **サブディレクトリ単位の遅延ヒントロード（Goose `SubdirectoryHintTracker`）** — M。`after_tool_callback` でアクセスしたディレクトリを監視し、未ロードの指示ファイルだけ遅延注入。8K 窓で有効。→ #115
8. **ツールペア要約（Goose `compute_tool_call_cutoff`）** — 参考にしない。DAK の artifact 退避 + paging のほうが決定論的で LLM 呼び出しコストも無い。
9. **バックグラウンドシェル実行とドレインタイムアウト** — 優先度低。mcp-server をステートレスに保つ原則と衝突しうる。
10. **他社 CLI エージェントをプロバイダとしてラップ（Goose `manages_own_context()`）** — 見送り。DAK の主要ユースケースと目的が異なる。

### ADK が既にネイティブに提供しているため模倣不要なもの

- Gemini CLI の `Turn` / `Scheduler` によるツール呼び出し状態機械とストリーム処理は ADK の `LlmAgent` 実行ループと `FunctionTool` 機構が担う。
- モデルフォールバックチェーン（pro→flash→flash-lite）は LiteLLM の `fallbacks` / `model_group` で代替可能。
- GEMINI.md 階層探索は ADK にも Goose にも標準実装が無く、必要なら DAK 側で薄く自作（#115）。

## 総括

Gemini CLI は「圧縮・ループ検出・編集修正」まわりの**閾値とプロンプトが極めて具体的にチューニングされ、テストされている**点で参照価値が高く、特に 1〜3 は DAK の「小型ローカルモデルでもコンテキスト予算内に収める」制約に直結する。Goose は「安全性（プロンプトインジェクション対策のテスト保証、read_only 優先の承認省略）」と「サブエージェントへの自然文での協調指示」の面で参考になるが、コンテキスト管理の主力機構（ツールペア要約）やサーバー抽象（ACP 経由の他社エージェントラップ）は DAK の現在の設計と方向性が異なり、参考にする価値は低い。
