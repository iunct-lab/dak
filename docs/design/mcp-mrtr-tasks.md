# MCP の入力要求の往復（MRTR）と Tasks 拡張: 採否の比較

PBI #326（Task #329）。MCP 2026-07-28 版の入力要求の往復（MRTR、SEP-2322）を危険操作の確認・Payment Required・質問に使うか、
Tasks 拡張（`io.modelcontextprotocol/tasks`、SEP-2663）を `run_command` の長い実行に使うかを、試作（#327・#328）と一次資料をもとに比べる。
2026-07-28 版の影響の全体と扱い先は `docs/design/mcp-2026-07-28.md`（#322）。

## 一次資料（確認日 2026-10-27）

- MCP 2026-07-28 版の変更一覧（MRTR は SEP-2322、Tasks は SEP-2663）:
  https://github.com/modelcontextprotocol/modelcontextprotocol/blob/main/docs/specification/2026-07-28/changelog.mdx
- python の mcp SDK のマルチラウンドの説明（`Resolve`・`Elicit`・`ElicitationResult`）: https://py.sdk.modelcontextprotocol.io/v2/handlers/multi-round-trip/
- mcp SDK v2.2.0 のリリースノート（「The tasks extension (SEP-2663) … not implemented yet」）:
  https://github.com/modelcontextprotocol/python-sdk/releases/tag/v2.2.0 。最新の v2.3.0（2026-10-02）のリリースノートに Tasks の記述は無い
  （https://github.com/modelcontextprotocol/python-sdk/releases/tag/v2.3.0 ）。ROADMAP（https://github.com/modelcontextprotocol/python-sdk/blob/main/ROADMAP.md ）は「Tasks extension … deferred at 2.0」で、
  Issue #2806「Implement SEP-2663: Tasks Extension」は open（https://github.com/modelcontextprotocol/python-sdk/issues/2806 ）
- FastMCP 4（単体パッケージ `fastmcp`）v4.0.0 のリリースノート（2026-08-31。「Background tasks (`@mcp.tool(task=True)`) … via the
  `io.modelcontextprotocol/tasks` extension, shipped in the optional `fastmcp-tasks` package on the same Docket engine」、
  「Add guard-mode multi-round-trip tools (SEP-2322)」、「`ctx.elicit()` is old-protocol-only」）:
  https://github.com/PrefectHQ/fastmcp/releases/tag/v4.0.0 。最新は v4.1.4（2026-10-26）
- `fastmcp-tasks` 4.1.4 の依存（`pydocket>=0.26.1`、`redis`）: https://pypi.org/pypi/fastmcp-tasks/json 。
  `pydocket` 0.27.0 の依存（`redis>=6`、`burner-redis`）: https://pypi.org/pypi/pydocket/json
- google/adk-python の Issue #6826「Support the MCP Tasks extension (SEP-2663) in McpToolset」（2026-08-20 作成、open）:
  https://github.com/google/adk-python/issues/6826
- google-adk 2.12.0（`agent/uv.lock` の版）の `McpTool`: https://github.com/google/adk-python/blob/v2.12.0/src/google/adk/tools/mcp_tool/mcp_tool.py
  （`session.call_tool(...)` を `allow_input_required` なしで呼ぶ。結果の `resultType` は捨てるだけで、
  コメントは「Acting on it (`input_required` drives elicitation) is a feature, not compatibility」）。最新の google-adk は 2.13.0

## 確かめた事実

### 試作のテスト

| 事実 | 根拠 |
|---|---|
| 2026-07-28 版のクライアントには、mcp-server の試作ツール `confirm_probe` が `input_required`（`requestState` と `elicitation/create` の問い 1 つ）を返す。`inputResponses` で `proceed=true` と答えたときだけファイルを作り、`proceed=false`・拒否（decline）では作らずに `Not executed: <理由>` を返す | `mcp-server/tests/test_mrtr_probe.py` の `test_probe_input_required`・`test_probe_proceed`・`test_probe_decline`・`test_probe_rejected_question`（#327） |
| 確認の答えは、確認したときの引数に縛られる。別のパスで前の `requestState` をやり直すと SDK が `Invalid or expired requestState` で拒む（問いの文面からパスを外しても同じだったのは手元の確認で、テストにはしていない）。ただし resolver（問い）はツールの本体より先に走るので、試作ではパスの検査が問いの後になる（範囲外のパスでも一度聞いてから拒む）。聞く前に拒むなら resolver の中で検査する | `test_probe_answer_is_bound_to_the_path`・`test_probe_refuses_path_outside_tmp`（#327） |
| 旧仕様のセッションでは SDK が `elicitation/create` に切り替える（`-32603` にならない）。ただし DAK の mcp-server と同じ `json_response=True` では送り返す道が無く、「this transport context has no back-channel for server-initiated requests」で失敗する。SSE で応答すれば問いが届いて答えられる | `test_probe_legacy_session`（xfail）・`test_probe_legacy_session_over_sse`（#327） |
| ADK の `McpToolset(elicitation_callback=...)` は、旧仕様で SSE で応答するサーバなら問いを受けて答えられる | `agent/tests/test_mcp_elicitation_probe.py` の `test_accept_runs_the_tool`・`test_decline_does_not_run_the_tool`（#328） |
| コールバックは toolset ごとに 1 つで、引数に ADK の `ToolContext` は無い。ただし mcp 2.x ではツール呼び出しのタスクの中で動くので、`before_tool_callback` で ContextVar に置いた `ToolContext` をコールバックから読める（#328 の時点の mcp 1.x では読めなかった） | `test_callback_runs_in_the_tool_calls_task`（#328 のテストを #561 で mcp 2.x に合わせて直したもの） |
| コールバックが待つ間、ツール呼び出しは開いたまま。`sse_read_timeout`（既定 300 秒）で切れる | `test_open_call_is_bounded_by_sse_read_timeout` |
| `json_response=True` のサーバ（DAK の mcp-server と同じ）では問いが届かず、mcp 2.x では「no back-channel」のエラーですぐ終わる | `test_json_response_server_cannot_elicit` |

### 今の版（google-adk 2.12.0 + mcp 2.3.0）での手元の確認

#328 の後にエージェントは mcp 2.x と 2026-07-28 版の接続に移った（`docs/design/mcp-2026-07-28.md` の「エージェント側の接続」）。
そこで、`confirm_probe` と同じ形（`Resolve` + `Elicit`）のツールを持つ mcp 2.3.0 のサーバを uvicorn で立て、
`McpToolset(elicitation_callback=...)`（常に accept を返すコールバック）から `run_async` で呼んだ（2026-10-27、テストにはしていない）:

| エージェントの接続（`ADK_ENABLE_MCP_MODERN_PROTOCOL`） | サーバの応答 | 結果 |
|---|---|---|
| `1`（DAK の既定。2026-07-28 版） | `json_response=True` / SSE | どちらも失敗。ツールの結果は `{"error": "… Server returned InputRequiredResult; pass allow_input_required=True to receive it …"}`。コールバックは呼ばれない |
| `0`（旧仕様） | `json_response=True` | 失敗。「Cannot send 'elicitation/create': this transport context has no back-channel …」 |
| `0`（旧仕様） | SSE | 成功。コールバックに問いが届き、accept でツールが実行された |

つまり **DAK の今の構成（既定の接続 + `json_response=True`）では、MCP サーバが MRTR や elicitation で確認を求めても、エージェントはそれを受けられない**。
外部の MCP サーバが MRTR を返す場合も同じで、そのツールは毎回エラーになる。

## 確認・Payment Required・質問: 今の方式と MRTR 案

今の方式:

- **確認**: `agent/dak_agent/permission.py` の `PermissionPlugin.before_tool_callback` が、ツールと引数ごとに allow / ask / deny を決める。
  ask なら ADK の `tool_context.request_confirmation(...)` で確認を求め、invocation はそこで終わる（HTTP の接続は残らない）。
  答えは同じセッションへの次の `POST /run` の functionResponse で、どのクライアントからでも返せる（#100、`docs/design/approval-queue.md`）。
  保留の一覧はセッションのイベントから作る（`agent/dak_agent/approvals.py`、期限は `DAK_APPROVAL_TIMEOUT_SECONDS`、既定 900 秒）
- **Payment Required**: エージェントの中のスキルのツールが `PaymentRequiredError`（`agent/dak_agent/errors.py`）を投げ、
  `adaptive_agent.py::_on_tool_error` が `handlers/payment_handler.py` で構造化した Observation にする（`ENABLE_AP2_PROTOCOL=true` のとき）。
  払うかどうかはモデルが決める（「we never auto-pay」）。リモートの MCP サーバが支払いを求める経路は無い
- **質問**: `agent/dak_agent/builtin_tools.py` の `ask_question` が問いを返して invocation を終える。答えは次の利用者のメッセージ

| | 方式 | どこで止まるか | 誰が決めるか | 別クライアントから答えられるか（#100） | 今の ADK で動くか | 暗黙の決済・自動承認が入らないか |
|---|---|---|---|---|---|---|
| 確認 | 今（`PermissionPlugin` + `request_confirmation`） | エージェント。ツールを呼ぶ前に invocation を終える | 利用者（規則で allow / deny が決まるものは規則） | 答えられる（`/approvals` と functionResponse） | 動く | 入らない。答えが無ければ実行しない |
| 確認 | MRTR（サーバが `input_required` を返す） | MCP サーバ。ツールの中で問いを返し、クライアントがやり直すまで実行しない | サーバが問い、クライアントが答える。DAK では `elicitation_callback` が答えを作る | 今は答えられない。コールバックは ContextVar 経由で `ToolContext` を読めるが（mcp 2.x、#328 のテスト）、問いをセッションのイベントにする道が無いので `/approvals` に出ず、答えを待つ間は呼び出しが開いたまま（`sse_read_timeout` まで）。2026-07-28 版なら呼び出しは開いたままにならず、`requestState` を持って後でやり直せる形だが、ADK はそれを扱わない | 動かない（上の手元の確認。既定の接続ではエラー、旧仕様でも `json_response=True` では届かない） | サーバ側は入らない（答えがあるまで実行しない、#327 のテスト）。ただしコールバックが自動で accept すると自動承認になる。コールバックは利用者に聞く形にしなければならない |
| Payment Required | 今（`PaymentRequiredError` → Observation） | エージェントの中のツール。例外で止まる | モデル（払うツールを呼ぶかどうか）。払うツール自体も `PermissionPlugin` の規則にかかる | 支払いの判断はモデルなので該当しない。払うツールの確認は上の「確認」と同じ | 動く（エージェントの中だけ） | 入らない（自動では払わない） |
| Payment Required | MRTR（サーバが支払いの承認を `input_required` で求める） | MCP サーバ | クライアント。答えるのがコールバックなので、モデルの判断を通らない | 今は答えられない（確認と同じ） | 動かない（確認と同じ） | 入りうる。コールバックが accept を返すと、モデルも利用者も通らずに支払いが進む。採るときは、ADK が問いを確認フロー（利用者かモデルの判断）に渡す形で受けることが前提になる |
| 質問 | 今（`ask_question`） | エージェント。invocation を終える | 利用者 | 次のメッセージで答える | 動く | 該当しない |
| 質問 | MRTR（サーバが質問を `input_required` で返す） | MCP サーバ | コールバック | 今は答えられない（確認と同じ） | 動かない | 該当しない。ただし DAK のサーバのツールは利用者への質問を必要としない（モデルが `ask_question` で聞けば足りる） |

## Tasks 拡張: `run_command` の長い実行

- 今: `run_command`（`mcp-server/main.py`）は `subprocess.run(..., timeout=60)` で、60 秒を超えると「timed out」で終わる。
  `SANDBOX_MODE=docker` のときは別の経路（`mcp-server/sandbox.py` の `SandboxManager.exec_in_session`）で、コンテナの中の `timeout 60` と
  docker CLI の `timeout=65` の 2 つの上限がある。
  エージェント側は MCP の HTTP クライアントの読み取りの上限が 300 秒（`agent/dak_agent/skill_tools.py::_no_redirect_http_client` の
  `httpx2.Timeout(30.0, read=300.0)`）
- mcp SDK: 2.3.0 も Tasks 拡張を実装していない（上の一次資料）
- FastMCP 4: `fastmcp-tasks` で実装している。`fastmcp-tasks` は Docket（`pydocket`）と Redis に依存する
- ADK: `McpToolset` は Tasks 拡張を扱わない（google-adk 2.12.0 の `McpTool` は `call_tool` の結果を待つだけ。`tasks/get` を送る箇所が無い）。
  対応を求める Issue #6826 は open。google-adk 2.13.0 のリリースノートにも MCP の Tasks の記述は無い。
  したがって、サーバが Tasks を出しても、DAK のエージェントは今はそれを使えない（ADK が対応したときにどう見えるかは未確認）

| 選択肢 | 依存の追加 | 書き換えの量 | ADK 側で使えるか | 小型ローカル LLM への影響 |
|---|---|---|---|---|
| mcp SDK の実装を待つ | 無し | 今は無し。実装されたら `run_command` を Tasks にする分 | 今は使えない（#6826 が open） | 今は無し。対応後も、ポーリングをクライアント（ADK）がするなら、モデルに見えるのは最終の結果だけで変わらない（未確認） |
| 単体の FastMCP 4 に移る | `fastmcp`（Apache-2.0）と `fastmcp-tasks`（Apache-2.0）、その先の `pydocket`（MIT）と Redis。Redis を compose のサービスに足すか、インメモリの代替で動かすかは未確認 | 大きい。mcp-server を SDK の `MCPServer` から FastMCP 4 に移す（`ToolCallLogMiddleware`、`create_app()`、transport の設定、テスト） | 使えない（ADK が Tasks を扱わない）。移っても DAK のエージェントからの見え方は今と同じ | 無し（エージェントから見えないため） |
| Tasks を使わず、タイムアウトを環境変数で設定できるようにする | 無し | 小さい。`run_command` の `timeout=60` と、Docker モードの `sandbox.py` の `timeout 60` / `timeout=65` を同じ環境変数（例: `MCP_COMMAND_TIMEOUT_SECONDS`）から読む。300 秒より長くするならエージェント側の読み取りの上限も合わせる | 使える（今の `tools/call` のまま） | 無し。モデルは 1 回の呼び出しの結果を待つだけ（待つ時間が延びるだけ） |

## 方針と見送りの理由

MRTR も Tasks も MCP の標準の機能で、使うなら標準のまま使う。DAK 独自の代わりの仕組み（入力要求を独自の Observation に変える、支払いの要求を独自の形のエラーで返す、Tasks の代わりのポーリングの口を足すなど）は作らない。
今入れないのは、クライアント側の部品が標準にまだ追いついていないため:

- **MRTR**: DAK のエージェント（google-adk 2.12.0）は 2026-07-28 版の接続で `InputRequiredResult` をエラーにし、旧仕様でも `json_response=True` のサーバからは問いを受けられない（上の「確かめた事実」）。
  サーバ側（mcp SDK 2.3.0）は作れる（#327）が、今入れると DAK のエージェントからの呼び出しがエラーになる。
  旧仕様 + SSE なら受けられるが、コールバックは問いをセッションのイベント（`adk_request_confirmation`）にできず、答えを待つ間ツール呼び出しと HTTP の接続が開いたまま（`sse_read_timeout` まで）になるので、今の確認（`PermissionPlugin` → ADK の確認 → `/approvals`）の代わりにはならない
- **Tasks**: mcp SDK が未実装（python-sdk #2806）で、ADK の `McpToolset` も扱わない（adk-python #6826）。単体の FastMCP 4 に移ればサーバ側は出せるが、依存（Redis を含む）と書き換えが大きいのに、DAK のエージェントからは使えない

見直す契機（どれかが起きたら、この文書の表を今の版で確かめ直し、実装の PBI を起こす）:

- MRTR: ADK の `McpTool` が `input_required` を扱う（`allow_input_required` か SDK の `Client` の MRTR の driver を使い、問いを ADK の確認フローに渡す）ようになったとき。
  確認・Payment Required・質問のどれをサーバの MRTR に移すかは、そのとき上の比較表で決める。Payment Required は、答えを利用者かモデルの判断に通す形で受けられることが条件
- Tasks: mcp SDK が Tasks を実装し（python-sdk #2806）、かつ ADK が `McpToolset` で Tasks を扱う（adk-python #6826）ようになったとき

`run_command` の 60 秒のタイムアウトを設定で変えられるようにするのは、Tasks の代わりではない（長い処理を受け付けて後で結果を取りに来る仕組みにはならない）。この採否とは別の小さな改善として、要るときに別の要望で扱う。

## 採否（2026-10-27）

利用者の回答: 「A'でよい」。A' は「標準（MRTR・Tasks）を採る方針を決め、実装は SDK と ADK の対応を待つ。独自の代わりは作らない」。

- MRTR: 採る方針。今は実装しない（ADK の対応待ち）
- Tasks: 採る方針。今は実装しない（mcp SDK と ADK の対応待ち）
- 実装の PBI: 今は起こさない。上の「見直す契機」が起きたときに、次の案から起こす（そのとき今の版で確かめ直して直す）

## 実装の PBI の案（見直す契機が起きたとき）

1. **題**: MCP サーバが MRTR（`input_required`）で求める確認を、DAK のエージェントが ADK の確認フローで利用者に聞いて答えられる
   - 前提: ADK の `McpTool` が `input_required` を扱う
   - 受け入れ条件の案:
     - サーバが返した確認の問いが、セッションのイベント（`adk_request_confirmation` か ADK が用意する形）になり、`/approvals` に出る（検証: エージェントの単体テストで、MRTR を返す試作のサーバの問いが保留の一覧に出る）
     - 答えが「実行する」のときだけサーバのツールが実行され、「しない」・期限切れのときは実行されない。自動の承認は入らない（検証: 同じテストで accept / decline / 期限切れ）
     - 支払いの要求を MRTR で受けるなら、答えは利用者かモデルの判断を通る（コールバックが自動で accept しない）（検証: テスト）
2. **題**: `run_command` の長い実行を Tasks 拡張で受け付け、DAK のエージェントが結果を取りに来られる
   - 前提: mcp SDK が Tasks を実装（python-sdk #2806）し、ADK の `McpToolset` が Tasks を扱う（adk-python #6826）
   - 受け入れ条件の案:
     - Tasks に対応したクライアントからの `run_command` が task として受け付けられ、60 秒を超えるコマンドの結果を `tasks/get` で受け取れる（検証: mcp-server の単体テスト）
     - DAK のエージェントから長いコマンドを実行すると、タイムアウトで終わらずに結果が返る（検証: 統合テスト）
     - Tasks に対応しないクライアントからは、今の `tools/call` のまま使える（検証: 既存のテスト）
