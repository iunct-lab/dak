#!/bin/sh
# Enable this repository's git hooks on a fresh clone (#291). Run once per clone:
#
#   scripts/setup/install_hooks.sh
#
# Sets core.hooksPath to .githooks (pre-commit: staged changes; pre-push: the
# commits being pushed; both scanned by gitleaks) and checks gitleaks is there.
set -u

root=$(git rev-parse --show-toplevel) || exit 2
cd "$root" || exit 2

if ! git config core.hooksPath .githooks; then
  echo "NG  could not set core.hooksPath" >&2
  exit 1
fi
for hook in .githooks/*; do
  [ -f "$hook" ] && chmod +x "$hook"
done

if ! command -v gitleaks >/dev/null 2>&1; then
  echo "NG  gitleaks is not installed; the hooks will refuse to commit and push until it is."
  echo "    Install: brew install gitleaks (other OS: https://github.com/gitleaks/gitleaks#installing)"
  exit 1
fi

echo "OK  core.hooksPath=.githooks, gitleaks $(gitleaks version 2>/dev/null)"
echo "    Enabled hooks: $(cd .githooks && ls | tr '\n' ' ')"
echo "    Before a push or PR, skills run: scripts/security/check.sh"
