# Eval スコアボード（継続テスト）

DAK の「実モデル」品質を継続的に測るための仕組み（要件6）。

## 2 つのテスト層

1. **決定論 golden replay**（PR CI, 高速, 実LLM不要）
   `tests/integration/golden/*.json` を fake-LLM で再生し、ツール呼び出しの回帰を検出。
   → `tests/integration/test_golden_replay.py`
   → 増やし方: `tests/integration/golden/README.md`

2. **実LLM スモーク**（小型 Ollama, 寛容アサーション, 手動）
   以前は `nightly-eval.yml` が夜間に回して pass-rate を `history.jsonl`（リリース `eval-history` の asset）に追記していた。#822 でやめたので、回帰の検知は `./scripts/smoke_local_llm.sh`（`DAK_SMOKE_REAL_LLM=1`）の手動実行。PR ゲートではなく傾向シグナル。

補助: 同じスモークを安価なクラウドモデルで手動実行することもできる
（`./scripts/smoke_cloud_llm.sh`、既定 `openai/gpt-5.6-luna`、1 回数セント程度）。
ローカルの GPU/メモリが塞がっている時や、プロバイダ採用前の品質確認に使う。
小型ローカル LLM の候補比較（`qwen3:14b` など）は [local-models.md](local-models.md)。
Bedrock のクラウドモデルで回すときの費用・頻度の比較（過去の調査。GitHub OIDC の経路と IAM ロールは #822 で消した）は [cloud-eval.md](cloud-eval.md)。

## history.jsonl

記録は git の外に持つ: リリース `eval-history`（版ではない固定のリリース）の asset `history.jsonl`。
以前は毎晩 nightly-eval（#822 でやめた。記録は 2026-10-17 で止まっている）が asset を落として 1 行足し、その全体の写しを実行の artifact `nightly-eval` に残してから asset を差し替える。
main への直接の push はルールセットに止められ、評価の結果は枝に含める内容でもないため（#517）。

```bash
gh release download eval-history -p history.jsonl          # 今の記録を落とす
```

1 行 1 実行の JSON Lines:

```json
{"date": "2026-10-02", "model": "llama3.1:8b", "total": 4, "passed": 3, "failed": 1, "skipped": 0, "pass_rate": 0.75, "provider": "ollama", "runner": "github-hosted", "profile": "", "small_model": "", "context": {"model_calls": 9, "overflow_calls": 0, "compactions": 1, "total_tokens": 41000, "overflow_rate": 0.0}}
```

- `provider`: どの経路で回したか（`ollama` / `bedrock`）。この項目の無い古い行は `ollama` とみなす
- `runner`: 実行環境（GitHub のランナーなら `github-hosted`）
- `profile`: エージェントに `DAK_HARNESS_PROFILE` で指定したハーネスプロファイル（`agent/profiles/<名前>.yaml`）。空は未指定で、モデル名に合う `pattern` のプロファイルが使われる（`qwen` を含むモデルなら `qwen-small`、ほかは `default`）。この項目の無い古い行は空とみなす。プロファイルあり/なしの比較は、同じ `model` で `DAK_HARNESS_PROFILE` を空と `<名前>` にして実LLMスモークを 2 回手動で回し、2 回の `pass_rate` を見比べる（プロファイルの効かない側を確実にしたいなら `default`。以前は `workflow_dispatch` の `-f profile=` で流していた。#822 でやめた）
- `small_model`: エージェントに `DAK_SMALL_MODEL` で指定した Meta-Agent（モード切替の設定を作る呼び出し）のモデル。空は未指定（メインのモデル）。この項目の無い古い行は空とみなす。Meta-Agent のモデルあり/なしの比較は、同じモデルで `./scripts/smoke_local_llm.sh` と `LOCAL_SMALL_OLLAMA_MODEL=<小さいモデル> ./scripts/smoke_local_llm.sh`（例 `qwen3:1.7b`。pull して `LOCAL_SMALL_MODEL_NAME=ollama_chat/<モデル>` でエージェントに渡す）の 2 回を手動で回し、2 回の `pass_rate` を見比べる。Meta-Agent を通るのはスモークの `test_mode_switch_runs_meta_agent` だけ（Meta-Agent が設定を返せないと fail）。行に残すなら、スクリプトは JUnit XML を書かないので `--keep` で残したスタックに `cd tests/integration && DAK_SMOKE_REAL_LLM=1 LOCAL_MODEL_NAME=ollama_chat/<モデル> DAK_SMALL_MODEL=ollama_chat/<小さいモデル> uv run pytest test_smoke_real_llm.py --junitxml=eval-report.xml` を流し（`LOCAL_MODEL_NAME` が無いと `test_minimal_overhead_matches_direct_call` が skip し、skip は `pass_rate` を下げる）、`dak-maint eval-record --junit <その XML> --history history.jsonl --model <モデル> --small-model <小さいモデル>`（`maintenance/` で実行）。なしの回は `DAK_SMALL_MODEL` と `--small-model` を外す。2 つのモデルが同時にメモリに載らない環境では、ありの回が読み込みの時間で遅くなる・時間切れになることがある（モデルの質ではなく読み込みの差）
- `vulnerabilities`: 5 つの `uv.lock`（`agent`・`mcp-server`・`bff`・`cli`・`integration`）を `uv audit`（preview）にかけた結果。lock ごとに `{"ids": [GHSA/CVE の ID], "error": null}`、audit できなかった lock は `ids` が空で `error` に理由。見るだけで、成否には使わない（nightly は #822 でやめた）。ID を渡さない経路（Bedrock のジョブ）と古い行は `{}` か欄なし
- `context`: 長いツールループの指標（PBI #93）。実 LLM スモークの `test_long_investigation_records_context_metrics` が同じセッションで数ターンのファイル調査を回し、`record_testsuite_property`（スイートは xunit2）で JUnit XML に残した `context_*` の property の和。`model_calls` はモデルの呼び出し（usage・エラー・ハーネスの `[CONTEXT_OVERFLOW]` の応答のどれかを持つイベント）、`overflow_calls` はそのうちエラーか `[CONTEXT_OVERFLOW]` で返った数、`overflow_rate` はその比（和から計算し直す）、`compactions` はセッションの圧縮のイベント（`actions.compaction`）の数、`total_tokens` は `usageMetadata.totalTokenCount` の和。残すには `--junitxml` を付けてスモークを流し、その XML を `eval-record` に渡す（`small_model` の項と同じ手順）。property の無い XML と古い行は `{}` か欄なし。決定論の側の窓超過の回帰（巨大なツール結果を 1 回の依頼で繰り返す）は fake-LLM の `tests/integration/test_context_harness_stress.py`

行は `dak-maint eval-record`（`maintenance/`）が JUnit XML から書く。経路ごとの今月の実行回数は
`dak-maint eval-budget --history <落とした history.jsonl> --provider <経路> --limit <回数>`（`maintenance/` で実行）が数え、上限に達していれば `allowed=false` と理由を出す。

差し替え（`gh release upload … --clobber`）は消してから上げるので、途中で失敗すると asset が消えることがある。
そのときは**差し替えに失敗したその実行**の artifact の写しから戻す（写しは差し替えの前に上がっていて、その晩の行まで入っている。写しが上がらなかった晩は差し替えないので、asset は前の晩のまま残る）:

```bash
gh run download <差し替えに失敗した実行の run-id> -n nightly-eval -D restore     # restore/eval-history/history.jsonl
gh release upload eval-history restore/eval-history/history.jsonl --clobber
```

pass_rate の推移を見て、モデル更新やプロンプト改善の効果を追跡する。

## 「使うほど育つ」ループ

```
実LLMスモークで新しい成功セッション
  └─ capture_golden.py で決定論 golden に凍結
       └─ （以前は capture-golden ワークフローが PR 提案。#822 でやめたので、今は手元で PR にする）
            └─ マージで PR CI の回帰スイートが増える
```
