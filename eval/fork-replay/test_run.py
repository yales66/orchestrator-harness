import json
import os
import tempfile
from pathlib import Path

import pytest

import run

REPO_EN = Path(__file__).resolve().parents[2] / "en"


def write_session(tmp_path, records):
    p = tmp_path / "sess.jsonl"
    p.write_text("\n".join(json.dumps(r) for r in records) + "\n")
    return str(p)


RECORDS = [
    {"uuid": "u0", "parentUuid": None, "type": "user", "message": {"content": "first prompt"}},
    {"uuid": "a0", "parentUuid": "u0", "type": "assistant", "message": {"content": [{"type": "text", "text": "ok"}]}},
    {"uuid": "u1", "parentUuid": "a0", "type": "user", "message": {"content": [{"type": "text", "text": "second prompt"}]}},
    {"uuid": "m1", "parentUuid": "u1", "type": "user", "isMeta": True, "message": {"content": "<system-reminder>x</system-reminder>"}},
    {"uuid": "a1", "parentUuid": "m1", "type": "assistant", "message": {"content": [{"type": "tool_use", "name": "Read", "input": {}}]}},
    {"uuid": "t1", "parentUuid": "a1", "type": "user", "message": {"content": [{"type": "tool_result", "content": "..."}]}},
    {"uuid": "a2", "parentUuid": "t1", "type": "assistant", "message": {"content": [{"type": "text", "text": "Shall I push?"}]}},
]


def case(path, mode, uuid, resume_input="Stop hook feedback:\nx"):
    return {"source_session": path, "fork_mode": mode, "fork_uuid": uuid, "resume_input": resume_input}


def test_after_mode_keeps_the_fork_message_and_sends_resume_input(tmp_path):
    p = write_session(tmp_path, RECORDS)
    assert run.fork_plan(case(p, "after", "a2")) == ("a2", "Stop hook feedback:\nx", 0)


def test_before_mode_rewinds_to_the_turn_prompt_skipping_tool_results_and_meta(tmp_path):
    p = write_session(tmp_path, RECORDS)
    at, prompt, rewound = run.fork_plan(case(p, "before", "a2", None))
    assert (at, prompt, rewound) == ("a0", "second prompt", 2)


def test_before_mode_refuses_the_first_turn(tmp_path):
    p = write_session(tmp_path, RECORDS)
    with pytest.raises(ValueError):
        run.fork_plan(case(p, "before", "a0", None))


def test_install_config_from_harness_tree(tmp_path):
    cfg = run._merge(run.DEFAULT_CFG, {"drop_hook_events": ["Stop"], "stub": {"extra_readonly": ["ToolSearch"]}})
    dest = run.install_config(str(REPO_EN), str(tmp_path / "config"), cfg, str(tmp_path / "calls.jsonl"))
    settings = json.load(open(os.path.join(dest, "settings.json")))
    assert "Stop" not in settings["hooks"]
    first = settings["hooks"]["PreToolUse"][0]
    assert first["matcher"] == "*" and "stub_hook.py" in first["hooks"][0]["command"]
    assert "$HOME/.claude" not in json.dumps(settings)
    assert not (Path(dest) / "hooks" / "tests").exists()
    stub = json.load(open(tmp_path / "stub.json"))
    assert stub["log"].endswith("calls.jsonl") and stub["extra_readonly"] == ["ToolSearch"]


def test_temp_root_is_the_resolved_system_temp_dir():
    # The session copy is placed under the slug of the cwd, and Claude Code sees that cwd
    # with symlinks resolved, so the root must already be a real path.
    assert run.TMP_ROOT == os.path.realpath(tempfile.gettempdir())


OLD_PLAYBOOK = "# 编排者 Playbook\n\nold rules\n"
NEW_PLAYBOOK = "# 编排者 Playbook\n\nnew rules\n"
INJECTED = [
    {"uuid": "h0", "parentUuid": None, "type": "attachment",
     "attachment": {"type": "hook_success", "hookEvent": "SessionStart",
                    "stdout": json.dumps({"hookSpecificOutput": {"hookEventName": "SessionStart",
                                                                 "additionalContext": OLD_PLAYBOOK}})}},
    {"uuid": "h1", "parentUuid": "h0", "type": "attachment",
     "attachment": {"type": "hook_additional_context", "hookEvent": "SessionStart",
                    "content": [OLD_PLAYBOOK, "other context"]},
     "rendered": [{"content": "<system-reminder>\nSessionStart hook additional context: " + OLD_PLAYBOOK
                              + "\n</system-reminder>", "isMeta": True}]},
] + [dict(r, parentUuid=r["parentUuid"] or "h1") for r in RECORDS]


def test_replace_playbook_swaps_every_injected_copy_and_nothing_else(tmp_path):
    p = write_session(tmp_path, INJECTED)
    assert run.replace_playbook(p, NEW_PLAYBOOK) == 2
    recs = [json.loads(l) for l in open(p)]
    assert recs[1]["attachment"]["content"] == [NEW_PLAYBOOK, "other context"]
    # Claude Code replays a resumed attachment from its pre-rendered text.
    assert recs[1]["rendered"][0]["content"] == ("<system-reminder>\nSessionStart hook additional context: "
                                                 + NEW_PLAYBOOK + "\n</system-reminder>")
    out = json.loads(recs[0]["attachment"]["stdout"])["hookSpecificOutput"]["additionalContext"]
    assert out == NEW_PLAYBOOK
    assert OLD_PLAYBOOK not in open(p).read()
    assert recs[2:] == [json.loads(json.dumps(r)) for r in INJECTED[2:]]


def test_replace_playbook_refuses_a_session_without_a_playbook(tmp_path):
    p = write_session(tmp_path, RECORDS)
    with pytest.raises(ValueError):
        run.replace_playbook(p, NEW_PLAYBOOK)


def test_install_config_writes_the_playbook_under_test(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "settings.json").write_text("{}")
    (src / "orchestrator-playbook.md").write_text(OLD_PLAYBOOK)
    dest = run.install_config(str(src), str(tmp_path / "cfg" / "config"), run.DEFAULT_CFG,
                              str(tmp_path / "calls.jsonl"), playbook=NEW_PLAYBOOK)
    assert (Path(dest) / "orchestrator-playbook.md").read_text() == NEW_PLAYBOOK


def test_raw_bodies_dir_is_passed_to_claude_code(tmp_path):
    env = run.child_env("/cfg", "/home", "claude-opus-5-5", str(tmp_path / "bodies"))
    assert env["OTEL_LOG_RAW_API_BODIES"] == "file:" + str(tmp_path / "bodies")
    assert "OTEL_LOG_RAW_API_BODIES" not in run.child_env("/cfg", "/home", "claude-opus-5-5", None)


@pytest.mark.parametrize("path, want", [
    ("/r/.claude/worktrees/fix-x", ("/r", "")),
    ("/r/.claude/worktrees/fix-x/web", ("/r", "web")),
], ids=["worktree-root", "worktree-subdir"])
def test_removed_worktree_resolves_to_its_main_repository(path, want):
    assert run.resolve_repo({"path": path, "commit": "c"}) == want


def test_existing_repository_is_used_as_recorded(tmp_path):
    assert run.resolve_repo({"path": str(tmp_path), "commit": "c", "subdir": "s"}) == (str(tmp_path), "s")


def test_harness_approval_is_kept_per_variant(tmp_path):
    before, after = tmp_path / "before.md", tmp_path / "after.md"
    before.write_text("# 编排者 Playbook\n\nbefore\n")
    after.write_text("# 编排者 Playbook\n\nafter\n")
    cfg = tmp_path / "cfg.json"
    cfg.write_text("{}")

    def args(variant, playbook, approve=False):
        return run.parse_args(["--cases", str(cfg), "--flow", str(tmp_path), "--config", str(REPO_EN),
                               "--grader", str(cfg), "--eval-config", str(cfg), "--variant", variant,
                               "--playbook", str(playbook)] + (["--approve-harness"] if approve else []))

    run.check_harness(args("baseline", before, True), str(tmp_path))
    run.check_harness(args("v1", after, True), str(tmp_path))
    run.check_harness(args("baseline", before), str(tmp_path))
    run.check_harness(args("v1", after), str(tmp_path))
    with pytest.raises(SystemExit):
        run.check_harness(args("v1", before), str(tmp_path))


def test_replays_run_at_effort_high_by_default(tmp_path, monkeypatch):
    import sys
    import types
    fake = types.ModuleType("claude_agent_sdk")
    fake.ClaudeAgentOptions = lambda **kw: kw
    monkeypatch.setitem(sys.modules, "claude_agent_sdk", fake)
    args = run.parse_args(["--cases", "c", "--flow", "f", "--config", "x", "--grader", "g", "--eval-config", "e"])
    case = {"source_session": "/s/abc.jsonl"}
    opts = run.build_options(case, run.DEFAULT_CFG, args, "/cwd", "/cfg", "/home", "u1", str(tmp_path / "err.log"))
    assert opts["effort"] == "high"


CUT_RECORDS = [
    {"type": "mode", "mode": "default"},
    {"uuid": "h0", "parentUuid": None, "type": "attachment",
     "attachment": {"type": "hook_additional_context", "hookEvent": "SessionStart", "content": [OLD_PLAYBOOK]}},
    {"uuid": "u0", "parentUuid": "h0", "type": "user", "message": {"content": "earlier task"}},
    {"uuid": "s0", "parentUuid": "u0", "type": "attachment", "attachment": {"type": "skill_listing", "content": "skills"}},
    {"uuid": "x0", "parentUuid": "s0", "type": "attachment", "attachment": {"type": "edited_text_file", "content": "f"}},
    {"uuid": "a0", "parentUuid": "x0", "type": "assistant", "message": {"content": [{"type": "text", "text": "done"}]}},
    {"uuid": "u1", "parentUuid": "a0", "type": "user", "message": {"content": [{"type": "text", "text": "new task"}]}},
    {"uuid": "a1", "parentUuid": "u1", "type": "assistant", "message": {"content": [{"type": "tool_use", "name": "Read", "input": {}}]}},
    {"uuid": "t1", "parentUuid": "a1", "type": "user", "message": {"content": [{"type": "tool_result", "content": "..."}]}},
    {"uuid": "u2", "parentUuid": "t1", "type": "user", "message": {"content": "go on"}},
    {"uuid": "a2", "parentUuid": "u2", "type": "assistant", "message": {"content": [{"type": "text", "text": "Shall I push?"}]}},
]


def test_cut_session_drops_the_earlier_task_but_keeps_session_level_records(tmp_path):
    p = write_session(tmp_path, CUT_RECORDS)
    assert run.cut_session(p, "u1") == 3
    recs = [json.loads(l) for l in open(p)]
    assert [r.get("uuid") for r in recs] == [None, "h0", "s0", "u1", "a1", "t1", "u2", "a2"]
    parent = {r["uuid"]: r["parentUuid"] for r in recs if r.get("uuid")}
    assert parent["s0"] == "h0" and parent["u1"] == "s0" and parent["a1"] == "u1"


def test_before_mode_resumes_on_the_cut_chain(tmp_path):
    p = write_session(tmp_path, CUT_RECORDS)
    run.cut_session(p, "u2")
    assert run.fork_plan(case(p, "before", "a2", None)) == ("s0", "go on", 1)


@pytest.mark.parametrize("cut", ["nope", "t1", "u0"], ids=["missing", "tool-result", "first-prompt"])
def test_cut_session_refuses_a_cut_that_is_not_a_later_prompt(tmp_path, cut):
    p = write_session(tmp_path, CUT_RECORDS)
    with pytest.raises(ValueError):
        run.cut_session(p, cut)


def test_attempt_root_is_the_same_for_every_rep_of_a_case_and_variant():
    # The path reaches the system prompt, so a fixed one lets later reps read the cached prefix.
    a = run.attempt_root({"id": "abc123def456789"}, "baseline")
    assert a == run.attempt_root({"id": "abc123def456789"}, "baseline")
    assert a != run.attempt_root({"id": "abc123def456789"}, "v1")
    assert os.path.dirname(a) == run.TMP_ROOT


def test_reps_of_one_case_are_grouped_to_run_in_order():
    c1, c2 = {"id": "c1"}, {"id": "c2"}
    assert run.group_reps([(c1, 1), (c2, 0), (c1, 0)]) == [[(c1, 0), (c1, 1)], [(c2, 0)]]
