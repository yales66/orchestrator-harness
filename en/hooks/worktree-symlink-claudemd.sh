#!/usr/bin/env bash
# worktree-symlink-claudemd.sh — despite the name, symlinks CLAUDE.md
# **and** node_modules + .env* into a freshly-created git worktree.
#
# Runs on WorktreeCreate (or PostToolUse:EnterWorktree). For each target:
#   - CLAUDE.md       → main/CLAUDE.md  (git tracked; also flip skip-worktree)
#   - node_modules    → main/node_modules
#   - .env / .env.*   → main/<same-name>  (skip *.example, *.sample, *.schema)
#
# Already-symlinked targets are left alone (idempotent). Real files/dirs
# in the worktree are NEVER overwritten — we bail on those so user work is
# never destroyed. The tracked CLAUDE.md is the one exception, and only when
# it matches HEAD: a worktree CLAUDE.md with uncommitted changes is kept and
# reported, because skip-worktree would hide the swap from `git status`.

set -u

payload=$(cat)

# Extract worktree path. WorktreeCreate uses `.path`; PostToolUse on
# EnterWorktree puts it under `.tool_input.path` or `.tool_response.path`.
worktree=$(printf '%s' "$payload" | jq -r '
  .path //
  .worktree //
  .tool_response.path //
  .tool_response.worktree_path //
  .tool_response.cwd //
  .tool_input.path //
  .tool_input.target //
  empty
' 2>/dev/null)

[ -z "$worktree" ] && exit 0
[ ! -d "$worktree" ] && exit 0

main=$(git -C "$worktree" worktree list --porcelain 2>/dev/null \
  | awk '/^worktree / {print $2; exit}')

[ -z "$main" ] && exit 0

# git prints physical paths, while the payload path may pass through a
# symlinked directory (macOS /var → /private/var). Resolve both sides so the
# main-worktree check holds and relpath yields a link that resolves from the
# worktree's real location.
worktree=$(cd "$worktree" 2>/dev/null && pwd -P) || exit 0
main=$(cd "$main" 2>/dev/null && pwd -P) || exit 0
[ "$main" = "$worktree" ] && exit 0

# relpath FROM worktree TO $1 — portable relative symlink
relpath() {
  python3 -c "import os,sys; print(os.path.relpath(sys.argv[1], sys.argv[2]))" "$1" "$worktree" 2>/dev/null
}

created=()
kept=()

link_target() {
  local src="$1"           # absolute path under $main
  local name="$2"          # basename as it will appear in $worktree
  local skip_worktree="$3" # "true" for git-tracked files (CLAUDE.md)

  local dest="$worktree/$name"
  [ -e "$src" ] || [ -L "$src" ] || return 0
  # Already a symlink → idempotent, skip.
  [ -L "$dest" ] && return 0
  # Real file/dir in the worktree → don't clobber user work.
  if [ -e "$dest" ] && [ "$skip_worktree" != "true" ]; then
    return 0
  fi

  # Tracked file present in the worktree: replace it only if it matches the
  # blob in HEAD, so uncommitted edits (staged or not) are never discarded.
  if [ -e "$dest" ] && [ "$skip_worktree" = "true" ]; then
    local head_blob
    head_blob=$(git -C "$worktree" rev-parse -q --verify "HEAD:./$name" 2>/dev/null)
    if [ -z "$head_blob" ] \
      || [ "$head_blob" != "$(git -C "$worktree" hash-object -- "$name" 2>/dev/null)" ]; then
      kept+=("$name: it differs from HEAD (uncommitted changes), not symlinked")
      return 0
    fi
  fi

  local rel
  rel=$(relpath "$src")
  [ -z "$rel" ] && return 0
  # The link text must resolve from the worktree; otherwise keep the original.
  [ -e "$worktree/$rel" ] || [ -L "$worktree/$rel" ] || return 0

  if [ "$skip_worktree" = "true" ]; then
    # git-tracked: tell git to ignore the symlink swap, then replace.
    (cd "$worktree" && git update-index --skip-worktree "$name" 2>/dev/null || true)
    rm -f "$dest"
  fi

  ln -s "$rel" "$dest" && created+=("$name → $rel")
}

# 1) CLAUDE.md (git-tracked)
link_target "$main/CLAUDE.md" "CLAUDE.md" "true"

# 2) node_modules (gitignored)
link_target "$main/node_modules" "node_modules" "false"

# 3) .env / .env.* (gitignored; skip template files that ARE tracked)
shopt -s nullglob 2>/dev/null || true
for src in "$main"/.env "$main"/.env.*; do
  [ -e "$src" ] || continue
  base=$(basename "$src")
  case "$base" in
    *.example|*.sample|*.schema|*.template) continue ;;
  esac
  link_target "$src" "$base" "false"
done

parts=()
if [ ${#created[@]} -gt 0 ]; then
  summary=$(printf '%s, ' "${created[@]}")
  parts+=("symlinked ${summary%, }")
fi
if [ ${#kept[@]} -gt 0 ]; then
  summary=$(printf '%s, ' "${kept[@]}")
  parts+=("kept ${summary%, }")
fi
if [ ${#parts[@]} -gt 0 ]; then
  summary=$(printf '%s; ' "${parts[@]}")
  printf '{"systemMessage":"worktree %s: %s"}\n' "$(basename "$worktree")" "${summary%; }"
fi
