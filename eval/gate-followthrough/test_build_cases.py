import json
import os
import sys
import types

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import build_cases  # noqa: E402

CONNECTOR_REASON = "越界那一步要经连接器执行，拒绝记录里观察不到"
CONNECTOR_IDS = ["69d3ef72d373", "765c3f0d91af"]
OTHER_ID = "000000000000"


def _population(ids):
    return [({"id": i, "session_id": "s-" + i, "uuid": "u-" + i, "timestamp": "2026-09-01T00:00:00Z"},
             {"a1": "rightly-asked", "criterion": "paid", "shape": "yes-no-offer"},
             {"id": i, "a1_fired": True})
            for i in ids]


@pytest.fixture
def run_build(tmp_path, monkeypatch):
    """Run build() over a fake population whose transcripts are all missing."""
    def run(annotated_ids):
        ids = CONNECTOR_IDS + [OTHER_ID]
        monkeypatch.setattr(build_cases, "select", lambda _: _population(ids))
        ann = tmp_path / "ann.jsonl"
        ann.write_text("".join(
            json.dumps({"id": i, "situation": "s", "gist": "g", "forbidden": []}) + "\n"
            for i in annotated_ids), encoding="utf-8")
        out = tmp_path / "out"
        out.mkdir()
        build_cases.build(types.SimpleNamespace(
            annotations=str(ann), out=str(out), replay_data="unused",
            projects=[str(tmp_path / "no-projects")], hook="unused", hook_command="unused"))
        return (out / "cases.jsonl").read_text(encoding="utf-8"), (out / "inputs.html").read_text(encoding="utf-8")
    return run


@pytest.mark.parametrize("annotated", [CONNECTOR_IDS + [OTHER_ID], [OTHER_ID]],
                         ids=["annotated", "annotation-missing"])
def test_connector_only_cases_are_excluded_with_their_reason(run_build, annotated):
    cases, page = run_build(annotated)
    for cid in CONNECTOR_IDS:
        assert cid not in cases
        assert f"<tr><td><code>{cid}</code></td><td>{CONNECTOR_REASON}</td></tr>" in page


def test_other_cases_keep_their_own_exclusion_reason(run_build):
    _, page = run_build(CONNECTOR_IDS + [OTHER_ID])
    assert f"<tr><td><code>{OTHER_ID}</code></td><td>source transcript not found</td></tr>" in page
