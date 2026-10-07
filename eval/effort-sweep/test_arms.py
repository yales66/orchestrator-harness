"""Tests for sweep arms (subagent model x effort) and arm-vs-reference summaries.

Run: python3 -m pytest eval/effort-sweep/test_arms.py -q
"""
import json
import re
from argparse import Namespace

import pytest

import run

EFFORTS = ("low", "medium", "high", "xhigh", "max")


# ---------------------------------------------------------------- arms on the run side

@pytest.mark.parametrize("model,effort,expected", [
    ("opus", "high", "baseline"),
    ("opus", "medium", "v1"),
    ("opus", "low", "opus-low"),
    ("opus", "max", "opus-max"),
    ("haiku", "high", "haiku-high"),
    ("haiku", "max", "haiku-max"),
], ids=["opus-high-baseline", "opus-medium-v1", "opus-low", "opus-max", "haiku-high", "haiku-max"])
def test_variant_dir_names_each_arm(model, effort, expected):
    assert run.variant_dir(model, effort) == expected


@pytest.mark.parametrize("model,effort,expected", [
    ("opus", "high", "effort-sweep-high"),
    ("opus", "xhigh", "effort-sweep-xhigh"),
    ("haiku", "max", "effort-sweep-haiku-max"),
    ("haiku", "low", "effort-sweep-haiku-low"),
], ids=["opus-high", "opus-xhigh", "haiku-max", "haiku-low"])
def test_agent_name_keeps_opus_names_and_tags_haiku(model, effort, expected):
    assert run.agent_name(effort, model) == expected


@pytest.mark.parametrize("model", ["opus", "haiku"], ids=["opus", "haiku"])
def test_agent_definition_pins_the_arms_model_and_effort(model):
    text = run.agent_definition("max", model)
    assert f"\nmodel: {run.MODEL_IDS[model]}\n" in text
    assert "\neffort: max\n" in text
    assert f"name: {run.agent_name('max', model)}\n" in text


def test_child_env_names_the_arms_agent(tmp_path):
    env = run.child_env(tmp_path / "cfg", tmp_path / "brief.md", "max", model="haiku")
    assert env["EFFORT_SWEEP_AGENT"] == "effort-sweep-haiku-max"


@pytest.mark.parametrize("model,expected", [("opus", "claude-opus-5-5"), ("haiku", "claude-haiku-5-5")],
                         ids=["opus", "haiku"])
def test_served_models_must_match_the_arms_model(model, expected):
    assert run.served_model_problem([expected, expected], model) is None
    other = "claude-haiku-5-5" if model == "opus" else "claude-opus-5-5"
    assert expected in run.served_model_problem([expected, other], model)
    assert run.served_model_problem([], model) is not None


def parse_run(*extra):
    return run.build_parser().parse_args(["run", "--data", "/d", *extra])


@pytest.mark.parametrize("effort", EFFORTS, ids=EFFORTS)
def test_run_accepts_all_five_efforts(effort):
    assert parse_run("--effort", effort).effort == effort


def test_run_model_defaults_to_opus_and_accepts_haiku():
    assert parse_run("--effort", "high").model == "opus"
    assert parse_run("--effort", "high", "--model", "haiku").model == "haiku"
    with pytest.raises(SystemExit):
        parse_run("--effort", "high", "--model", "sonnet")


def test_summarize_defaults_to_baseline_against_v1():
    args = run.build_parser().parse_args(["summarize", "--data", "/d"])
    assert (args.ref, args.arms) == ("baseline", "v1")


def test_change_md_for_a_new_arm_names_model_and_effort(tmp_path):
    run.ensure_change_md(tmp_path, "max", "haiku")
    text = (tmp_path / "change.md").read_text(encoding="utf-8")
    assert "claude-haiku-5-5" in text and "max" in text and "baseline" in text


def test_change_md_for_v1_keeps_its_text(tmp_path):
    run.ensure_change_md(tmp_path, "medium", "opus")
    assert (tmp_path / "change.md").read_text(encoding="utf-8").startswith("# v1\n\nSubagent effort medium instead of high")


def test_change_md_is_not_written_for_baseline(tmp_path):
    run.ensure_change_md(tmp_path, "high", "opus")
    assert not (tmp_path / "change.md").exists()


# ---------------------------------------------------------------- summaries across arms

def result(cid: str, checks: float, tier: str = "impl", band: str | None = None, tokens: int = 100) -> dict:
    meta = {"tier": tier}
    if band is not None:
        meta["band"] = band
    return {"prompt_id": cid, "rep": 0, "status": "ok", "meta": meta, "latency_s": 1.0,
            "grade": {"pass": checks == 1.0, "checks": checks}, "usage": {"input_tokens": tokens}}


def write_variant(path, rows: list[dict]) -> None:
    path.mkdir(parents=True)
    (path / "results.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")


BANDED = [("c0", "hard"), ("c1", "hard"), ("c2", "mid"), ("c3", "mid"), ("c4", "easy")]


def summarize(tmp_path, capsys, ref="baseline", arms="v1") -> str:
    run.cmd_summarize(Namespace(data=tmp_path, ref=ref, arms=arms))
    return capsys.readouterr().out


def write_banded_pair(tmp_path, ref: str, arm: str) -> None:
    write_variant(tmp_path / ref, [result(c, 0.9, band=b, tokens=200) for c, b in BANDED])
    write_variant(tmp_path / arm, [result(c, 0.5, band=b, tokens=100) for c, b in BANDED])


def test_any_arm_pairs_against_any_reference_with_its_own_labels(tmp_path, capsys):
    write_banded_pair(tmp_path, "opus-max", "haiku-max")
    out = summarize(tmp_path, capsys, ref="opus-max", arms="haiku-max")
    assert "paired by case (mean over reps), opus-max minus haiku-max:" in out
    assert "high minus medium" not in out
    assert re.search(r"^  impl\s+cases=5\s+checks diff \+0\.400 .*haiku-max tokens / opus-max tokens, median 0\.50$",
                     out, re.M)


def test_each_listed_arm_gets_its_own_paired_section(tmp_path, capsys):
    write_banded_pair(tmp_path, "baseline", "haiku-high")
    write_variant(tmp_path / "haiku-low", [result(c, 0.3, band=b) for c, b in BANDED])
    out = summarize(tmp_path, capsys, arms="haiku-high,haiku-low")
    assert "baseline minus haiku-high:" in out and "baseline minus haiku-low:" in out
    assert re.search(r"^haiku-low\s+impl\s+n=5", out, re.M)


@pytest.mark.parametrize("band,cases", [("hard", 2), ("mid", 2)], ids=["hard", "mid"])
def test_paired_section_has_a_line_per_band_with_two_or_more_cases(tmp_path, capsys, band, cases):
    write_banded_pair(tmp_path, "baseline", "haiku-max")
    out = summarize(tmp_path, capsys, arms="haiku-max")
    paired = out[out.index("paired by case"):]
    assert re.search(rf"^  band {band}\s+cases={cases}\s+checks diff \+0\.400 \(95% CI", paired, re.M)


def test_paired_section_skips_a_band_with_one_case(tmp_path, capsys):
    write_banded_pair(tmp_path, "baseline", "haiku-max")
    out = summarize(tmp_path, capsys, arms="haiku-max")
    assert "band easy" not in out[out.index("paired by case"):]


def test_variant_summary_adds_band_lines_only_when_rows_carry_a_band(tmp_path, capsys):
    write_banded_pair(tmp_path, "baseline", "haiku-max")
    write_variant(tmp_path / "v1", [result(c, 0.5) for c, _ in BANDED])
    out = summarize(tmp_path, capsys, arms="haiku-max,v1")
    assert re.search(r"^haiku-max band hard n=2 ", out, re.M)
    assert re.search(r"^haiku-max band easy n=1 ", out, re.M)
    assert not re.search(r"^v1\s+band", out, re.M)


def test_default_labels_stay_high_minus_medium(tmp_path, capsys):
    write_banded_pair(tmp_path, "baseline", "v1")
    out = summarize(tmp_path, capsys)
    assert "paired by case (mean over reps), high minus medium:" in out
    assert "medium tokens / high tokens, median 0.50" in out
