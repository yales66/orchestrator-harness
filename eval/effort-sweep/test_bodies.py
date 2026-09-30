import json
from pathlib import Path

import run

BRIEF = "Fix the deploy drain so that in-flight jobs finish before shutdown."


def write_body(d: Path, name: str, first_user: str, effort):
    body = {"model": "claude-opus-5-5", "messages": [{"role": "user", "content": [{"type": "text", "text": first_user}]}]}
    if effort:
        body["output_config"] = {"effort": effort}
    (d / f"{name}.request.json").write_text(json.dumps(body))


def test_efforts_are_split_into_subagent_and_main_thread(tmp_path):
    write_body(tmp_path, "a", "<system-reminder>x</system-reminder>Call the Agent tool exactly once", "high")
    write_body(tmp_path, "b", BRIEF, "medium")
    write_body(tmp_path, "c", BRIEF, "medium")
    (tmp_path / "index.jsonl").write_text("{}\n")
    assert run.efforts_from_bodies(tmp_path, BRIEF) == {"subagent": ["medium"], "main": ["high"]}


def test_a_request_without_effort_is_reported_as_default(tmp_path):
    write_body(tmp_path, "b", BRIEF, None)
    assert run.efforts_from_bodies(tmp_path, BRIEF) == {"subagent": ["default"], "main": []}


def test_child_env_asks_claude_code_for_the_request_bodies(tmp_path):
    env = run.child_env(tmp_path / "cfg", tmp_path / "brief.md", "medium", tmp_path / "bodies")
    assert env["OTEL_LOG_RAW_API_BODIES"] == "file:" + str(tmp_path / "bodies")
