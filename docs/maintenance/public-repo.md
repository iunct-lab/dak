# 公開リポジトリ（Private から main のツリーだけを送る）

PBI #822（要望 #821）。開発用のリポジトリを Private にし、公開は別のリポジトリに新しい履歴で main のツリーだけを送る。

- 開発は Private の開発用リポジトリ（以下 `<private>`）。Issue・Project・PR・レビュー・リリースタグは全部ここ
- 公開は `iunct-lab/dak`（以下 `<public>`）。Private の main の**ツリー**だけを受け取り、Private のコミットは 1 つも入らない
- 送るのは `ops-kit public-sync`（共通キットの `bin/ops-kit`。公開先は `ops.config.json` の `publicSync.target`）
- 公開する前に 1 回、共通キットのスキル `public-release-gate`（2 ランナーの網羅チェック）を通す（#828）

## 仕組み

仕組みそのもの（ツリーだけを送る、初回と 2 回目、`--adopted`、ホームパスとメールアドレスの検査、`--dry-run`、公開側の 1 式）は共通キットの `ops-kit/README.md` の「公開リポジトリへの同期」（Private の名前の検査はキットの `public-sync.ts`）。ここにはこのリポジトリの値だけを置く。`<private>` の名前は追跡するファイルに書かない（公開に出すツリーに入ると同期が止まる。名前は PBI #822 の決定ログ）。

`ops.config.json` の `publicSync`:

| 設定 | ファイル | 理由 |
|---|---|---|
| `exclude` | `.claude/settings.json` | 開発者のローカルのエージェントの許可リスト（依存導入・テスト実行・compose 操作の包括的な承認）。公開側は PR を受けず、読者に勧める設定ではない（フェーズゲート #828 の指摘）。Private-only |
| `exclude` | `.github/CODEOWNERS` | 保守者の GitHub アカウント名を公開側に載せない（利用者の判断 2026-10-22。フェーズゲート #828 で codex が high、claude が low と分かれた）。公開側は PR を受けないので機能も使わない。`docs/CHARTER.md` のレビュー必須は Private 側だけで効く |
| （対応済み） | `ops.config.json` の `projectUrl` | 非公開の Project の URL を追跡するファイルから外し、変数 `DAK_PROJECT_URL` から読む（#931、フェーズゲート #828 の指摘） |
| `rewrite` | なし | 公開に出すツリーに `<private>` の名前は無い（dry-run の検査が通る）。`SECURITY.md` と Issue テンプレはキットの 1 式が入る |

## 回し方

1. Private の main の作業ツリーでなく、`git fetch origin && D=$(mktemp -d)/pub-src && git worktree add --detach "$D" origin/main && cd "$D"` の上で `ops-kit public-sync --dry-run` を回し、送るツリーを見る（キットは設定を今のディレクトリから上へ探し、ツリーは `origin/main` から作るので、設定も main と揃える）。終わったら `git worktree remove "$D"`
2. 改名（#829）の前は、今のリポジトリが公開先と同じ名前なので、改名後の `<private>` の owner/name と空の公開先を渡して回す（何も送らない）:
   ```bash
   B=$(mktemp -d)/pub.git; git init -q --bare "$B"
   GH_REPO=<private の owner/name> ops-kit public-sync --dry-run --target-url "$B"
   ```
   改名の後は、clone ごとに `origin` を（worktree は clone の設定を共有する） `git remote set-url origin <private の URL>` で新しい名前に直し（キットは Private の名前を `GH_REPO`、無ければ `origin` から読む。古い URL のままだと公開先と同じ名前になって止まり、公開リポジトリを作った後は古い URL が公開側を指す）、`GH_REPO` も `--target-url` も付けない
3. 初回（#830）は、空の `<public>` の main へ根のコミットを**直接 push する**（PR は出ない）。dry-run の `with tree <sha>` を確かめてから送る
4. 2 回目からは `ops-kit public-sync` が `sync/<sha>` の PR を出すので、`<public>` の CI を見る。赤なら、その同期の PR を閉じてから Private で直して同期をやり直す（開いたままだと「sync PR #n is still open」で止まる）
5. 同期の PR は `<public>` で **Rebase and merge** でマージする（次の同期が本文の `Private-Main:` で前回を見つけるため）

## 公開側で動く workflow

Private では何も動かさない。`<public>` で動くのは:

| workflow | 役目 |
|---|---|
| `ci.yml` | 同期の PR のテスト（secrets を使わない。Private 側の PR はこのファイルを `local-ci.ts` で回す） |
| `labels.yml` | `.github/labels.yml` のラベルの同期 |
| `close-pull-requests.yml` | キットの 1 式。メンバーと `sync/*` 以外の PR を方針の返信つきで閉じる |

## 公開側で受けるもの

- 要望（不具合も要望の形）: `<public>` の Issue の Request テンプレだけ。受けたら `request-to-backlog` の「公開側の Issue から」で Private の要望 Issue にする。公開側に Private の番号・内部の情報を書かない
- 脆弱性: `SECURITY.md` の案内の Security Advisory
- 質問: Discussions
- Pull Request: 受け付けない（上の `close-pull-requests.yml`）

## 公開する日

改名（#829）と公開（#830）は、利用者の合図があってから同じ日に進める予定だった。手順は各 Task の本文。

- 2026-10-22: 改名と Private 化（#829）
  - 公開前ゲートの合格より前に切り替わった（誰の操作かの記録は無い）。公開（#830）は同じ日にならず、ゲートの合格を待つ
  - 切り替えた後の数: open の Issue 89・Project の項目 745・リリース 211・PR 370（全状態）
  - 前の数は取っていない（記録の前に切り替わっていた）。今のデータを作成・クローズの日時で 11:20 UTC（最後に Actions が動いた push）に戻すと Issue 89・項目 745・リリース 211・PR 369 で、差は切り替えの後に出した #960 だけ。ただし今のデータから出した数なので、切り替えで消えたものがあっても見つけられない
  - 以後、Private 側の Actions はジョブのステップ 0 件で失敗する（#960 で確かめた）
- 2026-10-31: 公開（#830）。Private で作って同期してから、利用者の指示で Public にした
  - 公開前ゲートは 1 ランナー（tree `54ab9dc`。verdict pass、high 0 件、振り分け前）だけ通し、もう 1 ランナーは利用者の判断で公開の後に回す（#1023）。今の公開 tree `a56edc5` は `54ab9dc` からテスト 1 行だけ違い、ゲートはまだ通していない
  - 初回は tree `54ab9dc` を main へ直接 push。CI の `scripts` の 1 件が `exclude` のファイルの存在確認で落ちたので #1024 で直し、2 回目の同期（tree `a56edc5`）で `integration` まで成功した
  - 公開側: Discussions と脆弱性の非公開報告は有効（後者は Public にした後でないと有効にできない）、merge は Rebase and merge だけ、secrets は 0 件、起票された Issue は 0 件
  - 公開側の CI のログ（main の push の実行）に、開発用の名前・ホームパス・認証に使える値の形は無かった（`git grep` 相当の文字列の検索と `ops-kit scan-text`）
  - 旧名 `iunct-lab/Decentralized-Agent-Kit` は 404。旧 URL の参照は公開側のツリー（Issue テンプレはキットの 1 式に置き換わる）、手元の記事のリポジトリ、PyPI の同名のパッケージに無い。ほかの外部の参照は調べていない
