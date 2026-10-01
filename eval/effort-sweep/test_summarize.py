"""Tests for the paired-difference interval in `run.py summarize`. Run: python3 -m pytest eval/effort-sweep/test_summarize.py -q"""
import json
import re
import statistics
from argparse import Namespace

import pytest

import run

# Two-sided 0.975 quantiles of Student's t, from published tables; past 30 degrees of freedom the normal 1.96 stands in.
T_QUANTILE = {1: 12.706, 5: 2.571, 30: 2.042, 39: 1.96}

LINE = re.compile(r"^\s+impl\s+cases=(\d+)\s+checks diff ([+-][\d.]+) \(95% CI ([+-][\d.]+) to ([+-][\d.]+)\)", re.M)


def result(cid: str, checks: float) -> dict:
    return {"prompt_id": cid, "rep": 0, "status": "ok", "meta": {"tier": "impl"}, "latency_s": 1.0,
            "grade": {"pass": checks == 1.0, "checks": checks}, "usage": {"input_tokens": 100, "output_tokens": 10}}


def write_variant(path, rows: list[dict]) -> None:
    path.mkdir(parents=True)
    (path / "results.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")


def diffs_for(n: int) -> list[float]:
    base = [0.10, -0.05, 0.20, 0.00, 0.15, -0.10]
    return [base[i % len(base)] + 0.01 * (i // len(base)) for i in range(n)]


@pytest.mark.parametrize("n", [2, 6, 31, 40], ids=["df1", "df5", "df30", "df39-normal"])
def test_paired_interval_half_width_uses_t_quantile(tmp_path, capsys, n):
    diffs = diffs_for(n)
    write_variant(tmp_path / run.VARIANT_DIR["high"], [result(f"c{i}", 0.5 + d) for i, d in enumerate(diffs)])
    write_variant(tmp_path / run.VARIANT_DIR["medium"], [result(f"c{i}", 0.5) for i in range(n)])

    run.cmd_summarize(Namespace(data=tmp_path))

    m = LINE.search(capsys.readouterr().out)
    assert m, "no paired line for the impl tier"
    cases, mean, lo, hi = int(m[1]), float(m[2]), float(m[3]), float(m[4])
    half = T_QUANTILE[n - 1] * statistics.stdev(diffs) / n ** 0.5
    assert cases == n
    assert mean == pytest.approx(statistics.mean(diffs), abs=1e-3)
    assert (hi - lo) / 2 == pytest.approx(half, abs=6e-4)
