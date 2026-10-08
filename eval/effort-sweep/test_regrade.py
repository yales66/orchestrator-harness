"""Tests for keeping answer files in raw/ and for `regrade`.

Run: python3 -m pytest eval/effort-sweep/test_regrade.py -q
"""
import json
from argparse import Namespace

import pytest

import run

WS = "/tmp/effort-sweep-c-r0-1"
OUT = "/tmp/effort-sweep-c-x/out"


def case(cid="c", tier="lookup", answer_files=(), checks=None, allowed=()):
    return {"id": cid, "tier": tier, "answer_files": list(answer_files), "allowed_outputs": list(allowed),
            "checks": checks or [{"id": "k", "any": ["ALPHA"], "desc": "alpha"}]}


def write_cases(data, cases):
    data.mkdir(parents=True, exist_ok=True)
    (data / "cases.jsonl").write_text("".join(json.dumps(c) + "\n" for c in cases), encoding="utf-8")


def tool_use(uid, name, **inp):
    return {"type": "assistant", "cwd": WS,
            "message": {"content": [{"type": "tool_use", "id": uid, "name": name, "input": inp}]}}


def tool_result(uid, error=False):
    return {"type": "user", "cwd": WS,
            "message": {"content": [{"type": "tool_result", "tool_use_id": uid, "is_error": error, "content": "x"}]}}


def say(text):
    return {"type": "assistant", "cwd": WS, "message": {"content": [{"type": "text", "text": text}]}}


def result_row(cid="c", rep=0, tier="lookup", grade=None, status="ok", stray=(), extra_meta=None):
    meta = {"tier": tier, "grade_detail": {"stray_writes": list(stray)}}
    meta.update(extra_meta or {})
    return {"prompt_id": cid, "rep": rep, "status": status, "grade": grade or {"pass": 0, "checks": 0.0},
            "explanation": {"pass": "old"}, "meta": meta}


def write_attempt(arm, row, transcript, saved=None):
    """Append `row` to arm/results.jsonl and write its raw dir with the transcript and saved answer files."""
    arm.mkdir(parents=True, exist_ok=True)
    with open(arm / "results.jsonl", "a", encoding="utf-8") as fh:
        fh.write(json.dumps(row) + "\n")
    raw = arm / "raw" / f"{row['prompt_id']}_rep{row['rep']}"
    raw.mkdir(parents=True, exist_ok=True)
    (raw / "subagent.jsonl").write_text("".join(json.dumps(r) + "\n" for r in transcript), encoding="utf-8")
    for name, text in (saved or {}).items():
        (raw / "answer_files").mkdir(exist_ok=True)
        (raw / "answer_files" / name).write_text(text, encoding="utf-8")
    return raw


def regrade(data, arms="v1", dry_run=False):
    return run.cmd_regrade(Namespace(data=data, arms=arms, dry_run=dry_run))


# ---------------------------------------------------------------- saving answer files

@pytest.mark.parametrize("tmpl,name", [
    ("{ws}/design/.bak/flow-facts.md", "design__.bak__flow-facts.md"),
    ("{out}/macos27-adoption.md", "macos27-adoption.md"),
    ("{ws}/a.md", "a.md"),
], ids=["ws-nested", "out-top", "ws-top"])
def test_answer_file_key_flattens_the_path_after_the_placeholder(tmpl, name):
    assert run.answer_file_key(tmpl) == name


def test_save_answer_files_copies_each_file_read_for_grading(tmp_path):
    ws, out, raw = tmp_path / "ws", tmp_path / "out", tmp_path / "raw"
    (ws / "design" / ".bak").mkdir(parents=True)
    (ws / "design" / ".bak" / "flow-facts.md").write_bytes(b"facts \xff")
    out.mkdir()
    (out / "r.md").write_text("report", encoding="utf-8")
    c = case(answer_files=["{ws}/design/.bak/flow-facts.md", "{out}/r.md", "{ws}/absent.md"])

    run.save_answer_files(c, ws, out, raw)

    saved = raw / "answer_files"
    assert sorted(p.name for p in saved.iterdir()) == ["design__.bak__flow-facts.md", "r.md"]
    assert (saved / "design__.bak__flow-facts.md").read_bytes() == b"facts \xff"


def test_save_answer_files_makes_no_dir_when_case_has_none(tmp_path):
    run.save_answer_files(case(), tmp_path, tmp_path, tmp_path / "raw")
    assert not (tmp_path / "raw" / "answer_files").exists()


# ---------------------------------------------------------------- rebuilding from the transcript

@pytest.mark.parametrize("transcript,expected", [
    ([tool_use("w", "Write", file_path=f"{WS}/a.md", content="one ALPHA two")], "one ALPHA two"),
    ([tool_use("w", "Write", file_path=f"{WS}/a.md", content="x y x"),
      tool_use("e", "Edit", file_path=f"{WS}/a.md", old_string="x", new_string="z")], "z y x"),
    ([tool_use("w", "Write", file_path=f"{WS}/a.md", content="x y x"),
      tool_use("e", "Edit", file_path=f"{WS}/a.md", old_string="x", new_string="z", replace_all=True)], "z y z"),
    ([tool_use("w1", "Write", file_path=f"{WS}/a.md", content="first"),
      tool_use("e1", "Edit", file_path=f"{WS}/a.md", old_string="first", new_string="edited"),
      tool_use("w2", "Write", file_path=f"{WS}/a.md", content="second")], "second"),
    ([tool_use("w", "Write", file_path=f"{WS}/a.md", content="a b"),
      tool_use("e1", "Edit", file_path=f"{WS}/a.md", old_string="a", new_string="c"),
      tool_use("e2", "Edit", file_path=f"{WS}/a.md", old_string="c b", new_string="done")], "done"),
    ([tool_use("w", "Write", file_path=f"{WS}/a.md", content="keep"),
      tool_use("e", "Edit", file_path=f"{WS}/a.md", old_string="keep", new_string="lost"),
      tool_result("e", error=True)], "keep"),
    ([tool_use("w", "Write", file_path=f"{WS}/other/a.md", content="wrong")], None),
    ([tool_use("e", "Edit", file_path=f"{WS}/a.md", old_string="x", new_string="y")], None),
    ([], None),
], ids=["write-only", "edit-first-occurrence", "edit-replace-all", "last-write-wins", "edits-in-order",
        "failed-edit-skipped", "other-path-ignored", "edit-without-write", "no-calls"])
def test_rebuild_answer_file(transcript, expected):
    assert run.rebuild_answer_file(transcript, "{ws}/a.md") == expected


def test_rebuild_matches_out_files_by_the_out_dir():
    transcript = [tool_use("w", "Write", file_path=f"{OUT}/r.md", content="from out")]
    assert run.rebuild_answer_file(transcript, "{out}/r.md") == "from out"


# ---------------------------------------------------------------- regrade

def test_regrade_rebuilds_answer_and_keeps_report_format(tmp_path):
    data = tmp_path / "data"
    write_cases(data, [case(answer_files=["{ws}/a.md"],
                            checks=[{"id": "k", "any": [r"\[a\.md\]\nALPHA"], "desc": "header then body"}])])
    write_attempt(data / "v1", result_row(),
                  [tool_use("w", "Write", file_path=f"{WS}/a.md", content="ALPHA"), say("report")])

    assert regrade(data) == 0

    r = run.read_jsonl(data / "v1" / "results.jsonl")[0]
    assert r["grade"] == {"pass": 1, "checks": 1.0}


@pytest.mark.parametrize("saved,transcript_text,source", [
    ({"a.md": "ALPHA"}, "nothing", "saved"),
    ({}, "ALPHA", "rebuilt"),
    ({"a.md": "ALPHA"}, "ALPHA", "saved"),
], ids=["saved-only", "rebuilt-only", "saved-wins"])
def test_regrade_prefers_saved_over_rebuilt(tmp_path, capsys, saved, transcript_text, source):
    data = tmp_path / "data"
    write_cases(data, [case(answer_files=["{ws}/a.md"])])
    write_attempt(data / "v1", result_row(),
                  [tool_use("w", "Write", file_path=f"{WS}/a.md", content=transcript_text), say("report")], saved)

    regrade(data)

    assert run.read_jsonl(data / "v1" / "results.jsonl")[0]["grade"]["pass"] == 1
    assert f"{source} 1" in capsys.readouterr().out


def test_saved_file_is_used_even_when_transcript_disagrees(tmp_path):
    data = tmp_path / "data"
    write_cases(data, [case(answer_files=["{ws}/a.md"], checks=[{"id": "k", "any": ["SAVED"], "desc": "s"}])])
    write_attempt(data / "v1", result_row(),
                  [tool_use("w", "Write", file_path=f"{WS}/a.md", content="REBUILT"), say("report")], {"a.md": "SAVED"})
    regrade(data)
    assert run.read_jsonl(data / "v1" / "results.jsonl")[0]["grade"]["pass"] == 1


def test_regrade_counts_missing_answer_files(tmp_path, capsys):
    data = tmp_path / "data"
    write_cases(data, [case(answer_files=["{ws}/a.md", "{out}/b.md"])])
    write_attempt(data / "v1", result_row(), [say("ALPHA")])
    regrade(data)
    out = capsys.readouterr().out
    assert "saved 0" in out and "rebuilt 0" in out and "missing 2" in out
    assert run.read_jsonl(data / "v1" / "results.jsonl")[0]["grade"]["pass"] == 1


def test_grade_original_is_kept_from_the_first_regrade_only(tmp_path):
    data = tmp_path / "data"
    write_cases(data, [case()])
    write_attempt(data / "v1", result_row(grade={"pass": 0, "checks": 0.25}), [say("ALPHA")])

    regrade(data)
    first = run.read_jsonl(data / "v1" / "results.jsonl")[0]
    write_cases(data, [case(checks=[{"id": "k", "any": ["BETA"], "desc": "beta"}])])
    regrade(data)
    second = run.read_jsonl(data / "v1" / "results.jsonl")[0]

    assert first["grade"] == {"pass": 1, "checks": 1.0}
    assert first["meta"]["grade_original"] == {"pass": 0, "checks": 0.25}
    assert second["meta"]["grade_original"] == {"pass": 0, "checks": 0.25}
    assert second["grade"]["pass"] == 0
    assert second["meta"]["grade_detail"]["checks"][0] == {"id": "k", "ok": False, "note": "no match: beta"}
    assert second["meta"]["regraded_at"]


def test_regrade_carries_recorded_stray_writes_into_readonly(tmp_path):
    data = tmp_path / "data"
    write_cases(data, [case()])
    write_attempt(data / "v1", result_row(stray=["notes.md"]), [say("ALPHA")])
    regrade(data)
    r = run.read_jsonl(data / "v1" / "results.jsonl")[0]
    assert r["grade"]["pass"] == 0
    assert r["meta"]["grade_detail"]["stray_writes"] == ["notes.md"]


@pytest.mark.parametrize("row", [
    result_row(tier="impl", grade={"pass": 0, "checks": 0.5}),
    result_row(status="truncated", grade={"pass": 0, "checks": 0.5}),
], ids=["impl", "not-ok"])
def test_regrade_leaves_impl_and_non_ok_rows_untouched(tmp_path, row):
    data = tmp_path / "data"
    write_cases(data, [case(tier=row["meta"]["tier"])])
    write_attempt(data / "v1", row, [say("ALPHA")])
    regrade(data)
    assert run.read_jsonl(data / "v1" / "results.jsonl")[0] == row


def test_dry_run_prints_changes_and_writes_nothing(tmp_path, capsys):
    data = tmp_path / "data"
    write_cases(data, [case()])
    write_attempt(data / "v1", result_row(grade={"pass": 0, "checks": 0.5}), [say("ALPHA")])
    before = (data / "v1" / "results.jsonl").read_bytes()

    assert regrade(data, dry_run=True) == 0

    assert (data / "v1" / "results.jsonl").read_bytes() == before
    assert not list((data / "v1").glob("*.tmp"))
    out = capsys.readouterr().out
    assert "c rep0" in out and "pass 0->1" in out and "checks 0.50->1.00" in out


def test_summary_counts_rows_and_pass_changes(tmp_path, capsys):
    data = tmp_path / "data"
    write_cases(data, [case("c"), case("d")])
    write_attempt(data / "v1", result_row("c", grade={"pass": 0, "checks": 0.0}), [say("ALPHA")])
    write_attempt(data / "v1", result_row("d", grade={"pass": 1, "checks": 1.0}), [say("ALPHA")])
    write_attempt(data / "v1", result_row("c", rep=1, tier="impl"), [say("ALPHA")])
    regrade(data)
    summary = [l for l in capsys.readouterr().out.splitlines() if l.startswith("v1:")]
    assert summary and "regraded 2 row(s)" in summary[0] and "pass changed on 1" in summary[0]


def test_regrade_is_wired_to_the_cli():
    args = run.build_parser().parse_args(["regrade", "--data", "/x", "--arms", "a,b", "--dry-run"])
    assert args.cmd == "regrade" and args.arms == "a,b" and args.dry_run
