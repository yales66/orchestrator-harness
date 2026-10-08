"""Tests for the case-set exclusions. Run: python3 -m pytest eval/effort-sweep/test_exclude.py -q"""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import load_cases  # noqa: E402
from render_inputs import render  # noqa: E402


def write_cases(path: Path, rows: list[dict]) -> Path:
    path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
    return path


def ro_case(cid: str, tier: str = "lookup", exclude: str | None = None) -> dict:
    row = {"id": cid, "tier": tier, "summary": f"summary of {cid}", "repo": "/r/demo", "base": "abc1234",
           "prompt": "brief", "checks": [], "grading": "g", "adopted_in": "a",
           "source": {"ts": "2026-09-20T10:00:00Z"}, "history": {"usage": {}, "models": {}, "tool_calls": 0}}
    if exclude is not None:
        row["exclude"] = exclude
    return row


@pytest.mark.parametrize("tier", ["impl", "lookup", "judgement"], ids=["impl", "lookup", "judgement"])
def test_load_cases_drops_a_case_that_carries_an_exclusion_reason(tmp_path, tier):
    path = write_cases(tmp_path / "cases.jsonl", [ro_case("keep-me"), ro_case("drop-me", tier, "repeats keep-me")])
    assert [c["id"] for c in load_cases(path)] == ["keep-me"]


@pytest.mark.parametrize("reason", ["", "   "], ids=["empty", "blank"])
def test_an_exclusion_without_a_reason_is_refused(tmp_path, reason):
    path = write_cases(tmp_path / "cases.jsonl", [ro_case("keep-me"), ro_case("drop-me", exclude=reason)])
    with pytest.raises(SystemExit, match="drop-me"):
        load_cases(path)


def test_load_cases_can_return_excluded_cases_for_rendering(tmp_path):
    path = write_cases(tmp_path / "cases.jsonl", [ro_case("keep-me"), ro_case("drop-me", exclude="repeats keep-me")])
    assert [c["id"] for c in load_cases(path, include_excluded=True)] == ["keep-me", "drop-me"]


def test_render_lists_exclusions_with_reasons_and_keeps_them_out_of_the_index(tmp_path):
    path = write_cases(tmp_path / "cases.jsonl",
                       [ro_case("keep-me"), ro_case("drop-a", exclude="reason a"),
                        ro_case("drop-b", "judgement", exclude="reason b")])
    page = render(load_cases(path), load_cases(path, include_excluded=True))
    excluded_part = page[page.index("id='excluded'"):]
    for cid, reason in [("drop-a", "reason a"), ("drop-b", "reason b")]:
        assert cid in excluded_part
        assert reason in excluded_part
    assert "以下 2 个案例不参加运行" in excluded_part
    assert "href='#drop-a'" not in page
    assert "id='drop-a'" not in page
    assert "href='#keep-me'" in page
