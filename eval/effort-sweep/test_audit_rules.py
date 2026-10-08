"""Tests for the impl grading rules: excluded landed tests, and grading the worktree an attempt built.

Run: python3 -m pytest eval/effort-sweep/test_audit_rules.py -q
"""
import copy
import json
import subprocess
from argparse import Namespace

import pytest

import run

# ---------------------------------------------------------------- outputs

PYTEST_OUT = """\
tests/test_textnorm.py:81: AssertionError
=========================== short test summary info ============================
FAILED tests/test_evaluate.py::test_metrics[strict] - KeyError: 'e...
FAILED tests/test_evaluate.py::test_choose_tau_rejects_bad_input[off-grid]
ERROR tests/test_fakewords.py::test_levenshtein - fixture 'x' not found
3 failed, 94 passed in 4.31s
"""
PYTEST_IDS = ["tests/test_evaluate.py::test_metrics[strict]",
              "tests/test_evaluate.py::test_choose_tau_rejects_bad_input[off-grid]",
              "tests/test_fakewords.py::test_levenshtein"]

VITEST_ID = ("components/portfolio/positions-view.test.tsx > PositionsView: holdings whose cost is unknown > "
             "shows a neutral dash for the P&L while the market value stays")
VITEST_OUT = f"""\
 ❯ |dom| components/portfolio/positions-view.test.tsx (23 tests | 1 failed) 2717ms
     × shows a neutral dash for the P&L while the market value stays 45ms

 Test Files  1 failed (1)
      Tests  1 failed | 22 passed (23)
   Duration  5.66s

⎯⎯⎯ Failed Tests 1 ⎯⎯⎯

 FAIL  |dom| {VITEST_ID}
AssertionError: expected '' to be 'var(--text-muted)' // Object.is equality
"""

COLLECTION_ERROR = """\
=========================== short test summary info ============================
ERROR tests/test_fakewords.py
!!!!!!!!!!!!!!!!!!!! Interrupted: 1 error during collection !!!!!!!!!!!!!!!!!!!!
1 error in 0.38s
"""


@pytest.mark.parametrize("out,expected", [
    (PYTEST_OUT, PYTEST_IDS),
    (VITEST_OUT, [VITEST_ID]),
    (" ✗ a.test.ts > Suite > one 12ms\n × a.test.ts > Suite > two 3.5ms\n FAIL  a.test.ts > Suite > one\n"
     "      Tests  2 failed | 1 passed (3)\n", ["a.test.ts > Suite > one", "a.test.ts > Suite > two"]),
    ("10 passed in 0.1s\n", []),
], ids=["pytest-failed-and-error", "vitest-project-prefix-stripped", "vitest-marks-durations-deduped", "all-passed"])
def test_failed_tests_reads_the_failure_ids(out, expected):
    assert run.failed_tests(out) == expected


@pytest.mark.parametrize("out", [
    "…" + PYTEST_OUT.split("\n", 3)[3],
    "Traceback (most recent call last):\nImportError\n",
    " FAIL  a.test.ts > S > t\n      Tests  1 failed | 1 passed (2)\n     Errors  1 error\n",
], ids=["cut-before-some-failed-lines", "no-summary-line", "vitest-unhandled-errors"])
def test_failed_tests_none_when_failures_are_not_all_listed(out):
    assert run.failed_tests(out) is None


# ---------------------------------------------------------------- apply_hidden_exclude

def hidden_run(out: str, code=1) -> dict:
    return {"cmd": "pytest -q", "code": code, "ok": code == 0, "seconds": 1.0, "out": out}


def impl_detail(*runs, out_of_scope=(), self_ok=(True,)) -> dict:
    return {"changed": ["src/a.py", *out_of_scope], "out_of_scope": list(out_of_scope),
            "selfcheck": [{"cmd": "t", "code": 0 if ok else 1, "ok": ok, "out": ""} for ok in self_ok],
            "hidden": list(runs), "hidden_pass": all(r["ok"] for r in runs) if runs else None}


def impl_case(exclude=None) -> dict:
    hidden = {"files": [], "commands": [{"run": "pytest -q"}]}
    if exclude is not None:
        hidden["exclude"] = exclude
    return {"id": "c", "tier": "impl", "scope": ["src/**"], "selfcheck": {"commands": []}, "hidden": hidden,
            "base": "HEAD"}


def applied(out, exclude, code=1) -> dict:
    d = impl_detail(hidden_run(out, code))
    run.apply_hidden_exclude(impl_case(exclude), d)
    return d["hidden"][0]


def test_every_failure_excluded_makes_the_run_pass():
    h = applied(PYTEST_OUT, PYTEST_IDS)
    assert h["ok"] is True
    assert h["excluded"] == PYTEST_IDS
    assert tuple(h["counts_after"]) == (94, 94)
    assert not h.get("indeterminate")


def test_a_remaining_failure_keeps_the_run_failed():
    h = applied(PYTEST_OUT, PYTEST_IDS[:2])
    assert h["ok"] is False
    assert h["excluded"] == PYTEST_IDS[:2]
    assert tuple(h["counts_after"]) == (94, 95)


@pytest.mark.parametrize("exclude", [
    ["tests/test_evaluate.py::test_metrics", *PYTEST_IDS[1:]],
    [p.replace("tests/", "pilot/tests/") for p in PYTEST_IDS],
], ids=["param-left-off", "other-rootdir"])
def test_pytest_ids_match_only_in_full(exclude):
    assert applied(PYTEST_OUT, exclude)["ok"] is False


@pytest.mark.parametrize("exclude", [
    [VITEST_ID],
    [VITEST_ID[:-len(" while the market value stays")]],
], ids=["full", "cut-short"])
def test_vitest_ids_match_by_prefix(exclude):
    h = applied(VITEST_OUT, exclude)
    assert h["ok"] is True and tuple(h["counts_after"]) == (22, 22)


def test_collection_error_is_indeterminate_and_leaves_checks():
    h = applied(COLLECTION_ERROR, [])
    assert h["ok"] is None and h["indeterminate"] is True


def test_unlisted_failures_are_indeterminate_and_keep_ok():
    h = applied("…" + PYTEST_OUT.split("\n", 3)[3], PYTEST_IDS)
    assert h["ok"] is False and h["indeterminate"] is True
    assert "excluded" not in h


@pytest.mark.parametrize("out,code", [
    ("77 passed in 0.4s\n", 0),
    ("1 failed, 3 passed in 0.1s\n", None),
], ids=["passing-run", "timed-out"])
def test_runs_that_passed_or_timed_out_are_left_alone(out, code):
    before = hidden_run(out, code)
    assert applied(out, PYTEST_IDS, code) == before


def test_no_exclude_list_keeps_failures():
    h = applied(PYTEST_OUT, None)
    assert h["ok"] is False and "excluded" not in h and not h.get("indeterminate")


def test_reapplying_follows_the_current_exclude_list():
    d = impl_detail(hidden_run(PYTEST_OUT))
    run.apply_hidden_exclude(impl_case(PYTEST_IDS), d)
    once = copy.deepcopy(d)
    run.apply_hidden_exclude(impl_case(PYTEST_IDS), d)
    assert d == once
    run.apply_hidden_exclude(impl_case([]), d)
    assert d["hidden"][0]["ok"] is False and "excluded" not in d["hidden"][0]


def test_hidden_pass_follows_the_rescored_runs():
    d = impl_detail(hidden_run(PYTEST_OUT), hidden_run(COLLECTION_ERROR))
    run.apply_hidden_exclude(impl_case(PYTEST_IDS), d)
    assert d["hidden_pass"] is None
    d = impl_detail(hidden_run(PYTEST_OUT))
    run.apply_hidden_exclude(impl_case(PYTEST_IDS), d)
    assert d["hidden_pass"] is True


# ---------------------------------------------------------------- hidden_tests after exclusion

def test_hidden_tests_use_counts_after_and_skip_indeterminate():
    d = impl_detail(hidden_run(PYTEST_OUT), hidden_run(COLLECTION_ERROR), hidden_run("8 passed in 1s\n", 0))
    run.apply_hidden_exclude(impl_case(PYTEST_IDS[:2]), d)
    assert run.hidden_tests(d) == (94 + 8, 95 + 8)


# ---------------------------------------------------------------- impl_grade_from_detail

@pytest.mark.parametrize("d,expected", [
    (impl_detail(hidden_run(PYTEST_OUT)), {"pass": 1, "checks": 3 / 4}),
    (impl_detail(hidden_run(PYTEST_OUT), out_of_scope=["x.py"]), {"pass": 0, "checks": 2 / 4}),
    (impl_detail(self_ok=(True, False)), {"pass": 0, "checks": 3 / 4}),
    (impl_detail(hidden_run("5 passed in 1s\n", 0), hidden_run(COLLECTION_ERROR)), {"pass": 1, "checks": 4 / 5}),
], ids=["hidden-fail", "out-of-scope", "selfcheck-fail", "same-as-grade-impl-before-exclusion"])
def test_impl_grade_from_detail_matches_grade_impl(d, expected):
    assert run.impl_grade_from_detail(d)["grade"] == pytest.approx(expected)


def test_indeterminate_run_leaves_the_checks_denominator():
    d = impl_detail(hidden_run("5 passed in 1s\n", 0), hidden_run(COLLECTION_ERROR))
    run.apply_hidden_exclude(impl_case([]), d)
    g = run.impl_grade_from_detail(d)
    assert g["grade"] == {"pass": 1, "checks": 1.0}
    assert "hidden2=n/a" in g["explanation"]["pass"]


# ---------------------------------------------------------------- regrade of impl rows

def write_data(data, cases, rows):
    (data / "v1").mkdir(parents=True)
    (data / "cases.jsonl").write_text("".join(json.dumps(c) + "\n" for c in cases), encoding="utf-8")
    (data / "v1" / "results.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")


def impl_row(d, rep=0) -> dict:
    g = run.impl_grade_from_detail(d)
    return {"prompt_id": "c", "rep": rep, "status": "ok", "grade": g["grade"], "explanation": g["explanation"],
            "meta": {"tier": "impl", "grade_detail": d}}


def regrade(data, dry_run=False):
    return run.cmd_regrade(Namespace(data=data, arms="v1", dry_run=dry_run))


def test_regrade_rescores_impl_rows_offline(tmp_path, capsys):
    data = tmp_path / "data"
    write_data(data, [impl_case(PYTEST_IDS)],
               [impl_row(impl_detail(hidden_run(PYTEST_OUT))), impl_row(impl_detail(hidden_run(COLLECTION_ERROR)), 1)])

    assert regrade(data) == 0

    rows = run.read_jsonl(data / "v1" / "results.jsonl")
    assert [r["grade"] for r in rows] == [{"pass": 1, "checks": 1.0}, {"pass": 1, "checks": 1.0}]
    assert [r["meta"]["grade_original"]["checks"] for r in rows] == [0.75, 0.75]
    assert all(r["meta"]["regraded_at"] for r in rows)
    assert rows[0]["meta"]["grade_detail"]["hidden"][0]["excluded"] == PYTEST_IDS
    summary = next(l for l in capsys.readouterr().out.splitlines() if l.startswith("v1:"))
    assert "impl rows rescored 2 (pass changed on 0, checks changed on 2, indeterminate hidden runs 1)" in summary


def test_regrade_keeps_the_first_impl_grade_original(tmp_path):
    data = tmp_path / "data"
    write_data(data, [impl_case(PYTEST_IDS)], [impl_row(impl_detail(hidden_run(PYTEST_OUT)))])
    regrade(data)
    regrade(data)
    r = run.read_jsonl(data / "v1" / "results.jsonl")[0]
    assert r["meta"]["grade_original"] == {"pass": 1, "checks": 0.75}


def test_regrade_dry_run_writes_no_impl_row(tmp_path, capsys):
    data = tmp_path / "data"
    write_data(data, [impl_case(PYTEST_IDS)], [impl_row(impl_detail(hidden_run(PYTEST_OUT)))])
    before = (data / "v1" / "results.jsonl").read_bytes()
    regrade(data, dry_run=True)
    assert (data / "v1" / "results.jsonl").read_bytes() == before
    assert "c rep0: pass 1->1 checks 0.75->1.00" in capsys.readouterr().out


# ---------------------------------------------------------------- grading_root

def git(cwd, *args) -> str:
    return subprocess.run(["git", "-C", str(cwd), "-c", "core.hooksPath=/dev/null", "-c", "user.email=t@t",
                           "-c", "user.name=t", *args], check=True, capture_output=True, text=True).stdout


@pytest.fixture
def ws(tmp_path):
    """A clone-like workspace on `main` with src/a.py and docs/x.md committed."""
    w = tmp_path / "ws"
    w.mkdir()
    git(w, "init", "-q", "-b", "main")
    (w / "src").mkdir()
    (w / "src" / "a.py").write_text("a = 1\n")
    (w / "docs").mkdir()
    (w / "docs" / "x.md").write_text("x\n")
    git(w, "add", "-A")
    git(w, "commit", "-qm", "base")
    return w


def scope_case(ws_path) -> dict:
    return {"id": "c", "tier": "impl", "scope": ["src/**"], "base": git(ws_path, "rev-parse", "HEAD").strip(),
            "selfcheck": {"commands": [{"run": "grep -q 2 src/a.py"}]}}


def add_worktree(ws_path, rel, change=None, commit=False):
    git(ws_path, "worktree", "add", "-q", rel, "-b", "wt-" + rel.rsplit("/", 1)[-1])
    wt = ws_path / rel
    if change:
        (wt / "src" / "a.py").write_text(change)
        if commit:
            git(wt, "commit", "-qam", "change")
    return wt


@pytest.mark.parametrize("setup,expected", [
    (lambda w: None, "."),
    (lambda w: add_worktree(w, ".worktrees/f", "a = 2\n"), ".worktrees/f"),
    (lambda w: add_worktree(w, ".worktrees/f", "a = 2\n", commit=True), ".worktrees/f"),
    (lambda w: add_worktree(w, ".worktrees/f"), "."),
    (lambda w: (add_worktree(w, ".worktrees/f", "a = 2\n"), (w / "src" / "a.py").write_text("a = 3\n")), "."),
    (lambda w: (add_worktree(w, ".worktrees/f", "a = 2\n"), add_worktree(w, ".worktrees/g", "a = 3\n")), "."),
    (lambda w: (add_worktree(w, ".worktrees/f", "a = 2\n"), add_worktree(w, ".worktrees/g")), ".worktrees/f"),
    (lambda w: (add_worktree(w, ".worktrees/f", "a = 2\n"), (w / "docs" / "x.md").write_text("y\n")), ".worktrees/f"),
    (lambda w: add_worktree(w, "../outside", "a = 2\n"), "."),
], ids=["no-worktree", "uncommitted-change", "committed-change", "worktree-unchanged", "main-changed-in-scope",
        "two-changed-worktrees", "one-of-two-changed", "main-changed-outside-scope", "worktree-outside-ws"])
def test_grading_root(ws, setup, expected):
    case = scope_case(ws)
    before = run.dirty_manifest(ws)
    setup(ws)
    assert run.grading_root(ws, case, before) == ws / expected


def test_attempt_grades_the_worktree_and_records_it(ws):
    case = scope_case(ws)
    before = run.dirty_manifest(ws)
    add_worktree(ws, ".worktrees/f", "a = 2\n")
    g, root, reset_from = run.grade_impl_attempt(case, ws, before)
    assert root == ".worktrees/f"
    assert g["grade"] == {"pass": 1, "checks": 1.0}
    assert g["detail"]["changed"] == ["src/a.py"]
    assert reset_from is None


def test_committed_worktree_change_is_graded_like_an_uncommitted_one(ws):
    case = scope_case(ws)
    before = run.dirty_manifest(ws)
    wt = add_worktree(ws, ".worktrees/f", "a = 2\n", commit=True)
    head = git(wt, "rev-parse", "HEAD").strip()
    g, root, reset_from = run.grade_impl_attempt(case, ws, before)
    assert (root, reset_from) == (".worktrees/f", head)
    assert g["detail"]["changed"] == ["src/a.py"]
    assert g["grade"] == {"pass": 1, "checks": 1.0}


def test_committed_main_workspace_change_is_graded_like_an_uncommitted_one(ws):
    case = scope_case(ws)
    before = run.dirty_manifest(ws)
    (ws / "src" / "a.py").write_text("a = 2\n")
    git(ws, "commit", "-qam", "change")
    head = git(ws, "rev-parse", "HEAD").strip()
    g, root, reset_from = run.grade_impl_attempt(case, ws, before)
    assert (root, reset_from) == (".", head)
    assert g["detail"]["changed"] == ["src/a.py"]
    assert g["grade"] == {"pass": 1, "checks": 1.0}


def test_main_workspace_grading_ignores_worktree_dirs(ws):
    case = scope_case(ws)
    before = run.dirty_manifest(ws)
    add_worktree(ws, ".worktrees/f", "a = 3\n")
    (ws / "src" / "a.py").write_text("a = 2\n")
    g, root, _ = run.grade_impl_attempt(case, ws, before)
    assert root == "."
    assert g["detail"]["out_of_scope"] == []
    assert g["grade"]["pass"] == 1
