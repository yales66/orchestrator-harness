#!/usr/bin/env bash
# Static context measurement: first-request input of the main thread and of
# one general-purpose subagent, under two configurations that differ only in
# where the orchestrator playbook lives.
#
#   H  en/ (or zh/) installed as shipped: playbook injected by the SessionStart hook
#   N  the same copy installed, no SessionStart hook, playbook appended to CLAUDE.md
#
# Every run gets its own fresh CLAUDE_CONFIG_DIR, HOME and working directory
# under a temp dir, so nothing from the real ~/.claude is read.
#
# Auth: export CLAUDE_CODE_OAUTH_TOKEN (from `claude setup-token`) or
# ANTHROPIC_API_KEY before running. The token is passed through the
# environment only and is never written to disk.
#
# Env knobs: SC_COPY (en or zh, default en; zh writes results.zh.*), SC_MODEL (default claude-opus-5-5), SC_REPEATS (default 2),
# SC_WORK (temp dir to keep raw logs in), SC_MAX_INPUT (abort threshold,
# default 100000 tokens of first-request input), SC_RETRIES (rounds of reruns
# for runs that `parse_usage.py check` finds not comparable, default 3).
#
# SC_MODEL must be a full model id containing opus, sonnet, haiku or fable: the
# prompt passes that alias as the Agent tool's model parameter, because the
# installed playbook tells the main thread to pick a subagent model itself and
# CLAUDE_CODE_SUBAGENT_MODEL does not override an explicit one.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$HERE/../.." && pwd)"
COPY="${SC_COPY:-en}"
case "$COPY" in en|zh) ;; *) echo "SC_COPY must be en or zh" >&2; exit 2 ;; esac
SRC="$REPO/$COPY"
OUT="results"
[ "$COPY" = en ] || OUT="results.$COPY"
export SC_PLAYBOOK="$SRC/orchestrator-playbook.md"
MODEL="${SC_MODEL:-claude-opus-5-5}"
REPEATS="${SC_REPEATS:-2}"
RETRIES="${SC_RETRIES:-3}"
MAX_INPUT="${SC_MAX_INPUT:-100000}"
WORK="${SC_WORK:-$(mktemp -d "${TMPDIR:-/tmp}/static-context.XXXXXX")}"
mkdir -p "$WORK"

case "$MODEL" in
  *opus*) ALIAS=opus ;;
  *sonnet*) ALIAS=sonnet ;;
  *haiku*) ALIAS=haiku ;;
  *fable*) ALIAS=fable ;;
  *) echo "SC_MODEL must name opus, sonnet, haiku or fable: $MODEL" >&2; exit 2 ;;
esac

PROMPT='Call the Agent tool (also named Task) exactly once, with subagent_type "general-purpose", model "'"$ALIAS"'", description "Reply OK", and prompt "Reply with exactly: OK". Do not call any other tool and do not read any file. After the Agent tool returns, reply with exactly: DONE'

# settings.json for H/N: the hooks block of en/settings.example.json with
# $HOME/.claude rewritten to the temp config dir; N also drops SessionStart.
write_settings() {  # $1 config dir, $2 keep_session_start (1/0)
  python3 - "$SRC/settings.example.json" "$1" "$2" > "$1/settings.json" <<'PY'
import json, sys
src, cfg, keep = sys.argv[1], sys.argv[2], sys.argv[3] == "1"
hooks = json.load(open(src, encoding="utf-8"))["hooks"]
if not keep:
    hooks.pop("SessionStart", None)
text = json.dumps({"hooks": hooks}, indent=2).replace("$HOME/.claude", cfg)
sys.stdout.write(text + "\n")
PY
}

install_config() {  # $1 variant, $2 config dir
  local v="$1" cfg="$2"
  mkdir -p "$cfg"
  case "$v" in
    H|N)
      cp -R "$SRC/hooks" "$cfg/hooks"
      rm -rf "$cfg/hooks/tests"
      cp -R "$SRC/skills" "$cfg/skills"
      cp -R "$SRC/agents" "$cfg/agents"
      cp "$SRC/CLAUDE.md" "$cfg/CLAUDE.md"
      if [ "$v" = H ]; then
        cp "$SRC/orchestrator-playbook.md" "$cfg/orchestrator-playbook.md"
        write_settings "$cfg" 1
      else
        printf '\n\n' >> "$cfg/CLAUDE.md"
        cat "$SRC/orchestrator-playbook.md" >> "$cfg/CLAUDE.md"
        write_settings "$cfg" 0
      fi
      ;;
  esac
}

run_one() {  # $1 variant, $2 repeat index, $3 attempts discarded so far (default 0)
  local v="$1" i="$2" dir="$WORK/$1-$2"
  rm -rf "$dir"
  mkdir -p "$dir/home" "$dir/cwd"
  echo "${3:-0}" > "$dir/discarded_attempts"
  install_config "$v" "$dir/config"
  echo "running $v #$i in $dir" >&2
  (
    cd "$dir/cwd"
    env -i \
      PATH="$PATH" HOME="$dir/home" USER="${USER:-}" LOGNAME="${LOGNAME:-}" \
      SHELL=/bin/bash TMPDIR="${TMPDIR:-/tmp}" LANG=en_US.UTF-8 TERM=dumb \
      CLAUDE_CONFIG_DIR="$dir/config" \
      CLAUDE_CODE_SUBAGENT_MODEL="$MODEL" \
      DISABLE_AUTOUPDATER=1 \
      "${AUTH_ENV[@]}" \
      claude -p "$PROMPT" \
        --model "$MODEL" \
        --output-format stream-json --verbose --include-hook-events \
        --allowedTools Agent \
        --max-budget-usd 0.5 \
      > "$dir/stream.jsonl" 2> "$dir/stderr.log"
  ) || echo "claude exited non-zero for $v #$i (see $dir/stderr.log)" >&2

  python3 "$HERE/parse_usage.py" run "$dir" "$v" "$MAX_INPUT" > "$dir/summary.json"
}

if [ -n "${SC_SETUP_ONLY:-}" ]; then
  for v in H N; do install_config "$v" "$WORK/$v-setup/config"; done
  (cd "$WORK" && find . -type f | sort | xargs wc -c)
  exit 0
fi

if [ -z "${CLAUDE_CODE_OAUTH_TOKEN:-}" ] && [ -z "${ANTHROPIC_API_KEY:-}" ]; then
  cat >&2 <<'EOF'
No credentials in the environment. A fresh CLAUDE_CONFIG_DIR cannot see the
keychain login, so run once:
  claude setup-token
then export the printed token and rerun:
  export CLAUDE_CODE_OAUTH_TOKEN=<token>
  bash eval/static-context/run.sh
EOF
  exit 3
fi

AUTH_ENV=()
[ -n "${CLAUDE_CODE_OAUTH_TOKEN:-}" ] && AUTH_ENV+=("CLAUDE_CODE_OAUTH_TOKEN=$CLAUDE_CODE_OAUTH_TOKEN")
[ -n "${ANTHROPIC_API_KEY:-}" ] && AUTH_ENV+=("ANTHROPIC_API_KEY=$ANTHROPIC_API_KEY")

for i in $(seq 1 "$REPEATS"); do
  for v in H N; do
    run_one "$v" "$i"
  done
done

# Rerun, in place, every run whose subagent model or deferred tool set makes it
# not comparable; the discard count survives in the run directory.
round=0
redo="$(python3 "$HERE/parse_usage.py" check "$WORK" "$MODEL")"
while [ -n "$redo" ] && [ "$round" -lt "$RETRIES" ]; do
  round=$((round + 1))
  echo "retry round $round of $RETRIES:" $redo >&2
  for name in $redo; do
    n="$(cat "$WORK/$name/discarded_attempts" 2>/dev/null || echo 0)"
    run_one "${name%-*}" "${name#*-}" "$((n + 1))"
  done
  redo="$(python3 "$HERE/parse_usage.py" check "$WORK" "$MODEL")"
done
[ -z "$redo" ] || echo "still invalid after $RETRIES retry rounds, marked in the results:" $redo >&2

python3 "$HERE/parse_usage.py" aggregate "$WORK" "$HERE/$OUT.json" "$HERE/$OUT.md" \
  "$(claude --version | awk '{print $1}')" "$MODEL" "$REPEATS" "$COPY"
echo "raw logs kept in $WORK" >&2
echo "wrote $HERE/$OUT.json and $HERE/$OUT.md" >&2
