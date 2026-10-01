import json

import pytest

from parse_usage import (aggregate, check_work, deferred_tool_names, first_calls, first_transcript_call,
                         group_summary, hook_events, invalid_runs, last_heading, playbook_delivered, render_md)


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


def _summary(variant, main_total, sub_total, sub_model="claude-opus-5-5", deferred=None):
    call = {"input_tokens": 2, "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0,
            "model": "claude-opus-5-5"}
    out = {
        "variant": variant,
        "stream": {"main": dict(call, total=main_total),
                   "subagent": dict(call, total=sub_total, model=sub_model)},
        "transcript": {"main": {"total": main_total}, "subagent": {"total": sub_total}},
        "hook_events": [],
        "playbook_in_main_transcript": True,
        "playbook_in_subagent_transcript": variant == "N",
        "claude_md_bytes": 0,
    }
    if deferred is not None:
        out["deferred_tools"] = deferred
    return out


def _write_runs(root, summaries, discarded=None):
    """Lay out <root>/<name>/summary.json per run, plus discarded_attempts where given."""
    for name, summary in summaries.items():
        run = root / name
        run.mkdir()
        (run / "summary.json").write_text(json.dumps(summary))
        if discarded and name in discarded:
            (run / "discarded_attempts").write_text("%d\n" % discarded[name])
    return root


@pytest.fixture
def work_dir(tmp_path):
    """Run directories for groups H and N only, as run.sh leaves them."""
    totals = {"H": (19426, 9747), "N": (19415, 12440)}
    return _write_runs(tmp_path, {"%s-%d" % (v, i): _summary(v, *totals[v])
                                  for v in totals for i in (1, 2)})


def test_aggregate_reads_groups_h_and_n_and_compares_n_with_h(work_dir):
    res = aggregate(str(work_dir), "2.1.284", "claude-opus-5-5", 2)
    assert list(res["groups"]) == ["H", "N"]
    assert res["deltas_first_valid_run"] == {"N_minus_H": {"main": -11, "subagent": 2693}}


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
    assert "%s/skills, %s/agents, orchestrator-playbook.md" % (copy, copy) in md
    other = "zh" if copy == "en" else "en"
    assert "%s/CLAUDE.md" % other not in md


# ---- run validity: subagent model and deferred tool set ---------------------

BASE_TOOLS = ["EnterWorktree", "ExitWorktree", "Monitor", "NotebookEdit", "SendMessage", "TaskStop",
              "WebFetch", "WebSearch"]
EXTRA_TOOLS = ["CronCreate", "CronDelete", "CronList", "DesignSync", "PushNotification", "RemoteTrigger"]
FULL_TOOLS = sorted(BASE_TOOLS + EXTRA_TOOLS)
HAIKU = "claude-haiku-4-5-20251001"


def _delta(added=(), removed=(), readded=()):
    return _attachment("deferred_tools_delta", addedNames=list(added), removedNames=list(removed),
                       readdedNames=list(readded))


@pytest.mark.parametrize(
    "records, names",
    [
        ([_delta(added=["B", "A"]), assistant("m1", None, usage(1, 1, 1))], ["A", "B"]),
        ([_delta(added=["A", "B"]), _delta(removed=["A"], readded=["C"])], ["B", "C"]),
        ([_delta(added=["A"]), assistant("m1", None, usage(1, 1, 1)), _delta(added=["B"])], ["A"]),
        ([_attachment("skill_listing", addedNames=["X"]), assistant("m1", None, usage(1, 1, 1))], []),
    ],
    ids=["sorted_added_names", "removed_and_readded", "ignores_deltas_after_first_call", "other_attachments"],
)
def test_deferred_tool_names_is_the_set_before_the_first_call(records, names):
    assert deferred_tool_names(lines(*records)) == names


def _judged(sub_model="claude-opus-5-5", main=FULL_TOOLS, sub=FULL_TOOLS, variant="H"):
    return _summary(variant, 100, 50, sub_model=sub_model, deferred={"main": list(main), "subagent": list(sub)})


# The last case mirrors the logged runs: two haiku subagents, and among the two
# opus runs one subagent got six extra deferred tools.
@pytest.mark.parametrize(
    "runs, invalid",
    [
        ({"H-1": _judged(), "H-2": _judged(), "N-1": _judged(), "N-2": _judged()}, []),
        ({"H-1": _judged(), "H-2": _judged(sub_model=HAIKU), "N-1": _judged(), "N-2": _judged()}, ["H-2"]),
        ({"H-1": _judged(), "H-2": _judged(), "N-1": _judged(sub=BASE_TOOLS), "N-2": _judged()}, ["N-1"]),
        ({"H-1": _judged(), "H-2": _judged(main=BASE_TOOLS), "N-1": _judged(), "N-2": _judged()}, ["H-2"]),
        ({"H-1": _judged(), "N-1": _judged(sub=BASE_TOOLS)}, ["H-1"]),
        ({"H-1": _judged(), "H-2": _judged(sub_model=HAIKU), "N-1": _judged(sub_model=HAIKU),
          "N-2": _judged(sub=BASE_TOOLS)}, ["H-1", "H-2", "N-1"]),
    ],
    ids=["all_comparable", "subagent_model_differs", "majority_subagent_set_wins", "main_set_compared_too",
         "tie_prefers_fewer_tools", "model_invalid_runs_do_not_vote"],
)
def test_invalid_runs(runs, invalid):
    assert sorted(invalid_runs(runs, "claude-opus-5-5")) == invalid


def test_invalid_runs_flags_a_missing_subagent_call():
    run = _judged()
    run["stream"]["subagent"] = None
    assert list(invalid_runs({"H-1": _judged(), "H-2": run}, "claude-opus-5-5")) == ["H-2"]


def test_invalid_runs_gives_a_reason_per_rule():
    reasons = invalid_runs({"H-1": _judged(sub_model=HAIKU), "N-1": _judged(sub=BASE_TOOLS),
                            "N-2": _judged(sub=BASE_TOOLS), "H-2": _judged()}, "claude-opus-5-5")
    assert "claude-haiku-4-5-20251001" in " ".join(reasons["H-1"])
    assert "CronCreate" in " ".join(reasons["H-2"])


def _write_transcripts(run, main_records, sub_records):
    """Transcripts in the layout Claude Code writes under CLAUDE_CONFIG_DIR/projects."""
    proj = run / "config" / "projects" / "-cwd"
    (proj / "sess" / "subagents").mkdir(parents=True)
    (proj / "sess.jsonl").write_text("\n".join(lines(*main_records)) + "\n")
    (proj / "sess" / "subagents" / "agent-a1.jsonl").write_text("\n".join(lines(*sub_records)) + "\n")


def test_check_work_lists_invalid_run_dirs_in_order_and_skips_other_dirs(tmp_path):
    _write_runs(tmp_path, {"H-1": _judged(), "H-2": _judged(sub_model=HAIKU), "N-1": _judged(),
                           "N-2": _judged(sub_model=HAIKU), "N-10": _judged()})
    (tmp_path / "H-setup").mkdir()
    assert check_work(str(tmp_path), "claude-opus-5-5") == ["H-2", "N-2"]


def test_check_work_reads_deferred_tools_from_transcripts_when_the_summary_lacks_them(tmp_path):
    _write_runs(tmp_path, {"H-1": _summary("H", 100, 50), "N-1": _judged(sub=BASE_TOOLS),
                           "N-2": _judged(sub=BASE_TOOLS)})
    first = assistant("m1", None, usage(1, 1, 1))
    _write_transcripts(tmp_path / "H-1", [_delta(added=FULL_TOOLS), first], [_delta(added=FULL_TOOLS), first])
    assert check_work(str(tmp_path), "claude-opus-5-5") == ["H-1"]


def test_check_command_prints_one_run_dir_per_line(tmp_path, capsys):
    import parse_usage
    _write_runs(tmp_path, {"H-1": _judged(sub_model=HAIKU), "H-2": _judged(), "N-1": _judged(sub_model=HAIKU)})
    assert parse_usage._main(["parse_usage.py", "check", str(tmp_path), "claude-opus-5-5"]) == 0
    assert capsys.readouterr().out == "H-1\nN-1\n"


@pytest.fixture
def mixed_work(tmp_path):
    """H-1 ran its subagent on haiku and was retried twice; the other runs are comparable."""
    return _write_runs(tmp_path, {
        "H-1": _summary("H", 20317, 13188, sub_model=HAIKU, deferred={"main": [], "subagent": []}),
        "H-2": _summary("H", 20317, 10188, deferred={"main": [], "subagent": []}),
        "N-1": _summary("N", 20306, 13491, deferred={"main": [], "subagent": []}),
        "N-2": _summary("N", 20306, 13491, deferred={"main": [], "subagent": []}),
    }, discarded={"H-1": 3, "N-2": 1})


def test_aggregate_records_validity_discards_and_deferred_tools_per_run(mixed_work):
    res = aggregate(str(mixed_work), "2.1.285", "claude-opus-5-5", 2)
    h1, h2 = res["groups"]["H"]["runs"]
    assert (h1["valid"], h1["discarded_attempts"]) == (False, 3)
    assert (h2["valid"], h2["discarded_attempts"]) == (True, 0)
    assert res["groups"]["N"]["runs"][1]["discarded_attempts"] == 1
    assert h2["deferred_tools"] == {"main": [], "subagent": []}
    assert h1["invalid_reasons"]


def test_aggregate_compares_and_checks_consistency_on_valid_runs_only(mixed_work):
    res = aggregate(str(mixed_work), "2.1.285", "claude-opus-5-5", 2)
    assert res["deltas_first_valid_run"] == {"N_minus_H": {"main": -11, "subagent": 3303}}
    assert res["groups"]["H"]["subagent_totals"] == [10188]
    assert res["groups"]["H"]["consistent"] is True


def test_aggregate_reports_na_when_a_group_has_no_valid_run(tmp_path):
    _write_runs(tmp_path, {"H-1": _judged(sub_model=HAIKU), "N-1": _judged()})
    res = aggregate(str(tmp_path), "2.1.285", "claude-opus-5-5", 1)
    assert res["deltas_first_valid_run"] == {"N_minus_H": {"main": None, "subagent": None}}
    assert res["groups"]["H"]["consistent"] is None
    md = render_md(res)
    assert "| N minus H | n/a | n/a |" in md
    assert "| H | n/a | n/a | n/a |" in md


def test_render_md_adds_valid_and_discarded_columns(mixed_work):
    md = render_md(aggregate(str(mixed_work), "2.1.285", "claude-opus-5-5", 2))
    header = next(l for l in md.splitlines() if l.startswith("| Group | Run | Main input"))
    assert header.endswith("| Valid | Discarded attempts |")
    rows = [l for l in md.splitlines() if l.startswith("| H | 1 | 2 |")]
    assert rows and rows[0].endswith("| no | 3 |")
