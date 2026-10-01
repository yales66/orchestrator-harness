#!/usr/bin/env python3
"""PreToolUse hook for fork replay: record every tool call, run only read-only ones.

A replayed decision must never reach the outside world, yet the model should still be
able to look around before it decides. So every call is appended to a JSON-lines log,
Read/Grep/Glob and Bash commands that pass a conservative read-only whitelist are
allowed, and everything else is denied. The denial is what makes the replay safe; the
log is what the grader reads.

Usage (as registered in a replay config's settings.json):
    python3 stub_hook.py CONFIG_JSON
CONFIG_JSON holds {"log": path, "extra_readonly": [tool names], "deny_reason": str,
"stop_on_deny": bool}; with stop_on_deny the first denied call also ends the query.

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


_HOLE = re.compile(r"\x00(\d+)\x00")


def _mask_quotes(cmd):
    """(cmd with each quoted string replaced by a placeholder, the quoted strings), or None.

    Operators inside quotes are text, so the command is split only after masking. A
    double-quoted string that runs a command substitution is refused outright.
    """
    out, held, i = [], [], 0
    while i < len(cmd):
        ch = cmd[i]
        if ch in "'\"":
            j = i + 1
            while j < len(cmd) and cmd[j] != ch:
                j += 2 if ch == '"' and cmd[j] == "\\" else 1
            if j >= len(cmd):
                return None
            text = cmd[i:j + 1]
            if ch == '"' and ("$(" in text or "`" in text):
                return None
            held.append(text)
            out.append(f"\x00{len(held) - 1}\x00")
            i = j + 1
        elif ch == "\\" and i + 1 < len(cmd):
            out.append(cmd[i:i + 2])
            i += 2
        else:
            out.append(ch)
            i += 1
    return "".join(out), held


def _unmask(text, held):
    return _HOLE.sub(lambda m: held[int(m.group(1))], text)


def _substitute_reads(masked, held):
    """Replace each $(...) whose command only reads with a plain word; None if one may write."""
    while "$(" in masked:
        start = masked.index("$(")
        depth, j = 0, start + 1
        while j < len(masked):
            depth += {"(": 1, ")": -1}.get(masked[j], 0)
            if depth == 0:
                break
            j += 1
        if j >= len(masked) or not bash_is_readonly(_unmask(masked[start + 2:j], held)):
            return None
        masked = masked[:start] + "SUBST" + masked[j + 1:]
    return masked


def _segments(cmd):
    """Split a command line on control operators outside quotes; None if it may write."""
    m = _mask_quotes(cmd)
    if m is None:
        return None
    masked, held = m
    masked = _substitute_reads(masked, held)
    if masked is None or "`" in masked or "<(" in masked or ">(" in masked:
        return None
    stripped = SAFE_REDIRECTS.sub(" ", masked)
    if ">" in stripped or "<<" in stripped:
        return None
    parts = re.split(r"&&|\|\||[;|\n&]", stripped)
    return [_unmask(p, held).strip() for p in parts if p.strip()]


SHELL_KEYWORDS = {"do", "then", "else", "elif", "if", "while", "until", "!"}
SHELL_CLOSERS = {"done", "fi"}


def _awk_readonly(args):
    """awk with an inline program that cannot write a file or run a command."""
    program = next((a for a in args if not a.startswith("-")), None)
    if program is None or any(a == "-f" or a.startswith("--file") for a in args):
        return False
    return not re.search(r"system|>|\||getline|fflush|close", program)


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
    while words and words[0] in SHELL_KEYWORDS:
        words = words[1:]
    if len(words) == 1 and words[0] in SHELL_CLOSERS:
        return True
    if words[:1] == ["for"] and (len(words) == 2 or words[2:3] == ["in"]):
        return True  # the loop head only names words; any substitution in them was checked
    assigned = False
    while words and ENV_ASSIGN.match(words[0]):
        words, assigned = words[1:], True
    if not words:
        return assigned  # a bare assignment sets a shell variable and nothing else
    prog, args = words[0].rsplit("/", 1)[-1], words[1:]
    if prog == "awk":
        return _awk_readonly(args)
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
        # GNU sed runs a shell command with the e command or the e flag of s///.
        runs = any(re.search(r"(^|[\d/;$}])\s*e(\s|$)|/[gpiImM0-9]*e[gpiImM0-9]*(\s|;|$)", a) for a in operands)
        script_file = any(a == "-f" or a.startswith("--file") for a in args)
        return not (in_place or writes or runs or script_file)
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
    result = {"hookSpecificOutput": out}
    if decision == "deny":
        out["permissionDecisionReason"] = cfg.get("deny_reason", "Blocked by PreToolUse hook.")
        if cfg.get("stop_on_deny"):
            # The first call that would act ends the query before the model sees any reply to it.
            result.update({"continue": False, "stopReason": "fork replay: first non-read-only call recorded"})
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    # Fail closed: exit code 2 blocks the tool call, so a broken stub can never let a
    # side effect through the way a crashed, non-blocking hook would.
    try:
        main()
    except Exception as e:  # noqa: BLE001
        print(f"fork-replay stub failed, call blocked: {e}", file=sys.stderr)
        sys.exit(2)
