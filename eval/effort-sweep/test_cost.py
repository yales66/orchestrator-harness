"""Tests for per-request dollar cost, `reprice`, and cost in summaries.

Run: python3 -m pytest eval/effort-sweep/test_cost.py -q
"""
import json
from argparse import Namespace

import pytest

import run

OPUS, HAIKU = "claude-opus-5-5", "claude-haiku-5-5"
M = 1_000_000


def assistant(mid: str, model: str, inp=0, cw=0, cr=0, out=0, split=None) -> dict:
    """One transcript line of an assistant message; `split` is (5m, 1h) cache-write tokens or None."""
    usage = {"input_tokens": inp, "cache_creation_input_tokens": cw, "cache_read_input_tokens": cr, "output_tokens": out}
    if split is not None:
        usage["cache_creation"] = {"ephemeral_5m_input_tokens": split[0], "ephemeral_1h_input_tokens": split[1]}
    return {"type": "assistant", "message": {"id": mid, "model": model, "usage": usage}}


# ---------------------------------------------------------------- request_costs

@pytest.mark.parametrize("records,dollars,unpriced", [
    ([assistant("a", OPUS, inp=M, cw=M, cr=M, out=M)], 4 + 5 + 0.20 + 20, 0),
    ([assistant("a", HAIKU, inp=40_000, cr=60_000, out=M)], (40_000 * 0.10 + 60_000 * 0.01) / M + 0.50, 0),
    ([assistant("a", HAIKU, inp=40_001, cr=60_000, out=M)], (40_001 * 0.50 + 60_000 * 0.05) / M + 2.50, 0),
    ([assistant("a", HAIKU, inp=1, cw=50_000, cr=50_000, out=M)], (1 * 0.50 + 50_000 * 0.625 + 50_000 * 0.05) / M + 2.50, 0),
    ([assistant("a", OPUS, cw=3 * M, split=(M, 2 * M))], 5 + 2 * 8, 0),
    ([assistant("a", HAIKU, cw=M, split=(0, M))], 1.00, 0),
    ([assistant("a", OPUS, cw=2 * M)], 2 * 5, 0),
    ([assistant("a", OPUS, out=M), assistant("a", OPUS, out=2 * M)], 2 * 20, 0),
    ([assistant("a", OPUS, out=M), assistant("b", OPUS, out=M)], 2 * 20, 0),
    ([assistant("a", OPUS, out=M), assistant("s", "<synthetic>", out=M)], 20, 1),
    ([assistant("a", "claude-unknown-9", out=M)], 0, 1),
    ([{"type": "user", "message": {"content": "hi"}}, assistant("a", OPUS, inp=M)], 4, 0),
], ids=["opus-all-fields", "haiku-at-100k-low", "haiku-over-100k-high", "haiku-cache-write-counts-to-prompt",
        "opus-5m-1h-split", "haiku-1h-split", "no-split-falls-back-to-5m", "same-id-last-line-only",
        "distinct-ids-both-count", "synthetic-unpriced", "unknown-model-unpriced", "user-lines-ignored"])
def test_request_costs(records, dollars, unpriced):
    total, n = run.request_costs(records)
    assert total == pytest.approx(dollars)
    assert n == unpriced


# ---------------------------------------------------------------- reprice

def write_arm(path, rows: list[dict], transcripts: dict) -> None:
    """An arm directory with results.jsonl rows and raw/<id>_rep<k>/subagent.jsonl for each key of `transcripts`."""
    path.mkdir(parents=True)
    (path / "results.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    for key, records in transcripts.items():
        raw = path / "raw" / key
        raw.mkdir(parents=True)
        (raw / "subagent.jsonl").write_text("".join(json.dumps(r) + "\n" for r in records), encoding="utf-8")


def row(cid: str, checks: float = 1.0, tier: str = "impl", cost=None, rep: int = 0) -> dict:
    r = {"prompt_id": cid, "rep": rep, "status": "ok", "meta": {"tier": tier}, "latency_s": 1.0,
         "grade": {"pass": checks == 1.0, "checks": checks}, "usage": {"input_tokens": 100, "output_tokens": 10}}
    if cost is not None:
        r["cost_usd"] = cost
    return r


def test_reprice_rewrites_cost_and_nulls_rows_without_raw(tmp_path, capsys):
    arm = tmp_path / "v1"
    write_arm(arm, [row("c0"), row("c1"), row("c2", rep=1)],
              {"c0_rep0": [assistant("a", OPUS, out=M)], "c2_rep1": [assistant("b", OPUS, inp=M)]})

    assert run.cmd_reprice(Namespace(data=tmp_path, arms="v1")) == 0

    rows = run.read_jsonl(arm / "results.jsonl")
    assert [r["cost_usd"] for r in rows] == [pytest.approx(20), None, pytest.approx(4)]
    assert [r["prompt_id"] for r in rows] == ["c0", "c1", "c2"]
    assert "1" in capsys.readouterr().out
    assert not list(arm.glob("*.tmp"))


def test_reprice_is_wired_to_the_cli():
    args = run.build_parser().parse_args(["reprice", "--data", "/x", "--arms", "a,b"])
    assert args.cmd == "reprice" and args.arms == "a,b"


# ---------------------------------------------------------------- summarize

def test_summarize_variant_prints_total_and_median_cost(tmp_path, capsys):
    write_arm(tmp_path / "v1", [row("c0", cost=1.0), row("c1", cost=2.0), row("c2", cost=4.5)], {})
    run.summarize_variant(tmp_path / "v1")
    impl = next(l for l in capsys.readouterr().out.splitlines() if " impl " in l)
    assert impl.endswith("cost $7.50 (median $2.000/attempt)")


@pytest.mark.parametrize("ref_costs,arm_costs,shown", [
    ((2.0, 4.0), (1.0, 2.0), "; v1 cost / baseline cost 0.50"),
    ((None, None), (1.0, 2.0), None),
    ((2.0, 4.0), (None, None), None),
], ids=["both-priced", "ref-unpriced", "arm-unpriced"])
def test_paired_line_shows_cost_ratio_only_when_both_sides_priced(tmp_path, capsys, ref_costs, arm_costs, shown):
    write_arm(tmp_path / "baseline", [row(f"c{i}", 1.0, cost=c) for i, c in enumerate(ref_costs)], {})
    write_arm(tmp_path / "v1", [row(f"c{i}", 0.5, cost=c) for i, c in enumerate(arm_costs)], {})
    run.cmd_summarize(Namespace(data=tmp_path, ref="baseline", arms="v1"))
    paired = [l for l in capsys.readouterr().out.splitlines() if "cases=" in l]
    assert paired
    for line in paired:
        if shown:
            assert line.endswith(shown)
        else:
            assert "cost /" not in line


def test_cost_ratio_averages_reps_before_summing_cases(tmp_path, capsys):
    # c0: ref reps 1 and 3 (mean 2), arm 1; c1: ref 6, arm reps 2 and 4 (mean 3) -> (1 + 3) / (2 + 6)
    write_arm(tmp_path / "baseline", [row("c0", cost=1.0), row("c0", cost=3.0, rep=1), row("c1", cost=6.0)], {})
    write_arm(tmp_path / "v1", [row("c0", 0.5, cost=1.0), row("c1", 0.5, cost=2.0), row("c1", 0.5, cost=4.0, rep=1)], {})
    run.cmd_summarize(Namespace(data=tmp_path, ref="baseline", arms="v1"))
    impl = next(l for l in capsys.readouterr().out.splitlines() if "cases=" in l and " impl " in l)
    assert impl.endswith("; v1 cost / baseline cost 0.50")


def test_rows_without_cost_print_no_cost(tmp_path, capsys):
    write_arm(tmp_path / "baseline", [row("c0", 1.0), row("c1", 0.0)], {})
    write_arm(tmp_path / "v1", [row("c0", 0.5), row("c1", 0.5)], {})
    run.cmd_summarize(Namespace(data=tmp_path))
    assert "cost" not in capsys.readouterr().out
