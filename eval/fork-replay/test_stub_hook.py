import json
import subprocess
import sys
from pathlib import Path

import pytest

from stub_hook import bash_is_readonly, decide

HERE = Path(__file__).resolve().parent

READONLY = [
    "ls -la",
    "cat README.md | head -20",
    "git status --short",
    "git -C /tmp/repo log --oneline -5",
    "git --no-pager diff HEAD~1",
    "git branch -a",
    "git branch --show-current",
    "grep -rn foo src/ 2>/dev/null",
    "rg -n 'x' . && wc -l a.txt",
    "find . -name '*.py' -type f",
    "sed -n '1,40p' app.py",
    "cd web && ls",
    "GIT_PAGER=cat git show abc123",
    "gh pr view 26 --json state",
    "git remote -v",
    "git config --get user.name",
    "jq '.a' x.json",
    "ls 2>&1 | head",
]

MUTATING = [
    "git push origin main",
    "git commit -m 'x'",
    "git branch -D feature",
    "git branch new-branch",
    "git worktree remove ../wt",
    "git -c core.pager=sh log",
    "gh pr create --fill",
    "gh pr merge 26 --squash",
    "gh api repos/o/r/issues -f title=x",
    "rm -rf build",
    "echo hi > out.txt",
    "cat a >> b",
    "sed -i '' 's/a/b/' f.txt",
    "find . -name '*.pyc' -delete",
    "find . -exec rm {} \\;",
    "python3 script.py",
    "ls $(rm -rf x)",
    "ls `touch y`",
    "curl https://api.example.com",
    "ssh pc 'nvidia-smi'",
    "cat f | tee copy.txt",
    "awk '{print > \"x\"}' f",
    "sed -n 'w out.txt' f",
    "sort -o out.txt f",
    "tree -o out.txt",
    "uniq in.txt out.txt",
    "rg --pre ./x.sh foo",
    "",
]


@pytest.mark.parametrize("cmd", READONLY, ids=READONLY)
def test_readonly_commands_pass(cmd):
    assert bash_is_readonly(cmd)


@pytest.mark.parametrize("cmd", MUTATING, ids=[c or "<empty>" for c in MUTATING])
def test_mutating_or_unknown_commands_are_denied(cmd):
    assert not bash_is_readonly(cmd)


@pytest.mark.parametrize(
    "tool,inp,expected",
    [
        ("Read", {"file_path": "/x"}, "allow"),
        ("Grep", {"pattern": "x"}, "allow"),
        ("Glob", {"pattern": "*"}, "allow"),
        ("Bash", {"command": "git log -1"}, "allow"),
        ("Bash", {"command": "git push"}, "deny"),
        ("Write", {"file_path": "/x", "content": "y"}, "deny"),
        ("Agent", {"prompt": "do it"}, "deny"),
        ("AskUserQuestion", {"questions": []}, "deny"),
        ("mcp__anysite__execute", {}, "deny"),
    ],
    ids=["read", "grep", "glob", "bash-ro", "bash-push", "write", "agent", "ask", "mcp"],
)
def test_decide(tool, inp, expected):
    assert decide(tool, inp, extra_readonly=()) == expected


def test_extra_readonly_tools_are_allowed():
    assert decide("ToolSearch", {"query": "x"}, extra_readonly=("ToolSearch",)) == "allow"
    assert decide("ToolSearch", {"query": "x"}, extra_readonly=()) == "deny"


def test_hook_logs_every_call_and_denies_side_effects(tmp_path):
    log = tmp_path / "calls.jsonl"
    cfg = tmp_path / "stub.json"
    cfg.write_text(json.dumps({"log": str(log), "extra_readonly": [], "deny_reason": "blocked"}))

    def run(tool, inp):
        payload = {"hook_event_name": "PreToolUse", "tool_name": tool, "tool_input": inp,
                   "tool_use_id": "t1", "session_id": "s"}
        out = subprocess.run([sys.executable, str(HERE / "stub_hook.py"), str(cfg)],
                             input=json.dumps(payload), capture_output=True, text=True, check=True)
        return json.loads(out.stdout)["hookSpecificOutput"]

    assert run("Read", {"file_path": "/x"})["permissionDecision"] == "allow"
    denied = run("Bash", {"command": "git push"})
    assert denied["permissionDecision"] == "deny"
    assert denied["permissionDecisionReason"] == "blocked"
    rows = [json.loads(l) for l in log.read_text().splitlines()]
    assert [(r["tool"], r["decision"]) for r in rows] == [("Read", "allow"), ("Bash", "deny")]
    assert rows[1]["input"] == {"command": "git push"}


def test_hook_fails_closed_when_its_config_is_unreadable(tmp_path):
    payload = {"hook_event_name": "PreToolUse", "tool_name": "Bash", "tool_input": {"command": "git push"}}
    out = subprocess.run([sys.executable, str(HERE / "stub_hook.py"), str(tmp_path / "missing.json")],
                         input=json.dumps(payload), capture_output=True, text=True)
    assert out.returncode == 2
