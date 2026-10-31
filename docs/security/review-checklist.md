# セキュリティの確認項目（push 前・PR レビュー）

このリポジトリは公開されている。push した時点で、内容は誰でも読める。
鍵や非公開の情報は、公開される前に多段で止める。この文書は、その中で人と LLM が目で見る項目の、唯一の出どころにする。

## 段

| 段 | いつ | 何を止めるか |
|---|---|---|
| pre-commit（`.githooks/pre-commit`） | コミットのとき | ステージした差分の鍵（gitleaks） |
| pre-push（`.githooks/pre-push`） | push の手前 | push するコミットの鍵（gitleaks。`git commit --no-verify` で作ったコミットも。`git push --no-verify` や、フックを有効にしていない clone では飛ばされる） |
| 検査の入口（`scripts/security/check.sh`） | スキルが push 前・PR 前に呼ぶ | フックの有効化、指定範囲の gitleaks、この文書の項目の一覧 |
| CI の `secrets` ジョブ | push の後 | 全履歴の鍵（公開された後の検出。失効の合図） |
| GitHub の secret scanning / push protection | push のとき | 既知の形式の鍵 |
| レビュー（人と LLM） | PR | 下の項目（パターンでは捕まらないもの） |

gitleaks のルールは `.gitleaks.toml` にある。標準で検出されない鍵の形式は、そこにルールを足す。
clone したら、まず `scripts/setup/install_hooks.sh` でフックを有効にする。

## LLM が見る項目

<!-- 1 行に 1 項目（`- ` で始まる行）。scripts/security/check.sh がこの形で読んで出す。 -->

- 鍵・トークン・パスワードの値（gitleaks のルールに無い形式も。長いランダムな文字列、`key=` / `token:` の右辺）
- 鍵や認証情報を含む URL（`https://user:pass@...`、クエリの `?key=` / `?token=`）
- `.env`、認証情報のファイル、秘密鍵（`*.pem`、`id_*`）、クラウドの設定ファイルの混入
- 非公開のリポジトリ・プロジェクト・人の名前、社内の Issue 番号やチケットへの言及
- 利用者のユーザー名を含む絶対パス、ホスト名、社内の IP アドレス、メールアドレス
- スクラッチ・作業用のファイル（`/tmp` の写し、デバッグの出力、`*.orig`、`*.patch`）の混入
- ログ・フィクスチャ・スクリーンショットに残った実データ（セッション ID、利用者の入力、応答の中身）
- コメントやコミットメッセージに残った内部の情報（非公開の設計、他のリポジトリの内部構造）
- 検査を弱める変更（`.gitleaksignore` への追加、`.gitleaks.toml` の allowlist やルールの削除、`.githooks/` や CI の `secrets` ジョブの変更）。同じ差分に鍵があれば、どの段のスキャナーも通ってしまう
- バイナリや生成物の中の実データ（ノートブックの出力、DB のダンプ、画像）
