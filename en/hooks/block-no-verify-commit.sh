#!/bin/bash
# PreToolUse(Bash) hook: block `git commit --no-verify/-n`, which would bypass the
# global commit-msg hook. Does NOT validate the message itself (that's commit-msg's job) —
# it only closes the one bypass hole. Non-git-commit commands pass through untouched.
#
# 判定靠 token 解析而非全命令 grep：子串匹配同时漏真阳（`git commit -n` 里 git 与
# commit 相邻，夹不进 `.+`）与误伤真阴（`git log` 配 echo 的 commit 字样、`[ -n "$C" ]`）。
python3 -c '
import json, re, shlex, sys

try:
    cmd = json.load(sys.stdin).get("tool_input", {}).get("command", "")
except Exception:
    sys.exit(0)

# git 全局选项中带独立值的，跳过其值才能定位子命令
GIT_VALUED = {"-C", "-c", "--git-dir", "--work-tree", "--namespace", "--exec-path", "--config-env"}
# commit 选项中带独立值的，跳过其值，避免把 message 正文当选项（git commit -m "add -n flag"）
COMMIT_VALUED = {"-m", "--message", "-F", "--file", "-C", "--reuse-message", "-c",
                 "--reedit-message", "--author", "--date", "--cleanup", "-t", "--template",
                 "--fixup", "--squash", "--trailer", "-S", "--gpg-sign", "--pathspec-from-file"}

def bypasses(part):
    try:
        toks = shlex.split(part)
    except ValueError:
        return False
    if "git" not in toks:
        return False
    i = toks.index("git") + 1
    while i < len(toks):                      # 跳过 git 全局选项，定位子命令
        t = toks[i]
        if t in GIT_VALUED: i += 2; continue
        if t.startswith("-"): i += 1; continue
        break
    if i >= len(toks) or toks[i] != "commit":
        return False
    args, j = toks[i + 1:], 0
    while j < len(args):                      # 只在 commit 自己的选项位上认 -n/--no-verify
        a = args[j]
        if a in ("--no-verify", "-n"): return True
        if a in COMMIT_VALUED: j += 2; continue
        j += 1
    return False

# 命令替换里的 git 也要看得见；拆成子命令逐条判，避免无关片段互相污染
flat = cmd.replace("$(", " ").replace("`", " ").replace(")", " ")
if any(bypasses(p) for p in re.split(r"(?:&&|\|\||[;&|\n])", flat)):
    print(json.dumps({"hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "permissionDecision": "deny",
        "permissionDecisionReason": "git commit --no-verify/-n is disabled: commit-msg format checks must run. If a bypass is truly needed, ask the human."
    }}))
sys.exit(0)
' 2>/dev/null
exit 0
