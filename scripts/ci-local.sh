#!/usr/bin/env bash
# Run the checks of .github/workflows/ci.yml on this machine: the hook tests of
# both copies, the pytest tests of the skill scripts in both copies, shellcheck
# over the hooks, their tests, the skill shell scripts and the repository
# scripts, and the en/zh parity check. Every check runs even after one fails,
# and the script exits non-zero if any did.
#
# CI runs the hook tests on Ubuntu and on macOS's system bash 3.2; this script
# covers only the operating system it is run on and the bash that runs it, so
# on a Mac `/bin/bash scripts/ci-local.sh` matches the bash CI uses there.
#
# Run from anywhere: bash scripts/ci-local.sh
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT" || exit 2
# The hook tests start each hook with `bash` from PATH; putting the bash that runs
# this script first makes the hooks run under it too.
PATH="$(dirname "$BASH"):$PATH"
export PATH
status=0

for t in en/hooks/tests/*.test.sh zh/hooks/tests/*.test.sh; do
  if out="$("$BASH" "$t" 2>&1)"; then
    echo "ok    $t"
  else
    echo "FAIL  $t"
    printf '%s\n' "$out" | tail -n 20
    status=1
  fi
done

# Each copy runs in its own pytest process: the two copies hold test modules of
# the same name, which one process cannot import side by side. The cache
# provider and bytecode writing are off so the run leaves no files behind.
if ! python3 -m pytest --version >/dev/null 2>&1; then
  echo "FAIL  pytest is not installed"
  status=1
else
  for d in en/skills/*/scripts zh/skills/*/scripts; do
    ls "$d"/test_*.py >/dev/null 2>&1 || continue
    if out="$(PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q -p no:cacheprovider "$d" 2>&1)"; then
      echo "ok    pytest $d"
    else
      echo "FAIL  pytest $d"
      printf '%s\n' "$out" | tail -n 20
      status=1
    fi
  done
fi

if ! command -v shellcheck >/dev/null 2>&1; then
  echo "FAIL  shellcheck is not installed"
  status=1
elif shellcheck --severity=warning \
    scripts/*.sh en/hooks/*.sh zh/hooks/*.sh \
    en/hooks/tests/*.sh zh/hooks/tests/*.sh \
    en/skills/*/scripts/*.sh zh/skills/*/scripts/*.sh; then
  echo "ok    shellcheck"
else
  echo "FAIL  shellcheck"
  status=1
fi

if "$BASH" scripts/check-parity.sh; then
  echo "ok    parity"
else
  echo "FAIL  parity"
  status=1
fi

if "$BASH" scripts/check-public.sh; then
  echo "ok    public"
else
  echo "FAIL  public"
  status=1
fi

exit "$status"
