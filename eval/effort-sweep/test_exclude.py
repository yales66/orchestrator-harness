"""Tests for the case-set exclusions. Run: python3 -m pytest eval/effort-sweep/test_exclude.py -q"""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import EXCLUDE, load_cases  # noqa: E402
from render_inputs import render  # noqa: E402

EXCLUDED_IDS = ["impl-aggregator-providers", "lookup-obs-api", "lookup-obs-worker",
                "judge-recheck-r4-r11", "judge-recheck-r5"]


def write_cases(path: Path, rows: list[dict]) -> Path:
    path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
    return path


def ro_case(cid: str, tier: str = "lookup") -> dict:
    return {"id": cid, "tier": tier, "summary": f"summary of {cid}", "repo": "/r/demo", "base": "abc1234",
            "prompt": "brief", "checks": [], "grading": "g", "adopted_in": "a",
            "source": {"ts": "2026-09-20T10:00:00Z"}, "history": {"usage": {}, "models": {}, "tool_calls": 0}}


@pytest.mark.parametrize("cid", EXCLUDED_IDS, ids=EXCLUDED_IDS)
def test_load_cases_drops_each_excluded_id(tmp_path, cid):
    path = write_cases(tmp_path / "cases.jsonl", [ro_case("keep-me"), ro_case(cid)])
    assert [c["id"] for c in load_cases(path)] == ["keep-me"]


@pytest.mark.parametrize("cid", EXCLUDED_IDS, ids=EXCLUDED_IDS)
def test_every_exclusion_carries_a_reason(cid):
    assert EXCLUDE[cid].strip()


def test_load_cases_can_return_excluded_cases_for_rendering(tmp_path):
    path = write_cases(tmp_path / "cases.jsonl", [ro_case("keep-me"), ro_case("lookup-obs-api")])
    assert [c["id"] for c in load_cases(path, include_excluded=True)] == ["keep-me", "lookup-obs-api"]


def test_render_lists_exclusions_with_reasons_and_keeps_them_out_of_the_index(tmp_path):
    path = write_cases(tmp_path / "cases.jsonl",
                       [ro_case("keep-me"), ro_case("lookup-obs-api"), ro_case("judge-recheck-r5", "judgement")])
    page = render(load_cases(path), load_cases(path, include_excluded=True))
    excluded_part = page[page.index("id='excluded'"):]
    for cid in EXCLUDED_IDS:
        assert cid in excluded_part
        assert EXCLUDE[cid] in excluded_part
    assert "href='#lookup-obs-api'" not in page
    assert "id='lookup-obs-api'" not in page
    assert "href='#keep-me'" in page
