#!/bin/sh
# Security check before push / PR (#291). Skills call this one command.
#
#   scripts/security/check.sh                      # staged changes (default)
#   scripts/security/check.sh --range main..HEAD   # a range of commits
#   scripts/security/check.sh --no-checklist       # skip the list for reviewers
#
# Fails (exit 1) when the git hooks are not enabled, gitleaks is missing, or
# gitleaks finds a secret. Then prints what a reviewer (or LLM) must still look
# at by eye: the list in docs/security/review-checklist.md (its only source).
set -u

usage() { sed -n '2,11p' "$0" | sed 's/^# \{0,1\}//'; }

root=$(git rev-parse --show-toplevel) || exit 2
mode=staged
range=
checklist=1
while [ $# -gt 0 ]; do
  case "$1" in
    --staged) mode=staged ;;
    --range) mode=range; range=${2:-}; shift ;;
    --no-checklist) checklist=0 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "check.sh: unknown argument: $1" >&2; usage >&2; exit 2 ;;
  esac
  shift
done
if [ "$mode" = range ] && [ -z "$range" ]; then
  echo "check.sh: --range needs a revision range, e.g. main..HEAD" >&2
  exit 2
fi

fail=0

hooks=$(git -C "$root" config core.hooksPath || true)
hooks_dir=${hooks%/}
hooks_dir=${hooks_dir#./}
case "$hooks_dir" in
  /*) ;;
  ?*) hooks_dir="$root/$hooks_dir" ;;
esac
if [ -n "$hooks" ] && [ "${hooks_dir##*/}" = ".githooks" ] && [ -f "$hooks_dir/pre-commit" ]; then
  echo "OK  git hooks are enabled (core.hooksPath=$hooks)"
else
  echo "NG  git hooks are not enabled (core.hooksPath=${hooks:-unset})."
  echo "    Run: scripts/setup/install_hooks.sh"
  fail=1
fi

range_ok=1
if [ "$mode" = range ]; then
  # Only revisions, --not and --remotes[=<name>] (what pre-push passes for a new
  # branch): no other git log options. And git must resolve it: gitleaks scans
  # nothing, and says "no leaks found", for a range git cannot resolve.
  set -f
  for token in $range; do
    case "$token" in
      --not|--remotes|--remotes=*) ;;
      -*) range_ok=0 ;;
    esac
  done
  # shellcheck disable=SC2086
  if [ "$range_ok" = 1 ] && ! git -C "$root" rev-list --quiet $range -- >/dev/null 2>&1; then
    range_ok=0
  fi
  set +f
  if [ "$range_ok" = 0 ]; then
    echo "NG  the range \"$range\" is not a revision range git can resolve (fetch first, or check the names)."
    fail=1
  fi
fi

if ! command -v gitleaks >/dev/null 2>&1; then
  echo "NG  gitleaks is not installed."
  echo "    Install: brew install gitleaks (other OS: https://github.com/gitleaks/gitleaks#installing)"
  fail=1
elif [ "$range_ok" = 1 ]; then
  if [ "$mode" = staged ]; then
    what="staged changes"
    set -- git --pre-commit --staged
  else
    what="commits $range"
    set -- git "--log-opts=$range"
  fi
  if gitleaks "$@" --config "$root/.gitleaks.toml" --gitleaks-ignore-path "$root/.gitleaksignore" \
      --redact --no-banner "$root"; then
    echo "OK  gitleaks found no secrets in $what"
  else
    echo "NG  gitleaks found secrets in $what (see above). Remove them; if a key was ever pushed, revoke it."
    fail=1
  fi
fi

if [ "$checklist" = 1 ]; then
  items=$(awk '/^## LLM が見る項目$/ {on=1; next} on && /^#/ {exit} on && /^- / {print}' \
    "$root/docs/security/review-checklist.md" 2>/dev/null)
  echo
  if [ -n "$items" ]; then
    echo "Also check by eye (docs/security/review-checklist.md):"
    echo "$items"
  else
    echo "NG  no review items found under \"## LLM が見る項目\" in docs/security/review-checklist.md."
    fail=1
  fi
fi

exit "$fail"
