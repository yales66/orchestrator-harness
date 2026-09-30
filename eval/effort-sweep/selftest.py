"""Offline check of the graders: no model is called.

For every case three constructed end states go through the same workspace
setup and grader the runner uses:

  oracle  impl: the files the original change landed with, overlaid on the base
          commit; read-only tiers: the report the main thread adopted.
  null    impl: the untouched workspace; read-only tiers: an empty report.
  broken  impl: only the original change's tests, implementation left at base,
          so something changed but the self-verification fails; read-only
          tiers: a plausible report with the key conclusion wrong.

  leak    the prepared clone itself: `git log --all` lists no commit newer
          than the dispatch commit or outside its history, only `main` is
          left, no remote, and `git cat-file -e` fails for the landed commit
          and for every source branch tip that is not an ancestor of the base.

Expected: oracle passes, null and broken fail, leak is clean. Exit status 1 on
any mismatch.

  python3 eval/effort-sweep/selftest.py --data "$DATA" [--cases id,id] [--states oracle,null,broken,leak]
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import dirty_manifest, leak_check, load_cases, overlay, prepare_workspace, remove_workspace  # noqa: E402
from grade import grade_impl, grade_text  # noqa: E402

EXPECT = {"oracle": 1, "null": 0, "broken": 0, "leak": 1}


def run_state(case: dict, state: str, keep: bool) -> dict:
    t0 = time.monotonic()
    if state == "leak":
        ws = prepare_workspace(case, "selftest-leak")
        try:
            problems = leak_check(case, ws)
        finally:
            if not keep:
                remove_workspace(ws)
        return {"id": case["id"], "tier": case["tier"], "state": state, "pass": int(not problems),
                "checks": float(not problems), "ok": not problems, "seconds": round(time.monotonic() - t0, 1),
                "explanation": "; ".join(problems) or "clone holds only the dispatch commit's history",
                "detail": {"problems": problems}}
    if case["tier"] == "impl":
        ws = prepare_workspace(case, f"selftest-{state}")
        try:
            before = dirty_manifest(ws)
            if state == "oracle":
                overlay(case["repo"], case["oracle_commit"], case["oracle_files"], ws)
            elif state == "broken":
                overlay(case["repo"], case["oracle_commit"], case["broken_files"], ws)
            g = grade_impl(case, ws, before)
        finally:
            if not keep:
                remove_workspace(ws)
    else:
        answer = {"oracle": case["oracle_answer"], "null": "", "broken": case["wrong_answer"]}[state]
        g = grade_text(case, answer, changed=[])
    return {"id": case["id"], "tier": case["tier"], "state": state, "pass": g["grade"]["pass"],
            "checks": round(g["grade"]["checks"], 3), "ok": g["grade"]["pass"] == EXPECT[state],
            "seconds": round(time.monotonic() - t0, 1), "explanation": g["explanation"]["pass"], "detail": g["detail"]}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data", required=True, type=Path, help="flow directory holding cases.jsonl")
    ap.add_argument("--cases", default="", help="comma-separated case ids (default: all)")
    ap.add_argument("--states", default="oracle,null,broken,leak")
    ap.add_argument("--jobs", type=int, default=3, help="cases graded in parallel")
    ap.add_argument("--keep", action="store_true", help="keep workspaces for inspection")
    ap.add_argument("--out", type=Path, help="write per-state results as JSON lines here")
    args = ap.parse_args()

    cases = load_cases(args.data / "cases.jsonl")
    if args.cases:
        wanted = set(args.cases.split(","))
        cases = [c for c in cases if c["id"] in wanted]
    states = args.states.split(",")
    jobs = [(c, s) for c in cases for s in states]
    with ThreadPoolExecutor(max_workers=args.jobs) as pool:
        rows = list(pool.map(lambda cs: run_state(cs[0], cs[1], args.keep), jobs))

    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            for r in rows:
                fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    bad = [r for r in rows if not r["ok"]]
    for r in rows:
        mark = "ok " if r["ok"] else "BAD"
        print(f"{mark} {r['id']:<14} {r['state']:<7} pass={r['pass']} checks={r['checks']:.2f} {r['seconds']:>6}s  {r['explanation'][:160]}")
    print()
    for s in states:
        sub = [r for r in rows if r["state"] == s]
        if sub:
            print(f"{s:<7} pass rate {sum(r['pass'] for r in sub)}/{len(sub)} = {sum(r['pass'] for r in sub) / len(sub):.0%} (expected {EXPECT[s]:.0%})")
    print("mismatches:", len(bad))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
