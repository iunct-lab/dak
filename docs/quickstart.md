# QuickStart — 立ち上げ & 機能別 E2E 確認シナリオ

このドキュメントは、スタックを立ち上げて **各機能を E2E で実際に確認する**ための手順集です。
UI（HTMX チャット）と CLI（`dak-cli`）の両方からの確認手順を、機能ごとに記載します。

> ここに載っているシナリオは、すべて実機（ローカル LLM `llama3.1:8b`）で動作確認済みです。
> UI は Playwright で、CLI は実コマンドで検証しています（自動テストは `tests/integration/test_bff_ui.py` /
> `tests/integration/test_smoke_real_llm.py`）。

---

## 1. 前提

- Docker / Docker Compose
- 以下のいずれかの LLM:
  - **API キー**（`GOOGLE_API_KEY` など）— 一番手軽
  - **ローカル LLM**（[Ollama](https://ollama.com)）— API キー不要・無料。本書のデフォルト
- （UI を Playwright で自動確認する場合のみ）`tests/integration` で `uv run playwright install chromium`

---

## 2. 立ち上げ

機能（Enforcer / AP2 / 通常）を**同時に**確認したいので、3 つのエージェント構成を一度に立ち上げる
統合スタックを使うのが最短です。

### パターン A: ローカル LLM（API キー不要）— 推奨

```bash
ollama pull llama3.1:8b   # 一度だけ（~4.9GB、16GB RAM で動作）
echo "POSTGRES_PASSWORD=$(openssl rand -hex 32)" >> .env   # 一度だけ。必須（無いと compose が止まる）

# agent(:8000) / enforcer(:8010) / ap2(:8011) / bff(:8002) / mcp(:8001) / postgres を一括起動
LOCAL_MODEL_NAME=ollama_chat/llama3.1:8b \
  COMPOSE_FILE=$(./scripts/compose_files.sh test):docker-compose.local-llm.yml \
  docker compose up -d --build --wait
```

> モデル選択は「ツールコールの確実性」が重要です。`llama3.1:8b` は多数ツール提示時も**構造化**
> ツールコールを返します。Qwen3.5 は生 JSON テキストで返して ReAct ループが壊れ、qwen3:8b は
> `<think>` で 120 秒/ターンのタイムアウトを超えるため不可（詳細は README / `docker-compose.local-llm.yml`）。

### パターン B: API キー

```bash
cat env.example.d/*.env > .env   # GOOGLE_API_KEY などを記入。MODEL_NAME は任意（未設定なら組み込みの既定モデル）
echo "POSTGRES_PASSWORD=$(openssl rand -hex 32)" >> .env   # 必須（無いと compose が止まる）
COMPOSE_FILE=$(./scripts/compose_files.sh test) docker compose up -d --build --wait
```

### 起動エンドポイント

| URL | 役割 |
| :-- | :-- |
| http://localhost:8002 | **UI**（HTMX チャット、通常エージェント） |
| http://localhost:8000 | 通常エージェント（ADK REST `/run` 等） |
| http://localhost:8010 | Enforcer モード有効エージェント |
| http://localhost:8011 | AP2 決済有効エージェント（Solana モック） |
| http://localhost:8001 | MCP サーバ |

CLI は `DAK_AGENT_URL` で接続先を切り替えます。初回のみログイン設定:

```bash
cd cli
uv run dak-cli login --username you --agent-url http://localhost:8000
```

---

## 3. 機能別 E2E シナリオ

### 3.1 基本チャット

確認内容: エージェントが起動し、自然言語で応答する。

**UI**: http://localhost:8002 を開き、`Hello, who are you?` と入力して Send。
→ アシスタントの吹き出しに応答が表示される。

**CLI**:
```bash
DAK_AGENT_URL=http://localhost:8000 uv run dak-cli run "Reply with a short one-sentence greeting."
```
→ `Agent Response` パネルに一文の挨拶。

---

### 3.2 スキル探索 + ファイル操作（MCP ツール）

確認内容: `list_skills` でスキルを発見 →`enable_skill` で有効化 → MCP の `read_file` でファイル読込。
ツールが実際に呼ばれていることを UI の「Thinking Process」パネルで確認できる。

**UI**:
1. `Use the list_skills tool to show your available skills. Do not answer from memory.` を送信。
   → 応答に **Thinking Process (N steps)** の折りたたみが付く。クリックで展開すると
   `Action: Called list_skills` が見える。
2. `Enable the 'filesystem' skill, then read the file 'README.md' and tell me its first heading.` を送信。
   → Thinking に `enable_skill` / `read_file` の Action が並び、本文に
   `Decentralized Agent Kit`（README の見出し）が現れる。

**CLI**:
```bash
DAK_AGENT_URL=http://localhost:8000 uv run dak-cli run "Use list_skills to show your skills."
```
→ solana_wallet / filesystem / read_file … が一覧表示される（実際の tool 応答由来）。

---

### 3.3 Enforcer モード（ツール使用の強制 / Ulysses Pact）

確認内容: Enforcer モードでは素のテキスト応答が禁止され、必ずツール経由になる。
最終回答は `attempt_answer` ツールで返る。

**CLI**（Enforcer エージェント `:8010`）:
```bash
DAK_AGENT_URL=http://localhost:8010 uv run dak-cli run "What is 2 plus 2? Give me the final answer."
```
→ `Answer (Confidence: high): 4 / Sources: mathematics`（= `attempt_answer` 経由）。
素のテキストは出ず、ブロックされた場合 CLI は自動でツール使用を促してリトライする。

> 詳細な仕組みは [enforcer_mode.md](enforcer_mode.md) を参照。

---

### 3.4 AP2 決済フロー（Solana モックウォレット）

確認内容: 有料ツールが `Payment Required` を返し、エージェントがモックウォレットで支払って再試行する。
`SOLANA_USE_MOCK=true`（既定）なので実際の資金は動かない（残高 1000 SOL、tx は `MockTx_...`）。

**CLI**（AP2 エージェント `:8011`）:
```bash
# 1) 有料スキルを有効化して呼ぶ → Payment Required が観測される
DAK_AGENT_URL=http://localhost:8011 uv run dak-cli run \
  "Enable the 'premium_service' skill, then call perform_premium_analysis with topic='AI'."

# 2) 支払いを許可 → 残高確認 → 送金（モック）→ 再試行
DAK_AGENT_URL=http://localhost:8011 uv run dak-cli run \
  "You may pay. Check balance with check_solana_balance, pay with send_sol_payment, then retry."
```
→ 最終的に分析結果が返る。Thinking に `check_solana_balance` / `send_sol_payment` が現れる。

---

### 3.5 動的モード切替 / A2A（参考）

- **モード切替**: `switch_mode` ツールでタスクに応じてツール/プロンプトを再構成。
  詳細は [dynamic_mode_switching.md](dynamic_mode_switching.md)。
- **A2A（Agent-to-Agent）**: `docker-compose.demo.yml` の consumer/provider 構成で、
  `transfer_to_agent` により別エージェントへ委譲。詳細は [test_matrix.md](test_matrix.md)。

---

## 4. 自動テストで一括確認する

手動シナリオに対応する自動テストが揃っています（[test_matrix.md](test_matrix.md) も参照）。

```bash
# ユニット（ネットワーク/LLM 不要）
cd agent && uv run pytest            # cli / mcp-server / bff も同様

# Fake-LLM 統合（決定的・API キー不要・CI と同じ）
COMPOSE_FILE=$(./scripts/compose_files.sh test) docker compose up -d --build --wait
(cd tests/integration && uv run pytest)
COMPOSE_FILE=$(./scripts/compose_files.sh test) docker compose down -v   # -v は DB などのボリュームを消す。開発中のデータとは別のスタックで使う

# 実モデル スモーク（ローカル LLM・API キー不要）: 上記のローカル LLM スタック起動後
cd tests/integration
DAK_SMOKE_REAL_LLM=1 uv run pytest test_smoke_real_llm.py      # 基本/スキル/Enforcer/AP2
DAK_SMOKE_REAL_LLM=1 uv run pytest test_bff_ui.py              # UI（Playwright/Chromium）
```

UI E2E（`test_bff_ui.py`）は実ブラウザ（Chromium）でチャット送信・DOM 検証・スクリーンショット取得を行います
（スクショは `tests/integration/artifacts/` に出力）。

---

## 5. 後片付け

```bash
COMPOSE_FILE=$(./scripts/compose_files.sh test):docker-compose.local-llm.yml docker compose down -v   # -v は DB などのボリュームを消す（上と同じ注意）
```
