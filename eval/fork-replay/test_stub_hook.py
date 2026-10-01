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


def _hook(tmp_path, cfg, tool, inp):
    """Run the stub as Claude Code would and return its parsed stdout."""
    path = tmp_path / "stub.json"
    path.write_text(json.dumps(cfg))
    payload = {"hook_event_name": "PreToolUse", "tool_name": tool, "tool_input": inp,
               "tool_use_id": "t1", "session_id": "s"}
    out = subprocess.run([sys.executable, str(HERE / "stub_hook.py"), str(path)],
                         input=json.dumps(payload), capture_output=True, text=True, check=True)
    return json.loads(out.stdout)


def test_hook_logs_every_call_and_denies_side_effects(tmp_path):
    log = tmp_path / "calls.jsonl"
    cfg = {"log": str(log), "extra_readonly": [], "deny_reason": "blocked"}

    def run(tool, inp):
        return _hook(tmp_path, cfg, tool, inp)["hookSpecificOutput"]

    assert run("Read", {"file_path": "/x"})["permissionDecision"] == "allow"
    denied = run("Bash", {"command": "git push"})
    assert denied["permissionDecision"] == "deny"
    assert denied["permissionDecisionReason"] == "blocked"
    rows = [json.loads(l) for l in log.read_text().splitlines()]
    assert [(r["tool"], r["decision"]) for r in rows] == [("Read", "allow"), ("Bash", "deny")]
    assert rows[1]["input"] == {"command": "git push"}


@pytest.mark.parametrize("stop_on_deny, tool, inp, stops", [
    (True, "Bash", {"command": "git push"}, True),
    (True, "AskUserQuestion", {"questions": []}, True),
    (True, "Read", {"file_path": "/x"}, False),
    (False, "Bash", {"command": "git push"}, False),
], ids=["deny-stops", "ask-stops", "allow-continues", "switch-off-continues"])
def test_stop_on_deny_ends_the_query_at_the_first_denied_call(tmp_path, stop_on_deny, tool, inp, stops):
    # Claude Code stops the loop only when continue:false comes with a hook deny; a deny from
    # can_use_tool or an allow with continue:false would let the model see a refusal or run the call.
    cfg = {"log": str(tmp_path / "calls.jsonl"), "deny_reason": "blocked", "stop_on_deny": stop_on_deny}
    out = _hook(tmp_path, cfg, tool, inp)
    assert (out.get("continue") is False) is stops
    assert ("stopReason" in out) is stops


def test_hook_fails_closed_when_its_config_is_unreadable(tmp_path):
    payload = {"hook_event_name": "PreToolUse", "tool_name": "Bash", "tool_input": {"command": "git push"}}
    out = subprocess.run([sys.executable, str(HERE / "stub_hook.py"), str(tmp_path / "missing.json")],
                         input=json.dumps(payload), capture_output=True, text=True)
    assert out.returncode == 2


# Reads the ask-or-act trial saw denied, and the writes that look like them.
TRIAL_READS = [
    'grep -n "idle\\|Idle\\|pause" Sources/TimerEngine.swift | head -30; git show --stat 742d5da | head -30',
    "grep -c 'Test-driven agentic\\|characterisation' archive/resume-v2ai.md",
    "D=/Users/x/.claude; git -C $D status --short; sed -n '66,72p' $D/orchestrator-playbook.md",
    'for p in a/SKILL.md "b/SKILL.md"; do ls -la "$p" 2>&1; done',
    "awk '/待变更/{f=1} f' profile/claims-ledger.md | head -40",
    "ls -la x */resume.md 2>/dev/null | awk '{print $6,$7,$9}'",
    "for b in $(git for-each-ref --format='%(refname:short)' refs/heads); do git ls-tree --name-only $b docs/adr; done",
    "echo 'a > b'; grep -n '->' src/main.ts",
    'if [ -f HANDOFF.md ]; then head -20 HANDOFF.md; else echo none; fi',
]
TRIAL_WRITES = [
    "awk '{print > \"out.txt\"}' in.txt",
    "awk 'BEGIN{system(\"rm -rf x\")}'",
    "for f in *.txt; do rm $f; done",
    "D=$(rm -rf x); ls",
    'echo "$(touch x)"',
    "X=1 python3 train.py",
    "grep x a | tee out.txt",
    'if [ -f a ]; then rm a; fi',
]


@pytest.mark.parametrize("cmd", TRIAL_READS, ids=[str(i) for i in range(len(TRIAL_READS))])
def test_quoted_operators_loops_assignments_and_awk_reads_pass(cmd):
    assert bash_is_readonly(cmd)


@pytest.mark.parametrize("cmd", TRIAL_WRITES, ids=[str(i) for i in range(len(TRIAL_WRITES))])
def test_writes_hidden_in_awk_loops_and_substitutions_are_denied(cmd):
    assert not bash_is_readonly(cmd)


@pytest.mark.parametrize("cmd, ok", [
    ("git ls-files | sed 's|/.*||' | sort | uniq -c", True),
    ("sed -e 's/a/b/' -e 's/c/d/' notes.txt", True),
    ("sed 's/a/b/w out.txt' notes.txt", False),
    ("sed -i '' 's/a/b/' notes.txt", False),
    ("sed '1e rm -rf x' notes.txt", False),
    ("sed -f script.sed notes.txt", False),
], ids=["pipe-substitute", "two-expressions", "w-flag", "in-place", "e-command", "script-file"])
def test_sed_printing_to_stdout_is_a_read(cmd, ok):
    assert bash_is_readonly(cmd) is ok
