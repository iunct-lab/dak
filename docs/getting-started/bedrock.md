# Amazon Bedrock で Claude / GPT を使う

DAK のモデル指定は LiteLLM 形式（`MODEL_NAME` 環境変数）なので、Bedrock 上のモデルは
`bedrock/` プレフィックスを付けるだけで利用できる。エージェント側のコード変更は不要。

```bash
# .env
MODEL_NAME=bedrock/us.anthropic.claude-haiku-4-5-20251001-v1:0
AWS_REGION_NAME=us-east-1
AWS_BEARER_TOKEN_BEDROCK=...   # 認証方式は下記参照
```

```bash
export COMPOSE_FILE=$(./scripts/compose_files.sh)   # Bedrock の受け渡しは compose/base/bedrock.yml
docker compose up -d --build
# 動作確認は BFF (http://localhost:8002) か dak-cli で
```

## モデル ID（2026-08 時点）

Bedrock の新しめの Claude はリージョン単発 ID ではなく **inference profile**
（`us.` / `global.` プレフィックス）経由での呼び出しが基本。

| モデル | `MODEL_NAME` | 参考価格 (in/out per 1M tok) |
|--------|--------------|------------------------------|
| Claude Haiku 4.5 | `bedrock/us.anthropic.claude-haiku-4-5-20251001-v1:0` | $1.00 / $5.00 |
| Claude Sonnet 5 | `bedrock/us.anthropic.claude-sonnet-5` ※ | 1P と同等 |
| GPT-OSS 20B (open-weight) | `bedrock/converse/openai.gpt-oss-20b-1:0` | ~$0.07 / $0.20 |
| GPT-OSS 120B (open-weight) | `bedrock/converse/openai.gpt-oss-120b-1:0` | ~$0.15 / $0.60 |
| GPT-5.6 Luna | `bedrock/us.openai.gpt-5.6-luna` ※ | $0.20 / $1.20 (Global CRIS) |

※ 印は LiteLLM 経由での呼び出し形式が未検証（Bedrock 側の提供は確認済み）。
動かない場合は `bedrock/converse/<id>` 形式を試すか、Issue を参照。
なお GPT を使うだけなら OpenAI 直（`MODEL_NAME=openai/gpt-5.6-luna` +
`OPENAI_API_KEY`）が最も単純で、Bedrock 経由は「AWS 側で課金/ガバナンスを
一元化したい」場合の選択肢。

## 認証: API キーかセッション（SigV4）か

LiteLLM は両方をサポートする。使い分けの指針:

| 方式 | 環境変数 | 向いている場面 | 注意点 |
|------|----------|----------------|--------|
| **Bedrock API キー**（bearer） | `AWS_BEARER_TOKEN_BEDROCK` | ローカル開発・コンテナに env で渡すだけの手軽さ | 長期キーは IAM ユーザー紐付き（最大2本、Bedrock 限定スコープ）。漏洩時のリスクは SigV4 より高いので本番非推奨 |
| **標準 AWS 認証（SigV4）** | `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` / `AWS_SESSION_TOKEN` | 本番・CI。AWS 推奨のデフォルト | コンテナには `~/.aws` が無いので `AWS_PROFILE` は効かない。named profile（SSO・静的いずれも）は `aws configure export-credentials --format env` で環境変数化してから compose up |

**このリポジトリでの推奨**: ローカル開発は Bedrock API キー（短期発行を優先）、
CI で使う場合は GitHub OIDC → STS の一時クレデンシャル（SigV4）。

```bash
# SSO ユーザーの例
aws sso login --profile dev
eval "$(aws configure export-credentials --profile dev --format env)"
export AWS_REGION_NAME=us-east-1
export COMPOSE_FILE=$(./scripts/compose_files.sh)   # export した AWS_* は compose/base/bedrock.yml を通って agent に届く
MODEL_NAME=bedrock/us.anthropic.claude-haiku-4-5-20251001-v1:0 docker compose up -d
```

## コンテキストウィンドウ

コンテキストハーネス（`docs/architecture/harness_engineering.md`）はモデルのコンテキスト長から
圧縮閾値（既定 60%）やツール出力上限を算出する。コンテキスト長は litellm のモデルマップ（`litellm.get_model_info`）から
自動解決されるので、Bedrock の inference-profile ID もそのまま実際の値になる。
マップに無いモデルは保守的に 128K 扱いになるだけで、動作は壊れない
（`agent/dak_agent/mode_manager.py`）。

## 実LLMスモークを Bedrock で回す

```bash
CLOUD_MODEL_NAME=bedrock/us.anthropic.claude-haiku-4-5-20251001-v1:0 \
  ./scripts/smoke_cloud_llm.sh
```

（クラウドモデルでのスモーク実行の詳細は `scripts/smoke_cloud_llm.sh` を参照。）
