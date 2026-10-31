# Anthropic Haiku 5.5

モデルは `anthropic/claude-haiku-5-5`（LiteLLM と定期保守の選択形式）。
Anthropic API へ送るモデル ID は `claude-haiku-5-5`。
キーは `.env`、一時ファイル、Docker の環境変数設定に保存しない。

## ホストの Parameter Store

AWS Systems Manager Parameter Store に `SecureString` として登録する
（例: `/example/anthropic-api-key`。名前は環境に合わせる。リージョンは `agent/ssm_exec.py` が `ap-northeast-1` に固定しているので、そのリージョンに登録する）。
他のツールの認証情報（OAuth トークンなど）は別なので流用しない。

読取ポリシーがパラメーター名を個別に列挙する構成では、ホストの読取ポリシーへ
次のリソースを追加する（AWS 管理の KMS 鍵を使う前提）。

```yaml
- !Sub 'arn:aws:ssm:${AWS::Region}:${AWS::AccountId}:parameter/example/anthropic-api-key'
```

必要な操作は `ssm:GetParameter`。独自の KMS 鍵で暗号化した場合は、その鍵への
復号権限も必要。Docker の実行プロセスがインスタンスロールへアクセスできる
構成を使い、AWS のアクセスキーをファイルやコンテナ設定へコピーしない。

```bash
COMPOSE_FILE=$(./scripts/compose_files.sh):docker-compose.anthropic.yml docker compose up -d --build agent
```

Compose に入るのはモデル名とパラメーター名だけ。`agent/entrypoint.sh` が
コンテナ内部で `ssm_exec.py` を実行し、取得した値をサーバープロセスの環境へ
渡す。Docker の作成時の設定には API キーを含めない。SSM のアクセス拒否・
通信エラー・空の値・SecureString 以外は起動失敗となり、自動再試行しない。
既存の `.env` は非秘密の設定だけに使う。

## GitHub の定期保守

定期の workflow は #822 でやめた（Actions の secret と変数も消した）。手元で `dak-maint` を回すときは、環境変数 `MAINT_LLM_*` で渡す。次の既定値を使う。

```bash
export MAINT_LLM_MODEL=anthropic/claude-haiku-5-5   # MAINT_LLM_API_KEY は環境から渡し、ファイルに書かない
```

`MAINT_LLM_BASE_URL` は設定しない。Bedrock 用の OIDC のロールは #822 で消した。
`dak-maint triage` はキーと Anthropic モデルがある場合に LLM 評価を選択する。

定期保守は native Messages API を使い、Haiku 5.5 が拒否する `temperature=0`
などの sampling パラメーターを送らない。thinking は本文と分け、拒否・打ち切り・
本文のない応答は失敗として扱う。HTTP の再送は行わない。

公式: [Haiku 5.5 移行ガイド](https://platform.claude.com/docs/en/models/haiku-5-5/migration-guide)。

設定後の最小通信確認（`verify-anthropic` workflow）は #822 でやめた。手元で `dak-maint` を回して確かめる。実通信には API 利用量が発生する。
