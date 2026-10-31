<!-- タイトルは Conventional Commits 風に: feat:/fix:/test:/docs:/chore: など -->

## 概要 / Summary

<!-- 何を、なぜ変えたか。関連Issueがあれば `Closes #123` -->

## 影響コンポーネント / Affected components

- [ ] agent
- [ ] mcp-server
- [ ] bff
- [ ] cli
- [ ] tests/integration
- [ ] docs / infra (.github, docker-compose, scripts)

## テスト観点 / Testing

<!-- どう検証したか。該当するものにチェック -->

- [ ] 該当コンポーネントの `uv run pytest -q` が green
- [ ] `COMPOSE_FILE=$(./scripts/compose_files.sh test) docker compose` の統合テストが green（該当時）
- [ ] 実LLMスモーク `DAK_SMOKE_REAL_LLM=1`（該当時／任意）
- [ ] 新規/変更挙動に対するテストを追加した

## チェックリスト / Checklist

- [ ] 「System enables, Agent decides」の原則を壊していない（暗黙の副作用を追加していない）
- [ ] ドキュメント（docs/, README, AGENTS.md）を必要に応じ更新した
- [ ] 破壊的変更がある場合は概要に明記した
