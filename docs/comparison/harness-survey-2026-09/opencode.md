# OpenCode ハーネス実装調査（DAK が設計を参考にする観点）

対象: `anomalyco/opencode` v1.18.30（commit `228e9095`, 2026-09-14）、`packages/opencode/src/` を中心にコードを直接読んだ結果。`packages/core`（Effect ベースの共有サービス）、`packages/schema`、`packages/plugin` も参照。本レポートは**コードから読み取れる事実**を主とし、docs 由来の記述は最小限。

---

## a. アーキテクチャ：サーバ/クライアント分離・イベントバス・ストレージ・セッションモデル

**単一サーバ + 複数クライアント。** `packages/opencode` が「サーバ本体（HTTP + SSE）」で、TUI（`packages/tui`）、デスクトップ（`packages/desktop`/`app`）、SDK（`packages/sdk`）、Web（`packages/web`）はすべて HTTP クライアント。内部は Effect の `Context.Service` + `LayerNode` による DI（`session/prompt.ts` の `node.deps` に 25 サービスが並ぶ）。

**HTTP API**（`server/routes/instance/httpapi/groups/*.ts`）:
- `/session` … `POST /session`, `GET /session/:id`, `GET /session/:id/message`, `POST /session/:id/message`（同期 prompt）, `POST /session/:id/prompt_async`（即時返却、結果は SSE）, `/command`, `/shell`, `/summarize`（手動 compaction）, `/revert`, `/unrevert`, `/abort`, `/fork`, `/children`, `/diff`, `/todo`, `/share`, `/init`, `/status`
- `/permission` … `GET /permission`（保留一覧）, `POST /permission/:requestID/reply`, `/reject`
- `/question` … `POST /question/:requestID/reply` / `/reject`
- `/event`（インスタンス SSE）, `/global/event`, `/global/health`, `/global/config`
- 認証: `server/auth.ts` の `OPENCODE_SERVER_PASSWORD`（Basic 認証）。`server/mdns.ts` で LAN 広告。

**イベントバス**: `bus/global.ts` は `EventEmitter` を継承した `GlobalBusEmitter`（`{directory?, project?, workspace?, payload}` でスコープ付与）。各イベントは `@opencode-ai/schema` で型付き定義。主要イベント: `session.created/updated/deleted`, `message.updated/removed`, `message.part.updated`, `message.part.delta`（ストリーミング差分）, `session.diff`, `session.error`, `session.status`（busy/idle/retry）, `permission.asked/replied`, `question.*`, `todo.updated`, `file.edited`, `session.compacted`。クライアントは GET で現在状態を取り、以後 SSE を購読する「状態は常にサーバに一元化」の設計。

**ストレージ**: SQLite（`storage/db.bun.ts` / `db.node.ts`、drizzle-orm。`SessionTable`, `TodoTable` など）。

**セッション/メッセージモデル**（`schema/src/v1/session.ts`）:
- `Session.Info`: `id, projectID, title, parentID（子セッション）, agent, model, permission（セッション単位ルール）, revert, summary{additions,deletions,files}`。
- assistant メッセージには `tokens{input,output,reasoning,cache{read,write}}, cost, finish, error, summary(bool)`。
- Part 型: `text`（`synthetic`/`ignored` フラグ）, `reasoning`, `file`, `tool`（`state: pending|running|completed|error`、`state.time.compacted`）, `step-start`（`snapshot` ハッシュ）, `step-finish`, `patch`, `snapshot`, `agent`, `subtask`, `compaction`（`auto, overflow, tail_start_id`）, `retry`。
- 「システムが差し込んだテキスト」はすべて **user メッセージの `synthetic: true` な text part** として保存される（プランモード reminder、compaction 後の continue、サブタスク結果注入など）。これがログ・再現性・UI 表示の統一点。

**ループの実行状態**: `session/run-state.ts` の `ensureRunning(sessionID, ...)` でセッションごとに 1 本のループのみ。`prompt_async` はキューして即返し、進捗は `message.part.delta` で全クライアントへ。

**DAK との対比**: OpenCode は bff 相当を持たず「サーバが唯一の真実 + 薄いクライアント」。**承認・質問・進捗のような"待ち"状態はサーバ（agent）側で ID 付き保留キューとして持ち、bff/cli はそれを GET+SSE で映す**という型は、DAK の「複数クライアント横断の承認フロー」問題（#21）に直接効く。

---

## b. コンテキスト管理

### トリガ計算（`session/overflow.ts`, `provider/transform.ts`）
```ts
// transform.ts
export const OUTPUT_TOKEN_MAX = 32_000
export function maxOutputTokens(model, outputTokenMax = OUTPUT_TOKEN_MAX) {
  return Math.min(model.limit.output, outputTokenMax) || outputTokenMax }
// overflow.ts
const COMPACTION_BUFFER = 20_000
usable = limit.input ? max(0, limit.input - reserved)
                     : max(0, limit.context - maxOutputTokens(model))
  // reserved = cfg.compaction.reserved ?? min(20_000, maxOutputTokens)
isOverflow = (cfg.compaction.auto !== false) && limit.context !== 0 &&
  (tokens.total || input+output+cache.read+cache.write) >= usable
```
判定箇所は 2 つ: `processor.ts` の `step-finish`（usage 到着時に `needsCompaction = true` → ストリーム打ち切り）と、`prompt.ts` `runLoop` の各反復先頭。プロバイダが context overflow エラーを返した場合も `ContextOverflowError` を検出し compaction へ。`retry.ts` は overflow を再試行対象から除外。

**注意（DAK に直結）**: `limit.context === 0` だと auto compaction が**黙って無効**になる。カスタムモデルの既定は `context: 0, output: 0`（`provider.ts:1558-1561`）なので、Ollama/llama.cpp 用モデルは明示設定が必須。

### 要約フロー（`session/compaction.ts`, `core/src/session/compaction.ts`）
1. `compaction.create()` が user メッセージ + `compaction` part を追加。
2. 隠しエージェント `compaction`（全ツール deny、`prompt: compaction.txt`）。`tools: {}` で呼び、ツール呼び出しが来たら例外。
3. **直近保持（tail）**: `preserveRecentBudget = cfg.compaction.preserve_recent_tokens ?? clamp(usable*0.25, 2_000, 15_000)`。user 境界ごとに区切り、後ろから予算内に収まる turn を保持。
4. 要約対象は `serialize()` でテキスト化（`[User]:` / `[Assistant]:` / `[Assistant tool call]: name(json)` / `[Tool result]:` 2,000 文字で切り詰め）。過去の要約は `<prior-summary>` として渡し「更新」指示（`SUMMARY_UPDATE_INSTRUCTIONS`）。
5. 要約テンプレート `SUMMARY_TEMPLATE`: `## Objective / ## Important Details / ## Work State (Completed/Active/Blocked) / ## Next Move / ## Relevant Files`。「ファイルパス・シンボル・コマンド・エラー文字列を正確に保持」「要約したことに言及しない」。
6. `message-v2.ts` `filterCompacted()` がモデル送信時に並べ替え: `[compaction-user("What did we do so far?"), summary-assistant, ...retained tail..., continue-user]`。compaction 前の履歴は DB に残る。
7. auto の場合、`synthetic` user text「Continue if you have next steps, or stop and ask for clarification…」を追加してループ継続。
8. 要約自体が入らなければ `ContextOverflowError("Session too large to compact…")` で停止。

### 古いツール出力の剪定（`compaction.ts` `prune`）
`cfg.compaction.prune` 有効時、ループ終了後に fork 実行。後ろから走査し、**直近 2 user turn はスキップ**、`completed` ツール出力のトークン累計が `PRUNE_PROTECT=40_000` を超えた分を対象に、合計が `PRUNE_MINIMUM=20_000` を超えるときのみ `part.state.time.compacted = now` を付与（`skill` ツールは保護）。モデル送信時は `"[Old tool result content cleared]"` に置換。**要約せず ID だけ残す軽量圧縮**で、要約 LLM 呼び出しなしに効く。

### ツール出力上限
- 共通: `tool/truncate.ts` `MAX_LINES=2000`, `MAX_BYTES=50KB`。超過分は `Global.Path.data/tool-output/tool_<ulid>` に全文保存（7 日保持）、ヒント文は **task ツールを持つエージェントなら「explore サブエージェントに Grep/Read させろ」**、持たなければ「Grep か Read offset/limit で見ろ」。`Tool.define` の wrap で全ツールに自動適用。
- `read`: 既定 2000 行、1 行 2000 文字、50KB、`offset/limit`、出力は `N: line` 形式 + 末尾に `(Showing lines a-b of N. Use offset=b+1 to continue.)`。
- `bash`（`shell.ts`）: 既定タイムアウト 2 分、出力は **tail 方向**に切り、リングバッファ + 超過時はファイルへストリーム書き出し。
- `grep`/`glob`: ripgrep、100 件上限。`webfetch`: 5MB, 30s。
- `agent.steps` でステップ上限。最終ステップでは `MAX_STEPS_PROMPT`（"Tools are disabled… Respond with text ONLY"）を差し込む。

### トークン推定・キャッシュ
- `core/src/util/token.ts`: `Math.round(length / 4)`。tokenizer は使わない。
- `provider/transform.ts`: anthropic 系に `cacheControl: ephemeral` を system と末尾に付与、OpenAI 系は `promptCacheKey = sessionID`。
- `retry.ts`: 最大 5 回、2s×2^n（jitter 0.25）、`retry-after` ヘッダ優先。
- 小型モデル向け: タイトル生成は `provider.getSmallModel()`（`small_model` 設定）を使い、`<think>…</think>` を正規表現で除去。

---

## c. ツール

| id | パラメータ | 要点 |
|---|---|---|
| `read` | `filePath, offset?, limit?` | ディレクトリも読める。画像/PDF は添付。バイナリ判定。未存在なら類似名を最大 3 件「Did you mean」。読んだファイル近傍の AGENTS.md を `<system-reminder>` として同梱（メッセージ内 1 回）。 |
| `edit` | `filePath, oldString, newString, replaceAll?` | 後述 9 段マッチャ。ファイル単位ロック。保存後 formatter 実行、LSP 診断を出力に追記。 |
| `write` | `filePath, content` | 既存との diff を権限 metadata に。 |
| `apply_patch` | `patchText` | Codex 形式パッチ。**gpt-\* モデルでは edit/write の代わりにこれだけを出す**（`registry.ts` `usePatch`）。 |
| `bash` | `command, timeout?, workdir?` | tree-sitter で構文解析 → 各コマンドを権限パターン化。 |
| `glob` / `grep` | | ripgrep。100 件。 |
| `task` | `description, prompt, subagent_type, task_id?, background?` | 後述。 |
| `todowrite` | `todos[]{content,status,priority}` | SQLite、`todo.updated` イベント。 |
| `question` | `questions[]{question,header,options[],custom?,multiple?}` | 保留 → HTTP で回答。 |
| `plan_exit` | なし | question で「build に切替?」→ synthetic user メッセージで切替。 |
| `webfetch` | `url, format, timeout?` | turndown で Markdown 化。 |
| `skill` | `name` | SKILL.md 本文 + ベースディレクトリ + サンプルファイル一覧を `<skill_content>` で返す。 |
| `lsp`（experimental） | | goToDefinition/findReferences/hover/… |
| `invalid` | `tool, error` | 不正なツール呼び出しを結果として返すための受け皿。 |

**ツール基盤（`tool/tool.ts`）**: `Tool.define(id, init)` が実行を wrap し、(1) 引数デコード失敗時 `InvalidArgumentsError`（"…Please rewrite the input so it satisfies the expected schema."）をツール結果としてモデルへ返す、(2) 出力を `Truncate.output` に通す。

**edit のマッチャ（`tool/edit.ts` `replace()`）**: 順に試し最初に**一意**に見つかった候補で置換:
1. `SimpleReplacer` 完全一致 → 2. `LineTrimmedReplacer` → 3. `BlockAnchorReplacer` 先頭行・末尾行アンカー + Levenshtein ≥0.65 → 4. `WhitespaceNormalizedReplacer` → 5. `IndentationFlexibleReplacer` → 6. `EscapeNormalizedReplacer` → 7. `TrimmedBoundaryReplacer` → 8. `ContextAwareReplacer` → 9. `MultiOccurrenceReplacer`。
安全弁 `isDisproportionateMatch`: マッチ範囲が oldString より行数で `max(+3, ×2)`、文字数で `max(+500, ×4)` 以上大きければ拒否。複数一致は "Found multiple matches… Provide more surrounding context"。

**task / サブエージェント（`tool/task.ts`）**:
- 深さ制限 `cfg.subagent_depth`（既定 1）。
- 子セッションを `sessions.create({parentID, agent, permission})` で作成。`permission` は `deriveSubagentSessionPermission`: **親セッションの deny ルールと external_directory ルールのみ継承** + 子に明示許可がなければ `todowrite`/`task` を deny。
- `task_id` で既存子セッションを再利用。`background: true` は非同期化し、完了時に親セッションへ synthetic user メッセージとして注入。
- 返り値は**子の最終 assistant メッセージの最後の text part だけ**。

**LSP フィードバック**: `edit`/`write` 後に診断を `<diagnostics file=…>` ブロックで出力末尾に追記。

---

## d. エージェントと権限

**エージェント定義（`agent/agent.ts`）**:
- `build`（primary、既定）、`plan`（primary: `edit: {"*": deny, ".opencode/plans/*.md": allow}`）、`general`（subagent）、`explore`（subagent: `"*": deny` の上で `grep, glob, list, bash, webfetch, websearch, read: allow`）。
- 隠し: `compaction`, `title`, `summary` — 全ツール deny。
- defaults: `"*": allow, doom_loop: ask, external_directory: {"*": ask}, question: deny, read: {"*": allow, "*.env": ask, "*.env.example": allow}`。
- Markdown（`.opencode/agent/*.md` frontmatter + 本文）でも定義可。

**権限エンジン（`permission/index.ts`）**:
```ts
Rule = { permission: string, pattern: string, action: "allow"|"deny"|"ask" }
evaluate(permission, pattern, ...rulesets) =
  rulesets.flat().findLast(r => Wildcard.match(permission, r.permission) && Wildcard.match(pattern, r.pattern))
  ?? { action: "ask", permission, pattern: "*" }
```
- **後勝ち**のフラットなルール列。マージ順は `defaults → エージェント固有 → ユーザー config → セッション permission → セッション内 "always" 承認`。設定は `{"bash": {"git *": "allow", "*": "ask"}}` の形。
- `ask()`: deny → `DeniedError`（ルール一覧をメッセージに含めモデルへ返す）、ask → `permission.asked` を publish して `Deferred` で待機。`reply(once|always|reject, message?)`: reject + message は `CorrectedError`（フィードバックがツール結果としてモデルへ）。always は `request.always` のパターンを承認済みに追加。
- `bash` の `always` は `BashArity.prefix(tokens) + " *"`（`git checkout main` → `git checkout *`；`arity.ts` の辞書 ~130 語）。`edit/write` は worktree 相対パス。MCP ツールは `permission: <server>_<tool>`。
- `visibleTools()`: `"*": deny` のツールは**ツール一覧から外す**。
- `doom_loop`: `processor.ts` で直近 3 part が同一ツール・同一入力なら `permission.ask("doom_loop")`。
- 外部ディレクトリ: worktree 外パスに対して `external_directory` 権限を ask。

**承認のクライアント横断**: 保留は `Permission.Service` の `pending: Map<ID, {info, deferred}>`。どのクライアントも `GET /permission` で保留一覧を取得し、`POST /permission/:id/reply` で応答。**ツール実行そのものが ask で await するため、承認 UI がどこにあってもよい。**

**プランモード**: ツール権限（edit deny + ツール非表示）と **毎ターン user メッセージ末尾に synthetic な `<system-reminder>`** の二段構え（`session/reminders.ts`）。新方式 `plan-mode.txt` は Phase1 explore 並列 → Phase2 設計 → Phase3 レビュー → Phase4 プラン書き出し → Phase5 `plan_exit` の 5 段ワークフロー。

---

## e. 指示ファイルと system prompt

`session/instruction.ts` `systemPaths()`:
1. グローバル: `~/.config/opencode/AGENTS.md`、`~/.claude/CLAUDE.md`。
2. プロジェクト: `AGENTS.md` → `CLAUDE.md` → `CONTEXT.md` の順に cwd から worktree まで `findUp`。**最初に見つかった種類だけ採用**。
3. `config.instructions[]`: glob と `http(s)://` URL。

注入位置は `session/llm/request.ts`: `[agent.prompt ?? SystemPrompt.provider(model), environment, instructions, mcp_instructions, skills 一覧]` を **1 本の system メッセージに連結**（キャッシュ効率）。

**モデル別 system prompt（`session/system.ts`）**: `gpt-4|o1|o3`→beast.txt、`gemini-`→gemini.txt、`claude`→anthropic.txt、`kimi`→kimi.txt、**それ以外（Qwen, Llama, DeepSeek, Ollama 全般）→ default.txt**（最も短く汎用）。小型モデル専用の「弱いモデル向け緩和」は**存在しない**。

---

## f. プロバイダ・モデルカタログ

- `core/src/models-dev.ts`: `https://models.opencode.ai/api.json` を取得し **TTL 5 分**でキャッシュ、失敗時はディスクの古いものを使用。
- モデル項目: `limit{context, input?, output}`, `cost{…}`, `capabilities`, `variants`。
- ユーザー config `provider.<id>.models.<id>` で `limit` 等を上書き。**未指定モデルの `limit.context` は 0** → auto compaction が動かない。
- 小型モデル向けの「JSON 修復」「ツール呼び出し修復」は**無い**。あるのは (1) 引数スキーマ違反を `InvalidArgumentsError` で返して**モデル自身に書き直させる**、(2) `invalid` ツール、(3) `<think>` 除去、(4) `finish: "stop"` でもツール呼び出しが残っていればループ継続、の 4 点。

---

## g. プラグイン/フック（`packages/plugin/src/index.ts`）

`config`, `auth`, `event`, `tool`（カスタムツール）, `chat.message`, `chat.params`, `permission.ask`（ask 前に allow/deny を差し込める）, `tool.execute.before`（args 改変）, `tool.execute.after`（output 改変）, `tool.definition`, `shell.env`, `experimental.session.compacting`（要約プロンプト差替）, `experimental.compaction.autocontinue`。

---

## h. テスト

`bun test`。`test/fixture/fixture.ts` が一時ディレクトリ + SQLite + Effect Layer を組み立て、`test/fake/{provider,…}.ts` が偽プロバイダ。`test/session/compaction.test.ts` はストリームイベントを注入し tail/overflow 分岐を検証。`test/tool/edit.test.ts` + スナップショットで各 Replacer と**全ツールの JSON Schema をスナップショット**。`packages/http-recorder` で実 HTTP を録画再生。

---

## i. 設計思想（コードが語ること）

1. **サーバが唯一の状態保持者、クライアントは投影。** すべての介入（承認・質問・compaction・サブタスク結果・モード切替）が「セッションに保存される part/メッセージ」または「ID 付き保留リクエスト」として表現される。
2. **ハーネスの介入は synthetic な user テキストで行い、system prompt は 1 本に固定**（キャッシュ効率 + 監査性）。
3. **権限は「ツール名 × パターン → allow/ask/deny」の後勝ちフラットルール**に統一し、bash も構文解析でこの枠に落とす。deny はモデルへの説明つきエラーとして返す。
4. **コンテキストは"予約"で守る**: usable = context − max_output（≤32K）、要約 + 直近 25% 保持 + 古いツール出力の無要約剪定の 3 段。
5. **サブエージェントは独立セッション**、戻り値は最終テキストのみ、権限は「親の禁止のみ継承」。
6. **モデル差はプロンプト差で吸収**。
7. **ツール出力は"全文はファイル、モデルにはプレビュー + 取り出し手段"**。

---

## DAK が設計を参考にすべき候補（優先順）

| # | 候補 | OpenCode での実体 | DAK で重要な理由 | 実装スケッチ | 規模 | 原則との衝突 |
|---|---|---|---|---|---|---|
| 1 | **承認/質問の「保留キュー + reply API + イベント」モデル** | `permission/index.ts` `ask/reply/list`、`POST /permission/:id/reply {once\|always\|reject, message?}`、`permission.asked/replied` イベント | 複数クライアント横断の承認（#21）の答え。`reject + message` を Observation としてモデルに返す点は "Agent DECIDES" と整合 | agent に `ApprovalService`（pending dict + asyncio.Future）と `/approvals`, `/approvals/{id}/reply`、SSE。`before_tool_callback` で `await ask()`。bff は HTMX ポーリング/SSE、cli は `dak-cli approve` | M | なし |
| 2 | **`limit.context` に基づく usable 計算と compaction 予約** | `overflow.ts` `usable()`、`maxOutputTokens`（min(output, 32K)） | 8K–32K モデルでは出力予約を差し引かないと即溢れる。`context===0` は無効という落とし穴も設計に含める | LiteLLM `get_model_info()` → Ollama `/api/show` → 設定値。閾値を `context − min(output, reserve)` に | S–M | なし |
| 3 | **無要約の古いツール出力剪定（prune）** | `compaction.ts` `prune` | 小型モデルでは要約 LLM 呼び出し自体が高コスト/低品質。「古い出力を artifact 参照だけに縮退」する軽量段を要約の前段に置ける | `before_model_callback` で閾値超の function_response を `"[cleared; read_tool_output(id) で再取得可]"` に差し替え | S | なし |
| 4 | **構造化要約テンプレート + 直近 tail 保持 + prior-summary 更新** | `SUMMARY_TEMPLATE`, `SUMMARY_UPDATE_INSTRUCTIONS`、tail 予算 clamp(usable×0.25, 2K, 15K) | ADK 標準の圧縮より小型モデルに向く。直近 tail をそのまま残すことで「今の作業」が壊れない | 圧縮プロンプトを固定セクション化、tail 保持、要約後に synthetic user "Continue…" | S | なし |
| 5 | **エージェント別・パターン別 permission ルール（allow/ask/deny、後勝ち）** | `Permission.evaluate`、`fromConfig`、`visibleTools` | mode 切替と planner enforcer を宣言的ルールに統一できる。`"*": deny` のツールは一覧から消す＝小型モデルの誤呼び出し減 | `agent/dak_agent/permission.py` に Rule/evaluate/merge。`run_command` はコマンド先頭トークン + arity 辞書 | M | deny は構造化 Observation で返すので整合 |
| 6 | **plan モード = 権限 + 毎ターン synthetic reminder** | `reminders.ts`, `plan-mode.txt`, `plan_exit` | 小型モデルは system prompt だけでは制約を忘れるので、user 末尾の reminder が効く | mode=plan のとき `before_model_callback` で最後の user に reminder を追加 | S | なし |
| 7 | **ツール出力切り詰めヒントの分岐**（「サブエージェントに読ませろ」） | `truncate.ts` `hasTaskTool(agent)` | 切り詰め時に委譲を案内するだけで文脈消費が減る | `harness.py` の artifact 化メッセージに委譲を促す 1 文 | S | なし |
| 8 | **ドゥームループ検知（同一ツール・同一引数 ×3）** | `processor.ts` `DOOM_LOOP_THRESHOLD=3` | 小型モデルは同じ呼び出しを繰り返しやすい | `before_tool_callback` で直近 3 呼び出しを比較 | S | なし |
| 9 | **edit の多段フォールバック matcher + 過大一致拒否** | `edit.ts` 9 Replacer + `isDisproportionateMatch` | 小型モデルは whitespace/インデントを崩しやすく、`edit_file` を安全に提供するなら必須 | mcp-server に `edit_file` を追加し Python で独自実装（`difflib`） | M | なし |
| 10 | **ツール引数スキーマ違反をツール結果として返す** | `InvalidArgumentsError`、`invalid` ツール | 小型モデルの自己修復率が上がる | `before_tool_callback` で検証、失敗時は Observation | S | なし |
| 11 | **タイトル/要約に small_model を使う + `<think>` 除去** | `provider.getSmallModel` | Ollama 環境では小型モデル分離が節約になる | `DAK_SMALL_MODEL` | S | なし |
| 12 | **git スナップショットによる undo/revert** | `snapshot/index.ts` | DAK はファイル操作が mcp-server 側にあり agent から直接 git 管理できない。**現状は採用しない** | L | 疎結合コンテナと衝突 |

**参考にしないもの**: (a) tree-sitter によるシェル構文解析（`shlex` + 先頭トークン辞書で十分）、(b) LSP 統合（mcp-server に言語サーバを同梱するコストが大きい。`run_command` で linter を走らせる方針で足りる）、(c) code-mode / background subagents（experimental）、(d) モデル別 system prompt ファイル群（DAK は LiteLLM 中立なので default 1 本 + 能力フラグの方が保守しやすい）。
