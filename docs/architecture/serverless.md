# DAK のサーバレス構成（AWS）— 設計と費用の概算

> Status: 実行環境を Lambda に決定（2026-10-08）、配置は #135 · 初版 2026-09-21 · 要望 #131
> 対象: ほかのアプリが標準の API として DAK を呼び、LLM 機能を使う用途。設計は特定の呼び出し元に依存しない。
> 前提: フロントエンドは呼び出し元のものだけ（DAK の BFF / HTMX と CLI は使わない）。
> 単価・対応リージョンは 2026-09-21 に公式ページで確認した値。数値は見積もり。ただし §3 の「S1 の実測（#252）」は 2026-10-07、「S2 の実測（#253）」と「イメージの大きさ（#251）」は 2026-10-08、§4 の「最小の呼び出しの上乗せ（#248）」は 2026-10-09、「実用途の実測（#249）」は 2026-10-26 の実機の値。

## 0. 結論

1. **DAK は、用途ごとの専用コードを書かずに LLM 機能を使うための汎用 API とする。** 最小の呼び出しは、LLM を直接呼ぶ場合と同じ回数・同じトークンで済むべき。
   高度な機能（ツール、スキル、モード切替、A2A、検査と再試行）は、呼び出し元が有効にしたときだけ費用がかかる。
2. **最初の見積もりでは、今の DAK はこの条件を満たしていなかった。** DAK 経由は直接呼び出しの約 2 倍になった。
   原因は、エージェントであること自体ではなく、設定がプロセス全体で 1 通りに固定されていることにあった（§2）。これを直す PBI を切った（§5）。
   直した後の実測（#249、§4）では、LLM の呼び出し回数は直接呼び出しと同じで、1 セッションの費用の差は約 3%（推論トークンのばらつきを含む）だった。
   ただし、ツールと出力スキーマを一緒に使うと、スキーマに合わない応答が検査されずに返る（#1001）。
3. **サーバレスは成り立つ。** 1 回の呼び出しを「上限つき・状態を持たない」ものにすれば、Lambda でも AgentCore Runtime でも動く。
   費用はほぼ LLM で決まり、実行環境の費用は月 300 セッションでも Lambda で月 2 USD ほど（実測の所要時間から。§4）。
4. **決定と未決**（§6）: Global CRIS は許可（2026-09-21）。実行環境は Lambda（S1）に決めた（2026-10-08、実機での実現性検証 #141 の後）。

## 1. 想定する使い方（見積もりの仮定）

呼び出し元のアプリが、構造化された文書（JSON）を生成し、対話で直し、その文書について質問する、という使い方を仮定する。
生成 1 回・修正 10 回・質問 20 回を「1 セッション」と呼び、費用はこの単位で見積もる（呼び出し元から見た利用の単位。DAK / ADK のセッションとは別）。

| 操作 | 頻度（1 セッションあたり） | DAK への指定 |
|---|---|---|
| G: 初回生成 | 1 回 | 指示 = 生成の手順、出力スキーマ = 文書の形、検査 = 呼び出し元の検査。ツールなし |
| E: 対話での修正 | 10 回 | G と同じ指定に、現在の文書と依頼を渡す |
| Q: 質問 | 20 回 | 指示 = 回答用の短い指示、入力 = 文書と質問。ツールなし |
| （オプション）ツールを使う修正 | 必要なとき | 呼び出し元の MCP（例: 外部の検索）を渡す |

## 2. 今の DAK の制約

### DAK を通すと費用が増える原因（#131 の追記を受けて分解）

| 要因 | 現状（根拠） | 直す PBI |
|---|---|---|
| 指示と出力の形を、呼び出しごとに渡せない | 指示・ツール・モデル・MCP の接続先は、import 時の環境変数で固定（`agent/dak_agent/agent.py:40-100`）。ADK 2.8 の `/run` には `state_delta` / `custom_metadata` の受け口がある（`google/adk/cli/api_server.py:521-532`）が、使っていない | #137 |
| ツールの定義が毎回すべて載る | MCP の 8 ツールと内蔵ツール（`planner`、`switch_mode`、`list_skills`、`enable_skill`、`read_tool_output`）| #136 |
| ツールが確認待ちで止まる（実際は止まらない） | `agent/dak_agent/agent.py:45` の `require_confirmation=True` は `AdaptiveAgent` が捨てるので効かず、モデルに渡る MCP のツールセットは全部 `require_confirmation=False`（`docs/design/permission-boundary.md`）| #136 / #101 |
| 検査を LLM の往復でしか行えない | 検査をツールとして渡すと、通る場合も「ツール → 結果 → 最終応答」の往復が要る | #140 |
| キャッシュが効かない経路 | Luna のプロンプトキャッシュは Responses API だけで効く。LiteLLM の `bedrock/` の既定は Converse | #94 |
| モード切替の Meta-LLM | 切替のたびに 1 回（`agent/dak_agent/mode_manager.py:216`）。毎ターンではない（最初の見積もりでは多く数えていた）| #139（呼び出し元が有効にしたときだけ）|

上乗せが 0 であることは、#139 で CI の不変条件にする。

CI の統合テスト `tests/integration/test_minimal_overhead.py` が、指示と出力スキーマだけを渡し `dak:tools: []` でツールを選ばない呼び出しについて、次を毎回確かめる（fake-LLM が受け取ったリクエストを数える）。

- LLM の呼び出しは 1 回（Meta-LLM は同じモデル名で呼ぶので、Meta-LLM も 0 回）。リクエストにツールの定義が無い
- メッセージのトークン（`agent/dak_agent/harness.py::estimate_tokens` の見積もり）が、同じ指示と入力で LLM を直接呼んだ場合との差 **N = 20 トークン**以内。DAK 固有の差は、ADK がどのエージェントの指示にも足す 1 行（`You are an agent. Your internal name is "dak_agent".`）だけで、実測は 14（DAK 56 / 直接 42、2026-09-28）。20 はこの行の分とわずかな余裕で、これを超えたら DAK が何かを足している

### サーバレスで困る点

| 点 | 現状（根拠） | 直す PBI |
|---|---|---|
| プロセスに置いた状態 | 有効スキル（`agent/dak_agent/adaptive_agent.py:42`）、モード切替のフラグ（`agent/dak_agent/mode_manager.py:38-39`）、指示の直接書き換え（`agent/dak_agent/adaptive_agent.py:319`、`agent/dak_agent/skill_tools.py:212`）が、全セッションで共有される 1 インスタンスに載っている。**Docker でもセッションが混ざる不具合** | #133 |
| 1 ターンの上限が無い | `RunConfig` の指定が無い。ADK の `max_llm_calls` は、プロセス全体の `ADK_MAX_LLM_CALLS` でしか変えられない（#134 で DAK 独自の上限を足した: `call_config.md` の「1 ターンの上限」） | #134 |
| 開発用サーバで起動 | ADK の開発用アプリ（`get_fast_api_app(web=True, a2a=True)`）を uvicorn で動かす（`agent/dak_agent/server.py`、`agent/Dockerfile` の末尾）。`agent/entrypoint.sh` が `agent.json` をファイルに書く | #135 |
| シェル・ファイル系ツール | `mcp-server/main.py` の `run_command`（`shell=True`）。作業場所はバインドマウントの `/projects` | #136（呼び出しで外せる）|
| 起動の重さ | import 時に Langfuse の `auth_check`（通信あり、`agent/dak_agent/patches.py:26-43`）と、solana などの読み込み | #135 |

## 3. 構成案

### 共通: 呼び出し元との境界

```text
ブラウザ（呼び出し元の画面だけ）
  → CloudFront → API Gateway HTTP API → 呼び出し元の Lambda
       POST /v1/generate … ジョブを作る（202 と job id を返す）
       GET  /v1/jobs/{id} … ポーリング
  → DAK（S1 / S2）を IAM 認証で呼ぶ。1 回ごとに次を渡す（#137 / #136 / #138 / #134 / #140）
       指示・出力スキーマ・ツール（なし / 一部 / 呼び出し元の MCP）・モデル・上限・検査
  DAK → Bedrock bedrock-runtime（global.openai.gpt-5.6-luna）。実行ロールの bedrock:InvokeModel で呼び、API キーは作らない
```

- **非同期は必須。** API Gateway HTTP API の統合タイムアウトは 30 秒。約 4k トークンの JSON に推論分も加えて出力するには、数十秒かかる見込み（API Gateway を挟む場合。呼び出し元のジョブ Lambda が直接 `Invoke` で待つ形なら 30 秒に縛られない。§3 S1 の実測）。
- **会話の状態は呼び出し元が持つ。** 呼び出しごとに、必要な文脈（例: 現在の文書と直近の会話）を渡す。DAK は呼び出しの中だけのセッションで動かし、DB を置かない。
- **DAK は 1 つ配置すればよい。** 用途の違いは、呼び出しごとの指定で表す。呼び出し元の内部（DB など）には依存しない。

### S1: Lambda（コンテナイメージ）

- 呼び出し元が `InvokeFunction`（非同期の Event）で起動する。上限は 1 回 15 分、応答は 6 MB（ストリーミング時 20 MB）。
- 利点: 呼び出し元が Lambda なら、同じ仕組みで配置・運用できる。
- 欠点: A2A の task を複数回の呼び出しにまたがって保持できない。ジョブ管理を自前で作る。Event 呼び出しは応答を返さないので、結果は DynamoDB のジョブに書き、呼び出し元がポーリングする（「ジョブ」の節、#716 で決定）。実測は下の表。

### S1 の実測（#252、2026-10-07）

`agent/Dockerfile` に AWS Lambda Web Adapter を足した dev 用イメージ（arm64、メモリ 1,536 MB、タイムアウト 15 分）を ECR に置き、東京の Lambda に配置して、us-east-1 の Nemotron Super 3 120B（`bedrock/converse/nvidia.nemotron-super-3-120b`）を呼んだ。MCP サーバは置かず（`MCP_SERVER_URL` は届かない先）、セッションは `/tmp` の SQLite。モデルは Luna ではないので、時間は §4 の前提（Luna）にそのまま当てはまらない。各数値は 1 回の測定で、ばらつきは見ていない。

| 確かめたこと | 結果 |
|---|---|
| 1 ターンの実行 | 成功。`/run` が Nemotron の応答を返した。初回の呼び出し 15 秒、2 回目 0.8 秒（呼び出し側の時間と REPORT の Duration が一致）。初回が長い原因は未確認（MCP に届かない待ちを含む可能性。ローカルの同じイメージでは 11.8 秒だった） |
| コールドスタート | 初回の呼び出しは約 19 秒。最初の Init が Lambda の Init 上限 10 秒で打ち切られ、呼び出しの中で再実行された分を足した値。別のコンテナの Init は約 9 秒だった。上限に近いので余裕が少ない。原因（読み込む依存など）は未計測。同時に呼ばれたときのコールドスタートは測っていない |
| 30 秒を超えるターン（同期 Invoke） | 約 2,500 語の出力を求めて 379 秒、HTTP 200 で完了。直接の `Invoke` は API Gateway の 30 秒に縛られない |
| 30 秒を超えるターン（非同期 Event） | 同じ指示で `InvokeFunction` が 0.85 秒で 202 を返し、約 86 秒（約 11 秒間隔のポーリングで完了を見た時刻）で完了。同じ指示でも 86〜379 秒とばらついた。Event は応答を返さず、失敗時は既定で最大 2 回再試行される（二重実行になりうる。未実測） |
| 完了の受け取り（ポーリング） | `GET /apps/.../sessions/<id>` は、ターンの実行中は別のコンテナが受けて 404 になった（ログで確認。セッションがコンテナの `/tmp` にある）。完了後に同じコンテナへ届いた 1 回だけ 200。呼び出しごとのセッションで動かす方針（§3 共通）なら DAK のセッションをポーリングする設計にはならず、結果は呼び出し元が受ける経路（Destinations、または同期 `Invoke`）で決める |
| IAM 認証の呼び出し | `lambda:InvokeFunction` を持つロールは成功（200）、持たないロールは AccessDeniedException。別の Lambda からの呼び出しは #135 で確かめた（下の「dev での実機の確認」） |

イメージは、読み取り専用のルートファイルシステムで動かすため、`entrypoint.sh` が起動時に書く `agent.json` をビルド時に作り、`uv run` を使わず venv の uvicorn を直接起動した（`/tmp` 以外に書かない）。本番の構成（#135）では、この 2 点を引き継ぐかと、呼び出しごとのセッションなら `/tmp` の SQLite を外せるかを決める。

### Lambda の入口（#715）

`agent/dak_agent/lambda_handler.py` の `handler(event, context)`。`adk web` も HTTP サーバも使わず、1 回の呼び出しで 1 ターンを返す。

| | 形 |
|---|---|
| 入力 | `{"message": "<text>", "state_delta": {"dak:…": …}}`。`state_delta` は省略可で、`/run` と同じ `dak:` キー（`call_config.md`）。ターンをまたぐなら `session_id`（下の「セッション」） |
| 成功 | `{"status": "succeeded", "output": "<最終応答のテキスト>"}`。`turn_limit_exceeded` などのエラー JSON も `output` にそのまま入る（判定は呼び出し元） |
| 失敗 | `{"status": "failed", "error": "<例外のクラス名>"}`、または不正な入力で LLM を呼ぶ前に `"invalid_event"`。メッセージは本文を含みうるので返さず、ログにも出さない |

- `session_id` が無ければ、呼び出しごとに `InMemorySessionService` を作って捨てる。DB も `/tmp` の SQLite も使わず、表にも何も書かない
- モジュールの先頭では標準ライブラリだけを import し、`dak_agent.agent` は最初の呼び出しで読む。Init の上限 10 秒（上の実測）に載せないため
- `dak:tools` が無ければ `[]` を入れる。MCP サーバを配置しないので、届かない接続先を待たない（続きのセッションは前のターンの値を使う）
- 呼び出しの本文と `state_delta` の値はログに出さない
- モデルの API キーを Parameter Store から読める（#804）。`DAK_API_KEY_PARAMETER` にパラメータの**名前**を渡すと、最初の呼び出しで 1 回だけ読んで `ANTHROPIC_API_KEY` に入れる。値はテンプレート・イメージ・ログのどこにも書かない。実行ロールには、そのパラメータだけの `ssm:GetParameter` を許す。指定が無ければ何も読まない（Bedrock を実行ロールで呼ぶ構成）

#### ジョブ（非同期の受け取り、#716）

結果の受け取りは「Event 呼び出し + 同じ関数の `op: get` でポーリング」に決めた（A2A の task は Lambda が呼び出しをまたいで持てず、Destinations は結果がジョブ ID でポーリングできないため）。

- 開始: `{"message": …, "job_id": "<id>"}` を `InvokeFunction`（Event）で呼ぶ。`job_id` があると、ターンの前に `DAK_TABLE` へ `pk = J#<job_id>`, `sk = JOB` を条件付きで書く（同じ `job_id` の 2 回目は実行せず `job_exists`）。終わると `succeeded`（`output`）か `failed`（`error`）に更新する。1 日後に TTL（`expires_at`）で消える
- 確認: `{"op": "get", "job_id": "<id>"}` を同期 `Invoke` で呼ぶと `{"job_id", "status", "output"?, "error"?}` を返す。`succeeded` / `waiting` / `output_too_large` で終わったセッションのジョブは `session_id` を、`waiting` なら `pending` も返す（`output_too_large` では `pending` が落ちるので、続けるには次の `message` を送る）。期限切れの承認に答えたジョブは `observation: timed_out` も返す（`output_too_large` でも）
- 状態: `running` / `succeeded` / `waiting`（下の「セッション」）/ `failed` / `timed_out`（`running` のまま Lambda のタイムアウトの時刻を過ぎた。ターンの後の結果の書き込みに失敗したときも `running` のままなので同じく `timed_out` と読める。呼び出し元は再投入してよい）/ `not_found`
- 失敗の理由: `job_exists`、`table_not_configured`（`DAK_TABLE` が無い）、`output_too_large`（`output` と `pending` で 350 KB 超。DynamoDB の 1 件の上限 400 KB）、`invalid_event`、例外のクラス名

#### セッション（`session_id`、#721）

`session_id`（と省略可の `user_id`。既定 `lambda`）を付けると、セッション（会話の履歴・state・承認待ちと質問）を `DAK_TABLE` に置き（`dynamodb_sessions.py`、最後の更新から 7 日で TTL）、次の同じ `session_id` の呼び出しが続きから動く。`job_id` と一緒に付けてよい。

- 錠: ターンの前に `pk = S#<app>#<user>#<session_id>`, `sk = LOCK` を条件付きで書き（無いか `lock_until` を過ぎている）、ターンの後に消す。`lock_until` は Lambda の残り時間までなので、タイムアウトで止まった錠も、消すのに失敗した錠（ログに残し、結果はそのまま返す）も残らない。取れなければ LLM を呼ばずに `{"status": "failed", "error": "session_busy"}`
- 結果: `{"status": "succeeded", "session_id", "output"}`。確認の要るツールか `ask_question` で止まったターンは `{"status": "waiting", "session_id", "output", "pending": [...]}`。`pending` の各項目は `GET /approvals` と同じ形（`id`・`session_id`・`kind`（`approval` / `question`）・`status`（`pending` / `timed_out`）など。`docs/design/approval-queue.md`）
- 答え: `{"op": "reply", "session_id", "approval_id": "<pending の id>", "mode": "once" | "always" | "reject", "reason"?}`（承認）か `{…, "answer": "<text>"}`（質問）。`POST /approvals/{id}/reply` と同じ判定で、保留に無い id は `not_found`、承認に `mode` が無い・質問に `answer` が無いと `invalid_event`。期限切れの承認は `timed_out` の答えで再開し、結果に `"observation": "timed_out"` が付く（もう一度答えない）。再開したターンがまた止まれば、ふたたび `waiting`。止まったジョブ（`job_id` 付き）は、答えた後も `op: get` が `waiting` のまま。再開したターンの結果は `op: reply` の戻り値か、`op: reply` に付けた新しい `job_id` で受け取る（同じ `job_id` は `job_exists`）
- アーティファクト（`read_tool_output` で読むツールの出力の全文）はターンをまたいで残らない
- 質問と答え（Enforcer Mode、#879）: `ask_question` と `attempt_answer` は Enforcer Mode のときだけ組み込みツールに入る。テンプレートのパラメータ `EnforcerMode=true`（既定 `false`）で関数の `ENABLE_ENFORCER_MODE` になる。Enforcer Mode は文だけの応答を止めるので、呼び出しは `dak:tools` に `ask_question` と `attempt_answer` を入れる（入れないと答えを返せない。Lambda の `dak:tools` の既定は `[]` で、Enforcer Mode でも `attempt_answer` を自動では足さない — ツールを選ぶのは呼び出し元）。`attempt_answer` で終わったターンの `output` は、その `answer` の文（`confidence` / `sources_used` は返さない）。ジョブの `op: get` の `output` も同じ

### 呼び出し元との契約（#837）

呼び出し元のアプリが Lambda の DAK を呼ぶアダプタは、この節だけを見て書けるようにする。値と名前は `agent/dak_agent/lambda_handler.py`・`lambda_runtime.py` が正で、形は単体テスト（`agent/tests/test_lambda_handler.py`・`test_lambda_runtime.py`）が確かめる。行の形を変えるときは PBI を立て、呼び出し元のアダプタと一緒に変える。

#### 1. 呼び出し方式

| 方式 | 要求 | 応答 |
|---|---|---|
| ストリーム（推奨） | `InvokeWithResponseStream`、本文に `"stream": true` | NDJSON（1 行 1 JSON）。生成の途中から `{"event": …}` の行が届き、最後の行が結果（下の 3） |
| 同期 | `Invoke`（`RequestResponse`）、`stream` なし | 結果の JSON 1 つ |
| 非同期 + ポーリング | `Invoke`（`Event`）に `job_id`、のち同期 `Invoke` で `{"op": "get", "job_id"}` | 上の「ジョブ」 |

- `stream` は `true` / `false` / 省略で送る。`false` と省略（と `null`）は同期と同じ。真偽値でない値（`0` を含む）と、`job_id` との併用は `invalid_event` の 1 行だけ（Event 呼び出しは応答が捨てられるので、流す意味が無い）
- 入口は、Python の標準ランタイムの代わりに Runtime API を標準ライブラリで叩くループ（`lambda_runtime.py`。応答のストリーミングに要る）。Lambda の外では、イメージの実行環境のエミュレータの下で動く

#### 2. 要求の形

| キー | 形 | |
|---|---|---|
| `message` | 文字列 | 利用者の発話。`op: reply` 以外では必須 |
| `parts` | genai の Part の JSON の配列（省略可） | 添付。`message` の後ろに足す。各要素は `{"text": …}` か `{"inlineData": {"mimeType", "data": <base64>}}` のどちらか 1 つだけ。ほか（`fileData`・関数の呼び出し・両方を持つもの・`data` か `mimeType` の無いもの）は `invalid_event` |
| `state_delta` | `dak:` キーの辞書（省略可） | `call_config.md` の呼び出しごとの指定。承認の事前設定（`owned_state_keys`）は `invalid_event` |
| `mcp_servers` | `[{"url", "type"?, "headers"?}]`（省略可） | 呼び出し元の MCP サーバ（下の 4）。`type` は `http`（既定）か `sse`、`headers` は `{"Authorization": "<表示できる ASCII の文字列>"}` だけ。`dak:tools` を `{"mcp_servers": …}` にするので、そのターンで使えるのは呼び出し元のサーバのツールだけ（組み込みのツールや名前の絞り込みとは一緒に使えない。`state_delta` の `dak:tools` と一緒に送ると `invalid_event`） |
| `session_id` / `user_id` | 文字列（省略可） | ターンをまたぐ（上の「セッション」）。`user_id` の既定は `lambda` |
| `job_id` | 文字列（省略可） | 非同期のジョブ（上の「ジョブ」）。`stream` とは併用できない |
| `stream` | 真偽値（省略可） | 上の 1 |

確認と質問への答えは `{"op": "reply", "session_id", "approval_id", …}`（上の「セッション」の「答え」）。答えにも `stream`・`mcp_servers`・`job_id` を付けられる（`mcp_servers` を付けると、再開したターンの `dak:tools` はそのサーバに替わる）。答えの `state_delta` は読まない（再開したターンはセッションの値のまま）。`parts` は質問への答えにだけ付けられ、承認への答えに付けると `invalid_event`（ADK は承認の答えと文を同じメッセージに置けない）。

大きさの上限は Lambda の要求の上限（同期・ストリームは 6 MB、Event は 1 MB）。`session_id` 付きでは、ターンのイベント（利用者の発話と添付を含む）が DynamoDB の 1 件（約 400 KB）に入らないと `event_too_large` で止まる。ターンの途中のイベントで起きることもあり、それまでにしたこと（ツールの実行など）は戻らない。

#### 3. ストリームの行と終わりの形

- 途中の行: `{"event": <ADK の Event>}`。Docker の DAK の `/run_sse` の `data` と同じ（`model_dump(mode="json", by_alias=True, exclude_none=True)`、キーは camelCase）。部分の文は `"partial": true` で届き、そのあとにまとめた文の Event が `"partial"` なしで届く。ツールの呼び出しと結果は `content.parts` の `functionCall` / `functionResponse`
- 最後の行: 同期の結果と同じ JSON 1 つ。`status` で見分ける

| `status` | ほかのキー | |
|---|---|---|
| `succeeded` | `output`、`session_id`? | ターンが終わった。`output` は最終応答の文（`attempt_answer` で終わったならその `answer`）。上限や許可外の MCP などの DAK のエラー JSON も `output` に入る（例: `mcp_server_not_allowed`） |
| `waiting` | `session_id`、`output`、`pending` | 確認の要るツールか `ask_question` で止まった。`pending` の各項目は `id`・`kind`（`approval` / `question`）・`tool_name`・`status`（`pending` / `timed_out`）・`session_id`・`requested_at` と、承認なら `tool_args`・`hint`、質問なら `questions`・`context`。`id` を `op: reply` の `approval_id` に入れて答える。確認を求めるのは組み込みのツール（`plan_exit` など）で、呼び出し元の MCP のツールは確認を求めない |
| `failed` | `error` | 下の値のどれか |

期限切れの承認に答えて再開したターンは、`succeeded` でも `waiting` でも `"observation": "timed_out"` が付く。

`error` の値: `invalid_event`（要求の形が違う。LLM を呼ばない）、`session_busy`（同じセッションのターンが実行中）、`not_found`（答えたセッションか `approval_id` が無い）、`table_not_configured`（`DAK_TABLE` が無い）、`job_exists`、`output_too_large`、`event_too_large`、それ以外は例外のクラス名（本文はログにも結果にも出さない）。

`{"status": …}` の行が無いままストリームが終わったら（Lambda のタイムアウト、接続の切断）、そのターンは失敗とみなす。`session_id` 付きなら、錠は Lambda の残り時間を過ぎれば外れる。

#### 4. 呼び出し元の MCP サーバ

呼び出し元の道具（ファイルの読み書きなど）は、呼び出し元が持つ MCP サーバとして渡す。DAK が MCP のクライアントになり、そのターンの中でつなぐ。

- 経路: Lambda は VPC に入れないので、届く先は**外から HTTPS で届く MCP サーバ**に限る。トランスポートは Streamable HTTP（`type: "sse"` なら SSE）。DAK は HTTP のリダイレクトをたどらない
- 認可: トークンは `headers` の `Authorization`（例: `Bearer <トークン>`）で送る。URL のクエリに載せない（MCP の認可の仕様）。ヘッダはそのターンの間だけ持ち、セッションの state・DynamoDB・ログ・結果のどれにも残さない。ターンが終わると、そのサーバへの接続も閉じる。だから `session_id` で続けるターンも、答え（`op: reply`）も、呼び出しごとに `mcp_servers` を付け直す（付けないと、前のターンで選んだサーバにヘッダなしでつなぐ）。トークンの発行と失効は呼び出し元が持つ（DAK は OAuth の取得の流れを持たない）
- 運用者の許可: 関数の `DAK_ALLOWED_MCP_URLS`（テンプレートのパラメータ `AllowedMcpUrls`、既定は空 = どれも許さない）にある URL だけ。`/` で終わる項目は前方一致で、スキーム・ホスト・ポートが同じで、パスがその項目で始まる URL を許す（例: `https://caller.example/mcp/` は `https://caller.example/mcp/<タスク>` を許す）。1 つでも許可外なら LLM を呼ばずに終わり、`output` に `mcp_server_not_allowed` が入る（`call_config.md`）
- ツール: 許可した呼び出し元のサーバのツールは確認待ちなしで動く。サーバの側で利用者の確認を待つあいだも Lambda は動き続けて課金される（1 ターンの上限は 840 秒、`DAK_MAX_TURN_SECONDS`）
- 届かないとき: そのサーバのツールを外してターンを続け、モデルにも届かないことを伝える（`call_config.md` の「呼び出し元の MCP が落ちているとき」）

#### 5. 呼び出し元のロールを許可する

- DAK の側: テンプレートのパラメータ `CallerRoleArn`（と省略可の `SecondCallerRoleArn`）に呼び出し元の実行ロールの ARN を渡す。そのロールにだけ `AWS::Lambda::Permission`（`lambda:InvokeFunction`）が付く
- 呼び出し元の側: そのロールの方針に、DAK の関数の ARN への `lambda:InvokeFunction` を足す。`InvokeWithResponseStream` も同じ操作で許可される（別の操作名は無い）
- 鍵は作らない。DAK はモデルを実行ロールで呼び、呼び出し元は IAM の署名で呼ぶ

#### 6. 例

ストリームの 1 ターン（行は省略して載せる）:

```json
{"message": "README の要点を 3 行で", "stream": true, "session_id": "s-1",
 "mcp_servers": [{"url": "https://caller.example/mcp/task-1", "headers": {"Authorization": "Bearer <トークン>"}}]}
```

```text
{"event": {"author": "dak_agent", "partial": true, "content": {"role": "model", "parts": [{"text": "README を読みます"}]}, …}}
{"event": {"author": "dak_agent", "content": {"role": "model", "parts": [{"functionCall": {"id": "c-1", "name": "read_file", "args": {"path": "README.md"}}}]}, …}}
{"event": {"author": "dak_agent", "content": {"role": "user", "parts": [{"functionResponse": {"id": "c-1", "name": "read_file", "response": {…}}}]}, …}}
{"event": {"author": "dak_agent", "content": {"role": "model", "parts": [{"text": "1. …\n2. …\n3. …"}]}, …}}
{"status": "succeeded", "session_id": "s-1", "output": "1. …\n2. …\n3. …"}
```

確認で止まって答えで再開する 2 回の呼び出し:

```text
→ {"message": "plans/tidy.md の計画で進めてよいか確かめて", "stream": true, "session_id": "s-2", "state_delta": {"dak:tools": ["plan_exit"]}}
← …{"event": …} の行…
← {"status": "waiting", "session_id": "s-2", "output": "", "pending": [{"id": "adk-…", "kind": "approval", "tool_name": "plan_exit", "tool_args": {"plan_path": "plans/tidy.md"}, "hint": "…", "status": "pending", "session_id": "s-2", "requested_at": 1792500000.0}]}

→ {"op": "reply", "session_id": "s-2", "approval_id": "adk-…", "mode": "once", "stream": true}
← …{"event": …} の行…
← {"status": "succeeded", "session_id": "s-2", "output": "計画が承認されました"}
```

質問（`kind: "question"`）なら答えは `{"op": "reply", "session_id", "approval_id", "answer": "<文>", "parts"?: […]}`。

### dev への配置の承認

dev への配置（`sam deploy`・変更セットの実行）は費用がかかるので、承認は PBI を Ready にするときに上限額（USD）を添えて PBI の `## 回答` で 1 回だけ取り、Task の手順 1 では聞き直さない。上限を超える見込みになったら、配置の前に止めて PBI で聞き直す。詳しくは `deploy/aws/README.md` の「Build and deploy」。

### dev での実機の確認（#719、2026-10-16）

`deploy/aws/` の 2 つのテンプレートを、東京の dev に配置して確かめた。`agent/Dockerfile.lambda` の arm64 イメージ（ECR 上で 337 MB）、メモリ 1,536 MB、モデルは us-east-1 の Claude Haiku 4.5（`bedrock/converse/us.anthropic.claude-haiku-4-5-20251001-v1:0`、IAM ロールで呼ぶ）。呼び出し元は `dev-caller.yaml` の `CallerRole` と `CallerFunction`。確かめたあと、両方のスタックと ECR の画像、呼び出し元のログを消した。各数値は 1 回の測定で、ばらつきは見ていない。

| 確かめたこと | 結果 |
|---|---|
| IAM の許可と拒否 | `CallerRole` の `Invoke` は 200。`ProbeRole`（呼び出しの権限なし）は `AccessDeniedException`。`CallerFunction`（別の Lambda）から `Event` で起動して `op: get` でポーリングし、結果を受け取れた |
| 出力スキーマ | 架空の要約の依頼（`dak:instruction` / `dak:output_schema` / `dak:tools: []`）で、スキーマに合う JSON（`summary` と `keywords`）が返った。**ただし `minItems` / `maxItems` を付けたスキーマは、3 回とも `{"status": "failed", "error": "BadRequestError"}`（Bedrock の構造化出力が配列の個数の制約を受け付けないためと推測。未確認）。外すと通った** |
| 出力上限（#134） | `dak:max_output_tokens: 20` の呼び出しは `status: succeeded` で、`output` に `{"error": "output_schema_validation_failed", "attempts": 3, "issues": [{"message": "invalid JSON: …"}], "last_response": "<途中で切れた JSON>"}` が入った。切れたことは分かるが、出力上限に達したという理由は返らない |
| 60 秒を超えるターン | 約 8,000 トークンの長文を `CallerFunction` 経由（Event + 5 秒間隔のポーリング）で求め、74 秒（`CallerFunction` の Duration 72 秒、DAK の Duration 68 秒）で `succeeded`（8,111 字）。DAK の `START` は 1 回で、再試行は起きていない |
| コールドスタート（3 回） | Init 0.21 / 0.20 / 0.31 秒（ハンドラが `dak_agent.agent` を最初の呼び出しで読むため）。最初の呼び出しの Duration は 35.2 / 15.2 / 15.2 秒（呼び出し側 36.6 / 16.5 / 16.6 秒） |
| ウォーム（3 回） | Duration 4.97 / 4.67 / 4.71 秒（呼び出し側 5.8 / 5.5 / 5.5 秒）。同じ要約の依頼で、モデルの時間を含む |
| ログ | 関数と `CallerFunction` の CloudWatch Logs の全件（約 720 行）を取り出して検索し、依頼文・出力・`state_delta` の値・認証情報は 0 件。出るのは START / END / REPORT、ライブラリの警告（MCP に届かない、Google の認証の警告）と、失敗した呼び出しの例外の記録 |
| 鍵 | `grep -rniE 'api_key\|secret\|AKIA' deploy/aws/ agent/Dockerfile.lambda` は何も出さない |

最初のコールドスタートが長い（35 秒）のは、新しい実行環境でイメージを初めて読んだためと推測している（未確認）。2 回目以降の 15 秒の内訳（依存の読み込み、MCP への接続待ち）は未計測。

### dev でのセッションの確認（#723、2026-10-19）

`session_id` でターンをまたぐ部分（上の「セッション」）を、#719 と同じ形（東京の dev、`agent/Dockerfile.lambda` の arm64 イメージ、Claude Haiku 4.5）で確かめた。実行ロールの表への操作に `Query`（セッションの読み出し）と `DeleteItem`（錠の解放）を足した。呼び出しは同期 `Invoke` で、`CallerRoleArn` に指定した開発者の主体から直接送った（IAM の許可と拒否は #719 で確かめたので、`dev-caller.yaml` は配置していない）。確かめたあと、スタックと ECR の画像を消した。各数値は 1 回の測定。

| 確かめたこと | 結果 |
|---|---|
| 2 ターンの会話 | 同じ `session_id` で、1 ターン目に架空の名前を伝え、2 ターン目に名前を聞くと、その名前を答えた（`succeeded`。呼び出し側の時間は、コールドスタートを含む 1 ターン目が 33.7 秒、2 ターン目が 6.7 秒） |
| 承認 | `dak:tools: ["plan_exit"]`（確認の要る組み込みツール）で `{"status": "waiting", "pending": [{"kind": "approval", "tool_name": "plan_exit", …}]}` が返り、`op: reply` の `mode: once` でツールが動いて `succeeded` |
| 質問 | `ask_question` は Enforcer Mode（`ENABLE_ENFORCER_MODE=true`）のときだけ組み込みツールに入る。テンプレートの既定では、`dak:tools` に名前を書いてもツールが無い（モデルは質問を文で書いて `succeeded` で終わった）。dev の関数の環境変数に一時的に足すと、`{"status": "waiting", "pending": [{"kind": "question", …}]}` → `op: reply` の `answer` → `succeeded` で、答えを踏まえて続いた。ただし Enforcer Mode の答えは `attempt_answer` の呼び出しで返るので、`output` は `""`（#877） |
| 表の項目 | `aws dynamodb scan` で、セッションの項目（`S#…` の `META` とイベント）は `expires_at` が 7 日後、ジョブは 1 日後。`expires_at` の無い項目は 0 件 |

### dev での質問と答えの確認（#881、2026-10-20）

上の「質問と答え」を、#723 と同じ形（東京の dev、`agent/Dockerfile.lambda` の arm64 イメージ、Claude Haiku 4.5、同期 `Invoke` を `CallerRoleArn` に指定した開発者の主体から）で、`EnforcerMode=true` で配置して確かめた。確かめたあと、スタックと ECR の画像を消した。各数値は 1 回の測定。

| 確かめたこと | 結果 |
|---|---|
| 質問 → 答え | `dak:tools: ["ask_question", "attempt_answer"]` と質問させる指示で `{"status": "waiting", "output": "", "pending": [{"kind": "question", …}]}`（コールドスタートを含めて 22.7 秒）。`op: reply` の `answer` で再開し、`succeeded` の `output` に答えの文が入った（6.9 秒）。表のイベントでは、答えは `attempt_answer` の呼び出しから来ていた |
| ジョブ | `job_id` 付きの `Event` で `dak:tools: ["attempt_answer"]` の 1 ターン。`op: get` は `{"status": "succeeded", "output": "Paris"}` |

質問の呼び出しには `job_id` も付けていた。そのジョブは、`job_id` を付けない `op: reply` で答えた後も `op: get` が `waiting` のまま（上の「答え」）。

### S2: Bedrock AgentCore Runtime（v2、東京対応）

- A2A または HTTP のプロトコルで配置する。呼び出し元は SigV4 で `InvokeAgentRuntime` を呼ぶ。セッションは microVM に固定され、長時間の実行もストリーミングも扱える。
- 利点: LLM の応答待ちの間は CPU が課金されない。A2A の task をそのまま使えるので、憲章の「標準プロトコルで結合」に合う。
- 欠点: AWS 固有の実行環境になる。アイドルのセッションは回収される（回収までの時間は `idleRuntimeSessionTimeout` で設定する。下の実測では 120 秒にした）。

### S2 の実測（#253、2026-10-08）

`agent/Dockerfile` のイメージに、AgentCore Runtime の HTTP の入口（`0.0.0.0:8080` の `GET /ping` と `POST /invocations`。`/invocations` は DAK の `/run`、`"stream": true` なら `/run_sse` に流す）を足した dev 用イメージを、東京の AgentCore Runtime に HTTP プロトコルで配置した。入口は書き捨てで、リポジトリには入れていない。
モデルは呼ばず、コンテナの中の OpenAI 互換の偽のサーバが答えた（指示で遅延を指定できる。ストリーミングでは 5 秒ごとに部分を返す）。MCP サーバは置かず、セッションはコンテナの `/tmp` の SQLite。アイドルの回収は `idleRuntimeSessionTimeout=120` に設定した。各数値は 1 回の測定で、ばらつきは見ていない。時間は呼び出し側（AWS CLI）で測ったので、CLI の起動の約 1 秒を含む。

| 確かめたこと | 結果 |
|---|---|
| アーキテクチャ | ARM64 のコンテナが必須（[HTTP プロトコルの契約](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-http-protocol-contract.html)）。arm64 のマシンで `agent/Dockerfile` をそのままビルドして動いた。x86_64 のマシンでは `docker buildx build --platform linux/arm64` でのクロスビルドが要るはずだが、試していない |
| 配置 | イメージ（#251 より前の依存、ECR 上で 360 MB）を指定して `create-agent-runtime` から READY まで 3.9 秒 |
| 1 ターンの実行 | 成功。`InvokeAgentRuntime` が DAK の応答を返した |
| コールドスタート | 作った直後の最初の呼び出しが 30.2 秒。うち約 14 秒は応答したプロセスが起動する前（CLI の起動の約 1 秒を含む。残りは microVM とイメージの起動と見られる）、6.1 秒が DAK の読み込み、9.8 秒が最初のターン。別のセッションの最初の呼び出しは 10.5 秒で、応答したプロセスは呼び出しの前から動いていた（AWS が前もって起動していたと見られるが、仕組みは確かめていない）。同じセッションの 2 回目は 1.5 秒（DAK の処理は 0.04 秒）。どのプロセスでも最初のターンだけが 7.6〜9.8 秒かかった（原因は未確認。S1 でも初回が遅かったが、モデルも条件も違うので比べていない） |
| セッションの分離 | 2 つのセッション ID に、別のプロセス（DAK の読み込み時間と起動からの時間が違う）が応答した。ほかのセッションの会話が見えないことは試していない（入口は AgentCore のセッション ID を DAK のセッション ID に使うので、同じプロセスでも分かれる） |
| 30 秒を超えるターン（同期） | 45 秒のターンが 47.4 秒、120 秒のターンが 122.1 秒で、JSON の応答を受け取れた。API Gateway を挟まない `InvokeAgentRuntime` は 30 秒に縛られない（同期の上限は 15 分） |
| 30 秒を超えるターン（ストリーミング） | `"stream": true` で、45 秒のターンが 48.7 秒、120 秒のターンが 121.1 秒。応答は部分（`partial: true`）のイベントの列で返った。偽のサーバは 5 秒ごとに部分を出すが、届いた時刻は測っていない（ストリーミングの上限は 60 分） |
| アイドルの回収 | 150 秒あけて同じセッション ID で呼ぶと、前とは別の、前もって起動していたプロセスが答えた（9.1 秒。ほとんどは最初のターンの 7.6 秒）。前のプロセスの `/tmp` のセッションは引き継がれないと見られる（会話の履歴が残るかは試していない）。呼び出しごとのセッションで動かす方針（§3 共通）なら影響しない |
| SigV4 の呼び出し | `bedrock-agentcore:InvokeAgentRuntime` を持つロールは成功、持たないロールは AccessDeniedException（どちらも同じマシンから）。別の Lambda からの呼び出しは未実施（実行環境を Lambda に決めたので確かめない） |
| 後片付け | `delete-agent-runtime` でランタイムとワークロード ID が消えた。ECR の画像も消した。前からあった ECR のリポジトリと実行ロールは消していない。この作業で作られたサービスにリンクされたロール（下）は残る |
| 費用 | 未計測（実行環境を Lambda に決めたので測らない。要るときは Cost Explorer で見る）。§4 の S1 は x86 の単価で見積もっていて、実際（arm64）より約 2 割高め |

配置する側の権限で、実機で初めて分かったこと（#562、#580、#589）:

- 名前で絞った権限だけではランタイムを作れない。作成の中で作られる既定のエンドポイント（`CreateAgentRuntimeEndpoint`）とワークロード ID（`CreateWorkloadIdentity`）が、名前の決まる前の `runtime/*`・`workload-identity/*` に対して、呼び出し側の権限で評価される。dev では、`CreateAgentRuntimeEndpoint` を `runtime/*` に（#562）、`CreateWorkloadIdentity` を `workload-identity/*` に、`GetAgentRuntime` と `DeleteAgentRuntime` を `runtime/*` に許した（#589 の利用者の回答）。使う・変える操作は `dak_dev_*` のまま
- アカウントで最初のランタイムを作るとき、サービスにリンクされたロール `AWSServiceRoleForBedrockAgentCoreRuntimeIdentity` が作られる（`iam:CreateServiceLinkedRole` が要る。一度作れば残る）
- `DeleteAgentRuntime` の中のワークロード ID の削除（`DeleteWorkloadIdentity`）も、呼び出し側の名前で CloudTrail に記録された。名前で絞った削除の権限では、ほかの名前で作ったランタイムのワークロード ID は消せない見込み（試していない。`DeleteWorkloadIdentity` は広げないと決めた。#589 の利用者の回答）

### イメージの大きさ（#251、2026-10-08）

`agent/Dockerfile` を、arm64 の使い捨てのビルド環境（Docker 28、BuildKit）でそのままビルドした値。ECR には送っていない（圧縮サイズは `docker save | gzip -9` で見積もった）。イメージとレイヤの MB・GB は 10 進（1 GB = 10^9 バイト）。パッケージごとの値は `du -sm` の MiB（切り上げ）。

| 項目 | 値 | AgentCore Runtime（2 GB）に対して | Lambda（10 GB）に対して |
|---|---:|---:|---:|
| 非圧縮（`docker image inspect` の Size） | 767 MB | 38%（残り 1.2 GB） | 8% |
| 圧縮（`docker save \| gzip -9`） | 253 MB | 13% | 3% |

上限を非圧縮と圧縮のどちらで数えるかは確かめていない。どちらで数えても収まる。
この見積もりを ECR 上の値と突き合わせてはいない。参考までに、#253 で別のイメージ（下の 1.54 GB のもの）を ECR に送ったときは 360 MB だった。中身が違うので、見積もりの確かさを示す値ではない。
レイヤの内訳は、土台の `python:3.12-slim` が 145 MB、`gcc` と `python3-dev` が 255 MB、依存（`uv sync`）が 318 MB、uv 本体が 45 MB。

削れる見込みがあるもの:

| 対象 | 大きさ | 理由 |
|---|---:|---|
| `gcc` と `python3-dev` のレイヤ | 255 MB | 実行には要らない。マルチステージにすれば実行用のイメージから外せる（arm64 の wheel が無い依存が残っていないかは未確認） |
| uv 本体（`/bin/uv`） | 45 MB | 実行時は venv を直接起動すれば要らない |
| `solders`（`solana` は 2 MB 未満で、上位 30 件に入らなかった） | 24 MB | 読み込むのは `agent/dak_agent/wallets/solana_wallet.py` だけ（`decorators.py` 経由でも読まれる）。読み込みは `ImportError` を受けるので、外しても既定のモック（`SOLANA_USE_MOCK=true`）では動き、実チェーンを使うときだけ失敗する |
| `psycopg2_binary.libs` | 16 MB | `agent/dak_agent` から読み込まれていない（セッションは `asyncpg`）。DB を置かない構成（§3 共通）なら外せる見込み |
| `pytest` など dev の依存 | 2 MB 以上 | `uv sync` が dev のグループも入れている。`--no-dev` で外せる |

依存で大きいのは `litellm`（85 MB）、`google`（32 MB）、`botocore`（25 MB）。どれもモデルの呼び出しに要る。`a2a-sdk` は 2 MB 未満で、ADK の A2A の受け口に要る。
ビルドの仕組みで値が変わる点に注意する。#253 で、PR #449・#563（依存の変更）より前の `agent/Dockerfile` を BuildKit を使わない別の環境でビルドしたときは、非圧縮が 1.54 GB と出た（依存も違うので、差の全部がビルドの仕組みによるとは言えない。内訳は調べていない。uv のキャッシュ `/root/.cache` がレイヤに残ると増える。上の環境では 5 MB）。本番のビルド（#135）では、配置する環境と同じ仕組みで測り直す。

#### Lambda 用イメージ（#717、2026-10-15）

`agent/Dockerfile.lambda`（公式の `public.ecr.aws/lambda/python:3.12` の 2 段。ビルド段だけ `gcc` と uv を持ち、実行段は依存と `dak_agent/`・`skills/`・`provider_skills/`・`profiles/`・`agent_config.yaml` だけ）を、上と同じ使い捨ての arm64 の環境でビルドした値。
#848 の後のイメージには `agent_config.d/` も入る（`agent/Dockerfile.lambda` の `COPY agent_config.d`）。下の値はその前に測ったもの。

| 項目 | 値 | Lambda（10 GB）に対して |
|---|---:|---:|
| 非圧縮（`docker image inspect` の Size） | 986 MB | 10% |
| 圧縮（`docker save \| gzip -1`） | 367 MB | 4% |

- 削ったもの: `gcc`・`python3-dev`・uv 本体・dev の依存・`agent.json`（実行段に入らない）。ただし上の `agent/Dockerfile`（767 MB）より**大きい**。Lambda のベースイメージが `python:3.12-slim` より大きく、依存を `pip install --target` で入れるためと見られる（レイヤの内訳は測っていない）。上限には余裕があるので、削るのは #719 の実測でコールドスタートが問題になってからにする
- 読み取り専用: 実行段は `/tmp` 以外に書かない（`PYTHONDONTWRITEBYTECODE=1`）。統合テストは `read_only: true` + `tmpfs: /tmp` で動かす
- 鍵: `env` に `api_key`・`secret`・`AKIA`・`token` を含む行は 0 件。`dak_agent/` と `agent_config.yaml` に `AKIA…` の形も 0 件（`ls -R` の名前の一致は、依存のモジュール名）

### 参考: 常時稼働（Fargate）

0.5 vCPU / 1 GB を 1 台置くだけで月約 22 USD（東京）。ALB（月約 18 USD〜）と DB を加えると、月 60 USD 前後になる。小さな呼び出し元の予算の目安（月 5〜10 USD）に収まらない。

## 4. 費用の概算

### 単価（GPT-5.6 Luna、Bedrock、Standard、入力 272K 以下、USD / 100 万トークン）

東京（ap-northeast-1）で使える経路は Global CRIS だけ（In-Region と Geo は非対応）。

| 経路 | 入力 | キャッシュ書き込み（30 分） | キャッシュ読み | 出力 |
|---|---:|---:|---:|---:|
| Global CRIS（東京から） | 0.20 | 0.25 | 0.02 | 1.20 |
| Geo / In-Region（米国） | 0.22 | 0.275 | 0.022 | 1.32 |

- プロンプトキャッシュは Responses API でだけ効く（Converse では効かない）。推論トークンは出力として課金される。Priority / Flex / Batch の層は無い。
- 出典: [モデルカード](https://docs.aws.amazon.com/bedrock/latest/userguide/model-card-openai-gpt-56-luna.html)、[AgentCore 料金](https://aws.amazon.com/bedrock/agentcore/pricing/)、[Lambda 料金](https://aws.amazon.com/lambda/pricing/)

### 1 回あたりのトークン（仮定と実測）

実測は下の「実用途の実測（#249）」の DAK の 3 回の平均（Claude Haiku 5.5。Luna ではないので、推論トークンの量はモデルで変わりうる）。

| | 入力（仮定） | 出力（推論を含む、仮定） | 入力（実測） | 出力（実測、うち推論） | 根拠 |
|---|---:|---:|---:|---:|---|
| 指示（手順 + 例） | 約 4.5k | — | 約 3.4k | — | 例を含む長めの指示を仮定（前の見積もりの値を据え置き）。実測は例の文書 17 項目を含む指示 |
| 文書（15〜25 項目の JSON） | 約 4k | 約 4k | — | 約 1.8k（推論を除く） | 項目の数に比例すると仮定。実測は 18〜20 項目 |
| G | 5k | 6k | 3.4k | 3.8k（2.0k） | 検査に落ちる確率を 30% とし、落ちたら 1 回作り直す（#140）。実測では基準線の 3 回とも 1 回目で通り、DAK でも作り直しは起きなかった |
| E | 10k（半分はキャッシュ） | 5k | 11.6k（2 回の呼び出しの合計、キャッシュ 0） | 4.2k（1.9k） | 修正後の文書を丸ごと返す（保守的な仮定）。実測はツール 1 回 + 最終応答の 2 呼び出し |
| Q | 5.3k | 0.8k | 5.0k | 0.3k（0.1k） | |

### 最小の呼び出しの上乗せ（実 LLM の実測、#248、2026-10-09）

`tests/integration/test_smoke_real_llm.py::test_minimal_overhead_matches_direct_call` で、同じ指示・入力・出力スキーマを、LiteLLM で直接 1 回と、DAK の最小の呼び出し（`dak:instruction` / `dak:output_schema` / `dak:tools: []`）で 1 回呼び、モデルが返した usage を比べた。
モデルは Bedrock の Claude Haiku 4.5（`bedrock/us.anthropic.claude-haiku-4-5-20251001-v1:0`、us-east-1）。Luna ではないので、トークンの数は上の単価表にそのまま当てはまらない。2 回測って 2 回とも同じ値だった。
DAK 経由には `dak:max_llm_calls: 1` も付けた。出力スキーマに合わない応答は作り直され、作り直した応答の usage だけが返るので、作り直しが起きれば失敗の応答になって分かるようにした（使ったのは上限だけで、プロンプトは変わらない）。

| | LLM 呼び出し | 入力トークン | 出力トークン |
|---|---:|---:|---:|
| 直接（LiteLLM） | 1 | 169 | 8 |
| DAK の最小の呼び出し | 1 | 185 | 8 |
| 差 | 0 | +16 | 0 |

入力の差 16 は、ADK がどのエージェントの指示にも足す 1 行（§2。fake-LLM での見積もりは 14）の分と見ている（モデルに届いた文面は記録していない）。DAK 経由の LLM 呼び出しは 1 回で、Meta-LLM は呼ばれなかった。
エージェントは統合スタックではなく単独で起動し、MCP サーバは置かなかった（`dak:tools: []` なので使わない）。
回し方は `CLOUD_MODEL_NAME=bedrock/… ./scripts/smoke_cloud_llm.sh`（Ollama なら `./scripts/smoke_local_llm.sh`）。結果は pytest の出力に JSON で出る。

### 実用途の実測（#249、2026-10-26）

§1 の使い方（G / E / Q）を、架空の依頼 3 本（イベント運営の進行表。JSON で 15〜25 項目）で 3 回ずつ、基準線と DAK で呼んだ。

- **モデル**: Anthropic の API の Claude Haiku 5.5（`anthropic/claude-haiku-5-5`。単価は入力 0.10 / 出力 0.50 USD / 100 万トークン）。Luna はこのアカウントでは呼べない（2026-10-26 に東京と us-east-1 で確かめた）ので、Luna 固有の値（4k トークンの生成にかかる時間、API Gateway の 30 秒を超えるか、Responses 経路のキャッシュ）は**未実測**。Haiku 5.5 は既定で推論（adaptive thinking）をするので、出力トークンの半分ほどが推論
- **基準線**: LiteLLM で直接呼ぶ。構造化出力（`response_format` の JSON Schema。ADK が送るのと同じ形）を付け、スキーマに落ちたら 1 回だけエラーを添えて作り直させる。E は自前のツールループ
- **DAK**: `dak:instruction` / `dak:output_schema` / `dak:inspection: {"json_schema": …}`（#137 / #140）。G と Q は `dak:tools: []`、E は `dak:tools: {"mcp_servers": [呼び出し元の MCP]}`（#136。部屋の空きを返す模擬の MCP サーバ）。DAK は main（69ec7cd）をホストで単独起動した（uvicorn、SQLite のセッション。Lambda ではない）
- **数え方**: どちらも同じ記録用の中継を通して Messages API を呼び、中継が 1 呼び出しごとの usage と時間を数えた（DAK のイベントの usage は、作り直した回の usage を数えないため）。所要は呼び出し元から見た 1 回の時間、「うち LLM」は中継で測った API の時間の合計
- 費用: 18 回で 24 呼び出し、約 0.04 USD

| 操作 | 本 | 方式 | LLM 呼び出し | 入力 | 出力（うち推論） | キャッシュ読み | 所要（秒） | うち LLM（秒） | スキーマに合う |
|---|---:|---|---:|---:|---:|---:|---:|---:|---|
| G | 1 | 基準線 | 1 | 3,425 | 6,302（4,217） | 0 | 26.3 | 25.9 | 1 回目で合う |
| G | 1 | DAK | 1 | 3,445 | 1,870（0） | 0 | 21.7 | 8.2 | 合う |
| G | 2 | 基準線 | 1 | 3,421 | 4,333（2,731） | 0 | 19.2 | 19.2 | 1 回目で合う |
| G | 2 | DAK | 1 | 3,441 | 3,421（1,735） | 0 | 15.4 | 15.2 | 合う |
| G | 3 | 基準線 | 1 | 3,425 | 5,812（3,992） | 0 | 26.1 | 26.1 | 1 回目で合う |
| G | 3 | DAK | 1 | 3,445 | 6,065（4,261） | 0 | 27.2 | 27.1 | 合う |
| E | 1 | 基準線 | 2 | 12,373 | 3,342（993） | 0 | 15.0 | 14.9 | 1 回目で合う |
| E | 1 | DAK | 2 | 12,145 | 3,912（1,537） | 0 | 15.2 | 14.9 | 合う |
| E | 2 | 基準線 | 2 | 11,339 | 3,788（2,016） | 0 | 17.4 | 17.4 | 1 回目で合う |
| E | 2 | DAK | 2 | 11,111 | 4,950（2,757） | 0 | 21.1 | 20.9 | **合わない（そのまま返った）** |
| E | 3 | 基準線 | 2 | 11,757 | 3,713（1,718） | 0 | 15.3 | 15.1 | 1 回目で合う |
| E | 3 | DAK | 2 | 11,529 | 3,809（1,507） | 0 | 16.1 | 15.7 | **合わない（そのまま返った）** |
| Q | 1 | 基準線 | 1 | 5,219 | 129（0） | 0 | 3.1 | 3.1 | 1 回目で合う |
| Q | 1 | DAK | 1 | 5,239 | 118（0） | 0 | 2.6 | 2.5 | 合う |
| Q | 2 | 基準線 | 1 | 4,694 | 405（211） | 0 | 2.7 | 2.7 | 1 回目で合う |
| Q | 2 | DAK | 1 | 4,714 | 330（165） | 0 | 3.0 | 2.9 | 合う |
| Q | 3 | 基準線 | 1 | 4,902 | 475（339） | 0 | 3.4 | 3.4 | 1 回目で合う |
| Q | 3 | DAK | 1 | 4,922 | 339（209） | 0 | 3.8 | 3.7 | 合う |

#### 基準線との差の要因（1 セッション = G 1 回 + E 10 回 + Q 20 回に換算）

| 要因 | 1 回あたりの差（DAK − 基準線、3 回の平均） | 1 セッションの差 | 説明 |
|---|---|---:|---|
| LLM の呼び出し回数 | G 0 / E 0 / Q 0 | 0 回（どちらも 41 回） | 作り直しは 18 回とも起きなかった（基準線も 1 回目で通った）。Meta-LLM も呼ばれない |
| 入力トークン | G +20 / E −228 / Q +20 | −1,860 | G・Q の +20 は ADK がどのエージェントの指示にも足す 1 行（§2、#248 の +16 と同じもの）。E の −228 は、ツールがあると ADK が構造化出力の指定の代わりに `set_model_response` のツールを足すため（リクエストの形が違う。下の「スキーマ」の行）|
| 出力トークン（推論） | G −1,648 / E +358 / Q −59 | +759 | リクエストの形が同じ G・Q でも両方向にぶれる。モデルの推論の量のばらつきで、DAK が足したものではない（3 回では分けきれない）|
| 出力トークン（推論以外） | G −49 / E +251 / Q −15 | +2,158 | E の +251 は回ごとに +26 / +421 / +307。大きい 2 回は、DAK の応答にスキーマに無い項目（`status`・`warnings` など）が足された回（下の「スキーマ」）で、スキーマに合った 1 回は +26。足された項目が差の大半と見ているが、3 回では確かめきれない |
| キャッシュ読み | すべて 0 | 0 | どちらもキャッシュの印を付けていない（DAK は既定でキャッシュを有効にしない、#94。基準線の LiteLLM も付けない）。指示の 3.4k トークンは毎回同じなので、効かせれば両方とも下がる（§6）|
| 所要時間（LLM 以外） | 1 回 0.1〜0.5 秒。起動後の最初の 1 回だけ 13.5 秒 | — | 最初の 1 回は DAK のプロセスの準備（遅延読み込みなど）。Lambda では Init と最初の呼び出しに当たる（§3 の S1 の実測、#135）|
| スキーマ | E で DAK は 3 回中 2 回、スキーマに合わない応答をそのまま返した | — | ツールと出力スキーマを一緒に使うと、ADK は最終応答を `set_model_response` のツール呼び出しで返させ、API 側でスキーマが強制されない。DAK の検査（`agent/dak_agent/adaptive_agent.py` の `_retry_on_inspection_failure`）はツール呼び出しを含む応答を検査しないので、作り直しも起きない。基準線は API の構造化出力で 3 回とも合った。**#1001** で直す |

費用の差は、Haiku 5.5 の実費で 1 セッション +0.0013 USD（+2.8%）、Luna の単価に当てると +0.0031 USD（+3.0%。うち入力 −0.0004、推論 +0.0009、推論以外の出力 +0.0026）。推論以外の出力の差の大半は #1001 の不具合でスキーマに無い項目が足された回のものと見ている。直した後にこの差が消えるかは未実測。

### 1 セッションあたり（G 1 回 + E 10 回 + Q 20 回）

| 方式 | 見積もり（Luna、仮定のトークン） | 実測（Haiku 5.5 の実費） | 実測のトークンに Luna の単価を当てた値 | 備考 |
|---|---:|---:|---:|---|
| 基準線: LLM を直接呼び、自前で再試行 | 約 0.13 USD（約 19 円） | 0.046 USD | 0.102 USD（約 15 円） | |
| **DAK（#137 / #136 / #140 / #94 の後）** | **約 0.13 USD（約 19 円）** | **0.047 USD** | **0.105 USD（約 16 円）** | 基準線との差は +2.8%（Haiku 5.5）/ +3.0%（Luna の単価）。LLM の呼び出し回数は同じ。要因は上の「基準線との差の要因」 |
| 今の DAK（参考、最初の見積もり） | 約 0.24〜0.37 USD | — | — | 検査をツールで往復し、ツールの定義を毎回載せた場合。0.37 はキャッシュが効かない場合 |

1 USD = 150 円で換算した。実測の E はツールを使う修正（呼び出し元の MCP を 1 回呼ぶ）なので、見積もりの「ツールを使う修正（オプション）」の分も含む。自前のループで書いた基準線と比べて、呼び出し回数の差は出なかった。
「Luna の単価を当てた値」は Haiku 5.5 のトークン数のままなので参考。Luna での値は未実測（Luna が使えない）。

### 月額（DAK、LLM + 実行環境）

1 セッションあたりの DAK の呼び出しは 31 回（LLM の呼び出しは 41 回）。S1 の実行時間は、1.5 GB のメモリで 1 回平均 8.3 秒とした（#249 の DAK の所要の平均 G 21.4 秒、E 17.5 秒、Q 3.1 秒の加重平均。ホストでの値で、Lambda のコールドスタートは含まない）。前の見積もりは 29 秒（G 90 秒、E 60 秒、Q 10 秒の仮定）。
LLM は実測のトークン（DAK、1 セッション 0.105 USD）に Luna の単価を当てた値。括弧内は Haiku 5.5 の実費（1 セッション 0.047 USD）。

| 規模 | セッション / 月 | LLM | S1 Lambda | S2 AgentCore | 合計（S1） |
|---|---:|---:|---:|---:|---:|
| S | 10 | 1.1（0.5） | 0.06 | 0.4 | **約 1.1 USD（約 170 円）** |
| M | 50 | 5.3（2.4） | 0.3 | 1.7 | **約 5.6 USD（約 840 円）** |
| L | 300 | 32（14） | 1.9 | 10.5 | **約 34 USD（約 5,000 円）** |

前の見積もり（仮定のトークンと 29 秒）は S 約 1.5 USD、M 約 7.5 USD、L 約 45 USD。差の大半は LLM（1 セッション 0.13 → 0.105 USD）と、所要の仮定（29 → 8.3 秒）による。

- S2 の見積もり: CPU は 1 vCPU を 2 秒、メモリは 1.5 GB を（29 秒 + アイドル 120 秒）とした。S2 は使わないと決めた（§6）ので、実測の所要では計算し直していない。
- 固定費は小さい。ECR（約 1 GB）で 0.1 USD、短期保持のログで 1 USD 未満。IAM ロールで Bedrock を呼ぶので、Secrets Manager も増えない。
- 足していないもの: 無料枠。AgentCore Memory（1,000 イベントあたり 0.25 USD。L では月約 19 USD になるので使わない）。常時稼働の DB。
- **費用の上限は構成で決まる。** 呼び出し元の 1 日の回数制限と、1 回の上限（#134）を掛けたものが、最悪の場合の月額になる。

## 5. PBI（#131 の派生）

| 順 | PBI | 内容 |
|---|---|---|
| 1 | #133 | セッションごとの有効スキル・モード・指示（混線の不具合）|
| 2 | #137 | 指示と出力スキーマを、呼び出しごとに指定する（書式は [call_config.md](call_config.md)）|
| 3 | #136 | ツールを、呼び出しごとに選ぶ（なし・一部・呼び出し元の MCP）|
| 4 | #139 | 最小の呼び出しの上乗せが 0 であることを、CI で保証する |
| 5 | #134 / #140 / #138 | 上限、検査と再試行、モデルの選択を、呼び出しごとに指定する |
| 6 | #132 | 実用途で実測し、直接呼び出しとの差を要因ごとに説明する |
| 並行 | #141 | AgentCore Runtime と Lambda の実現性を実機で確かめ、実行環境を選ぶ（DAK の改修とは独立）|
| 7 | #135 | AWS のサーバレス環境に配置する。#141 で Lambda（S1）に決めた。#141 で残ったこと: 起動を Init の上限 10 秒に収める、結果の受け取り方（#716 で決定: Event + ポーリング）、別の Lambda からの IAM 認証の呼び出し（#719 で確認済み）、読み取り専用のルートファイルシステムの扱い（`agent.json` をビルド時に作る、`uv run` を使わない）を引き継ぐか決める、呼び出しごとのセッションなら `/tmp` の SQLite を外せるか決める |
| 8 | #1001 | ツールと出力スキーマを一緒に使っても、スキーマと検査が効くようにする（#132 の実測 #249 で見つかった差）|

## 6. 決定事項と未決事項

| 論点 | 状態 | 内容 |
|---|---|---|
| データの所在 | **決定（2026-09-21）** | Global CRIS を許可する（モデルの経路がもともと Global のため）|
| 実行環境 | **決定（2026-10-08）** | Lambda（S1）を選んだ（#254）。比較は下の表。AgentCore Runtime のイメージの上限 2 GB（引き上げ不可）は、今のイメージ（767 MB・圧縮 253 MB、#251）では問題にならなかった |
| 費用の上限 | 未決 | 1 日 N 回 × 1 回の上限（#134）が、最悪の場合の月額になる |
| ツールあり + 出力スキーマの検査 | 未決（#1001） | ツールと出力スキーマを一緒に使うと、スキーマに合わない応答が検査されずに返る（#249 の E で 3 回中 2 回）。直すまで、ツールを使う修正では呼び出し元が応答を検査し直す |
| Luna での実測 | 未実測 | Luna はこのアカウントで呼べない（2026-10-26）。#249 は Claude Haiku 5.5 で測った。Luna の生成時間（API Gateway の 30 秒）、推論トークンの量、Responses 経路のキャッシュは見積もりのまま |
| プロンプトキャッシュ | 未決 | #249 では基準線も DAK もキャッシュ読みが 0（どちらもキャッシュの印を付けない）。指示は毎回同じなので、効かせれば両方の入力の費用が下がる。経路ごとに有効にするかは #94 の結果（既定では有効にしない）のまま |

### 実行環境の比較（#141、2026-10-08）

#252（S1）と #253（S2）の実測、#251 のイメージの大きさによる。各数値は 1 回の測定で、詳しくは §3。

| 観点 | S1: Lambda | S2: AgentCore Runtime |
|---|---|---|
| イメージの上限 | 10 GB（767 MB は 8%） | 2 GB・引き上げ不可（767 MB は 38%、圧縮 253 MB は 13%） |
| CPU | arm64 で確かめた（x86_64 も選べるが、試していない） | ARM64 だけ |
| 入口 | AWS Lambda Web Adapter で今のサーバのまま動いた（読み取り専用のルートファイルシステムのため、`agent.json` をビルド時に作り、`uv run` を使わなかった） | `/ping` と `/invocations`（または A2A）の入口が要る |
| コールドスタート | 初回 18.7 秒（Init が上限 10 秒で打ち切られて再実行）。2 回目 0.8 秒 | 作った直後の初回 30.2 秒、別のセッションの初回 10.5 秒、同じセッション 1.5 秒 |
| 30 秒を超えるターン | 同期 `Invoke` で 379 秒まで受け取れた（上限 15 分）。非同期 Event は応答を返さず、失敗時に最大 2 回再試行する（二重実行になりうる。未実測） | 同期とストリーミングで 120 秒まで受け取れた（上限は同期 15 分、ストリーミング 60 分、非同期ジョブ 8 時間） |
| 状態 | 実行中は別のコンテナが受けるとセッションが見えない | セッション ID ごとに別のプロセス。アイドルで回収される |
| 呼び出しの認証 | IAM（`lambda:InvokeFunction`）で許可と拒否を確かめた | SigV4（`InvokeAgentRuntime`）で許可と拒否を確かめた |
| 別の Lambda から | 成功（#719。`Event` + ポーリング） | 未実施 |
| 配置の権限 | 関数の名前で絞れる | 作成の中のエンドポイントとワークロード ID が名前の決まる前に評価され、名前だけでは絞れない。アカウントで初回にサービスにリンクされたロールが要る |
| 費用 | §4 の見積もりで月 300 セッションなら 6.7 USD | 未計測（Lambda に決めたので測らない）。§4 の見積もりで 10.5 USD |
| 呼び出し元との相性 | 呼び出し元が Lambda なら同じ仕組みで配置・運用できる | A2A の task をそのまま使える |

Lambda を選んだ理由（#254）: 呼び出し元が Lambda で、1 回の呼び出しを「上限つき・状態を持たない」ものにする方針（§3 共通）なら、S2 のセッションや非同期ジョブの利点を使わない。今の DAK の入口のまま動き、x86 も選べ、費用の見積もりも低い。2 GB の懸念は今は当たらないので、ストリーミングや 15 分を超えるジョブが要るときは S2 に移せる。
