"""Effort sweep runner: the same brief, dispatched to a subagent at effort high and at effort medium.

Each (case, rep) gets a fresh isolated clone of the case's repository holding
only the commit the brief was written against and its history (see common.py),
checked for leftovers of later work before the model is called, and a fresh
CLAUDE_CONFIG_DIR holding the
zh/ harness as installed (CLAUDE.md, playbook, hooks, skills, agents) plus one
agent definition, `effort-sweep-<effort>`, whose frontmatter pins the model and
the effort. `claude -p` starts a main thread that makes exactly one Agent call
to that agent; a PreToolUse hook swaps the placeholder prompt for the case's
brief, so the subagent receives the brief byte for byte. The subagent's own
transcript supplies the report, usage, model and tool calls; the main thread's
usage is kept apart as dispatch overhead.

  python3 eval/effort-sweep/run.py run --data "$DATA" --effort high      # -> $DATA/baseline/
  python3 eval/effort-sweep/run.py run --data "$DATA" --effort medium    # -> $DATA/v1/
  python3 eval/effort-sweep/run.py summarize --data "$DATA"
  python3 eval/effort-sweep/run.py run --data "$DATA" --effort high --dry-run   # no model call

The first real run stops with exit 2 until the user runs it once with
--approve-harness, which records a hash of the runner, grader, cases and the
installed rule files in $DATA/_state.json.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import statistics
import subprocess
import sys
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent.parent
sys.path.insert(0, str(HERE))

from common import (TIER_LABELS, TIERS, changed_since, dirty_manifest, git, leak_check, load_cases,  # noqa: E402
                    materialize_attachments, path_matches, prepare_workspace, read_answer_files,
                    remove_workspace, rewrite_prompt, sha256_files, wilson, WORK_ROOT)
from grade import grade_impl, grade_text, setup_ignores  # noqa: E402

MODEL = "claude-opus-5-5"
HARNESS = REPO_ROOT / "zh"
VARIANT_DIR = {"high": "baseline", "medium": "v1"}
PLACEHOLDER = "BRIEF"
AGENT_TOOLS = "Agent,Bash,Read,Edit,Write,Glob,Grep,NotebookEdit,TodoWrite,WebFetch,WebSearch"
METRICS = [
    {"id": "pass", "label": "通过", "kind": "binary"},
    {"id": "checks", "label": "检查点比例", "kind": "continuous"},
]
HARNESS_FILES = [HERE / "run.py", HERE / "grade.py", HERE / "common.py",
                 HARNESS / "CLAUDE.md", HARNESS / "orchestrator-playbook.md", HARNESS / "settings.example.json"]

AGENT_BODY = (
    "You are a Claude Code subagent. Carry out the task in the brief you are given, "
    "working in the current directory, and finish with the report the brief asks for."
)

INJECT_HOOK = r'''import json, os, sys
data = json.load(sys.stdin)
inp = data.get("tool_input") or {}
if data.get("tool_name") in ("Agent", "Task") and inp.get("subagent_type") == os.environ.get("EFFORT_SWEEP_AGENT"):
    brief = open(os.environ["EFFORT_SWEEP_BRIEF"], encoding="utf-8").read()
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "allow",
                                             "updatedInput": dict(inp, prompt=brief)}}))
'''

_write_lock = threading.Lock()


# ---------------------------------------------------------------- config dir

def agent_name(effort: str) -> str:
    return f"effort-sweep-{effort}"


def agent_definition(effort: str) -> str:
    return (f"---\nname: {agent_name(effort)}\n"
            f"description: Worker for the effort sweep eval; runs one brief at effort {effort}.\n"
            f"model: {MODEL}\neffort: {effort}\n---\n\n{AGENT_BODY}\n")


def build_config(cfg: Path, effort: str) -> None:
    """Install zh/ the way README's install steps do, plus the sweep agent and the brief-injection hook."""
    cfg.mkdir(parents=True)
    shutil.copy(HARNESS / "CLAUDE.md", cfg / "CLAUDE.md")
    shutil.copy(HARNESS / "orchestrator-playbook.md", cfg / "orchestrator-playbook.md")
    shutil.copytree(HARNESS / "hooks", cfg / "hooks", ignore=shutil.ignore_patterns("tests"))
    shutil.copytree(HARNESS / "skills", cfg / "skills")
    shutil.copytree(HARNESS / "agents", cfg / "agents")
    (cfg / "agents" / f"{agent_name(effort)}.md").write_text(agent_definition(effort), encoding="utf-8")
    (cfg / "hooks" / "effort_sweep_inject.py").write_text(INJECT_HOOK, encoding="utf-8")
    hooks = json.loads((HARNESS / "settings.example.json").read_text(encoding="utf-8"))["hooks"]
    hooks = json.loads(json.dumps(hooks).replace("$HOME/.claude", str(cfg)))
    hooks.setdefault("PreToolUse", []).insert(0, {
        "matcher": "Agent|Task",
        "hooks": [{"type": "command", "command": f"python3 {cfg}/hooks/effort_sweep_inject.py", "timeout": 10}],
    })
    (cfg / "settings.json").write_text(json.dumps({"hooks": hooks}, indent=2), encoding="utf-8")


def main_prompt(case: dict, effort: str, inline_brief: str | None) -> str:
    desc = case["id"]
    if inline_brief is None:
        return (f'Call the Agent tool exactly once, with subagent_type "{agent_name(effort)}", description "{desc}", '
                f'run_in_background false, and prompt "{PLACEHOLDER}". Do not call any other tool, do not read any '
                f'file and do not work on anything yourself. After the Agent tool returns, reply with exactly: DONE')
    return (f'Call the Agent tool exactly once, with subagent_type "{agent_name(effort)}", description "{desc}", '
            f'run_in_background false, and as prompt the text between the lines <<<BRIEF and BRIEF>>> below, copied '
            f'character for character without those two lines. Do not call any other tool, do not read any file and '
            f'do not work on anything yourself. After the Agent tool returns, reply with exactly: DONE\n'
            f'<<<BRIEF\n{inline_brief}\nBRIEF>>>')


def child_env(cfg: Path, brief_file: Path, effort: str) -> dict:
    env = {
        "PATH": os.environ["PATH"], "HOME": os.environ["HOME"], "USER": os.environ.get("USER", ""),
        "LOGNAME": os.environ.get("LOGNAME", ""), "SHELL": "/bin/bash", "LANG": "en_US.UTF-8", "TERM": "dumb",
        "TMPDIR": os.environ.get("TMPDIR", "/tmp"), "CLAUDE_CONFIG_DIR": str(cfg), "DISABLE_AUTOUPDATER": "1",
        "EFFORT_SWEEP_BRIEF": str(brief_file), "EFFORT_SWEEP_AGENT": agent_name(effort),
    }
    for key in ("CLAUDE_CODE_OAUTH_TOKEN", "ANTHROPIC_API_KEY"):
        if os.environ.get(key):
            env[key] = os.environ[key]
    assert "CLAUDE_CODE_EFFORT_LEVEL" not in env
    return env


# ---------------------------------------------------------------- transcripts

def read_jsonl(path: Path) -> list[dict]:
    out = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return out


def sum_usage(records: list[dict]) -> tuple[dict, list[str], str | None]:
    per_msg, models, stop = {}, [], None
    for r in records:
        if r.get("type") != "assistant":
            continue
        msg = r.get("message", {})
        if msg.get("model") and msg["model"] != "<synthetic>":
            models.append(msg["model"])
        if msg.get("usage"):
            per_msg[msg.get("id") or id(r)] = msg["usage"]
        stop = msg.get("stop_reason") or stop
    usage = {k: 0 for k in ("input_tokens", "output_tokens", "cache_read_input_tokens", "cache_creation_input_tokens")}
    for u in per_msg.values():
        for k in usage:
            usage[k] += u.get(k) or 0
    return usage, models, stop


def first_user_text(records: list[dict]) -> str:
    for r in records:
        if r.get("type") == "user":
            c = r.get("message", {}).get("content")
            if isinstance(c, str):
                return c
            if isinstance(c, list):
                return "".join(x.get("text", "") for x in c if isinstance(x, dict) and x.get("type") == "text")
    return ""


def final_report(records: list[dict]) -> str:
    final = ""
    for r in records:
        if r.get("type") != "assistant":
            continue
        for c in r.get("message", {}).get("content", []) or []:
            if not isinstance(c, dict):
                continue
            if c.get("type") == "text" and c.get("text", "").strip():
                final = c["text"]
            if c.get("type") == "tool_use" and c.get("name") == "SubagentHandback":
                final = (c.get("input") or {}).get("message", final)
    return final


def tool_uses(records: list[dict]) -> list[dict]:
    out = []
    for r in records:
        if r.get("type") == "assistant":
            for c in r.get("message", {}).get("content", []) or []:
                if isinstance(c, dict) and c.get("type") == "tool_use":
                    out.append(c)
    return out


def effort_evidence(records: list[dict], meta: dict) -> list[str]:
    """Every value stored under a key containing 'effort', to show which effort the subagent actually ran at."""
    found = []

    def walk(x, path):
        if isinstance(x, dict):
            for k, v in x.items():
                if "effort" in str(k).lower() and not isinstance(v, (dict, list)):
                    found.append(f"{path}.{k}={v}")
                walk(v, f"{path}.{k}")
        elif isinstance(x, list):
            for i, v in enumerate(x[:50]):
                walk(v, path)

    walk(meta, "meta")
    for r in records[:5]:
        walk(r, "record")
    return sorted(set(found))[:20]


def to_trace(records: list[dict], agent_md: str) -> list[dict]:
    turns = [{"role": "system", "content": agent_md}]
    for r in records:
        msg = r.get("message", {})
        if r.get("type") == "user":
            c = msg.get("content")
            if isinstance(c, str):
                turns.append({"role": "user", "content": c})
                continue
            for x in c or []:
                if not isinstance(x, dict):
                    continue
                if x.get("type") == "tool_result":
                    body = x.get("content")
                    if isinstance(body, list):
                        body = "\n".join(y.get("text", "") for y in body if isinstance(y, dict))
                    body = str(body or "")
                    turns.append({"role": "tool_result", "content": body if len(body) < 20000 else body[:20000] + "\n…[truncated]"})
                elif x.get("type") == "text":
                    turns.append({"role": "user", "content": x.get("text", "")})
        elif r.get("type") == "assistant":
            thinking = ""
            for x in msg.get("content", []) or []:
                if not isinstance(x, dict):
                    continue
                if x.get("type") == "thinking":
                    thinking += x.get("thinking", "")
                elif x.get("type") == "text":
                    turn = {"role": "assistant", "content": x.get("text", "")}
                    if thinking:
                        turn["thinking"], thinking = thinking, ""
                    turns.append(turn)
                elif x.get("type") == "tool_use":
                    turn = {"role": "tool_call", "name": x.get("name"), "content": json.dumps(x.get("input"), ensure_ascii=False, indent=2)}
                    if thinking:
                        turn["thinking"], thinking = thinking, ""
                    turns.append(turn)
    return turns


def normalise_brief(text: str) -> str:
    return "\n".join(line.rstrip() for line in text.strip().splitlines())


def leak_signals(uses: list[dict], case: dict) -> list[str]:
    """Tool calls that could reach the answer: the original checkout, or history after the base commit."""
    hits = []
    oracle = case.get("oracle_commit", "")
    for u in uses:
        if u.get("name") == "SubagentHandback":
            continue
        blob = json.dumps(u.get("input"), ensure_ascii=False)
        if case["repo"] in blob:
            hits.append(f"{u.get('name')}: original checkout path")
        if re.search(r"git[^\"]{0,40}(log|show|diff)[^\"]{0,80}--all", blob):
            hits.append(f"{u.get('name')}: git history across all refs")
        if oracle and oracle in blob:
            hits.append(f"{u.get('name')}: oracle commit {oracle}")
    return sorted(set(hits))


# ---------------------------------------------------------------- one attempt

def append_jsonl(path: Path, row: dict) -> None:
    with _write_lock:
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")


def record_error(vdir: Path, case: dict, rep: int, cls: str, detail: str, model=None, usage=None) -> None:
    append_jsonl(vdir / "errors.jsonl", {"prompt_id": case["id"], "rep": rep, "failure_class": cls, "detail": detail[:4000],
                                         "model": model, "usage": usage, "retries": 0, "ts": time.strftime("%Y-%m-%dT%H:%M:%S")})


def original_status(repo: str) -> str:
    return hashlib.sha1(git(repo, "status", "--porcelain=v1", check=False).encode()).hexdigest()


def run_attempt(case: dict, rep: int, args, vdir: Path) -> None:
    effort = args.effort
    tmp = Path(tempfile.mkdtemp(prefix=f"effort-sweep-{case['id']}-{effort}-", dir=WORK_ROOT))
    out_dir, cfg = tmp / "out", tmp / "config"
    out_dir.mkdir()
    try:
        ws = prepare_workspace(case, f"{effort}-r{rep}")
    except Exception as exc:
        record_error(vdir, case, rep, "harness_error", "workspace setup: " + repr(exc))
        shutil.rmtree(tmp, ignore_errors=True)
        return
    try:
        problems = leak_check(case, ws)
        if problems:
            record_error(vdir, case, rep, "workspace_leak", "; ".join(problems))
            return
        materialize_attachments(case, out_dir)
        brief = rewrite_prompt(case, ws, out_dir)
        brief_file = tmp / "brief.txt"
        brief_file.write_text(brief, encoding="utf-8")
        build_config(cfg, effort)
        before = dirty_manifest(ws)
        orig_before = original_status(case["repo"])
        cmd = ["claude", "-p", main_prompt(case, effort, brief if args.inline_brief else None),
               "--model", MODEL, "--output-format", "stream-json", "--verbose",
               "--permission-mode", "acceptEdits", "--allowedTools", AGENT_TOOLS,
               "--add-dir", str(out_dir), "--max-budget-usd", str(args.max_budget_usd)]
        if args.dry_run:
            leaked = case["repo"] in brief
            print(f"[dry-run] {case['id']} rep{rep} effort={effort}\n  workspace {ws}\n  config {cfg}\n"
                  f"  brief {brief_file} ({len(brief)} chars; original path left in brief: {leaked})\n"
                  f"  agent file {cfg / 'agents' / (agent_name(effort) + '.md')}\n  command {' '.join(cmd[:2])} <main prompt> {' '.join(cmd[3:])}")
            return

        env = child_env(cfg, brief_file, effort)
        t0 = time.monotonic()
        try:
            with open(tmp / "stream.jsonl", "w") as so, open(tmp / "stderr.log", "w") as se:
                proc = subprocess.run(cmd, cwd=ws, env=env, stdout=so, stderr=se, timeout=args.timeout_s, start_new_session=True)
            exit_code = proc.returncode
        except subprocess.TimeoutExpired:
            record_error(vdir, case, rep, "timeout", f"wall-clock ceiling {args.timeout_s}s")
            return
        wall = time.monotonic() - t0

        session = None
        for line in (tmp / "stream.jsonl").read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                ev = json.loads(line)
            except json.JSONDecodeError:
                continue
            session = ev.get("session_id") or session
        main_files = list(cfg.glob(f"projects/*/{session}.jsonl")) if session else []
        sub_files = list(cfg.glob(f"projects/*/{session}/subagents/agent-*.jsonl")) if session else []
        if len(sub_files) != 1:
            record_error(vdir, case, rep, "dispatch_missing" if not sub_files else "dispatch_multiple",
                         f"exit {exit_code}; {len(sub_files)} subagent transcripts; stderr tail: "
                         + (tmp / "stderr.log").read_text(errors="replace")[-1500:])
            return
        sub = read_jsonl(sub_files[0])
        meta_path = sub_files[0].with_suffix(".meta.json")
        sub_meta = json.loads(meta_path.read_text()) if meta_path.exists() else {}
        usage, models, stop = sum_usage(sub)
        main_usage, main_models, _ = sum_usage(read_jsonl(main_files[0])) if main_files else ({}, [], None)

        received = first_user_text(sub)
        if normalise_brief(received) != normalise_brief(brief):
            record_error(vdir, case, rep, "dispatch_mismatch",
                         f"subagent received {len(received)} chars, brief has {len(brief)}", models[-1] if models else None, usage)
            return
        wrong = sorted({m for m in models if m != MODEL})
        if not models or wrong:
            record_error(vdir, case, rep, "model_mismatch", f"served {sorted(set(models))}, expected {MODEL}",
                         models[-1] if models else None, usage)
            return

        uses = tool_uses(sub)
        report = final_report(sub)
        ignores = setup_ignores(case)
        if case["tier"] == "impl":
            g = grade_impl(case, ws, before)
        else:
            changed = [p for p in changed_since(ws, before) if not path_matches(p, ignores)]
            g = grade_text(case, report + read_answer_files(case, ws, out_dir), changed)

        stamps = [r.get("timestamp") for r in sub if r.get("timestamp")]
        span = None
        if len(stamps) >= 2:
            from datetime import datetime
            span = (datetime.fromisoformat(stamps[-1].replace("Z", "+00:00")) -
                    datetime.fromisoformat(stamps[0].replace("Z", "+00:00"))).total_seconds()

        raw = vdir / "raw" / f"{case['id']}_rep{rep}"
        raw.mkdir(parents=True, exist_ok=True)
        shutil.copy(sub_files[0], raw / "subagent.jsonl")
        if meta_path.exists():
            shutil.copy(meta_path, raw / "subagent.meta.json")
        for f in ("stream.jsonl", "stderr.log"):
            shutil.copy(tmp / f, raw / f)
        for f in out_dir.glob("*"):
            if f.is_file():
                shutil.copy(f, raw / f.name)

        agent_md = (cfg / "agents" / f"{agent_name(effort)}.md").read_text(encoding="utf-8")
        (vdir / "traces").mkdir(exist_ok=True)
        (vdir / "traces" / f"{case['id']}_rep{rep}.json").write_text(
            json.dumps(to_trace(sub, agent_md), ensure_ascii=False, indent=1), encoding="utf-8")

        row = {
            "prompt_id": case["id"], "prompt": brief, "rep": rep,
            "tags": [TIER_LABELS[case["tier"]], Path(case["repo"]).name],
            "status": "truncated" if stop == "max_tokens" else "ok", "stop_reason": stop,
            "grade": g["grade"], "explanation": g["explanation"],
            "model": models[-1], "usage": usage, "latency_s": round(span if span is not None else wall, 1),
            "tool_calls": len(uses),
            "meta": {
                "effort_requested": effort, "effort_seen": effort_evidence(sub, sub_meta),
                "tier": case["tier"], "base": case["base"], "exit_code": exit_code, "wall_s": round(wall, 1),
                "dispatch_usage": main_usage, "dispatch_models": sorted(set(main_models)),
                "leak_signals": leak_signals(uses, case),
                "original_repo_changed": original_status(case["repo"]) != orig_before,
                "grade_detail": g["detail"], "report_chars": len(report),
            },
        }
        append_jsonl(vdir / "results.jsonl", row)
        print(f"{case['id']} rep{rep} {effort}: pass={g['grade']['pass']} checks={g['grade']['checks']:.2f} "
              f"tokens={sum(usage.values())} tools={len(uses)}")
    except Exception as exc:  # harness failure: sidecar, never a zero in results
        record_error(vdir, case, rep, "harness_error", repr(exc))
    finally:
        if not args.keep:
            remove_workspace(ws)
            shutil.rmtree(tmp, ignore_errors=True)


# ---------------------------------------------------------------- commands

def harness_paths(data: Path) -> list[Path]:
    return HARNESS_FILES + [data / "cases.jsonl"]


def check_gate(data: Path, approve: bool) -> None:
    state_path = data / "_state.json"
    sha = sha256_files(harness_paths(data))
    state = json.loads(state_path.read_text()) if state_path.exists() else {}
    if approve:
        state.update({"flow": "effort-sweep", "metrics": METRICS,
                      "perf_fields": ["latency_s", "tool_calls", "usage"],
                      "harness_paths": [str(p) for p in harness_paths(data)], "harness_sha": sha,
                      "approved_at": time.strftime("%Y-%m-%dT%H:%M:%S")})
        state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"harness approved: {sha[:12]}")
        return
    if state.get("harness_sha") != sha:
        sys.exit("The runner, grader, cases or installed rule files differ from what was last approved "
                 f"(or nothing was approved yet). Review them, then rerun with --approve-harness. [{sha[:12]}]")


def ensure_change_md(vdir: Path, effort: str) -> None:
    if effort == "medium" and not (vdir / "change.md").exists():
        (vdir / "change.md").write_text(
            "# v1\n\nSubagent effort medium instead of high, set in the agent definition's frontmatter.\n\n"
            "Everything else is identical to baseline: model, brief, workspace, installed rule files and grader.\n",
            encoding="utf-8")


def cmd_run(args) -> int:
    data = args.data
    if os.environ.get("CLAUDE_CODE_EFFORT_LEVEL"):
        sys.exit("CLAUDE_CODE_EFFORT_LEVEL is set; it would override the agent frontmatter. Unset it first.")
    if not args.dry_run:
        check_gate(data, args.approve_harness)
        if args.approve_harness:
            return 0
        if not (os.environ.get("CLAUDE_CODE_OAUTH_TOKEN") or os.environ.get("ANTHROPIC_API_KEY")):
            sys.exit("A fresh CLAUDE_CONFIG_DIR cannot see the keychain login. Export CLAUDE_CODE_OAUTH_TOKEN "
                     "(from `claude setup-token`) or ANTHROPIC_API_KEY.")
    cases = load_cases(data / "cases.jsonl")
    if args.cases:
        wanted = set(args.cases.split(","))
        cases = [c for c in cases if c["id"] in wanted]
    elif args.dry_run:
        cases = [next(c for c in cases if c["tier"] == t) for t in TIERS]
    vdir = data / VARIANT_DIR[args.effort]
    done = set()
    if not args.dry_run:
        vdir.mkdir(parents=True, exist_ok=True)
        ensure_change_md(vdir, args.effort)
        if (vdir / "results.jsonl").exists():
            done = {(r["prompt_id"], r["rep"]) for r in read_jsonl(vdir / "results.jsonl")}
    todo = [(c, k) for k in range(args.reps) for c in cases if (c["id"], k) not in done]
    print(f"{len(todo)} attempt(s) to run, {len(done)} already in {vdir}")
    with ThreadPoolExecutor(max_workers=args.concurrency) as pool:
        list(pool.map(lambda ck: run_attempt(ck[0], ck[1], args, vdir), todo))
    if not args.dry_run:
        summarize_variant(vdir)
    return 0


def total_tokens(u: dict) -> int:
    return sum((u or {}).values())


def summarize_variant(vdir: Path) -> dict:
    rows = [r for r in read_jsonl(vdir / "results.jsonl") if r.get("status") == "ok"] if (vdir / "results.jsonl").exists() else []
    errs = read_jsonl(vdir / "errors.jsonl") if (vdir / "errors.jsonl").exists() else []
    out = {}
    for tier in (*TIERS, "all"):
        sub = [r for r in rows if tier == "all" or r["meta"]["tier"] == tier]
        if not sub:
            continue
        k = sum(r["grade"]["pass"] for r in sub)
        lo, hi = wilson(k, len(sub))
        toks = [total_tokens(r["usage"]) for r in sub]
        outs = [r["usage"].get("output_tokens", 0) for r in sub]
        out[tier] = {"n": len(sub), "pass": k / len(sub), "ci": (lo, hi),
                     "checks": statistics.mean(r["grade"]["checks"] for r in sub),
                     "tok_med": statistics.median(toks), "tok_min": min(toks), "tok_max": max(toks),
                     "out_med": statistics.median(outs), "lat_med": statistics.median(r["latency_s"] for r in sub)}
        s = out[tier]
        print(f"{vdir.name:<8} {tier:<9} n={s['n']:<3} pass {s['pass']:.0%} [{lo:.0%}, {hi:.0%}]  checks {s['checks']:.2f}  "
              f"tokens median {s['tok_med']:,.0f} (range {s['tok_min']:,}-{s['tok_max']:,}), output median {s['out_med']:,.0f}, "
              f"latency median {s['lat_med']:.0f}s")
    print(f"{vdir.name:<8} errors {len(errs)} (see errors.jsonl)")
    return out


def cmd_summarize(args) -> int:
    data = args.data
    per = {}
    for effort, name in VARIANT_DIR.items():
        vdir = data / name
        if (vdir / "results.jsonl").exists():
            summarize_variant(vdir)
            per[effort] = [r for r in read_jsonl(vdir / "results.jsonl") if r.get("status") == "ok"]
    if len(per) < 2:
        return 0
    print("\npaired by case (mean over reps), high minus medium:")
    for tier in (*TIERS, "all"):
        diffs, tok_ratio = [], []
        ids = {r["prompt_id"] for r in per["high"]} & {r["prompt_id"] for r in per["medium"]}
        for cid in sorted(ids):
            h = [r for r in per["high"] if r["prompt_id"] == cid and (tier == "all" or r["meta"]["tier"] == tier)]
            m = [r for r in per["medium"] if r["prompt_id"] == cid and (tier == "all" or r["meta"]["tier"] == tier)]
            if h and m:
                diffs.append(statistics.mean(r["grade"]["checks"] for r in h) - statistics.mean(r["grade"]["checks"] for r in m))
                th = statistics.mean(total_tokens(r["usage"]) for r in h)
                tm = statistics.mean(total_tokens(r["usage"]) for r in m)
                if th:
                    tok_ratio.append(tm / th)
        if len(diffs) >= 2:
            mean = statistics.mean(diffs)
            half = 1.96 * statistics.stdev(diffs) / len(diffs) ** 0.5
            print(f"  {tier:<9} cases={len(diffs):<3} checks diff {mean:+.3f} (95% CI {mean - half:+.3f} to {mean + half:+.3f}); "
                  f"medium tokens / high tokens, median {statistics.median(tok_ratio):.2f}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--data", required=True, type=Path)
    r.add_argument("--effort", required=True, choices=sorted(VARIANT_DIR))
    r.add_argument("--reps", type=int, default=1)
    r.add_argument("--cases", default="")
    r.add_argument("--concurrency", type=int, default=2)
    r.add_argument("--timeout-s", type=int, default=3600, help="hard wall-clock ceiling per attempt")
    r.add_argument("--max-budget-usd", type=float, default=25.0, help="passed to claude -p per attempt")
    r.add_argument("--inline-brief", action="store_true", help="have the main thread copy the brief instead of the hook")
    r.add_argument("--approve-harness", action="store_true")
    r.add_argument("--dry-run", action="store_true", help="build workspace, config and brief; call no model")
    r.add_argument("--keep", action="store_true", help="keep workspaces and config dirs")
    s = sub.add_parser("summarize")
    s.add_argument("--data", required=True, type=Path)
    args = ap.parse_args()
    return cmd_run(args) if args.cmd == "run" else cmd_summarize(args)


if __name__ == "__main__":
    sys.exit(main())
