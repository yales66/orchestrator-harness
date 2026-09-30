import json

import pytest

from parse_usage import (aggregate, first_calls, first_transcript_call, group_summary, hook_events, last_heading,
                         playbook_delivered, render_md)


def usage(inp, create, read):
    return {
        "input_tokens": inp,
        "cache_creation_input_tokens": create,
        "cache_read_input_tokens": read,
        "output_tokens": 7,
    }


def assistant(msg_id, parent, u, model="claude-opus-5-5"):
    return json.dumps({
        "type": "assistant",
        "parent_tool_use_id": parent,
        "message": {"id": msg_id, "model": model, "usage": u, "content": []},
    })


def lines(*objs):
    return [o if isinstance(o, str) else json.dumps(o) for o in objs]


INIT = {"type": "system", "subtype": "init", "model": "claude-opus-5-5"}
TOOL_RESULT = {"type": "user", "parent_tool_use_id": None, "message": {"content": []}}


def test_takes_only_the_first_main_thread_call():
    stream = lines(
        INIT,
        assistant("msg_1", None, usage(3, 100, 20)),
        TOOL_RESULT,
        assistant("msg_2", None, usage(5, 400, 900)),
    )
    main = first_calls(stream)["main"]
    assert (main["input_tokens"], main["cache_creation_input_tokens"],
            main["cache_read_input_tokens"], main["total"]) == (3, 100, 20, 123)
    assert main["message_id"] == "msg_1"


def test_separates_main_and_subagent_by_parent_tool_use_id():
    stream = lines(
        INIT,
        assistant("msg_1", None, usage(3, 100, 20)),
        # 子智能体的调用夹在主线程两次调用之间，靠 parent_tool_use_id 认出
        assistant("msg_s1", "toolu_A", usage(2, 50, 0)),
        assistant("msg_s2", "toolu_A", usage(9, 60, 50)),
        assistant("msg_2", None, usage(5, 400, 900)),
    )
    calls = first_calls(stream)
    assert calls["main"]["message_id"] == "msg_1"
    sub = calls["subagent"]
    assert sub["message_id"] == "msg_s1"
    assert sub["parent_tool_use_id"] == "toolu_A"
    assert sub["total"] == 52


def test_missing_subagent_is_none_and_non_json_lines_are_skipped():
    stream = ["not json", "", *lines(INIT, assistant("msg_1", None, usage(1, 2, 3)))]
    calls = first_calls(stream)
    assert calls["main"]["total"] == 6
    assert calls["subagent"] is None


def test_reports_model_of_each_first_call():
    stream = lines(
        assistant("msg_1", None, usage(1, 1, 1), model="claude-opus-5-5"),
        assistant("msg_s1", "toolu_A", usage(1, 1, 1), model="claude-other"),
    )
    calls = first_calls(stream)
    assert calls["main"]["model"] == "claude-opus-5-5"
    assert calls["subagent"]["model"] == "claude-other"


@pytest.mark.parametrize(
    "records, expected_id",
    [
        ([{"type": "user", "message": {"content": "hi"}},
          {"type": "assistant", "message": {"id": "m1", "model": "x", "usage": usage(1, 2, 3)}},
          {"type": "assistant", "message": {"id": "m2", "model": "x", "usage": usage(4, 5, 6)}}],
         "m1"),
        ([{"type": "assistant", "message": {"id": "m0", "model": "<synthetic>", "usage": usage(0, 0, 0)}},
          {"type": "assistant", "message": {"id": "m1", "model": "x", "usage": usage(1, 2, 3)}}],
         "m1"),
    ],
    ids=["first_assistant_in_transcript", "skips_synthetic_zero_usage"],
)
def test_first_transcript_call(records, expected_id):
    call = first_transcript_call(lines(*records))
    assert call["message_id"] == expected_id
    assert call["total"] == 6


def test_hook_events_lists_event_names_in_order_without_duplicates():
    stream = lines(
        {"type": "system", "subtype": "hook_started", "hook_event": "SessionStart", "hook_name": "SessionStart:startup"},
        {"type": "system", "subtype": "hook_response", "hook_event": "SessionStart", "hook_name": "SessionStart:startup"},
        INIT,
        {"type": "system", "subtype": "hook_started", "hook_event": "PreToolUse", "hook_name": "PreToolUse:Agent"},
    )
    assert hook_events(stream) == ["SessionStart", "PreToolUse"]


def _run(main_total, sub_total):
    return {"stream": {"main": {"total": main_total}, "subagent": {"total": sub_total}}}


@pytest.mark.parametrize(
    "runs, consistent",
    [
        ([_run(100, 50), _run(100, 50)], True),
        ([_run(100, 50), _run(101, 50)], False),
        ([_run(100, 50), _run(100, 49)], False),
    ],
    ids=["identical", "main_differs", "subagent_differs"],
)
def test_group_summary_flags_repeat_consistency(runs, consistent):
    g = group_summary(runs)
    assert g["consistent"] is consistent
    assert g["main_totals"] == [r["stream"]["main"]["total"] for r in runs]


def _summary(variant, main_total, sub_total):
    call = {"input_tokens": 2, "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0,
            "model": "claude-opus-5-5"}
    return {
        "variant": variant,
        "stream": {"main": dict(call, total=main_total), "subagent": dict(call, total=sub_total)},
        "transcript": {"main": {"total": main_total}, "subagent": {"total": sub_total}},
        "hook_events": [],
        "playbook_in_main_transcript": True,
        "playbook_in_subagent_transcript": variant == "N",
        "claude_md_bytes": 0,
    }


@pytest.fixture
def work_dir(tmp_path):
    """Run directories for groups H and N only, as run.sh leaves them."""
    totals = {"H": (19426, 9747), "N": (19415, 12440)}
    for v, (main_total, sub_total) in totals.items():
        for i in (1, 2):
            run = tmp_path / ("%s-%d" % (v, i))
            run.mkdir()
            (run / "summary.json").write_text(json.dumps(_summary(v, main_total, sub_total)))
    return tmp_path


def test_aggregate_reads_groups_h_and_n_and_compares_n_with_h(work_dir):
    res = aggregate(str(work_dir), "2.1.284", "claude-opus-5-5", 2)
    assert list(res["groups"]) == ["H", "N"]
    assert res["deltas_first_repeat"] == {"N_minus_H": {"main": -11, "subagent": 2693}}


def test_render_md_lists_only_groups_h_and_n(work_dir):
    md = render_md(aggregate(str(work_dir), "2.1.284", "claude-opus-5-5", 2))
    groups = {line.split("|")[1].strip() for line in md.splitlines()
              if line.startswith("| ") and len(line.split("|")) > 2}
    assert {"H", "N"} <= groups
    assert "V" not in groups
    assert "| N minus H | -11 | +2693 |" in md


PLAYBOOK = "# Orchestrator Playbook\n\n## 0. Keep conclusions\n\nbody\n\n## 5. Git\n\n- tail rule\n"
PREVIEW = ("<persisted-output>\nOutput too large (13.5KB). Full output saved to: /x/hook.txt\n\n"
           "Preview (first 2KB):\n# Orchestrator Playbook\n\n## 0. Keep conclusions\n...\n</persisted-output>")


def _attachment(kind, **fields):
    return {"type": "attachment", "attachment": dict(type=kind, **fields)}


def test_last_heading_is_the_final_section_title():
    assert last_heading(PLAYBOOK) == "## 5. Git"


@pytest.mark.parametrize(
    "records, delivered",
    [
        ([_attachment("hook_additional_context", content=[PLAYBOOK])], True),
        ([_attachment("instructions", files=[{"path": "CLAUDE.md", "content": "rules\n\n" + PLAYBOOK}])], True),
        ([_attachment("hook_success", stdout=PLAYBOOK),
          _attachment("hook_additional_context", content=[PREVIEW])], False),
        ([], False),
    ],
    ids=["hook_full", "claude_md", "hook_preview_only", "absent"],
)
def test_playbook_delivered_needs_the_final_heading_in_model_bound_context(records, delivered):
    assert playbook_delivered(lines(*records), last_heading(PLAYBOOK)) is delivered


@pytest.mark.parametrize("copy", ["en", "zh"])
def test_render_md_names_the_installed_copy(work_dir, copy):
    md = render_md(aggregate(str(work_dir), "2.1.285", "claude-opus-5-5", 2, copy=copy))
    assert "%s/CLAUDE.md, %s/hooks" % (copy, copy) in md
    other = "zh" if copy == "en" else "en"
    assert "%s/CLAUDE.md" % other not in md
