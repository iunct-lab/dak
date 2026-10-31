#!/usr/bin/env bash
# The compose files of the stack, ":"-joined for COMPOSE_FILE (docs/test_matrix.md).
#
#   COMPOSE_FILE=$(./scripts/compose_files.sh test) docker compose up -d --build --wait
#
# No argument: docker-compose.yml, then compose/base/*.yml.
# test:        those, then docker-compose.test.yml, then compose/test/*.yml.
# A feature adds its services and its agent environment as one new file in
# compose/test/ (compose/base/ for the default stack); no listed file changes.
# Files in a directory come in name order (LC_ALL=C). An optional overlay
# (docker-compose.local-llm.yml, ...) goes after the output: "$(...):<file>".
set -euo pipefail

root="$(cd "$(dirname "$0")/.." && pwd)"

case "${1-}" in
    "") dirs=(base) ;;
    test) dirs=(base test) ;;
    *)
        echo "usage: $0 [test]" >&2
        exit 2
        ;;
esac
[ "$#" -le 1 ] || { echo "usage: $0 [test]" >&2; exit 2; }

files=()
for d in "${dirs[@]}"; do
    if [ "$d" = base ]; then
        files+=("$root/docker-compose.yml")
    else
        files+=("$root/docker-compose.$d.yml")
    fi
    while IFS= read -r f; do
        files+=("$f")
    done < <(LC_ALL=C find "$root/compose/$d" -maxdepth 1 -type f -name '*.yml' 2>/dev/null | LC_ALL=C sort)
done

(IFS=:; echo "${files[*]}")
