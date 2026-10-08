#!/usr/bin/env bash
# Check that no tracked Markdown file names a path on the author's machine.
#
# The eval write-ups publish summaries of runs on private work, so a home
# directory path such as /Users/<name>/ or ~/Documents/ in a .md file means
# local detail leaked into the public repository. Paths under ~/.claude are
# the install location the harness documents and are not matched. Private
# project names cannot be caught by a pattern and are left to review.
#
# Run from anywhere: bash scripts/check-public.sh
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

if git grep -nE '/Users/|/home/[a-z]|~/Documents' -- '*.md'; then
  echo "public: local paths found in the lines above" >&2
  exit 1
fi
echo "public: OK (no local paths in tracked Markdown)"
