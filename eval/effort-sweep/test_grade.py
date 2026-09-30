"""Unit tests for the grader's pure functions. Run: python3 -m pytest eval/effort-sweep/test_grade.py -q"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import path_matches  # noqa: E402
from grade import expand_command, grade_text  # noqa: E402

CASE = {
    "id": "t",
    "tier": "lookup",
    "checks": [
        {"id": "loc", "desc": "points at the loop", "any": [r"pager\.py:8[01]"]},
        {"id": "cause", "desc": "names the cause", "any": [r"total\s*(为|=|==)\s*0", r"total is 0"]},
    ],
    "forbid": [{"id": "wrong", "desc": "blames MAX_PAGES", "any": [r"根因[^。\n]*MAX_PAGES"]}],
}


@pytest.mark.parametrize(
    "answer, expected_pass, expected_rate",
    [
        ("循环在 pager.py:81，后续页 total 为 0 导致提前退出", 1, 1.0),
        ("循环在 pager.py:81，但原因不明", 0, 3 / 4),
        ("pager.py:80 处 total is 0；根因是 MAX_PAGES 太小", 0, 3 / 4),
        ("", 0, 0.0),
        ("   \n", 0, 0.0),
    ],
    ids=["all-hit", "missing-cause", "forbidden-claim", "empty", "whitespace"],
)
def test_grade_text(answer, expected_pass, expected_rate):
    g = grade_text(CASE, answer, changed=[])
    assert g["grade"]["pass"] == expected_pass
    assert g["grade"]["checks"] == pytest.approx(expected_rate)


def test_grade_text_fails_when_readonly_task_wrote_into_repo():
    g = grade_text(CASE, "pager.py:81，total 为 0", changed=["src/fetchers/pager.py"])
    assert g["grade"]["pass"] == 0
    assert g["detail"]["readonly_ok"] is False


def test_grade_text_ignores_allowed_outputs():
    case = dict(CASE, allowed_outputs=["notes/**"])
    g = grade_text(case, "pager.py:81，total 为 0", changed=["notes/findings.md"])
    assert g["grade"]["pass"] == 1


def test_grade_text_marks_no_answer():
    g = grade_text(CASE, "", changed=[])
    assert g["detail"]["no_answer"] is True


@pytest.mark.parametrize(
    "path, patterns, expected",
    [
        ("backend/observability/x/y.py", ["backend/observability/**"], True),
        ("backend/observability.py", ["backend/observability/**"], False),
        ("tests/test_a.py", ["tests/test_*.py"], True),
        ("tests/sub/test_a.py", ["tests/test_*.py"], False),
        ("tests/sub/test_a.py", ["tests/**/test_*.py"], True),
        ("tests/test_a.py", ["tests/**/test_*.py"], True),
        ("web/lib/a.test.ts", ["web/**/*.test.ts"], True),
    ],
    ids=["dir-glob", "sibling-file", "star", "star-no-descend", "double-star-deep", "double-star-zero", "web-test"],
)
def test_path_matches(path, patterns, expected):
    assert path_matches(path, patterns) is expected


@pytest.mark.parametrize(
    "template, changed, expected",
    [
        ("pytest {changed:tests/**/test_*.py} -q", ["tests/test_a.py", "src/a.py"], "pytest tests/test_a.py -q"),
        ("cd web && vitest run {changed:web/**/*.test.ts|web/}", ["web/lib/x.test.ts"], "cd web && vitest run lib/x.test.ts"),
        ("pytest {changed:tests/**/test_*.py} -q", ["src/a.py"], None),
        ("ruff check .", [], "ruff check ."),
    ],
    ids=["expands", "strips-prefix", "nothing-changed", "no-placeholder"],
)
def test_expand_command(template, changed, expected):
    assert expand_command(template, changed) == expected
