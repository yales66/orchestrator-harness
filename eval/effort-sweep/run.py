"""Effort sweep runner: the same brief, dispatched to a subagent at a chosen model and effort.

Each (case, rep) gets a fresh isolated clone of the case's repository holding
only the commit the brief was written against and its history (see common.py),
checked for leftovers of later work before the model is called, and a fresh
CLAUDE_CONFIG_DIR holding the
zh/ harness as installed (CLAUDE.md, playbook, hooks, skills, agents) plus one
agent definition, `effort-sweep-<effort>` for Opus or `effort-sweep-<model>-<effort>`
otherwise, whose frontmatter pins the model and the effort. Each (model, effort)
arm writes to its own directory under $DATA; the dispatching main thread runs on
Opus for every arm. `claude -p` starts a main thread that makes exactly one Agent call
to that agent; a PreToolUse hook swaps the placeholder prompt for the case's
brief, so the subagent receives the brief byte for byte. The subagent's own
transcript supplies the report, usage, model and tool calls; the main thread's
usage is kept apart as dispatch overhead.

  python3 eval/effort-sweep/run.py run --data "$DATA" --effort high      # -> $DATA/baseline/
  python3 eval/effort-sweep/run.py run --data "$DATA" --effort medium    # -> $DATA/v1/
  python3 eval/effort-sweep/run.py run --data "$DATA" --model haiku --effort max   # -> $DATA/haiku-max/
  python3 eval/effort-sweep/run.py summarize --data "$DATA"
  python3 eval/effort-sweep/run.py summarize --data "$DATA" --ref baseline --arms haiku-high,haiku-max
  python3 eval/effort-sweep/run.py run --data "$DATA" --effort high --dry-run   # no model call
  python3 eval/effort-sweep/run.py reprice --data "$DATA" --arms baseline,v1   # cost_usd from raw transcripts

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

MODEL = "claude-opus-5-5"  # the dispatching main thread, the same for every arm
MODEL_IDS = {"opus": "claude-opus-5-5", "haiku": "claude-haiku-5-5"}
EFFORTS = ("low", "medium", "high", "xhigh", "max")
BANDS = ("hard", "mid", "easy")
HARNESS = REPO_ROOT / "zh"
# The first two arms keep the directory names their data was collected under.
VARIANT_DIR = {"high": "baseline", "medium": "v1"}
PLACEHOLDER = "BRIEF"
AGENT_TOOLS = "Agent,Bash,Read,Edit,Write,Glob,Grep,NotebookEdit,TodoWrite,WebFetch,WebSearch"
METRICS = [
    {"id": "pass", "label": "通过", "kind": "binary"},
    {"id": "checks", "label": "检查点比例", "kind": "continuous"},
]
# List prices in US dollars per million tokens, from https://platform.claude.com/docs/en/about-claude/pricing
# (retrieved 2026-10-08). Each tuple is (input, 5-minute cache write, 1-hour cache write, cache read, output).
# Haiku bills a whole request at the higher row once its prompt (input plus cache reads plus cache writes)
# exceeds HAIKU_LONG_PROMPT tokens.
PRICES = {
    "claude-opus-5-5": (4.0, 5.0, 8.0, 0.20, 20.0),
    "claude-haiku-5-5": (0.10, 0.125, 0.20, 0.01, 0.50),
}
HAIKU_LONG = (0.50, 0.625, 1.00, 0.05, 2.50)
HAIKU_LONG_PROMPT = 100_000
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

def variant_dir(model: str, effort: str) -> str:
    """Directory name of the (model, effort) arm under the data directory."""
    if model == "opus" and effort in VARIANT_DIR:
        return VARIANT_DIR[effort]
    return f"{model}-{effort}"


def agent_name(effort: str, model: str = "opus") -> str:
    return f"effort-sweep-{effort}" if model == "opus" else f"effort-sweep-{model}-{effort}"


def agent_definition(effort: str, model: str = "opus") -> str:
    return (f"---\nname: {agent_name(effort, model)}\n"
            f"description: Worker for the effort sweep eval; runs one brief at effort {effort}.\n"
            f"model: {MODEL_IDS[model]}\neffort: {effort}\n---\n\n{AGENT_BODY}\n")


def build_config(cfg: Path, effort: str, model: str = "opus") -> None:
    """Install zh/ the way README's install steps do, plus the sweep agent and the brief-injection hook."""
    cfg.mkdir(parents=True)
    shutil.copy(HARNESS / "CLAUDE.md", cfg / "CLAUDE.md")
    shutil.copy(HARNESS / "orchestrator-playbook.md", cfg / "orchestrator-playbook.md")
    shutil.copytree(HARNESS / "hooks", cfg / "hooks", ignore=shutil.ignore_patterns("tests"))
    shutil.copytree(HARNESS / "skills", cfg / "skills")
    shutil.copytree(HARNESS / "agents", cfg / "agents")
    (cfg / "agents" / f"{agent_name(effort, model)}.md").write_text(agent_definition(effort, model), encoding="utf-8")
    (cfg / "hooks" / "effort_sweep_inject.py").write_text(INJECT_HOOK, encoding="utf-8")
    hooks = json.loads((HARNESS / "settings.example.json").read_text(encoding="utf-8"))["hooks"]
    hooks = json.loads(json.dumps(hooks).replace("$HOME/.claude", str(cfg)))
    hooks.setdefault("PreToolUse", []).insert(0, {
        "matcher": "Agent|Task",
        "hooks": [{"type": "command", "command": f"python3 {cfg}/hooks/effort_sweep_inject.py", "timeout": 10}],
    })
    (cfg / "settings.json").write_text(json.dumps({"hooks": hooks}, indent=2), encoding="utf-8")


def main_prompt(case: dict, effort: str, inline_brief: str | None, model: str = "opus") -> str:
    desc = case["id"]
    if inline_brief is None:
        return (f'Call the Agent tool exactly once, with subagent_type "{agent_name(effort, model)}", description "{desc}", '
                f'run_in_background false, and prompt "{PLACEHOLDER}". Do not call any other tool, do not read any '
                f'file and do not work on anything yourself. After the Agent tool returns, reply with exactly: DONE')
    return (f'Call the Agent tool exactly once, with subagent_type "{agent_name(effort, model)}", description "{desc}", '
            f'run_in_background false, and as prompt the text between the lines <<<BRIEF and BRIEF>>> below, copied '
            f'character for character without those two lines. Do not call any other tool, do not read any file and '
            f'do not work on anything yourself. After the Agent tool returns, reply with exactly: DONE\n'
            f'<<<BRIEF\n{inline_brief}\nBRIEF>>>')


def child_env(cfg: Path, brief_file: Path, effort: str, bodies: Path | None = None, model: str = "opus") -> dict:
    env = {
        "PATH": os.environ["PATH"], "HOME": os.environ["HOME"], "USER": os.environ.get("USER", ""),
        "LOGNAME": os.environ.get("LOGNAME", ""), "SHELL": "/bin/bash", "LANG": "en_US.UTF-8", "TERM": "dumb",
        "TMPDIR": os.environ.get("TMPDIR", "/tmp"), "CLAUDE_CONFIG_DIR": str(cfg), "DISABLE_AUTOUPDATER": "1",
        "EFFORT_SWEEP_BRIEF": str(brief_file), "EFFORT_SWEEP_AGENT": agent_name(effort, model),
    }
    for key in ("CLAUDE_CODE_OAUTH_TOKEN", "ANTHROPIC_API_KEY"):
        if os.environ.get(key):
            env[key] = os.environ[key]
    if bodies is not None:
        # Claude Code writes every request body here; the effort the subagent's
        # requests carried is read back from them.
        env["OTEL_LOG_RAW_API_BODIES"] = f"file:{bodies}"
    assert "CLAUDE_CODE_EFFORT_LEVEL" not in env
    return env


def efforts_from_bodies(bodies: Path, brief: str) -> dict:
    """The output_config.effort values of the captured requests, split by thread.

    A request belongs to the subagent when its first user message contains the
    brief's opening; every other request is the dispatching main thread's. A
    request that sends no effort runs at the model's default and is listed as such.
    """
    head = normalise_brief(brief)[:200]
    seen = {"subagent": set(), "main": set()}
    for f in sorted(Path(bodies).glob("*.request.json")):
        body = json.loads(f.read_text(encoding="utf-8"))
        body = body.get("body", body)
        msgs = body.get("messages") or []
        first = msgs[0].get("content") if msgs else ""
        text = first if isinstance(first, str) else "".join(
            b.get("text", "") for b in first or [] if isinstance(b, dict))
        who = "subagent" if head and head in normalise_brief(text) else "main"
        seen[who].add((body.get("output_config") or {}).get("effort") or "default")
    return {k: sorted(v) for k, v in seen.items()}


# ---------------------------------------------------------------- transcripts

def read_jsonl(path: Path) -> list[dict]:
    out = []
    with open(path, encoding="utf-8", errors="replace") as fh:
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


def request_costs(records: list[dict]) -> tuple[float, int]:
    """Dollar cost of the assistant requests at list prices, and how many requests had no known price.

    A message spread over several transcript lines is priced once, from its last line, as `sum_usage` counts it.
    """
    per_msg = {}
    for r in records:
        msg = r.get("message", {}) if r.get("type") == "assistant" else {}
        if msg.get("usage"):
            per_msg[msg.get("id") or id(r)] = (msg.get("model"), msg["usage"])
    total, unpriced = 0.0, 0
    for model, u in per_msg.values():
        rates = PRICES.get(model)
        if rates is None:
            unpriced += 1
            continue
        inp, cr, cw = (u.get(k) or 0 for k in ("input_tokens", "cache_read_input_tokens", "cache_creation_input_tokens"))
        if model == MODEL_IDS["haiku"] and inp + cr + cw > HAIKU_LONG_PROMPT:
            rates = HAIKU_LONG
        split = u.get("cache_creation")
        if isinstance(split, dict):
            w5, w1 = split.get("ephemeral_5m_input_tokens") or 0, split.get("ephemeral_1h_input_tokens") or 0
        else:
            w5, w1 = cw, 0
        total += (inp * rates[0] + w5 * rates[1] + w1 * rates[2] + cr * rates[3]
                  + (u.get("output_tokens") or 0) * rates[4]) / 1_000_000
    return total, unpriced


def api_failure(stream: list[dict], sub: list[dict]) -> str | None:
    """Failure class when an API error cut the attempt short, else None.

    Claude Code ends a turn it cannot complete with a `<synthetic>` assistant message, and `sum_usage`
    leaves those out of the served models, so without this check a subagent stopped by a usage limit
    would be graded as if it had finished.
    """
    limited = any(ev.get("type") == "result" and ev.get("api_error_status") == 429 for ev in stream) or any(
        ev.get("type") == "rate_limit_event" and (ev.get("rate_limit_info") or {}).get("status") == "rejected"
        for ev in stream)
    errors = [r.get("error") for r in sub if r.get("type") == "assistant" and r.get("isApiErrorMessage")]
    if limited or "rate_limit" in errors:
        return "rate_limited"
    return "api_error" if errors else None


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


PLACEHOLDERS = ("{ws}/", "{out}/")


def answer_file_key(tmpl: str) -> str:
    """File name under raw/<case>_rep<k>/answer_files/ for an answer_files template: the path after {ws}/ or {out}/,
    with / turned into __."""
    for ph in PLACEHOLDERS:
        if tmpl.startswith(ph):
            tmpl = tmpl[len(ph):]
            break
    return tmpl.lstrip("/").replace("/", "__")


def resolve_answer_file(tmpl: str, ws: Path, out_dir: Path) -> Path:
    # Same substitution as common.read_answer_files.
    return Path(tmpl.replace("{ws}", str(ws)).replace("{out}", str(out_dir)))


def save_answer_files(case: dict, ws: Path, out_dir: Path, raw: Path) -> None:
    """Copy each answer file the grader read into raw/answer_files/, since the workspace holding it is deleted."""
    for tmpl in case.get("answer_files", []):
        src = resolve_answer_file(tmpl, ws, out_dir)
        if src.is_file():
            (raw / "answer_files").mkdir(parents=True, exist_ok=True)
            shutil.copy(src, raw / "answer_files" / answer_file_key(tmpl))


def rebuild_answer_file(records: list[dict], tmpl: str) -> str | None:
    """Content of an answer file as the subagent's Write and Edit calls left it, or None when no Write made it.

    {ws} is the transcript's cwd, where the attempt ran; {out} is a directory named `out` whose full path the
    transcript does not record, so its files are matched by that suffix. Calls whose tool_result is an error
    did not change the file and are skipped.
    """
    cwd = next((r["cwd"] for r in records if r.get("cwd")), None)
    if tmpl.startswith("{ws}/"):
        rel = tmpl[len("{ws}/"):]
        if cwd:
            target = os.path.normpath(os.path.join(cwd, rel))
            matches = lambda p: os.path.normpath(os.path.join(cwd, p)) == target
        else:
            matches = lambda p: p.endswith("/" + rel)
    elif tmpl.startswith("{out}/"):
        suffix = "/out/" + tmpl[len("{out}/"):]
        matches = lambda p: p.endswith(suffix)
    else:
        matches = lambda p: os.path.normpath(p) == os.path.normpath(tmpl)

    failed = set()
    for r in records:
        if r.get("type") == "user":
            for c in r.get("message", {}).get("content", []) or []:
                if isinstance(c, dict) and c.get("type") == "tool_result" and c.get("is_error"):
                    failed.add(c.get("tool_use_id"))
    text = None
    for use in tool_uses(records):
        inp = use.get("input") or {}
        if use.get("id") in failed or not matches(str(inp.get("file_path", ""))):
            continue
        if use.get("name") == "Write":
            text = inp.get("content", "")
        elif use.get("name") == "Edit" and text is not None:
            old, new = inp.get("old_string", ""), inp.get("new_string", "")
            text = text.replace(old, new) if inp.get("replace_all") else text.replace(old, new, 1)
    return text


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


def served_model_problem(models: list[str], model: str) -> str | None:
    """Why the subagent's served models do not show the arm's model, or None when they all do."""
    expected = MODEL_IDS[model]
    if models and all(m == expected for m in models):
        return None
    return f"served {sorted(set(models))}, expected {expected}"


def original_status(repo: str) -> str:
    return hashlib.sha1(git(repo, "status", "--porcelain=v1", check=False).encode()).hexdigest()


def nested_worktrees(ws: Path) -> list[Path]:
    """The linked worktrees of the workspace's repository whose directories lie inside the workspace."""
    root = Path(ws).resolve()
    out = []
    for line in git(ws, "worktree", "list", "--porcelain", check=False).splitlines():
        if line.startswith("worktree "):
            p = Path(line[len("worktree "):]).resolve()
            if p != root and root in p.parents:
                out.append(p)
    return out


def worktree_ignores(ws: Path) -> list[str]:
    """Globs covering each linked worktree inside the workspace, which git status lists as one untracked directory."""
    root = Path(ws).resolve()
    globs = []
    for p in nested_worktrees(ws):
        rel = p.relative_to(root).as_posix()
        globs += [rel, rel + "/", rel + "/**"]
    return globs


def worktree_changed(wt: Path, base: str) -> bool:
    """Whether the worktree differs from `base`, in its working tree or in commits made on its branch."""
    if dirty_manifest(wt):
        return True
    return subprocess.run(["git", "-C", str(wt), "diff", "--quiet", base, "HEAD"], capture_output=True).returncode != 0


def grading_root(ws: Path, case: dict, before: dict[str, str]) -> Path:
    """The directory an impl attempt is graded in: the workspace, or the one linked worktree inside it that holds
    the attempt's work.

    A brief can tell the agent to make its changes in a worktree of its own. The worktree is graded when the
    workspace has no change inside the case's scope (the worktree directories themselves aside) and exactly one
    linked worktree inside the workspace differs from the base commit.
    """
    ignores = setup_ignores(case) + worktree_ignores(ws)
    scope, deny = case["scope"], case.get("scope_deny", [])
    main_changed = [p for p in changed_since(ws, before) if not path_matches(p, ignores)
                    and path_matches(p, scope) and not path_matches(p, deny)]
    if main_changed:
        return ws
    changed = [p for p in nested_worktrees(ws) if worktree_changed(p, case["base"])]
    if len(changed) != 1:
        return ws
    return ws / changed[0].relative_to(Path(ws).resolve())


def soft_reset_to_base(root: Path, base: str) -> str | None:
    """`git reset --soft <base>` in `root` when its HEAD is elsewhere; returns the HEAD it moved from, or None."""
    head = git(root, "rev-parse", "HEAD").strip()
    if head == git(root, "rev-parse", f"{base}^{{commit}}").strip():
        return None
    git(root, "reset", "--soft", base)
    return head


def grade_impl_attempt(case: dict, ws: Path, before: dict[str, str]) -> tuple[dict, str, str | None]:
    """grade_impl in the attempt's grading root, with hidden.exclude applied; returns the grade, the root
    relative to the workspace ("." for the workspace itself).

    A worktree the attempt created starts clean, so it is graded against an empty manifest; the workspace is
    graded with its linked worktree directories ignored. The grader sees only what git status lists, so when the
    root's HEAD is not the base commit it is soft-reset to the base first: committed changes become staged ones
    and are graded like uncommitted changes. The third value is the HEAD before that reset, or None.
    """
    root = grading_root(ws, case, before)
    reset_from = soft_reset_to_base(root, case["base"])
    if root == ws:
        g = grade_impl({**case, "ignore": list(case.get("ignore", [])) + worktree_ignores(ws)}, ws, before)
    else:
        g = grade_impl(case, root, {})
    apply_hidden_exclude(case, g["detail"])
    g.update(impl_grade_from_detail(g["detail"]))
    return g, root.relative_to(ws).as_posix() if root != ws else ".", reset_from


def run_attempt(case: dict, rep: int, args, vdir: Path) -> None:
    effort, model = args.effort, getattr(args, "model", "opus")
    arm = effort if model == "opus" else f"{model}-{effort}"
    tmp = Path(tempfile.mkdtemp(prefix=f"effort-sweep-{case['id']}-{arm}-", dir=WORK_ROOT))
    out_dir, cfg = tmp / "out", tmp / "config"
    out_dir.mkdir()
    try:
        ws = prepare_workspace(case, f"{arm}-r{rep}")
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
        build_config(cfg, effort, model)
        before = dirty_manifest(ws)
        orig_before = original_status(case["repo"])
        cmd = ["claude", "-p", main_prompt(case, effort, brief if args.inline_brief else None, model),
               "--model", MODEL, "--output-format", "stream-json", "--verbose",
               "--permission-mode", "acceptEdits", "--allowedTools", AGENT_TOOLS,
               "--add-dir", str(out_dir), "--max-budget-usd", str(args.max_budget_usd)]
        if args.dry_run:
            leaked = case["repo"] in brief
            print(f"[dry-run] {case['id']} rep{rep} model={MODEL_IDS[model]} effort={effort}\n  workspace {ws}\n  config {cfg}\n"
                  f"  brief {brief_file} ({len(brief)} chars; original path left in brief: {leaked})\n"
                  f"  agent file {cfg / 'agents' / (agent_name(effort, model) + '.md')}\n  command {' '.join(cmd[:2])} <main prompt> {' '.join(cmd[3:])}")
            return

        env = child_env(cfg, brief_file, effort, tmp / "bodies", model)
        t0 = time.monotonic()
        try:
            with open(tmp / "stream.jsonl", "w") as so, open(tmp / "stderr.log", "w") as se:
                proc = subprocess.run(cmd, cwd=ws, env=env, stdout=so, stderr=se, timeout=args.timeout_s, start_new_session=True)
            exit_code = proc.returncode
        except subprocess.TimeoutExpired:
            record_error(vdir, case, rep, "timeout", f"wall-clock ceiling {args.timeout_s}s")
            return
        wall = time.monotonic() - t0

        stream = read_jsonl(tmp / "stream.jsonl")
        session = next((ev["session_id"] for ev in reversed(stream) if ev.get("session_id")), None)
        main_files = list(cfg.glob(f"projects/*/{session}.jsonl")) if session else []
        sub_files = list(cfg.glob(f"projects/*/{session}/subagents/agent-*.jsonl")) if session else []
        failure = api_failure(stream, read_jsonl(sub_files[0]) if len(sub_files) == 1 else [])
        if failure:
            record_error(vdir, case, rep, failure, f"exit {exit_code}; " + next(
                (str(ev.get("result"))[:300] for ev in stream if ev.get("type") == "result"), "no result event"))
            return
        if len(sub_files) != 1:
            record_error(vdir, case, rep, "dispatch_missing" if not sub_files else "dispatch_multiple",
                         f"exit {exit_code}; {len(sub_files)} subagent transcripts; stderr tail: "
                         + (tmp / "stderr.log").read_text(errors="replace")[-1500:])
            return
        sub = read_jsonl(sub_files[0])
        meta_path = sub_files[0].with_suffix(".meta.json")
        sub_meta = json.loads(meta_path.read_text()) if meta_path.exists() else {}
        usage, models, stop = sum_usage(sub)
        main_records = read_jsonl(main_files[0]) if main_files else []
        main_usage, main_models, _ = sum_usage(main_records) if main_files else ({}, [], None)
        cost, unpriced = request_costs(sub)
        dispatch_cost, dispatch_unpriced = request_costs(main_records)

        received = first_user_text(sub)
        if normalise_brief(received) != normalise_brief(brief):
            record_error(vdir, case, rep, "dispatch_mismatch",
                         f"subagent received {len(received)} chars, brief has {len(brief)}", models[-1] if models else None, usage)
            return
        problem = served_model_problem(models, model)
        if problem:
            record_error(vdir, case, rep, "model_mismatch", problem, models[-1] if models else None, usage)
            return

        efforts = efforts_from_bodies(tmp / "bodies", brief)
        if efforts["subagent"] != [effort]:
            record_error(vdir, case, rep, "effort_mismatch",
                         f"subagent requests carried effort {efforts['subagent']}, expected {effort}",
                         models[-1], usage)
            return

        uses = tool_uses(sub)
        report = final_report(sub)
        ignores = setup_ignores(case)
        root_rel = reset_from = None
        if case["tier"] == "impl":
            g, root_rel, reset_from = grade_impl_attempt(case, ws, before)
            changed = g["detail"]["changed"]
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
        save_answer_files(case, ws, out_dir, raw)

        agent_md = (cfg / "agents" / f"{agent_name(effort, model)}.md").read_text(encoding="utf-8")
        (vdir / "traces").mkdir(exist_ok=True)
        (vdir / "traces" / f"{case['id']}_rep{rep}.json").write_text(
            json.dumps(to_trace(sub, agent_md), ensure_ascii=False, indent=1), encoding="utf-8")

        row = {
            "prompt_id": case["id"], "prompt": brief, "rep": rep,
            "tags": [TIER_LABELS[case["tier"]], Path(case["repo"]).name],
            "status": "truncated" if stop == "max_tokens" else "ok", "stop_reason": stop,
            "grade": g["grade"], "explanation": g["explanation"],
            "model": models[-1], "usage": usage, "cost_usd": round(cost, 6), "latency_s": round(span if span is not None else wall, 1),
            "tool_calls": len(uses),
            "meta": {
                "effort_requested": effort, "effort_seen": effort_evidence(sub, sub_meta),
                "effort_in_requests": efforts,
                "tier": case["tier"], "band": case.get("band"), "base": case["base"], "exit_code": exit_code, "wall_s": round(wall, 1),
                "dispatch_usage": main_usage, "dispatch_models": sorted(set(main_models)),
                "dispatch_cost_usd": round(dispatch_cost, 6), "unpriced_requests": unpriced + dispatch_unpriced,
                "leak_signals": leak_signals(uses, case),
                "original_repo_changed": original_status(case["repo"]) != orig_before,
                "grade_detail": g["detail"], "changed": changed, "report_chars": len(report),
            },
        }
        if root_rel is not None:
            row["meta"].update(grading_root=root_rel, soft_reset_from=reset_from)
        append_jsonl(vdir / "results.jsonl", row)
        print(f"{case['id']} rep{rep} {arm}: pass={g['grade']['pass']} checks={g['grade']['checks']:.2f} "
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


def ensure_change_md(vdir: Path, effort: str, model: str = "opus") -> None:
    name = variant_dir(model, effort)
    if name == "baseline" or (vdir / "change.md").exists():
        return
    if name == "v1":
        text = ("# v1\n\nSubagent effort medium instead of high, set in the agent definition's frontmatter.\n\n"
                "Everything else is identical to baseline: model, brief, workspace, installed rule files and grader.\n")
    else:
        text = (f"# {name}\n\nSubagent model {MODEL_IDS[model]} at effort {effort}, set in the agent definition's "
                f"frontmatter.\n\nEverything else is identical to baseline: dispatching main thread, brief, workspace, "
                f"installed rule files and grader.\n")
    (vdir / "change.md").write_text(text, encoding="utf-8")


def dry_run_cases(cases: list[dict]) -> list[dict]:
    """One case per tier, for a dry run; a case set may leave a tier out."""
    first = {}
    for c in cases:
        first.setdefault(c["tier"], c)
    return [first[t] for t in TIERS if t in first]


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
        cases = dry_run_cases(cases)
    vdir = data / variant_dir(args.model, args.effort)
    done = set()
    if not args.dry_run:
        vdir.mkdir(parents=True, exist_ok=True)
        ensure_change_md(vdir, args.effort, args.model)
        if (vdir / "results.jsonl").exists():
            done = {(r["prompt_id"], r["rep"]) for r in read_jsonl(vdir / "results.jsonl")}
    todo = [(c, k) for k in range(args.reps) for c in cases if (c["id"], k) not in done]
    print(f"{len(todo)} attempt(s) to run, {len(done)} already in {vdir}")
    with ThreadPoolExecutor(max_workers=args.concurrency) as pool:
        list(pool.map(lambda ck: run_attempt(ck[0], ck[1], args, vdir), todo))
    if not args.dry_run:
        summarize_variant(vdir)
    return 0


# Two-sided 0.975 quantiles of Student's t for 1..30 degrees of freedom; the standard library has no t distribution,
# and past 30 degrees of freedom the normal 1.96 understates t by at most about 4%.
T975 = (12.706, 4.303, 3.182, 2.776, 2.571, 2.447, 2.365, 2.306, 2.262, 2.228,
        2.201, 2.179, 2.160, 2.145, 2.131, 2.120, 2.110, 2.101, 2.093, 2.086,
        2.080, 2.074, 2.069, 2.064, 2.060, 2.056, 2.052, 2.048, 2.045, 2.042)


def t975(df: int) -> float:
    return T975[df - 1] if df <= len(T975) else 1.96


def total_tokens(u: dict) -> int:
    return sum((u or {}).values())


def ok_rows(vdir: Path) -> list[dict]:
    return [r for r in read_jsonl(vdir / "results.jsonl") if r.get("status") == "ok"] if (vdir / "results.jsonl").exists() else []


def row_band(r: dict):
    return r["meta"].get("band")


def groups(rows: list[dict]) -> list[tuple[str, object]]:
    """(label, row predicate) for each tier, all, then each band some row carries."""
    out = [(tier, (lambda r, t=tier: t == "all" or r["meta"]["tier"] == t)) for tier in (*TIERS, "all")]
    present = {row_band(r) for r in rows}
    return out + [(f"band {b}", (lambda r, b=b: row_band(r) == b)) for b in BANDS if b in present]


def row_cost(r: dict):
    """The attempt's subagent cost in dollars, or None for a row priced by neither `run` nor `reprice`."""
    return r.get("cost_usd")


ANSI = re.compile(r"\x1b\[[0-9;]*m")
# pytest's closing line ("4 failed, 32 passed, 1 error in 0.25s") and vitest's Tests line ("Tests  3 failed | 33 passed (36)").
PYTEST_SUMMARY = re.compile(r"^[=\s]*(\d+ \w+(?:, \d+ \w+)*) in [\d.]+s\b")
VITEST_SUMMARY = re.compile(r"^\s*Tests\s+(\d+ \w+(?: \| \d+ \w+)*) \(\d+\)")
COUNT = re.compile(r"(\d+) (passed|failed|errors?)\b")


def summary_parts(out: str) -> dict | None:
    """{"passed", "failed", "errors"} from the last pytest or vitest summary line in `out`, or None without one."""
    found = None
    for line in ANSI.sub("", out or "").splitlines():
        m = PYTEST_SUMMARY.match(line) or VITEST_SUMMARY.match(line)
        if m:
            found = m[1]
    if found is None:
        return None
    parts = {"passed": 0, "failed": 0, "errors": 0}
    for n, kind in COUNT.findall(found):
        parts["errors" if kind.startswith("error") else kind] += int(n)
    return parts


def summary_counts(out: str) -> tuple[int, int] | None:
    """(passed, passed + failed + errors) from the last pytest or vitest summary line in `out`; skipped is left out."""
    parts = summary_parts(out)
    if parts is None:
        return None
    total = parts["passed"] + parts["failed"] + parts["errors"]
    return (parts["passed"], total) if total else None


PYTEST_FAILED = re.compile(r"^(?:FAILED|ERROR) (\S.*?)(?: - .*)?$")
VITEST_FAILED = re.compile(r"^\s*(?:FAIL|×|✗)\s+(.*\S)\s*$")
VITEST_PROJECT = re.compile(r"^\|[^|]+\|\s+")
VITEST_DURATION = re.compile(r"\s+\d+(?:\.\d+)?m?s$")
VITEST_ERRORS = re.compile(r"^\s*Errors\s+\d+ errors?\b")


def failed_tests(out: str) -> list[str] | None:
    """Ids of the failed tests a hidden command's output lists, in order and without repeats.

    pytest ids come from the short test summary's FAILED and ERROR lines, relative to pytest's rootdir; vitest ids
    are the `file > suite > test` lines marked FAIL, × or ✗, without the |project| prefix or trailing duration.
    None when the output does not account for every failure its summary line counts: the tail kept by the grader
    was cut before some of them, there is no summary line, or vitest reports errors raised outside any test.
    """
    text = ANSI.sub("", out or "")
    parts = summary_parts(text)
    if parts is None:
        return None
    ids = []
    for line in text.splitlines():
        if VITEST_ERRORS.match(line):
            return None
        m = PYTEST_FAILED.match(line)
        if m:
            tid = m[1]
        else:
            m = VITEST_FAILED.match(line)
            if not m or " > " not in m[1]:
                continue
            tid = VITEST_DURATION.sub("", VITEST_PROJECT.sub("", m[1]))
        if tid not in ids:
            ids.append(tid)
    return None if len(ids) < parts["failed"] + parts["errors"] else ids


def excluded_by(tid: str, exclude: list[str]) -> bool:
    """pytest ids match an exclude entry in full; vitest ids (` > `-joined) match by prefix, since entries may be cut."""
    return any(tid.startswith(e) if " > " in e else tid == e for e in exclude)


HIDDEN_RESCORE_KEYS = ("ok_raw", "indeterminate", "excluded", "counts_after")


def apply_hidden_exclude(case: dict, detail: dict) -> None:
    """Rescore grade_detail's hidden runs in place: failures of the landed tests listed in hidden.exclude do not count.

    A run cut off while collecting (0 passed and an error) cannot say how the landed tests fare: ok becomes None and
    the run is marked indeterminate. A run whose output does not list every failure is marked indeterminate with
    its ok kept. Otherwise the excluded failures are dropped, recorded in `excluded`, and leave the test count in
    `counts_after`; when they were all the failures, ok becomes True. Runs that passed or timed out are left alone.
    The ok the command itself gave is kept in `ok_raw`, so rescoring again follows the current exclude list.
    """
    exclude = list((case.get("hidden") or {}).get("exclude") or [])
    runs = (detail or {}).get("hidden") or []
    for h in runs:
        raw_ok = h.get("ok_raw", h.get("ok"))
        for k in HIDDEN_RESCORE_KEYS:
            h.pop(k, None)
        h["ok"] = raw_ok
        if raw_ok or h.get("code") is None:
            continue
        parts = summary_parts(h.get("out", ""))
        if parts is not None and parts["passed"] == 0 and parts["errors"]:
            h.update(ok_raw=raw_ok, ok=None, indeterminate=True)
            continue
        ids = failed_tests(h.get("out", ""))
        if ids is None:
            h["indeterminate"] = True
            continue
        dropped = [t for t in ids if excluded_by(t, exclude)]
        if not dropped:
            continue
        passed, total = summary_counts(h.get("out", ""))
        h.update(ok_raw=raw_ok, excluded=dropped, counts_after=[passed, total - len(dropped)])
        if len(dropped) == len(ids):
            h["ok"] = True
    if runs:
        oks = [h["ok"] for h in runs]
        detail["hidden_pass"] = False if False in oks else (None if None in oks else True)


def hidden_tests(detail: dict) -> tuple[int, int] | None:
    """(passed, total) summed over the hidden commands whose output carries a test summary; None when none does.

    A command that timed out (code None) counts as having no summary, whatever partial output it left; an
    indeterminate run is left out, and a run with excluded failures counts by its `counts_after`.
    """
    counts = []
    for h in (detail or {}).get("hidden") or []:
        if h.get("code") is None or h.get("indeterminate"):
            continue
        c = tuple(h["counts_after"]) if h.get("counts_after") else summary_counts(h.get("out", ""))
        if c is not None and c[1]:
            counts.append(c)
    if not counts:
        return None
    return sum(p for p, _ in counts), sum(t for _, t in counts)


def impl_grade_from_detail(detail: dict) -> dict:
    """{"grade", "explanation"} of an impl attempt from its grade_detail, on grade_impl's terms.

    The checks are changed, scope, each selfcheck and each hidden run; `checks` is the share that are ok, leaving
    out those whose ok is None. `pass` needs a change inside scope, none outside it, and every selfcheck ok.
    """
    changed, outside = detail.get("changed") or [], detail.get("out_of_scope") or []
    in_scope = [p for p in changed if p not in set(outside)]
    checks = [("changed", bool(in_scope), f"{len(in_scope)} file(s) changed inside scope"),
              ("scope", not outside, "outside scope: " + ", ".join(outside) if outside else "ok")]
    runs = detail.get("selfcheck") or []
    for i, r in enumerate(runs):
        if r.get("code") is None and str(r.get("out", "")).startswith("no changed file matches"):
            note = r["out"]
        else:
            note = f"exit {r.get('code')}{' (timeout)' if r.get('code') is None else ''}"
        checks.append((f"selfcheck{i + 1}", r.get("ok"), note))
    for i, h in enumerate(detail.get("hidden") or []):
        note = f"exit {h.get('code')}"
        if h.get("excluded"):
            note += f", {len(h['excluded'])} excluded failure(s)"
        if h.get("indeterminate"):
            note += ", indeterminate"
        checks.append((f"hidden{i + 1}", h.get("ok"), note))
    counted = [ok for _, ok, _ in checks if ok is not None]
    passed = bool(in_scope) and not outside and all(r.get("ok") for r in runs)
    mark = lambda ok: "n/a" if ok is None else ("ok" if ok else "FAIL")
    return {"grade": {"pass": int(passed), "checks": sum(bool(ok) for ok in counted) / len(counted)},
            "explanation": {"pass": "; ".join(f"{cid}={mark(ok)} ({note})" for cid, ok, note in checks)}}


def hidden_ratio(r: dict) -> float | None:
    counts = hidden_tests(r["meta"].get("grade_detail") or {})
    return counts[0] / counts[1] if counts else None


def summarize_variant(vdir: Path) -> dict:
    rows = ok_rows(vdir)
    errs = read_jsonl(vdir / "errors.jsonl") if (vdir / "errors.jsonl").exists() else []
    out = {}
    for tier, keep in groups(rows):
        sub = [r for r in rows if keep(r)]
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
        costs = [row_cost(r) for r in sub if row_cost(r) is not None]
        cost_text = ""
        if costs:
            out[tier].update(cost=sum(costs), cost_med=statistics.median(costs))
            cost_text = f", cost ${sum(costs):.2f} (median ${statistics.median(costs):.3f}/attempt)"
        ratios = [x for x in map(hidden_ratio, sub) if x is not None]
        if ratios:
            out[tier].update(hidden=statistics.mean(ratios), hidden_n=len(ratios))
            cost_text += f", hidden tests {statistics.mean(ratios):.2f} (n={len(ratios)})"
        s = out[tier]
        print(f"{vdir.name:<8} {tier:<9} n={s['n']:<3} pass {s['pass']:.0%} [{lo:.0%}, {hi:.0%}]  checks {s['checks']:.2f}  "
              f"tokens median {s['tok_med']:,.0f} (range {s['tok_min']:,}-{s['tok_max']:,}), output median {s['out_med']:,.0f}, "
              f"latency median {s['lat_med']:.0f}s{cost_text}")
    print(f"{vdir.name:<8} errors {len(errs)} (see errors.jsonl)")
    return out


def print_paired(ref: str, arm: str, ref_rows: list[dict], arm_rows: list[dict]) -> None:
    """Per-case mean checks of ref minus arm, with a t interval, per tier, overall and per band."""
    default = (ref, arm) == (VARIANT_DIR["high"], VARIANT_DIR["medium"])
    print(f"\npaired by case (mean over reps), {'high minus medium' if default else f'{ref} minus {arm}'}:")
    tok_label = "medium tokens / high tokens" if default else f"{arm} tokens / {ref} tokens"
    ids = {r["prompt_id"] for r in ref_rows} & {r["prompt_id"] for r in arm_rows}
    for label, keep in groups(ref_rows + arm_rows):
        diffs, tok_ratio, cost_ref, cost_arm, hidden_diffs = [], [], 0.0, 0.0, []
        for cid in sorted(ids):
            h = [r for r in ref_rows if r["prompt_id"] == cid and keep(r)]
            m = [r for r in arm_rows if r["prompt_id"] == cid and keep(r)]
            if h and m:
                diffs.append(statistics.mean(r["grade"]["checks"] for r in h) - statistics.mean(r["grade"]["checks"] for r in m))
                th = statistics.mean(total_tokens(r["usage"]) for r in h)
                tm = statistics.mean(total_tokens(r["usage"]) for r in m)
                if th:
                    tok_ratio.append(tm / th)
                ch = [row_cost(r) for r in h if row_cost(r) is not None]
                cm = [row_cost(r) for r in m if row_cost(r) is not None]
                if ch and cm:
                    cost_ref += statistics.mean(ch)
                    cost_arm += statistics.mean(cm)
                hh = [x for x in map(hidden_ratio, h) if x is not None]
                hm = [x for x in map(hidden_ratio, m) if x is not None]
                if hh and hm:
                    hidden_diffs.append(statistics.mean(hh) - statistics.mean(hm))
        if len(diffs) >= 2:
            mean = statistics.mean(diffs)
            half = t975(len(diffs) - 1) * statistics.stdev(diffs) / len(diffs) ** 0.5
            print(f"  {label:<9} cases={len(diffs):<3} checks diff {mean:+.3f} (95% CI {mean - half:+.3f} to {mean + half:+.3f}); "
                  f"{tok_label}, median {statistics.median(tok_ratio):.2f}"
                  + (f"; {arm} cost / {ref} cost {cost_arm / cost_ref:.2f}" if cost_ref else ""))
            if len(hidden_diffs) >= 2:
                mean = statistics.mean(hidden_diffs)
                half = t975(len(hidden_diffs) - 1) * statistics.stdev(hidden_diffs) / len(hidden_diffs) ** 0.5
                print(f"  {label:<9} hidden tests diff {mean:+.3f} (95% CI {mean - half:+.3f} to {mean + half:+.3f}), "
                      f"cases={len(hidden_diffs)}")


def cmd_summarize(args) -> int:
    data = args.data
    ref = getattr(args, "ref", VARIANT_DIR["high"])
    arms = [a for a in getattr(args, "arms", VARIANT_DIR["medium"]).split(",") if a and a != ref]
    per = {}
    for name in (ref, *arms):
        vdir = data / name
        if (vdir / "results.jsonl").exists():
            summarize_variant(vdir)
            per[name] = ok_rows(vdir)
    if ref not in per:
        return 0
    for arm in arms:
        if arm in per:
            print_paired(ref, arm, per[ref], per[arm])
    return 0


def cmd_reprice(args) -> int:
    """Recompute each row's cost_usd from its raw subagent transcript, rewriting results.jsonl in place."""
    for name in [a for a in args.arms.split(",") if a]:
        path = args.data / name / "results.jsonl"
        if not path.exists():
            print(f"{name}: no results.jsonl")
            continue
        rows, missing, unpriced = read_jsonl(path), 0, 0
        for r in rows:
            raw = args.data / name / "raw" / f"{r['prompt_id']}_rep{r['rep']}" / "subagent.jsonl"
            if raw.exists():
                cost, n = request_costs(read_jsonl(raw))
                r["cost_usd"], unpriced = round(cost, 6), unpriced + n
            else:
                r["cost_usd"], missing = None, missing + 1
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
        os.replace(tmp, path)
        total = sum(r["cost_usd"] for r in rows if r["cost_usd"] is not None)
        print(f"{name}: repriced {len(rows) - missing} row(s), total ${total:.2f}; {missing} without raw transcript "
              f"(cost_usd null); {unpriced} unpriced request(s)")
    return 0


def regrade_row(case: dict, raw: Path, row: dict, sources: dict) -> dict:
    """grade_text of an existing text-tier row against `case`, from the report and answer files kept in `raw`.

    Each answer file comes from raw/answer_files/ when saved there, else from the transcript's Write and Edit
    calls; `sources` counts saved / rebuilt / missing. The files are laid out in a scratch ws and out dir so
    that read_answer_files joins them to the report exactly as run_attempt did. readonly is judged on the
    workspace's change list in meta.changed; rows written before that field existed keep only
    grade_detail.stray_writes (the changes outside allowed_outputs), so those are judged on that.
    """
    records = read_jsonl(raw / "subagent.jsonl")
    with tempfile.TemporaryDirectory(prefix="effort-sweep-regrade-") as td:
        ws, out_dir = Path(td) / "ws", Path(td) / "out"
        ws.mkdir()
        out_dir.mkdir()
        for tmpl in case.get("answer_files", []):
            if not tmpl.startswith(PLACEHOLDERS):  # only {ws}/{out} paths can be laid out in the scratch dirs
                sources["missing"] += 1
                continue
            saved = raw / "answer_files" / answer_file_key(tmpl)
            dest = resolve_answer_file(tmpl, ws, out_dir)
            dest.parent.mkdir(parents=True, exist_ok=True)
            if saved.is_file():
                shutil.copy(saved, dest)
                sources["saved"] += 1
            elif (text := rebuild_answer_file(records, tmpl)) is not None:
                dest.write_bytes(text.encode("utf-8", errors="surrogatepass"))
                sources["rebuilt"] += 1
            else:
                sources["missing"] += 1
        answer = final_report(records) + read_answer_files(case, ws, out_dir)
    meta = row.get("meta") or {}
    changed = meta["changed"] if "changed" in meta else (meta.get("grade_detail") or {}).get("stray_writes") or []
    return grade_text(case, answer, changed)


def regrade_impl_row(case: dict, r: dict, counts: dict, arm: str, dry_run: bool, stamp: str) -> None:
    """Rescore an ok impl row offline: apply the case's hidden.exclude to its recorded hidden runs and recompute
    the grade from grade_detail; no command is run again. `counts` tallies rows, pass and checks changes, and
    indeterminate hidden runs. A dry run prints the change and leaves the row as it was.
    """
    meta = r["meta"]
    detail = json.loads(json.dumps(meta["grade_detail"]))
    apply_hidden_exclude(case, detail)
    g = impl_grade_from_detail(detail)
    old, new = r["grade"], g["grade"]
    counts["rows"] += 1
    counts["pass"] += int(old["pass"]) != int(new["pass"])
    counts["checks"] += old["checks"] != new["checks"]
    counts["indeterminate"] += sum(bool(h.get("indeterminate")) for h in detail["hidden"])
    if dry_run or old != new:
        print(f"  {arm} {r['prompt_id']} rep{r['rep']}: pass {int(old['pass'])}->{int(new['pass'])} "
              f"checks {old['checks']:.2f}->{new['checks']:.2f}")
    if dry_run:
        return
    meta.setdefault("grade_original", old)
    r["grade"], r["explanation"] = new, g["explanation"]
    meta["grade_detail"] = detail
    meta["regraded_at"] = stamp


def cmd_regrade(args) -> int:
    """Re-grade each ok row against the current cases.jsonl, rewriting results.jsonl in place.

    Text-tier rows are graded again from raw/; impl rows that recorded hidden runs are rescored from grade_detail.
    """
    from datetime import datetime, timezone

    cases = {c["id"]: c for c in load_cases(args.data / "cases.jsonl", include_excluded=True)}
    for name in [a for a in args.arms.split(",") if a]:
        path = args.data / name / "results.jsonl"
        if not path.exists():
            print(f"{name}: no results.jsonl")
            continue
        rows = read_jsonl(path)
        sources = {"saved": 0, "rebuilt": 0, "missing": 0}
        done = pass_changed = checks_changed = no_case = no_raw = 0
        impl = {"rows": 0, "pass": 0, "checks": 0, "indeterminate": 0}
        stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
        for r in rows:
            meta = r.get("meta") or {}
            if r.get("status") != "ok":
                continue
            if meta.get("tier") == "impl":
                if r["prompt_id"] in cases and (meta.get("grade_detail") or {}).get("hidden"):
                    regrade_impl_row(cases[r["prompt_id"]], r, impl, name, args.dry_run, stamp)
                continue
            raw = args.data / name / "raw" / f"{r['prompt_id']}_rep{r['rep']}"
            if r["prompt_id"] not in cases:
                no_case += 1
                continue
            if not (raw / "subagent.jsonl").exists():
                no_raw += 1
                continue
            g = regrade_row(cases[r["prompt_id"]], raw, r, sources)
            old, new = r["grade"], g["grade"]
            done += 1
            pass_changed += int(old["pass"]) != int(new["pass"])
            checks_changed += old["checks"] != new["checks"]
            if args.dry_run or old != new:
                print(f"  {name} {r['prompt_id']} rep{r['rep']}: pass {int(old['pass'])}->{int(new['pass'])} "
                      f"checks {old['checks']:.2f}->{new['checks']:.2f}")
            if args.dry_run:
                continue
            meta.setdefault("grade_original", old)
            r["grade"], r["explanation"] = new, g["explanation"]
            meta["grade_detail"] = g["detail"]
            meta["regraded_at"] = stamp
            r["meta"] = meta
        if not args.dry_run:
            tmp = path.with_name(path.name + ".tmp")
            tmp.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
            os.replace(tmp, path)
        print(f"{name}: regraded {done} row(s), pass changed on {pass_changed}, checks changed on {checks_changed}; "
              f"answer files saved {sources['saved']}, rebuilt {sources['rebuilt']}, missing {sources['missing']}; "
              f"skipped {no_case} with no case, {no_raw} with no raw transcript; "
              f"impl rows rescored {impl['rows']} (pass changed on {impl['pass']}, checks changed on {impl['checks']}, "
              f"indeterminate hidden runs {impl['indeterminate']})"
              + ("; dry run, nothing written" if args.dry_run else ""))
    return 0


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--data", required=True, type=Path)
    r.add_argument("--model", choices=sorted(MODEL_IDS), default="opus", help="the subagent's model")
    r.add_argument("--effort", required=True, choices=EFFORTS)
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
    s.add_argument("--ref", default=VARIANT_DIR["high"], help="arm directory every other arm is paired against")
    s.add_argument("--arms", default=VARIANT_DIR["medium"], help="comma-separated arm directories to compare with --ref")
    p = sub.add_parser("reprice", help="recompute cost_usd of existing rows from their raw subagent transcripts")
    p.add_argument("--data", required=True, type=Path)
    p.add_argument("--arms", default=f"{VARIANT_DIR['high']},{VARIANT_DIR['medium']}",
                   help="comma-separated arm directories to reprice")
    g = sub.add_parser("regrade", help="re-grade ok text-tier rows against the current cases.jsonl from raw/")
    g.add_argument("--data", required=True, type=Path)
    g.add_argument("--arms", default=f"{VARIANT_DIR['high']},{VARIANT_DIR['medium']}",
                   help="comma-separated arm directories to regrade")
    g.add_argument("--dry-run", action="store_true", help="print each row's old->new pass and checks; write nothing")
    return ap


def main() -> int:
    args = build_parser().parse_args()
    return {"run": cmd_run, "summarize": cmd_summarize, "reprice": cmd_reprice,
            "regrade": cmd_regrade}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
