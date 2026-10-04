#!/usr/bin/env bash
# Put a freshly generated handoff in place: <dir>/HANDOFF.new.md becomes <dir>/HANDOFF.md,
# and any previous HANDOFF.md moves to <dir>/.handoff-archive/HANDOFF.<UTC stamp>[-N].md.
# Usage: bash finalize.sh <dir>
# Exit 1 when HANDOFF.new.md is missing or empty; prints the absolute path of HANDOFF.md.
set -euo pipefail

if [ "$#" -ne 1 ]; then
  echo "用法：bash finalize.sh <dir>" >&2
  exit 1
fi

dir=$(cd "$1" && pwd -P)
new="$dir/HANDOFF.new.md"
cur="$dir/HANDOFF.md"

if [ ! -s "$new" ]; then
  echo "没有可落位的交接：$new 不存在或为空" >&2
  exit 1
fi

if [ -e "$cur" ]; then
  arc="$dir/.handoff-archive"
  mkdir -p "$arc"
  stamp=$(date -u +%Y%m%dT%H%M%SZ)
  dest="$arc/HANDOFF.$stamp.md"
  n=2
  while [ -e "$dest" ]; do
    dest="$arc/HANDOFF.$stamp-$n.md"
    n=$((n + 1))
  done
  mv "$cur" "$dest"
fi

mv "$new" "$cur"
printf '%s\n' "$cur"
