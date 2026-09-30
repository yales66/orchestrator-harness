#!/usr/bin/env python3
"""PreToolUse hook for fork replay: record every tool call, run only read-only ones.

A replayed decision must never reach the outside world, yet the model should still be
able to look around before it decides. So every call is appended to a JSON-lines log,
Read/Grep/Glob and Bash commands that pass a conservative read-only whitelist are
allowed, and everything else is denied. The denial is what makes the replay safe; the
log is what the grader reads.

Usage (as registered in a replay config's settings.json):
    python3 stub_hook.py CONFIG_JSON
CONFIG_JSON holds {"log": path, "extra_readonly": [tool names], "deny_reason": str}.

The Bash classifier errs towards "not read-only": a command it cannot prove harmless is
denied and logged, never executed. Only the Python standard library is used, because
the hook runs under whatever python3 the replay machine has.
"""
import json
import re
import shlex
import sys
import time

READONLY_TOOLS = ("Read", "Grep", "Glob")

# Programs whose every invocation is read-only when no output redirection is present.
PLAIN_READERS = {
    "ls", "cat", "head", "tail", "wc", "grep", "egrep", "fgrep", "rg", "pwd", "echo",
    "printf", "file", "stat", "du", "df", "tree", "which", "type", "whoami", "date",
    "uname", "basename", "dirname", "realpath", "readlink", "sort", "uniq", "cut", "tr",
    "diff", "cmp", "comm", "jq", "column", "nl", "md5", "shasum", "sha256sum", "xxd",
    "od", "strings", "printenv", "ps", "pgrep", "lsof", "test", "[", "true", "false",
    "cd", "less", "more",
}

GIT_READ_SUBCOMMANDS = {
    "status", "log", "show", "diff", "blame", "rev-parse", "ls-files", "ls-tree",
    "cat-file", "describe", "shortlog", "grep", "for-each-ref", "merge-base", "name-rev",
    "rev-list", "show-ref", "count-objects", "check-ignore", "whatchanged",
}
GIT_BRANCH_READ_FLAGS = {
    "-a", "-r", "-v", "-vv", "--list", "-l", "--show-current", "--all", "--remote",
    "--merged", "--no-merged", "--contains", "--no-contains", "--sort", "--format",
    "--no-color", "--color",
}
GH_READ = {
    ("pr", "view"), ("pr", "list"), ("pr", "status"), ("pr", "checks"), ("pr", "diff"),
    ("issue", "view"), ("issue", "list"), ("repo", "view"), ("run", "view"),
    ("run", "list"), ("release", "list"), ("release", "view"),
}
FIND_WRITE_FLAGS = {"-exec", "-execdir", "-delete", "-ok", "-okdir", "-fprint",
                    "-fprint0", "-fprintf", "-fls"}

# Redirections that cannot create or change a file.
SAFE_REDIRECTS = re.compile(r"\d?>&\d|&>\s*/dev/null|\d?>{1,2}\s*/dev/null")
ENV_ASSIGN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")


def _segments(cmd):
    """Split a command line on control operators; None if it uses substitution."""
    if "`" in cmd or "$(" in cmd or "<(" in cmd or ">(" in cmd:
        return None
    stripped = SAFE_REDIRECTS.sub(" ", cmd)
    if ">" in stripped or "<<" in stripped:
        return None
    parts = re.split(r"&&|\|\||[;|\n&]", stripped)
    return [p.strip() for p in parts if p.strip()]


def _git_readonly(args):
    i = 0
    while i < len(args):
        a = args[i]
        if a == "-C":
            i += 2
            continue
        if a in ("--no-pager", "-P") or a.startswith("--git-dir=") or a.startswith("--work-tree="):
            i += 1
            continue
        break
    if i >= len(args):
        return False
    sub, rest = args[i], args[i + 1:]
    if sub in GIT_READ_SUBCOMMANDS:
        return True
    if sub == "branch":
        return all(r.split("=")[0] in GIT_BRANCH_READ_FLAGS for r in rest if r.startswith("-")) \
            and (not [r for r in rest if not r.startswith("-")] or "--list" in rest or "-l" in rest
                 or "--contains" in rest or "--merged" in rest or "--no-merged" in rest)
    if sub == "remote":
        return not rest or rest[0] in ("-v", "--verbose", "get-url", "show")
    if sub == "config":
        return bool(rest) and rest[0] in ("--get", "--get-all", "--list", "-l", "--get-regexp")
    if sub == "tag":
        return not rest or rest[0] in ("-l", "--list")
    if sub == "worktree":
        return rest[:1] == ["list"]
    if sub == "stash":
        return rest[:1] in (["list"], ["show"])
    if sub == "reflog":
        return not rest or rest[0] == "show" or rest[0].startswith("-")
    return False


def _segment_readonly(seg):
    try:
        words = shlex.split(seg)
    except ValueError:
        return False
    while words and ENV_ASSIGN.match(words[0]):
        words = words[1:]
    if not words:
        return False
    prog, args = words[0].rsplit("/", 1)[-1], words[1:]
    flags = [a.split("=")[0] for a in args if a.startswith("-")]
    operands = [a for a in args if not a.startswith("-")]
    # Readers that can still write a file through an option or a second operand.
    if prog in ("sort", "tree") and ("-o" in flags or "--output" in flags):
        return False
    if prog == "uniq" and len(operands) > 1:
        return False
    if prog == "rg" and "--pre" in flags:
        return False
    if prog in PLAIN_READERS:
        return True
    if prog == "find":
        return not any(a in FIND_WRITE_FLAGS for a in args)
    if prog == "sed":
        in_place = any(a == "-i" or a.startswith("--in-place") or
                       (a.startswith("-") and not a.startswith("--") and "i" in a) for a in args)
        writes = any(re.search(r"(^|[\d/;$}])\s*[wW]\s+\S", a) for a in operands)
        return "-n" in args and not in_place and not writes
    if prog == "git":
        return _git_readonly(args)
    if prog == "gh":
        return len(args) >= 2 and (args[0], args[1]) in GH_READ
    return False


def bash_is_readonly(cmd):
    segs = _segments(cmd or "")
    if not segs:
        return False
    return all(_segment_readonly(s) for s in segs)


def decide(tool, tool_input, extra_readonly=()):
    if tool in READONLY_TOOLS or tool in extra_readonly:
        return "allow"
    if tool == "Bash" and bash_is_readonly((tool_input or {}).get("command", "")):
        return "allow"
    return "deny"


def main():
    cfg = json.load(open(sys.argv[1], encoding="utf-8"))
    payload = json.loads(sys.stdin.read() or "{}")
    tool = payload.get("tool_name", "")
    tool_input = payload.get("tool_input") or {}
    decision = decide(tool, tool_input, tuple(cfg.get("extra_readonly", ())))
    row = {
        "ts": time.time(),
        "tool": tool,
        "input": tool_input,
        "decision": decision,
        "tool_use_id": payload.get("tool_use_id"),
        "agent_id": payload.get("agent_id"),
        "session_id": payload.get("session_id"),
    }
    with open(cfg["log"], "a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")
    out = {"hookEventName": "PreToolUse", "permissionDecision": decision}
    if decision == "deny":
        out["permissionDecisionReason"] = cfg.get("deny_reason", "Blocked by PreToolUse hook.")
    print(json.dumps({"hookSpecificOutput": out}, ensure_ascii=False))


if __name__ == "__main__":
    # Fail closed: exit code 2 blocks the tool call, so a broken stub can never let a
    # side effect through the way a crashed, non-blocking hook would.
    try:
        main()
    except Exception as e:  # noqa: BLE001
        print(f"fork-replay stub failed, call blocked: {e}", file=sys.stderr)
        sys.exit(2)
