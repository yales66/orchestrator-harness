"""Tests for extract.py: which transcript records count as the user's own input, and git-state output."""
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
SCRIPT = HERE / "extract.py"
sys.path.insert(0, str(HERE))

REJECT = ("The user doesn't want to proceed with this tool use. The tool use was rejected "
          "(eg. if it was a file edit, the new_string was NOT written to the file). "
          "STOP what you are doing and wait for the user to tell you how to proceed.")

_seq = [0]


def _next(prefix):
    _seq[0] += 1
    return f"{prefix}-{_seq[0]:04d}"


def _ts(n):
    return f"2026-09-30T01:{n // 60:02d}:{n % 60:02d}.000Z"


def user(content, n=0, uuid=None, origin="human", **extra):
    rec = {"type": "user", "uuid": uuid or _next("u"), "timestamp": _ts(n),
           "isSidechain": False, "message": {"role": "user", "content": content}}
    if origin is not None:
        rec["origin"] = {"kind": origin}
    rec.update(extra)
    return rec


def tool_use(tool_id, name, inp, n=0):
    return {"type": "assistant", "uuid": _next("a"), "timestamp": _ts(n), "isSidechain": False,
            "message": {"role": "assistant", "content": [
                {"type": "tool_use", "id": tool_id, "name": name, "input": inp}]}}


def tool_result(tool_id, text, n=0, result=None, is_error=None):
    block = {"type": "tool_result", "tool_use_id": tool_id, "content": text}
    if is_error is not None:
        block["is_error"] = is_error
    return user([block], n=n, origin=None, toolUseResult=result if result is not None else text)


def write_jsonl(path, records):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records), encoding="utf-8")
    return path


def run(args, cwd=None, env_extra=None):
    env = dict(os.environ)
    env.pop("CLAUDE_CONFIG_DIR", None)
    env.update(env_extra or {})
    return subprocess.run([sys.executable, str(SCRIPT), *args], cwd=cwd, env=env,
                          capture_output=True, text=True)


def extract(tmp_path, records):
    """Run extract.py on the given records; return the text of user-messages.md."""
    transcript = write_jsonl(tmp_path / "t.jsonl", records)
    out = tmp_path / "out"
    proc = run(["--out", str(out), "--transcript", str(transcript)])
    assert proc.returncode == 0, proc.stderr
    return (out / "user-messages.md").read_text(encoding="utf-8")


def entries(md):
    """Split user-messages.md into its U-numbered entries: list of (number, header, body)."""
    parts = re.split(r"^## (U\d+)\b(.*)$", md, flags=re.M)
    return [(parts[i], parts[i + 1], parts[i + 2]) for i in range(1, len(parts), 3)]


# ---------------------------------------------------------------- exclusion

EXCLUDED = {
    "system-reminder": [user("<system-reminder>\nMARKER\n</system-reminder>", origin=None)],
    "task-notification-prefix": [user("<task-notification>\n<task-id>x</task-id>MARKER", origin=None)],
    "task-notification-origin": [user("MARKER done", origin="task-notification")],
    "peer-session-message": [user("Another Claude session sent a message:\n<agent-message>MARKER",
                                  origin="peer")],
    "peer-without-origin": [user("Another Claude session sent a message:\nMARKER", origin=None)],
    "local-command-caveat": [user("<local-command-caveat>Caveat: MARKER</local-command-caveat>",
                                  origin=None, isMeta=True)],
    "local-command-stdout": [user("<local-command-stdout>MARKER</local-command-stdout>", origin=None)],
    "interrupt-marker": [user([{"type": "text", "text": "[Request interrupted by user] MARKER"}],
                              origin=None)],
    "compact-summary": [user("This session is being continued from a previous conversation. MARKER",
                             origin=None, isCompactSummary=True)],
    "stop-hook-feedback": [user("Stop hook feedback:\nMARKER", origin=None, isMeta=True)],
    "skill-body-meta": [user([{"type": "text", "text": "Base directory for this skill: MARKER"}],
                             origin=None, isMeta=True)],
    "sidechain": [user("MARKER from subagent thread", isSidechain=True)],
    "ordinary-tool-result": [tool_use("t1", "Bash", {"command": "ls"}),
                             tool_result("t1", "MARKER file listing")],
    "bash-mode-stdout": [user("<bash-stdout>MARKER</bash-stdout>", origin=None)],
}


@pytest.mark.parametrize("records", EXCLUDED.values(), ids=EXCLUDED.keys())
def test_non_user_records_are_excluded(tmp_path, records):
    md = extract(tmp_path, records)
    assert "MARKER" not in md
    assert entries(md) == []


# ---------------------------------------------------------------- inclusion

def test_typed_text_kept_in_full_with_timestamp(tmp_path):
    long_text = "粘贴内容" + "x" * 5000 + "END"
    md = extract(tmp_path, [user("跑完了，同步数字吧", n=1), user(long_text, n=2)])
    got = entries(md)
    assert [e[0] for e in got] == ["U1", "U2"]
    assert _ts(1) in got[0][1] and "跑完了，同步数字吧" in got[0][2]
    assert long_text in got[1][2]


def test_image_block_is_marked(tmp_path):
    content = [{"type": "text", "text": "看这张图"}, {"type": "image", "source": {}}]
    md = extract(tmp_path, [user(content)])
    assert "看这张图" in md and "[image]" in md


SLASH = {
    "name-with-slash": ("<command-message>x</command-message>\n<command-name>/claude-api</command-name>\n"
                        "<command-args>prompt audit</command-args>", "/claude-api prompt audit"),
    "name-without-slash": ("<command-name>clear</command-name><command-args></command-args>", "/clear"),
}


@pytest.mark.parametrize("raw,expected", SLASH.values(), ids=SLASH.keys())
def test_slash_command_rendered_as_name_and_args(tmp_path, raw, expected):
    md = extract(tmp_path, [user(raw, origin=None)])
    (_, _, body), = entries(md)
    assert body.strip() == expected


def test_choice_answer_keeps_question_and_selected_option(tmp_path):
    q = "英文静态测量这次重跑没有可比的一对，怎么处理？"
    records = [
        tool_use("q1", "AskUserQuestion", {"questions": [{"question": q}]}),
        tool_result("q1", f'Your questions have been answered: "{q}"="先修脚本再重测". You can now continue.',
                    result={"questions": [{"question": q}], "answers": {q: "先修脚本再重测"}}),
    ]
    (_, header, body), = entries(extract(tmp_path, records))
    assert "选择题回答" in header
    assert q in body and "先修脚本再重测" in body


ANSWER_WORDINGS = {
    "questions-answered": 'Your questions have been answered: "范围？"="全套四处". You can now continue.',
    "user-answered": ('The user answered: "范围？"="全套四处". Read the answers carefully — they may '
                      'request clarification, changes, or that you not proceed — and follow what they actually say.'),
}


@pytest.mark.parametrize("text", ANSWER_WORDINGS.values(), ids=ANSWER_WORDINGS.keys())
def test_choice_answer_parsed_from_text_when_result_lacks_answers(tmp_path, text):
    items = entries(extract(tmp_path, [tool_result("q2", text)]))
    assert len(items) == 1
    (_, header, body), = items
    assert "选择题回答" in header
    assert "问：范围？" in body and "答：全套四处" in body


REJECTED = {
    "bash-command": ("Bash", {"command": "cd ~/x && git push origin main 2>&1 | tail -3"},
                     "拒绝了 Bash 调用", "git push origin main"),
    "edit-path": ("Edit", {"file_path": "/a/b/HANDOFF.md", "old_string": "o", "new_string": "n"},
                  "拒绝了 Edit 调用", "/a/b/HANDOFF.md"),
}


@pytest.mark.parametrize("name,inp,line,summary", REJECTED.values(), ids=REJECTED.keys())
def test_rejected_tool_call_names_tool_and_summary(tmp_path, name, inp, line, summary):
    records = [tool_use("r1", name, inp), tool_result("r1", REJECT, result="User rejected tool use", is_error=True)]
    (_, _, body), = entries(extract(tmp_path, records))
    assert line in body and summary in body


def test_rejected_summary_capped_at_120_chars(tmp_path):
    cmd = "echo " + "y" * 300
    records = [tool_use("r2", "Bash", {"command": cmd}), tool_result("r2", REJECT, is_error=True)]
    (_, _, body), = entries(extract(tmp_path, records))
    summary = body.strip().split("：", 1)[1]
    assert summary.startswith("echo yyy") and len(summary) <= 120


def test_entries_ordered_by_timestamp_and_deduplicated_by_uuid(tmp_path):
    first = user("第一条", n=1, uuid="dup")
    records = [user("第三条", n=3), first, user("第二条", n=2), dict(first)]
    got = entries(extract(tmp_path, records))
    assert [e[0] for e in got] == ["U1", "U2", "U3"]
    assert ["第一条" in got[0][2], "第二条" in got[1][2], "第三条" in got[2][2]] == [True] * 3


# ---------------------------------------------------------------- transcript discovery and CLI

def test_without_transcript_refuses_even_when_a_session_file_exists(tmp_path):
    # A parallel session in the same project can be the newest file, so no default is guessed.
    cfg, work = tmp_path / "cfg", tmp_path / "work"
    work.mkdir()
    write_jsonl(cfg / "projects" / "p" / "other.jsonl", [user("别的会话")])
    out = tmp_path / "out"
    proc = run(["--out", str(out)], cwd=work, env_extra={"CLAUDE_CONFIG_DIR": str(cfg)})
    assert proc.returncode == 2
    assert "--transcript" in proc.stderr
    assert not (out / "user-messages.md").exists()


def test_nonexistent_transcript_exits_2_with_path(tmp_path):
    missing = tmp_path / "nope.jsonl"
    proc = run(["--out", str(tmp_path / "out"), "--transcript", str(missing)], cwd=tmp_path)
    assert proc.returncode == 2
    assert str(missing) in proc.stderr


# ---------------------------------------------------------------- git-state.md

def git(repo, *args):
    # Fixture repos ignore the developer's global git config (hooks, signing) so they build anywhere.
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True,
                   env={**os.environ, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1",
                        "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
                        "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"})


def make_repo(tmp_path, commits, upstream_at=None):
    """Create a repo on branch main with `commits` commits; optionally an upstream at commit index."""
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    for i in range(commits):
        (repo / "f.txt").write_text(str(i))
        git(repo, "add", "f.txt")
        git(repo, "commit", "-q", "-m", f"commit-{i}")
    if upstream_at is not None:
        bare = tmp_path / "up.git"
        git(tmp_path, "init", "-q", "--bare", str(bare))
        git(repo, "remote", "add", "origin", str(bare))
        git(repo, "push", "-q", "origin", f"HEAD~{commits - 1 - upstream_at}:refs/heads/main")
        git(repo, "branch", "-q", "--set-upstream-to=origin/main")
    return repo


def git_state(tmp_path, repo):
    transcript = write_jsonl(tmp_path / "t.jsonl", [])
    out = tmp_path / "out"
    proc = run(["--out", str(out), "--transcript", str(transcript), "--repo", str(repo)])
    assert proc.returncode == 0, proc.stderr
    return (out / "git-state.md").read_text(encoding="utf-8")


def test_git_state_lists_branch_status_ahead_and_recent(tmp_path):
    repo = make_repo(tmp_path, 7, upstream_at=4)
    (repo / "new.txt").write_text("n")
    md = git_state(tmp_path, repo)
    assert str(repo) in md and "main" in md
    assert "?? new.txt" in md
    ahead = md.split("领先上游", 1)[1].split("最近", 1)[0]
    assert "commit-5" in ahead and "commit-6" in ahead and "commit-4" not in ahead
    recent = md.split("最近", 1)[1]
    assert all(f"commit-{i}" in recent for i in range(2, 7)) and "commit-1" not in recent


def test_git_state_notes_missing_upstream_and_caps_status(tmp_path):
    repo = make_repo(tmp_path, 1)
    for i in range(45):
        (repo / f"n{i:02d}.txt").write_text("n")
    md = git_state(tmp_path, repo)
    assert "无上游" in md
    assert len(re.findall(r"^\?\? n\d\d\.txt$", md, flags=re.M)) == 40
    assert "省略 5 行" in md
