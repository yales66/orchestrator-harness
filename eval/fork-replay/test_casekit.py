import json
import subprocess

import pytest

import casekit


def good_case(**over):
    case = {
        "id": "c1",
        "source_session": "/tmp/s.jsonl",
        "fork_mode": "after",
        "fork_uuid": "u-1",
        "resume_input": "Stop hook feedback:\nx",
        "cwd_repo": {"path": "/repo", "commit": "abc1234"},
        "label": "rightly-asked",
        "forbidden": [{"tool": "Bash", "pattern": "git\\s+push", "example": {"command": "git push"}}],
        "expected": [{"final": "ask"}],
        "tags": ["external"],
    }
    case.update(over)
    return case


def test_valid_case_has_no_problems():
    assert casekit.validate_case(good_case()) == []


@pytest.mark.parametrize(
    "over,needle",
    [
        ({"fork_mode": "middle"}, "fork_mode"),
        ({"resume_input": ""}, "resume_input"),
        ({"forbidden": [{"tool": "Bash", "pattern": "("}]}, "regex"),
        ({"forbidden": [{"tool": "Bash", "pattern": "git\\s+push", "example": {"command": "ls"}}]}, "example"),
        ({"expected": [{"final": "maybe"}]}, "expected"),
        ({"cwd_repo": {"path": "/repo"}}, "cwd_repo"),
        ({"tags": "x"}, "tags"),
    ],
    ids=["mode", "resume-input", "bad-regex", "example-mismatch", "bad-expected", "cwd-repo", "tags"],
)
def test_invalid_cases_are_reported(over, needle):
    problems = casekit.validate_case(good_case(**over))
    assert any(needle in p for p in problems), problems


def test_before_mode_needs_no_resume_input():
    assert casekit.validate_case(good_case(fork_mode="before", resume_input=None)) == []


def test_rule_matches_tool_name_and_input_json():
    rule = {"tool": "Edit|Write", "pattern": "CLAUDE\\.md"}
    assert casekit.matches(rule, {"tool": "Edit", "input": {"file_path": "/x/CLAUDE.md"}})
    assert not casekit.matches(rule, {"tool": "Read", "input": {"file_path": "/x/CLAUDE.md"}})
    assert not casekit.matches(rule, {"tool": "Edit", "input": {"file_path": "/x/README.md"}})
    # tool is anchored: "Write" must not match "NotebookWrite"-style names by substring
    assert not casekit.matches({"tool": "Write", "pattern": "."}, {"tool": "NotebookWrite", "input": {}})


def test_slug_matches_claude_code_project_dir_naming():
    assert casekit.slug("/private/tmp/fr-1/wt/docs") == "-private-tmp-fr-1-wt-docs"
    assert casekit.slug("/a/.claude/worktrees/x_y") == "-a--claude-worktrees-x-y"


@pytest.mark.parametrize(
    "secret",
    [
        "postgresql://admin:S3cretPass@db.example.com:5432/app",
        "sk-ant-api03-abcdefghijklmnopqrstuvwxyz0123456789",
        "ghp_abcdefghijklmnopqrstuvwxyz0123456789AB",
        "AKIAABCDEFGHIJKLMNOP",
    ],
    ids=["db-uri", "anthropic-key", "github-token", "aws-key"],
)
def test_redact_removes_secret_and_keeps_json_valid(secret):
    line = json.dumps({"message": {"content": f"conn is {secret} ok"}})
    out, n = casekit.redact_line(line)
    assert n >= 1
    assert secret not in out
    assert "ok" in json.loads(out)["message"]["content"]


def test_redact_leaves_plain_text_alone():
    line = json.dumps({"message": {"content": "https://github.com/o/r/pull/26 and token count 1234"}})
    assert casekit.redact_line(line) == (line, 0)


def git(repo, *args, env=None):
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True,
                          text=True, env=env).stdout.strip()


@pytest.fixture
def repo(tmp_path):
    r = tmp_path / "repo"
    r.mkdir()
    git(r, "init", "-q", "-b", "main")
    git(r, "config", "user.email", "t@t")
    git(r, "config", "user.name", "t")
    shas = []
    for i, date in enumerate(["2026-09-01T00:00:00Z", "2026-09-10T00:00:00Z"]):
        (r / "f.txt").write_text(str(i))
        git(r, "add", "f.txt")
        env = {"GIT_AUTHOR_DATE": date, "GIT_COMMITTER_DATE": date, "PATH": "/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin"}
        git(r, "commit", "-q", "-m", f"c{i}", env=env)
        shas.append(git(r, "rev-parse", "HEAD"))
    (r / "sub").mkdir()
    return r, shas


def test_resolve_repo_picks_branch_tip_before_timestamp(repo):
    r, shas = repo
    got = casekit.resolve_repo(str(r / "sub"), "main", "2026-09-05T00:00:00Z", transcript_lines=[])
    assert got["commit"] == shas[0]
    assert got["path"] == str(r.resolve())
    assert got["subdir"] == "sub"


def test_resolve_repo_falls_back_to_commit_output_in_transcript(repo):
    r, shas = repo
    lines = [json.dumps({"message": {"content": f"[gone-branch {shas[1][:7]}] c1\n 1 file changed"}})]
    got = casekit.resolve_repo(str(r), "gone-branch", "2026-09-20T00:00:00Z", transcript_lines=lines)
    assert got["commit"] == shas[1]
    assert got["method"] == "transcript-commit-output"


def test_resolve_repo_returns_none_outside_git(tmp_path):
    assert casekit.resolve_repo(str(tmp_path), "HEAD", "2026-09-20T00:00:00Z", transcript_lines=[]) is None


def test_redact_leaves_base64_payloads_intact():
    blob = "iVBORw0KGgo" + "Q" * 250 + "W7jwvqkTjTNO1kxT3JVFy07yBQ/AIzaSyA1234567890abcdefghijklmnopqrstuv+ghp_abcdefghijklmnopqrstuvwxyz0123456789AB" + "Q" * 50
    line = json.dumps({"source": {"type": "base64", "data": blob}})
    assert casekit.redact_line(line) == (line, 0)


def test_redact_catches_key_after_escaped_newline():
    line = json.dumps({"content": "# fill in\nsk-ant-api03-abcdefghijklmnopqrstuvwxyz0123456789"})
    out, n = casekit.redact_line(line)
    assert n == 1 and "abcdefghijklmnop" not in out


def test_resolve_repo_uses_remote_tracking_branch_when_local_is_deleted(repo):
    r, shas = repo
    git(r, "update-ref", "refs/remotes/origin/merged-away", shas[1])
    got = casekit.resolve_repo(str(r), "merged-away", "2026-09-20T00:00:00Z", transcript_lines=[])
    assert got["commit"] == shas[1]


def test_expected_may_be_the_bare_string_ask():
    assert casekit.validate_case(good_case(expected="ask")) == []
    assert casekit.expected_rules("ask") == [casekit.ASK]
    assert casekit.expected_rules([{"final": "ask"}, {"tool": "Bash", "pattern": "x"}])[1]["tool"] == "Bash"
