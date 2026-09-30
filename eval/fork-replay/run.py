#!/usr/bin/env python3
"""Fork replay runner: continue past Claude Code sessions from a decision point.

For each case (see casekit.validate_case and README.md) and each rep, the runner

1. checks out the case's repository at the recorded commit into a fresh
   `git worktree` under the system temp directory, or uses an empty directory when the case has
   no restorable repository;
2. builds a fresh CLAUDE_CONFIG_DIR from the configuration under test, drops the hook
   events the eval config names, and registers stub_hook.py as a PreToolUse hook on
   every tool, so reads run and every other call is logged and denied;
3. places the private session copy where Claude Code looks for it,
   $CLAUDE_CONFIG_DIR/projects/<slug of cwd>/<session id>.jsonl;
4. resumes it through the Agent SDK with resume + resume_session_at + fork_session:
   in "after" mode up to and including fork_uuid with resume_input as the next user
   message, in "before" mode up to the record before the user prompt that opened the
   fork_uuid turn, re-sending that prompt so the turn is generated afresh;
5. grades the continuation with the eval's grader and appends one row to
   <flow>/<variant>/results.jsonl, a trace to traces/<id>_rep<k>.json, or a failure to
   errors.jsonl, then removes the worktree and the temp directory.

Only --dry-run (steps 1 to 3, then cleanup) runs without credentials. A real run needs
CLAUDE_CODE_OAUTH_TOKEN or ANTHROPIC_API_KEY in the environment and the
claude-agent-sdk package (see README.md), and it refuses to start until the harness
fingerprint has been approved with --approve-harness.
"""
import argparse
import asyncio
import hashlib
import importlib.util
import json
import math
import os
import random
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import casekit  # noqa: E402

# Resolved because Claude Code names a session's project directory after its cwd as
# the OS reports it, with symlinks resolved, and on macOS the system temp directory
# sits behind a symlink; the session copy must land under that same name.
TMP_ROOT = os.path.realpath(tempfile.gettempdir())
STUB = os.path.join(HERE, "stub_hook.py")
DEFAULT_CFG = {
    "drop_hook_events": [],
    "stub": {"extra_readonly": [], "deny_reason": "Blocked by PreToolUse hook: this tool call was not run."},
    "sdk": {
        "rebuild_system_prompt": True,
        "verbatim_prompts": True,
        "setting_sources": ["user", "project", "local"],
        "max_turns": 40,
        "max_budget_usd": 3.0,
        "permission_mode": "default",
        # The sessions being replayed ran at high, which the installed configurations
        # do not set, and claude-opus-5-5 otherwise defaults to medium.
        "effort": "high",
    },
    "retry": {"attempts": 3, "base_s": 5.0},
}
RETRYABLE = ("overloaded", "529", "429", "rate limit", "rate_limit")


# ---------------------------------------------------------------- config dir

def _merge(base, over):
    out = dict(base)
    for k, v in (over or {}).items():
        out[k] = _merge(base[k], v) if isinstance(v, dict) and isinstance(base.get(k), dict) else v
    return out


def install_config(src, dest, cfg, log_path, playbook=None):
    """Build a CLAUDE_CONFIG_DIR at dest from src and wire the stub hook into it.

    src is either a harness tree shaped like agent-harness en/ (it has
    settings.example.json; installed the way eval/static-context installs it) or a
    ready configuration directory with its own settings.json. With playbook, that
    text replaces orchestrator-playbook.md, so a SessionStart hook that fires again
    during the replay injects the version under test.
    """
    os.makedirs(dest)
    if os.path.exists(os.path.join(src, "settings.example.json")):
        for d in ("hooks", "skills", "agents"):
            if os.path.isdir(os.path.join(src, d)):
                shutil.copytree(os.path.join(src, d), os.path.join(dest, d),
                                ignore=shutil.ignore_patterns("tests", "__pycache__"))
        for f in ("CLAUDE.md", "orchestrator-playbook.md"):
            if os.path.exists(os.path.join(src, f)):
                shutil.copy2(os.path.join(src, f), os.path.join(dest, f))
        text = open(os.path.join(src, "settings.example.json"), encoding="utf-8").read()
        settings = json.loads(text.replace("$HOME/.claude", dest))
    else:
        shutil.copytree(src, dest, dirs_exist_ok=True,
                        ignore=shutil.ignore_patterns("projects", "todos", "shell-snapshots",
                                                      "statsig", "file-history", ".git"))
        p = os.path.join(dest, "settings.json")
        settings = json.load(open(p, encoding="utf-8")) if os.path.exists(p) else {}
    hooks = settings.setdefault("hooks", {})
    for ev in cfg["drop_hook_events"]:
        hooks.pop(ev, None)
    stub_cfg = os.path.join(os.path.dirname(dest), "stub.json")
    json.dump({"log": log_path, **cfg["stub"]}, open(stub_cfg, "w", encoding="utf-8"))
    hooks.setdefault("PreToolUse", []).insert(0, {
        "matcher": "*",
        "hooks": [{"type": "command", "command": f"python3 {STUB} {stub_cfg}", "timeout": 10}],
    })
    json.dump(settings, open(os.path.join(dest, "settings.json"), "w", encoding="utf-8"), indent=2)
    if playbook is not None:
        with open(os.path.join(dest, "orchestrator-playbook.md"), "w", encoding="utf-8") as f:
            f.write(playbook)
    return dest


# ---------------------------------------------------------------- working dir

def prepare_cwd(case, root, unrestorable="empty"):
    """Return (cwd, worktree or None).

    A case without a restorable repository runs in an empty directory by default. With
    unrestorable="origin" it runs in the session's original directory as it is today;
    the stub still denies every non-read-only call, but reads then see today's files,
    not the files as they were at the fork point.
    """
    repo = case["cwd_repo"]
    if not repo:
        origin = (case.get("meta") or {}).get("origin_cwd")
        if unrestorable == "origin" and origin and os.path.isdir(origin):
            return origin, None
        cwd = os.path.join(root, "cwd")
        os.makedirs(cwd)
        return cwd, None
    path, subdir = resolve_repo(repo)
    wt = os.path.join(root, "wt")
    subprocess.run(["git", "-C", path, "worktree", "add", "--detach", wt, repo["commit"]],
                   check=True, capture_output=True, text=True)
    # normpath: Claude Code names the project directory after the cwd without a
    # trailing slash, and the session copy must sit in exactly that directory.
    cwd = os.path.normpath(os.path.join(wt, subdir))
    os.makedirs(cwd, exist_ok=True)
    return cwd, wt


WORKTREES = "/.claude/worktrees/"


def resolve_repo(repo):
    """(repository to check out from, subdirectory of the checkout to run in).

    A session that ran in a Claude Code worktree since removed records a path under
    <main>/.claude/worktrees/<name>; the commit is checked out from <main> instead,
    and whatever followed <name> in the path becomes the subdirectory.
    """
    path, subdir = repo["path"], repo.get("subdir") or ""
    if not os.path.isdir(path) and WORKTREES in path:
        main, _, rest = path.partition(WORKTREES)
        extra = rest.partition("/")[2]
        return main, os.path.join(extra, subdir) if extra and subdir else (extra or subdir)
    return path, subdir


def remove_worktree(case, wt):
    if wt:
        subprocess.run(["git", "-C", resolve_repo(case["cwd_repo"])[0], "worktree", "remove", "--force", wt],
                       capture_output=True, text=True)


def session_id_of(path):
    return os.path.splitext(os.path.basename(path))[0]


def place_session(case, cfgdir, cwd):
    dst = os.path.join(cfgdir, "projects", casekit.slug(cwd), os.path.basename(case["source_session"]))
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    shutil.copy2(case["source_session"], dst)
    return dst


PLAYBOOK_HEAD = re.compile(r"# [^\n]*Playbook\n")


def replace_playbook(path, text):
    """Swap every playbook the recorded SessionStart hook injected for text; return the count.

    The injected playbook is replayed to the model from the transcript, not reloaded
    from the configuration, so the session copy itself has to carry the version under
    test. Both records are rewritten: the hook_additional_context, including the
    rendered text a resume replays to the model, and the hook_success stdout it came from.
    """
    def swap(s):
        return (text, 1) if isinstance(s, str) and PLAYBOOK_HEAD.match(s) else (s, 0)

    out, n = [], 0
    with open(path, encoding="utf-8") as f:
        for line in f:
            r = json.loads(line)
            a = r.get("attachment") if isinstance(r.get("attachment"), dict) else {}
            if a.get("hookEvent") == "SessionStart" and a.get("type") == "hook_additional_context":
                olds = [c for c in a.get("content") or [] if swap(c)[1]]
                swapped = [swap(c) for c in a.get("content") or []]
                a["content"] = [c for c, _ in swapped]
                n += sum(k for _, k in swapped)
                # A resumed session is replayed from the record's pre-rendered text, not
                # from attachment.content, so the playbook inside it is swapped as well.
                for item in r.get("rendered") or []:
                    for old in olds:
                        if isinstance(item.get("content"), str) and old in item["content"]:
                            item["content"] = item["content"].replace(old, text)
                            olds = [o for o in olds if o != old]
                if r.get("rendered") and olds:
                    raise ValueError(f"injected playbook not found in the rendered text of {path}")
                line = json.dumps(r, ensure_ascii=False) + "\n"
            elif a.get("hookEvent") == "SessionStart" and a.get("type") == "hook_success" and a.get("stdout"):
                try:
                    o = json.loads(a["stdout"])
                except ValueError:
                    o = None
                hso = (o or {}).get("hookSpecificOutput") if isinstance(o, dict) else None
                if isinstance(hso, dict):
                    hso["additionalContext"], k = swap(hso.get("additionalContext"))
                    if k:
                        a["stdout"] = json.dumps(o)
                        n += k
                        line = json.dumps(r, ensure_ascii=False) + "\n"
            out.append(line)
    if n == 0:
        raise ValueError(f"no injected playbook to replace in {path}")
    with open(path, "w", encoding="utf-8") as f:
        f.writelines(out)
    return n


def fork_plan(case):
    """(resume_session_at, prompt, rewound) for the case's fork mode."""
    if case["fork_mode"] == "after":
        return case["fork_uuid"], case["resume_input"], 0
    recs = {}
    with open(case["source_session"], encoding="utf-8") as f:
        for line in f:
            r = json.loads(line)
            if r.get("uuid"):
                recs[r["uuid"]] = r
    cur, rewound = recs.get(case["fork_uuid"]), 0
    while cur is not None:
        content = (cur.get("message") or {}).get("content")
        is_prompt = cur.get("type") == "user" and not cur.get("isMeta") and (
            isinstance(content, str) or any(b.get("type") == "text" for b in content or []))
        if is_prompt:
            if not cur.get("parentUuid"):
                raise ValueError("before mode cannot fork at the first turn of a session")
            text = content if isinstance(content, str) else "\n".join(
                b["text"] for b in content if b.get("type") == "text")
            return cur["parentUuid"], text, rewound
        rewound += cur.get("type") == "assistant"
        cur = recs.get(cur.get("parentUuid"))
    raise ValueError("no user prompt found before fork_uuid")


# ---------------------------------------------------------------- trajectory

def read_calls(log_path):
    if not os.path.exists(log_path):
        return []
    return [json.loads(l) for l in open(log_path, encoding="utf-8") if l.strip()]


def to_trajectory_and_trace(prompt, messages, calls):
    texts, trace, thinking = [], [{"role": "user", "content": prompt}], None
    for m in messages:
        kind = type(m).__name__
        if kind == "AssistantMessage":
            for b in m.content:
                bk = type(b).__name__
                if bk == "ThinkingBlock":
                    thinking = b.thinking
                elif bk == "TextBlock":
                    texts.append(b.text)
                    trace.append({"role": "assistant", "content": b.text, **({"thinking": thinking} if thinking else {})})
                    thinking = None
                elif bk == "ToolUseBlock":
                    trace.append({"role": "tool_call", "name": b.name,
                                  "content": json.dumps(b.input, ensure_ascii=False, indent=2),
                                  **({"thinking": thinking} if thinking else {})})
                    thinking = None
        elif kind == "UserMessage" and isinstance(m.content, list):
            for b in m.content:
                if type(b).__name__ == "ToolResultBlock":
                    c = b.content if isinstance(b.content, str) else json.dumps(b.content, ensure_ascii=False)
                    trace.append({"role": "tool_result", "content": c})
    logged = [{"tool": c["tool"], "input": c["input"], "decision": c["decision"]} for c in calls]
    traj = {
        "calls": logged,
        "tool_calls": logged,  # same list under the name eval/rules-missed-asks reads
        "texts": texts,
        "final_text": texts[-1] if texts else "",
    }
    return traj, trace


# ---------------------------------------------------------------- harness gate

def harness_fingerprint(paths):
    h = hashlib.sha256()
    for p in sorted(paths):
        if os.path.isdir(p):
            for dp, dn, fn in sorted(os.walk(p)):
                dn[:] = sorted(d for d in dn if d not in ("__pycache__", ".git", "tests"))
                for f in sorted(fn):
                    fp = os.path.join(dp, f)
                    h.update(os.path.relpath(fp, p).encode())
                    h.update(open(fp, "rb").read())
        else:
            h.update(p.encode())
            h.update(open(p, "rb").read())
    return h.hexdigest()


def check_harness(args, flow):
    state = {}
    sp = os.path.join(flow, "_state.json")
    if os.path.exists(sp):
        state = json.load(open(sp, encoding="utf-8"))
    paths = [os.path.join(HERE, f) for f in ("run.py", "stub_hook.py", "casekit.py")]
    paths += [os.path.abspath(args.grader), os.path.abspath(args.eval_config),
              os.path.abspath(args.cases), os.path.abspath(args.config)]
    paths += [os.path.join(flow, p) for p in state.get("harness_paths", [])]
    if args.playbook:
        paths.append(os.path.abspath(args.playbook))
    sha = harness_fingerprint(paths)
    # Kept per variant, because arms of one flow may differ in what they run under,
    # such as the playbook, and each arm is approved on its own.
    rec = os.path.join(flow, "_harness.json")
    approved = json.load(open(rec, encoding="utf-8")) if os.path.exists(rec) else {}
    approved = approved.get("variants", {})
    if args.approve_harness:
        approved[args.variant] = {"sha": sha, "paths": sorted(paths), "approved_at": time.time()}
        json.dump({"variants": approved}, open(rec, "w", encoding="utf-8"), indent=2)
        return
    if approved.get(args.variant, {}).get("sha") != sha:
        print("harness fingerprint changed or never approved: review the runner, grader, eval config, "
              "cases and configuration under test, then rerun once with --approve-harness", file=sys.stderr)
        sys.exit(2)


# ---------------------------------------------------------------- one attempt

def child_env(cfgdir, home, model, raw_bodies=None):
    env = {"CLAUDE_CONFIG_DIR": cfgdir, "HOME": home, "DISABLE_AUTOUPDATER": "1",
           "CLAUDE_CODE_SUBAGENT_MODEL": model}
    if raw_bodies:
        # Claude Code writes each request body it sends into this directory, which is
        # how a trial run checks what prefix the model actually saw.
        env["OTEL_LOG_RAW_API_BODIES"] = "file:" + raw_bodies
    return env


def build_options(case, cfg, args, cwd, cfgdir, home, resume_at, stderr_path, raw_bodies=None):
    from claude_agent_sdk import ClaudeAgentOptions
    sdk = cfg["sdk"]
    env = child_env(cfgdir, home, args.model, raw_bodies)
    err = open(stderr_path, "a", encoding="utf-8")
    kw = dict(
        cwd=cwd,
        model=args.model,
        resume=session_id_of(case["source_session"]),
        resume_session_at=resume_at,
        fork_session=True,
        setting_sources=sdk["setting_sources"],
        permission_mode=sdk["permission_mode"],
        max_turns=sdk["max_turns"],
        max_budget_usd=sdk["max_budget_usd"],
        env=env,
        stderr=lambda line: err.write(line + "\n"),
    )
    async def deny_all(tool_name, tool_input, context):
        # Second layer behind the stub hook: anything that still reaches a permission
        # prompt is refused.
        from claude_agent_sdk import PermissionResultDeny
        return PermissionResultDeny(message=cfg["stub"]["deny_reason"])

    kw["can_use_tool"] = deny_all
    if sdk.get("effort"):
        kw["effort"] = sdk["effort"]
    if sdk["rebuild_system_prompt"]:
        kw["system_prompt"] = {"type": "preset", "preset": "claude_code", "snapshot": False}
    if sdk.get("verbatim_prompts"):
        kw["verbatim_prompts"] = True
    return ClaudeAgentOptions(**kw)


async def attempt(case, rep, cfg, args):
    root = tempfile.mkdtemp(prefix=f"fr-{case['id'][:8]}-r{rep}-", dir=TMP_ROOT)
    wt = None
    try:
        cwd, wt = prepare_cwd(case, root, args.unrestorable_cwd)
        log = os.path.join(root, "calls.jsonl")
        playbook = open(args.playbook, encoding="utf-8").read() if args.playbook else None
        cfgdir = install_config(args.config, os.path.join(root, "config"), cfg, log, playbook)
        home = os.path.join(root, "home")
        os.makedirs(home)
        placed = place_session(case, cfgdir, cwd)
        replaced = replace_playbook(placed, playbook) if playbook is not None else 0
        resume_at, prompt, rewound = fork_plan(case)
        if args.dry_run:
            return {"dry_run": True, "cwd": cwd, "worktree": wt, "session": placed,
                    "resume_session_at": resume_at, "rewound_assistant_records": rewound,
                    "playbooks_replaced": replaced,
                    "prompt_head": prompt[:120], "settings": json.load(open(os.path.join(cfgdir, "settings.json")))}
        from claude_agent_sdk import query
        raw = os.path.join(os.path.abspath(args.raw_bodies), f"{case['id']}_rep{rep}") if args.raw_bodies else None
        opts = build_options(case, cfg, args, cwd, cfgdir, home, resume_at, os.path.join(root, "stderr.log"), raw)
        t0, messages = time.monotonic(), []
        async for m in query(prompt=prompt, options=opts):
            messages.append(m)
        latency = time.monotonic() - t0
        calls = read_calls(log)
        traj, trace = to_trajectory_and_trace(prompt, messages, calls)
        result = next((m for m in reversed(messages) if type(m).__name__ == "ResultMessage"), None)
        models = {m.model for m in messages if type(m).__name__ == "AssistantMessage" and getattr(m, "model", None)}
        return {"traj": traj, "trace": trace, "result": result, "models": sorted(models),
                "latency_s": round(latency, 2), "rewound": rewound, "calls": calls}
    finally:
        remove_worktree(case, wt)
        if not args.keep:
            shutil.rmtree(root, ignore_errors=True)


# ---------------------------------------------------------------- run loop

def load_module(path):
    spec = importlib.util.spec_from_file_location("eval_grader", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def append(path, row, lock):
    with lock:
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def usage_dict(result):
    u = getattr(result, "usage", None) or {}
    keys = ("input_tokens", "output_tokens", "cache_read_input_tokens", "cache_creation_input_tokens")
    return {k: int(u.get(k, 0) or 0) for k in keys}


async def run_one(case, rep, cfg, args, grader, out, lock, sem):
    async with sem:
        tries = cfg["retry"]["attempts"]
        for k in range(1, tries + 1):
            err_row = {"prompt_id": case["id"], "rep": rep, "attempt": k, "variant": args.variant}
            try:
                r = await asyncio.wait_for(attempt(case, rep, cfg, args), args.timeout_s)
            except asyncio.TimeoutError:
                append(out["errors"], {**err_row, "failure_class": "timeout"}, lock)
                return
            except Exception as e:  # harness or serving error
                msg = str(e)
                if args.dry_run:
                    print(json.dumps({"id": case["id"], "dry_run_error": msg[:2000]}, ensure_ascii=False))
                    return
                retry = any(s in msg.lower() for s in RETRYABLE) and k < tries
                append(out["errors"], {**err_row, "failure_class": "harness-or-serving", "message": msg[:2000],
                                       "will_retry": retry}, lock)
                if retry:
                    await asyncio.sleep(cfg["retry"]["base_s"] * 2 ** (k - 1) * (0.5 + random.random()))
                    continue
                return
            if args.dry_run:
                print(json.dumps({"id": case["id"], **r}, ensure_ascii=False, indent=2))
                return
            res = r["result"]
            served_ok = all(m.startswith(args.model) for m in r["models"])
            if not served_ok:
                append(out["errors"], {**err_row, "failure_class": "served-model-mismatch",
                                       "model": r["models"], "usage": usage_dict(res)}, lock)
                return
            try:
                g = grader.grade(case, r["traj"], cfg)
            except Exception as e:
                append(out["errors"], {**err_row, "failure_class": "grader-error", "message": str(e)[:2000],
                                       "model": r["models"], "usage": usage_dict(res)}, lock)
                return
            subtype = getattr(res, "subtype", None)
            stop = getattr(res, "stop_reason", None) or subtype
            status = "truncated" if stop in ("max_tokens", "error_max_turns", "error_max_budget_usd") else "ok"
            trace_rel = f"traces/{case['id']}_rep{rep}.json"
            json.dump(r["trace"], open(os.path.join(out["dir"], trace_rel), "w", encoding="utf-8"),
                      ensure_ascii=False, indent=1)
            append(out["results"], {
                "prompt_id": case["id"], "rep": rep, "prompt": case["resume_input"] if case["fork_mode"] == "after" else r["trace"][0]["content"],
                "tags": case["tags"], "stop_reason": stop, "status": status,
                "grade": g["grade"], "explanation": g.get("explanation", {}),
                "model": r["models"][0] if r["models"] else args.model, "usage": usage_dict(res),
                "latency_s": r["latency_s"], "tool_calls": len(r["calls"]),
                "meta": {"outcome": g.get("outcome"), "first_action": g.get("first_action"),
                         "attempts": k, "num_turns": getattr(res, "num_turns", None),
                         "reported_cost_usd": getattr(res, "total_cost_usd", None),
                         "fork_session_id": getattr(res, "session_id", None),
                         "rewound_assistant_records": r["rewound"], "fork_mode": case["fork_mode"]},
                "trace": trace_rel,
            }, lock)
            return


def wilson(p, n, z=1.96):
    if n == 0:
        return (0.0, 0.0)
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (max(0.0, c - h), min(1.0, c + h))


def summarize(results_path, metric):
    rows = [json.loads(l) for l in open(results_path, encoding="utf-8")] if os.path.exists(results_path) else []
    ok = [r for r in rows if r["status"] == "ok"]
    vals = [r["grade"][metric] for r in ok]
    n = len(vals)
    p = sum(vals) / n if n else 0.0
    lo, hi = wilson(p, n)
    print(f"{metric}: {p:.3f} (95% CI {lo:.3f}-{hi:.3f}) over {n} ok rows; "
          f"{len(rows) - n} truncated; cases x reps = {len(rows)}")


async def main_async(args):
    cfg = _merge(DEFAULT_CFG, json.load(open(args.eval_config, encoding="utf-8")))
    cases = casekit.load_cases(args.cases)
    if args.only:
        keep = set(args.only.split(","))
        cases = [c for c in cases if c["id"] in keep]
    grader = load_module(args.grader)
    flow = os.path.abspath(args.flow)
    vdir = os.path.join(flow, args.variant)
    os.makedirs(os.path.join(vdir, "traces"), exist_ok=True)
    out = {"dir": vdir, "results": os.path.join(vdir, "results.jsonl"), "errors": os.path.join(vdir, "errors.jsonl")}
    if not args.dry_run:
        if not (os.environ.get("CLAUDE_CODE_OAUTH_TOKEN") or os.environ.get("ANTHROPIC_API_KEY")):
            sys.exit("no credentials: export CLAUDE_CODE_OAUTH_TOKEN (claude setup-token) or ANTHROPIC_API_KEY")
        check_harness(args, flow)
    done = set()
    if os.path.exists(out["results"]):
        done = {(r["prompt_id"], r["rep"]) for r in map(json.loads, open(out["results"], encoding="utf-8"))}
    lock = threading.Lock()
    sem = asyncio.Semaphore(args.concurrency)
    reps = 1 if args.dry_run else args.reps
    todo = [(c, k) for c in cases for k in range(reps) if (c["id"], k) not in done]
    await asyncio.gather(*(run_one(c, k, cfg, args, grader, out, lock, sem) for c, k in todo))
    if not args.dry_run:
        summarize(out["results"], cfg.get("primary_metric", "held"))


def parse_args(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--cases", required=True, help="cases.jsonl following the fork-replay contract")
    ap.add_argument("--flow", required=True, help="flow directory; results go to <flow>/<variant>/")
    ap.add_argument("--config", required=True,
                    help="configuration under test: a harness tree like agent-harness/en or a ready CLAUDE_CONFIG_DIR")
    ap.add_argument("--grader", required=True, help="python file defining grade(case, trajectory, cfg)")
    ap.add_argument("--eval-config", required=True, help="eval-specific JSON merged over the runner defaults")
    ap.add_argument("--variant", default="baseline", help="baseline or v<N>")
    ap.add_argument("--model", default="claude-opus-5-5")
    ap.add_argument("--reps", type=int, default=1)
    ap.add_argument("--concurrency", type=int, default=3)
    ap.add_argument("--timeout-s", type=float, default=900.0, help="hard wall-clock ceiling per attempt")
    ap.add_argument("--only", help="comma-separated case ids")
    ap.add_argument("--dry-run", action="store_true",
                    help="prepare worktree, config dir and session copy for each case, print the plan, clean up; no model call")
    ap.add_argument("--keep", action="store_true", help="keep each attempt's temp directory")
    ap.add_argument("--unrestorable-cwd", choices=("empty", "origin"), default="empty",
                    help="where a case without a restorable repository runs: an empty temp dir, or its original directory as it is today")
    ap.add_argument("--playbook",
                    help="orchestrator playbook under test: replaces the playbook injected into every session copy and the config's copy")
    ap.add_argument("--raw-bodies", help="directory for the raw API request bodies of each attempt, to check the prefix the model saw")
    ap.add_argument("--approve-harness", action="store_true",
                    help="record the current harness fingerprint as approved (the user's call, not the agent's)")
    args = ap.parse_args(argv)
    if args.variant != "baseline" and not (args.variant.startswith("v") and args.variant[1:].isdigit()):
        ap.error("--variant must be baseline or v<N>")
    return args


if __name__ == "__main__":
    asyncio.run(main_async(parse_args()))
