"""Tests for the hidden-test pass ratio of impl rows and for regrade reading meta.changed.

Run: python3 -m pytest eval/effort-sweep/test_hidden.py -q
"""
import json
import re
import statistics
from argparse import Namespace

import pytest

import run


def hidden_run(out: str, code=1) -> dict:
    return {"cmd": "pytest -q", "code": code, "ok": code == 0, "seconds": 1.0, "out": out}


def detail(*outs, code=1) -> dict:
    return {"hidden": [hidden_run(o, code) for o in outs]}


def row(cid: str, checks: float = 1.0, hidden=None, rep: int = 0, band=None) -> dict:
    """An ok impl row; `hidden` is a list of hidden-command outputs or None for a row without grade_detail."""
    meta = {"tier": "impl", "band": band}
    if hidden is not None:
        meta["grade_detail"] = detail(*hidden)
    return {"prompt_id": cid, "rep": rep, "status": "ok", "meta": meta, "latency_s": 1.0,
            "grade": {"pass": checks == 1.0, "checks": checks}, "usage": {"input_tokens": 100, "output_tokens": 10}}


def write_arm(path, rows: list[dict]) -> None:
    path.mkdir(parents=True)
    (path / "results.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")


def summarize(tmp_path, capsys, ref_rows, arm_rows) -> list[str]:
    write_arm(tmp_path / "baseline", ref_rows)
    write_arm(tmp_path / "v1", arm_rows)
    run.cmd_summarize(Namespace(data=tmp_path, ref="baseline", arms="v1"))
    return capsys.readouterr().out.splitlines()


def passed_of(n_pass: int, n_total: int) -> str:
    return f"{n_total - n_pass} failed, {n_pass} passed in 0.10s"


# ---------------------------------------------------------------- hidden_tests

@pytest.mark.parametrize("out,expected", [
    ("FAILED a.py::t\n4 failed, 32 passed in 0.25s\n", (32, 36)),
    ("........ [100%]\n77 passed in 0.40s\n", (77, 77)),
    ("===== 2 failed, 10 passed, 1 error in 1.2s =====", (10, 13)),
    ("5 passed, 2 skipped in 0.3s", (5, 5)),
    ("3 passed, 2 errors in 0.3s", (3, 5)),
    ("1 error in 0.05s", (0, 1)),
    (" Test Files  1 failed (1)\n      Tests  3 failed | 33 passed (36)\n   Duration  1.2s", (33, 36)),
    (" Test Files  1 passed (1)\n      Tests  36 passed (36)\n", (36, 36)),
    ("      Tests  1 failed | 30 passed | 2 skipped (33)\n", (30, 31)),
    ("\x1b[2m      Tests \x1b[22m \x1b[1m\x1b[31m2 failed\x1b[39m\x1b[22m\x1b[2m | \x1b[22m\x1b[1m\x1b[32m8 passed\x1b[39m\x1b[22m (10)",
     (8, 10)),
    ("1 failed, 9 passed in 0.1s\nrerun\n10 passed in 0.1s\n", (10, 10)),
], ids=["pytest-failed-passed", "pytest-all-passed", "pytest-error-counts-as-failure", "pytest-skipped-excluded",
        "pytest-errors-plural", "pytest-error-only", "vitest-failed-passed", "vitest-all-passed",
        "vitest-skipped-excluded", "vitest-ansi-colours", "last-summary-line-wins"])
def test_hidden_tests_parses_summary_line(out, expected):
    assert run.hidden_tests(detail(out)) == expected


def test_hidden_tests_sums_over_commands():
    assert run.hidden_tests(detail("4 failed, 32 passed in 0.25s", "Tests  36 passed (36)")) == (68, 72)


def test_hidden_tests_skips_commands_it_cannot_parse():
    assert run.hidden_tests(detail("77 passed in 0.40s", "Traceback: boom")) == (77, 77)


@pytest.mark.parametrize("d", [
    {},
    {"hidden": []},
    detail("Traceback (most recent call last):\nImportError"),
    detail("no tests ran in 0.01s"),
    detail("2 skipped in 0.01s"),
    {"hidden": [hidden_run("1 failed, 3 passed in 0.1s", code=None)]},
], ids=["no-hidden-key", "empty-hidden", "no-summary-line", "no-tests-ran", "only-skipped", "timed-out"])
def test_hidden_tests_none_when_nothing_parses(d):
    assert run.hidden_tests(d) is None


# ---------------------------------------------------------------- summarize_variant

HIDDEN_TAIL = re.compile(r", hidden tests ([\d.]+) \(n=(\d+)\)$")


def impl_line(tmp_path, capsys, rows) -> str:
    write_arm(tmp_path / "v1", rows)
    run.summarize_variant(tmp_path / "v1")
    return next(l for l in capsys.readouterr().out.splitlines() if " impl " in l)


def test_group_line_appends_mean_hidden_ratio_over_rows_that_parse(tmp_path, capsys):
    line = impl_line(tmp_path, capsys, [row("c0", hidden=[passed_of(3, 4)]), row("c1", hidden=[passed_of(1, 4)]),
                                        row("c2", hidden=["boom"]), row("c3")])
    m = HIDDEN_TAIL.search(line)
    assert m, line
    assert float(m[1]) == pytest.approx(statistics.mean([0.75, 0.25]), abs=5e-3)
    assert int(m[2]) == 2


@pytest.mark.parametrize("rows", [
    [row("c0"), row("c1")],
    [row("c0", hidden=["boom"]), row("c1", hidden=[])],
], ids=["no-grade-detail", "nothing-parses"])
def test_group_line_unchanged_without_hidden_ratio(tmp_path, capsys, rows):
    assert "hidden tests" not in impl_line(tmp_path, capsys, rows)


def test_band_group_gets_its_own_hidden_ratio(tmp_path, capsys):
    write_arm(tmp_path / "v1", [row("c0", hidden=[passed_of(1, 4)], band="hard"), row("c1", band="easy")])
    run.summarize_variant(tmp_path / "v1")
    out = capsys.readouterr().out.splitlines()
    hard = next(l for l in out if "band hard" in l)
    easy = next(l for l in out if "band easy" in l)
    assert hard.endswith(", hidden tests 0.25 (n=1)")
    assert "hidden tests" not in easy


# ---------------------------------------------------------------- print_paired

PAIRED_HIDDEN = re.compile(
    r"^  (\S+(?: \S+)?)\s+hidden tests diff ([+-][\d.]+) \(95% CI ([+-][\d.]+) to ([+-][\d.]+)\), cases=(\d+)$", re.M)


def test_paired_hidden_diff_averages_reps_then_uses_t_interval(tmp_path, capsys):
    # c0: ref reps 1.0 and 0.5 (mean 0.75), arm 0.5 -> +0.25; c1: ref 1.0, arm 0.25 -> +0.75; c2: ref 0.5, arm 0.5 -> 0
    ref = [row("c0", hidden=[passed_of(4, 4)]), row("c0", hidden=[passed_of(2, 4)], rep=1),
           row("c1", hidden=[passed_of(4, 4)]), row("c2", hidden=[passed_of(2, 4)])]
    arm = [row("c0", 0.5, hidden=[passed_of(2, 4)]), row("c1", 0.5, hidden=[passed_of(1, 4)]),
           row("c2", 0.5, hidden=[passed_of(2, 4)])]
    out = "\n".join(summarize(tmp_path, capsys, ref, arm))
    lines = {m[1]: m for m in PAIRED_HIDDEN.finditer(out)}
    assert set(lines) == {"impl", "all"}
    m = lines["impl"]
    diffs = [0.25, 0.75, 0.0]
    mean = statistics.mean(diffs)
    half = run.t975(2) * statistics.stdev(diffs) / 3 ** 0.5
    assert float(m[2]) == pytest.approx(mean, abs=6e-4)
    assert float(m[3]) == pytest.approx(mean - half, abs=6e-4)
    assert float(m[4]) == pytest.approx(mean + half, abs=6e-4)
    assert int(m[5]) == 3


def test_paired_hidden_line_follows_the_checks_line(tmp_path, capsys):
    out = summarize(tmp_path, capsys, [row(f"c{i}", hidden=[passed_of(4, 4)]) for i in range(2)],
                    [row(f"c{i}", 0.5, hidden=[passed_of(i + 1, 4)]) for i in range(2)])
    i = next(k for k, l in enumerate(out) if l.startswith("  impl") and "cases=" in l and "checks diff" in l)
    assert out[i + 1].startswith("  impl      hidden tests diff ")


@pytest.mark.parametrize("ref_hidden,arm_hidden", [
    ([passed_of(4, 4), passed_of(4, 4)], [None, None]),
    ([None, None], [passed_of(2, 4), passed_of(2, 4)]),
    ([passed_of(4, 4), None], [passed_of(2, 4), passed_of(2, 4)]),
    ([passed_of(4, 4), passed_of(4, 4)], [passed_of(2, 4), "boom"]),
], ids=["arm-has-none", "ref-has-none", "one-case-ref-missing", "one-case-arm-unparsable"])
def test_paired_hidden_line_needs_two_cases_with_ratio_on_both_arms(tmp_path, capsys, ref_hidden, arm_hidden):
    ref = [row(f"c{i}", hidden=None if h is None else [h]) for i, h in enumerate(ref_hidden)]
    arm = [row(f"c{i}", 0.5, hidden=None if h is None else [h]) for i, h in enumerate(arm_hidden)]
    out = summarize(tmp_path, capsys, ref, arm)
    assert any("checks diff" in l for l in out)
    assert not any("hidden tests diff" in l for l in out)


# ---------------------------------------------------------------- regrade uses meta.changed

def text_case() -> dict:
    return {"id": "c", "tier": "lookup", "answer_files": [], "allowed_outputs": ["notes.md"],
            "checks": [{"id": "k", "any": ["ALPHA"], "desc": "alpha"}]}


@pytest.mark.parametrize("meta,passed", [
    ({"grade_detail": {"stray_writes": []}, "changed": ["notes.md", "src/x.py"]}, 0),
    ({"grade_detail": {"stray_writes": []}, "changed": ["notes.md"]}, 1),
    ({"grade_detail": {"stray_writes": ["src/x.py"]}}, 0),
    ({"grade_detail": {"stray_writes": []}}, 1),
], ids=["changed-with-stray", "changed-all-allowed", "fallback-stray", "fallback-clean"])
def test_regrade_row_judges_readonly_on_meta_changed_when_present(tmp_path, meta, passed):
    raw = tmp_path / "raw"
    raw.mkdir()
    (raw / "subagent.jsonl").write_text(json.dumps(
        {"type": "assistant", "message": {"content": [{"type": "text", "text": "ALPHA"}]}}) + "\n", encoding="utf-8")
    r = {"prompt_id": "c", "rep": 0, "status": "ok", "meta": {"tier": "lookup", **meta}}
    g = run.regrade_row(text_case(), raw, r, {"saved": 0, "rebuilt": 0, "missing": 0})
    assert g["grade"]["pass"] == passed
