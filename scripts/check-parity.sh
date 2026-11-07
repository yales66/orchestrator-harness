#!/usr/bin/env bash
# Check that en/ and zh/ stay two complete copies of the same harness.
#
# 1. Both folders hold the same relative file paths. The one allowed
#    difference is zh/README.md: the English README is the repository root
#    README.md, so en/ has no README of its own.
# 2. Every file under hooks/ (scripts and their tests), agents/ and
#    skills/*/scripts/ (helper scripts a skill runs, and their tests) is
#    byte-identical in the two copies, because the README states that the hook
#    and skill scripts are identical.
# 3. settings.example.json registers the same hooks in both copies. The one
#    allowed difference is the REPLY_LANG=zh prefix on zh/'s reply-gate and
#    keepalive commands, which switches on the gate's reply-language check and
#    the keepalive's Chinese stop word 「完」 for a Chinese install; with that
#    prefix removed the two files are byte-identical.
#
# Run from anywhere: bash scripts/check-parity.sh
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ONLY_IN_ZH="README.md"
status=0

# list <lang>: relative paths of the files in that copy. Tracked files are used
# inside a git checkout so that local clutter such as .DS_Store does not count.
list() {
  if git -C "$ROOT" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    git -C "$ROOT" ls-files -- "$1" | sed "s|^$1/||"
  else
    (cd "$ROOT/$1" && find . -type f ! -name .DS_Store | sed 's|^\./||')
  fi | LC_ALL=C sort
}

en_files="$(list en)"
zh_files="$(list zh | grep -vxF "$ONLY_IN_ZH" || true)"

if [ -z "$en_files" ]; then
  echo "parity: no files found under en/" >&2
  exit 1
fi

if [ "$en_files" != "$zh_files" ]; then
  echo "parity: file lists differ (< only in en/, > only in zh/):"
  diff <(printf '%s\n' "$en_files") <(printf '%s\n' "$zh_files") | grep '^[<>]' || true
  status=1
fi

identical="$(printf '%s\n' "$en_files" | grep -E '^hooks/|^agents/|^skills/[^/]+/scripts/' || true)"
checked=0
while IFS= read -r rel; do
  [ -n "$rel" ] || continue
  [ -f "$ROOT/zh/$rel" ] || continue   # already reported as a list difference
  checked=$((checked+1))
  if ! cmp -s "$ROOT/en/$rel" "$ROOT/zh/$rel"; then
    echo "parity: en/$rel and zh/$rel differ"
    status=1
  fi
done <<< "$identical"

SETTINGS="settings.example.json"
if [ -f "$ROOT/en/$SETTINGS" ] && [ -f "$ROOT/zh/$SETTINGS" ]; then
  checked=$((checked+1))
  if ! sed 's/REPLY_LANG=zh //g' "$ROOT/zh/$SETTINGS" | cmp -s "$ROOT/en/$SETTINGS" -; then
    echo "parity: en/$SETTINGS and zh/$SETTINGS differ beyond the REPLY_LANG=zh prefix"
    status=1
  fi
fi

# Claude Code persists a single hook's SessionStart additionalContext longer
# than 10,000 characters (JavaScript string length) and hands the model only a
# 2KB preview; the limit applies to each hook separately. settings.example.json
# therefore registers the playbook hook once per part (--part 1, 2, ...), and
# the hook cuts the playbook into parts of at most 9,500 characters. Check that
# every part is within that size and that the playbook needs no more parts than
# the settings register, since a part past the last registered one never
# reaches the main thread.
MAX_CHARS="${PLAYBOOK_PART_MAX_CHARS:-9500}"
export PLAYBOOK_PART_DELAY=0
for lang in en zh; do
  hook="$ROOT/$lang/hooks/orchestrator-playbook-session-start.sh"
  settings="$ROOT/$lang/$SETTINGS"
  [ -f "$hook" ] && [ -f "$settings" ] || continue
  registered="$(grep -c 'orchestrator-playbook-session-start.sh --part' "$settings" || true)"
  if ! msg="$(python3 - "$hook" "$registered" "$MAX_CHARS" 2>&1 <<'PY'
import json, subprocess, sys
hook, registered, cap = sys.argv[1], int(sys.argv[2]), int(sys.argv[3])
def part(i):
    out = subprocess.run(["bash", hook, "--part", str(i)], capture_output=True, text=True, check=True).stdout
    return json.loads(out)["hookSpecificOutput"]["additionalContext"] if out.strip() else None
for i in range(1, registered + 1):
    ctx = part(i)
    if ctx is not None and len(ctx.encode("utf-16-le")) // 2 > cap:
        sys.exit("part %d is %d characters, over %d" % (i, len(ctx.encode("utf-16-le")) // 2, cap))
if registered == 0 or part(registered + 1) is not None:
    sys.exit("the playbook needs more parts than the %d the settings register" % registered)
PY
)"; then
    echo "parity: $lang/orchestrator-playbook.md: $msg" >&2
    status=1
  fi
done

if [ "$status" -eq 0 ]; then
  echo "parity: OK ($(printf '%s\n' "$en_files" | wc -l | tr -d ' ') files in each copy, $checked compared)"
fi
exit "$status"
