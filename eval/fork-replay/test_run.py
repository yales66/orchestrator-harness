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
