"""Extract first-API-call input token usage from Claude Code logs.

Two log shapes are handled:
  stream-json from `claude -p --output-format stream-json --verbose`, where
  subagent messages carry a non-null parent_tool_use_id and main-thread
  messages carry null;
  session transcript jsonl, where each file holds one thread (the main
  session file, or one subagents/agent-*.jsonl file).

Usage:
  python3 parse_usage.py stream <stream.jsonl>
  python3 parse_usage.py transcript <transcript.jsonl>
  python3 parse_usage.py run <run_dir> <variant> <max_input>        (used by run.sh)
  python3 parse_usage.py check <work_dir> <model>                   (used by run.sh)
  python3 parse_usage.py aggregate <work_dir> <results.json> <results.md> \
      <claude_version> <model> <repeats> [copy]                     (used by run.sh)

check prints, one per line, the run directories (H-1, N-2, ...) under
<work_dir> whose results are not comparable and should be rerun, with the
reasons on stderr. <model> is the requested model id, the same string run.sh
passes to --model. A run is not comparable when its subagent ran on another
model, or when the deferred tools announced to its main thread or to its
subagent differ from the reference set: the set most runs with the requested
subagent model received, the smaller set on a tie.
"""
import json
import os
import re
import sys

FIELDS = ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens")


def _records(lines):
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except ValueError:
            continue
        if isinstance(obj, dict):
            yield obj


def _call(obj):
    """Return a usage summary for an assistant record, or None if it is not a real API call."""
    if obj.get("type") != "assistant":
        return None
    msg = obj.get("message")
    if not isinstance(msg, dict) or not isinstance(msg.get("usage"), dict):
        return None
    if msg.get("model") == "<synthetic>":
        return None
    u = msg["usage"]
    out = {k: int(u.get(k) or 0) for k in FIELDS}
    out["total"] = sum(out[k] for k in FIELDS)
    out["model"] = msg.get("model")
    out["message_id"] = msg.get("id")
    return out


def first_calls(lines):
    """First main-thread call and first subagent call in a stream-json log."""
    main = sub = None
    for obj in _records(lines):
        call = _call(obj)
        if call is None:
            continue
        parent = obj.get("parent_tool_use_id")
        if parent is None and main is None:
            main = call
        elif parent is not None and sub is None:
            call["parent_tool_use_id"] = parent
            sub = call
        if main is not None and sub is not None:
            break
    return {"main": main, "subagent": sub}


def first_transcript_call(lines):
    """First real assistant call in a single-thread transcript jsonl."""
    for obj in _records(lines):
        call = _call(obj)
        if call is not None:
            return call
    return None


def hook_events(lines):
    """Distinct hook event names seen in a stream-json log, in first-seen order."""
    seen = []
    for obj in _records(lines):
        if obj.get("type") != "system" or not str(obj.get("subtype") or "").startswith("hook"):
            continue
        name = obj.get("hook_event") or obj.get("hook_event_name") \
            or str(obj.get("hook_name") or "").split(":")[0]
        if name and name not in seen:
            seen.append(name)
    return seen


def group_summary(runs):
    """Per-group totals across valid repeats and whether they matched exactly.

    Runs without a "valid" flag count as valid; consistent is None when no run is valid.
    """
    runs = [r for r in runs if r.get("valid", True)]
    main = [r["stream"]["main"]["total"] for r in runs]
    sub = [(r["stream"].get("subagent") or {}).get("total") for r in runs]
    return {
        "main_totals": main,
        "subagent_totals": sub,
        "consistent": (len(set(main)) == 1 and len(set(sub)) == 1) if runs else None,
    }


# ---- run.sh glue: per-run summary and aggregation -------------------------

PLAYBOOK_PATH = os.environ.get("SC_PLAYBOOK") or os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "..", "en", "orchestrator-playbook.md")


def last_heading(text):
    return [l.rstrip("\n") for l in text.splitlines() if l.startswith("## ")][-1]


# Only these attachments reach the model. hook_success keeps the raw hook stdout,
# which holds the whole playbook even when Claude Code hands the model a 2KB
# preview in hook_additional_context instead.
DELIVERED = ("hook_additional_context", "instructions")


def playbook_delivered(lines, heading):
    """True when the playbook's final heading is in context the model receives."""
    for obj in _records(lines):
        att = obj.get("attachment")
        if isinstance(att, dict) and att.get("type") in DELIVERED:
            if heading in json.dumps(att, ensure_ascii=False):
                return True
    return False


DEFERRED = "deferred_tools_delta"


def deferred_tool_names(lines):
    """Sorted deferred tool names announced to a thread before its first API call."""
    names = set()
    for obj in _records(lines):
        if _call(obj) is not None:
            break
        att = obj.get("attachment")
        if isinstance(att, dict) and att.get("type") == DEFERRED:
            names |= set(att.get("addedNames") or []) | set(att.get("readdedNames") or [])
            names -= set(att.get("removedNames") or [])
    return sorted(names)


def _read_lines(path):
    with open(path, encoding="utf-8") as f:
        return f.readlines()


def _transcripts(config_dir):
    import glob
    import os
    proj = os.path.join(config_dir, "projects")
    mains = sorted(p for p in glob.glob(os.path.join(proj, "*", "*.jsonl")))
    subs = sorted(glob.glob(os.path.join(proj, "*", "*", "subagents", "*.jsonl")),
                  key=os.path.getmtime)
    return mains, subs


def _init(lines):
    for obj in _records(lines):
        if obj.get("type") == "system" and obj.get("subtype") == "init":
            keep = ("claude_code_version", "model", "apiKeySource", "skills",
                    "plugins", "mcp_servers", "agents")
            out = {k: obj.get(k) for k in keep if k in obj}
            out["tool_count"] = len(obj.get("tools") or [])
            return out
    return None


def _result(lines):
    for obj in _records(lines):
        if obj.get("type") == "result":
            return {k: obj.get(k) for k in ("is_error", "result", "total_cost_usd", "num_turns")}
    return None


def _thread_lines(run_dir):
    """Transcript paths and lines of the main thread and of the first subagent."""
    mains, subs = _transcripts(os.path.join(run_dir, "config"))
    main_lines = [l for p in mains for l in _read_lines(p)]
    sub_lines = _read_lines(subs[0]) if subs else []
    if not sub_lines:  # older layouts keep the subagent inline as sidechain records
        side = [l for l in main_lines if '"isSidechain":true' in l.replace(" ", "")]
        main_lines = [l for l in main_lines if l not in side]
        sub_lines = side
    return mains, subs, main_lines, sub_lines


def _deferred_tools(main_lines, sub_lines):
    return {"main": deferred_tool_names(main_lines), "subagent": deferred_tool_names(sub_lines)}


def summarize_run(run_dir, variant, max_input):
    stream = _read_lines(os.path.join(run_dir, "stream.jsonl"))
    cfg = os.path.join(run_dir, "config")
    mains, subs, main_lines, sub_lines = _thread_lines(run_dir)
    claude_md = os.path.join(cfg, "CLAUDE.md")
    heading = last_heading(open(PLAYBOOK_PATH, encoding="utf-8").read())
    out = {
        "variant": variant,
        "stream": first_calls(stream),
        "transcript": {
            "main": first_transcript_call(main_lines),
            "subagent": first_transcript_call(sub_lines),
            "main_files": [os.path.relpath(p, run_dir) for p in mains],
            "subagent_files": [os.path.relpath(p, run_dir) for p in subs],
        },
        "hook_events": hook_events(stream),
        "playbook_in_main_transcript": playbook_delivered(main_lines, heading),
        "playbook_in_subagent_transcript": playbook_delivered(sub_lines, heading),
        "deferred_tools": _deferred_tools(main_lines, sub_lines),
        "claude_md_bytes": os.path.getsize(claude_md) if os.path.exists(claude_md) else 0,
        "init": _init(stream),
        "result": _result(stream),
    }
    problems = []
    for who in ("main", "subagent"):
        call = out["stream"][who]
        if call is None:
            problems.append("no %s call in stream" % who)
        elif call["total"] > max_input:
            problems.append("%s first-request input %d exceeds %d" % (who, call["total"], max_input))
    return out, problems


# ---- run validity -----------------------------------------------------------

RUN_DIR = re.compile(r"^([HN])-(\d+)$")
DISCARDED_FILE = "discarded_attempts"  # written by run.sh, counts reruns of this run dir


def load_run(run_dir):
    """summary.json of a run, plus its discard count and deferred tool sets.

    Summaries written before deferred_tools existed get the sets from the
    transcripts still kept in the run directory.
    """
    with open(os.path.join(run_dir, "summary.json"), encoding="utf-8") as f:
        run = json.load(f)
    if "deferred_tools" not in run:
        _, _, main_lines, sub_lines = _thread_lines(run_dir)
        run["deferred_tools"] = _deferred_tools(main_lines, sub_lines)
    try:
        with open(os.path.join(run_dir, DISCARDED_FILE), encoding="utf-8") as f:
            run["discarded_attempts"] = int(f.read().strip() or 0)
    except FileNotFoundError:
        run["discarded_attempts"] = 0
    return run


def _reference(sets):
    """The set most runs share; on a tie the one with fewest names."""
    counts = {}
    for s in sets:
        counts[s] = counts.get(s, 0) + 1
    return min(counts, key=lambda s: (-counts[s], len(s), s))


def invalid_runs(runs, model):
    """Runs whose numbers are not comparable, as {name: [reason, ...]} in input order.

    runs maps a run name to its summary. Rule one drops runs whose subagent did
    not run on the requested model. Rule two compares, among the remaining runs,
    the deferred tool set of the main thread and of the subagent with the
    reference set of that thread.
    """
    bad = {}
    for name, run in runs.items():
        got = ((run.get("stream") or {}).get("subagent") or {}).get("model")
        if got != model:
            bad[name] = ["subagent model %s, requested %s" % (got or "missing", model)]
    kept = [n for n in runs if n not in bad]
    for who, label in (("main", "main thread"), ("subagent", "subagent")):
        sets = {n: tuple(sorted((runs[n].get("deferred_tools") or {}).get(who) or [])) for n in kept}
        if not sets:
            continue
        ref = _reference(list(sets.values()))
        for n, got in sets.items():
            if got != ref:
                extra = ", ".join(sorted(set(got) - set(ref))) or "none"
                missing = ", ".join(sorted(set(ref) - set(got))) or "none"
                bad.setdefault(n, []).append(
                    "%s deferred tools differ from the reference set (extra: %s; missing: %s)"
                    % (label, extra, missing))
    return {n: bad[n] for n in runs if n in bad}


def _run_names(work):
    found = [m for m in (RUN_DIR.match(n) for n in os.listdir(work)) if m
             and os.path.isdir(os.path.join(work, m.group(0)))]
    return [m.group(0) for m in sorted(found, key=lambda m: (m.group(1), int(m.group(2))))]


def check_reasons(work, model):
    names = _run_names(work)
    return invalid_runs({n: load_run(os.path.join(work, n)) for n in names}, model)


def check_work(work, model):
    """Names of the run directories under work that should be rerun, in run order."""
    return list(check_reasons(work, model))


# ---- aggregation ------------------------------------------------------------

def aggregate(work, version, model, repeats, copy="en"):
    import datetime
    runs = {"%s-%d" % (v, i): load_run(os.path.join(work, "%s-%d" % (v, i)))
            for v in ("H", "N") for i in range(1, repeats + 1)}
    reasons = invalid_runs(runs, model)
    for name, run in runs.items():
        run["valid"] = name not in reasons
        run["invalid_reasons"] = reasons.get(name, [])
    groups = {}
    for v in ("H", "N"):
        group_runs = [runs["%s-%d" % (v, i)] for i in range(1, repeats + 1)]
        g = group_summary(group_runs)
        g["first_valid_run"] = next((i for i, r in enumerate(group_runs, 1) if r["valid"]), None)
        g["runs"] = group_runs
        groups[v] = g

    def first(v, who):
        i = groups[v]["first_valid_run"]
        return None if i is None else groups[v]["runs"][i - 1]["stream"][who]["total"]

    def diff(a, b, who):
        x, y = first(a, who), first(b, who)
        return None if x is None or y is None else x - y

    deltas = {
        "%s_minus_%s" % (a, b): {"main": diff(a, b, "main"), "subagent": diff(a, b, "subagent")}
        for a, b in (("N", "H"),)
    }
    return {
        "copy": copy,
        "claude_code_version": version,
        "model": model,
        "date_utc": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d"),
        "repeats": repeats,
        "groups": groups,
        "deltas_first_valid_run": deltas,
    }


def _cell(call, key):
    return "" if call is None else str(call.get(key, ""))


def _signed(n):
    return "n/a" if n is None else "%+d" % n


def _yes_no(flag):
    return "n/a" if flag is None else ("yes" if flag else "no")


def render_md(res):
    L = []
    L.append("# Static context measurement\n")
    L.append("This file is generated by `run.sh` from `results.json`. It reports the first-request input "
             "of the main thread and of one general-purpose subagent under two configurations that differ "
             "only in where the orchestrator playbook lives. First-request input is the input tokens of a "
             "thread's first API request, which hold only fixed content: Claude Code's own system prompt and "
             "tool definitions, CLAUDE.md, the skill list, any text injected by hooks, and for a subagent the "
             "brief it was given; nothing the thread reads or produces later is included.\n")
    L.append("## Configurations\n")
    L.append("| Group | Installed into a fresh CLAUDE_CONFIG_DIR | Playbook location |")
    L.append("|---|---|---|")
    c = res.get("copy", "en")
    L.append("| H | {c}/CLAUDE.md, {c}/hooks, {c}/skills, {c}/agents, orchestrator-playbook.md, and the hooks block of {c}/settings.example.json | injected into the main thread by the SessionStart hook |".format(c=c))
    L.append("| N | the same as H, but without the SessionStart hook registration | appended to the end of CLAUDE.md |")
    L.append("")
    L.append("Each run also uses a fresh HOME and an empty working directory outside any git repository, "
             "so no user or project CLAUDE.md, skill, plugin or MCP server outside the table above is loaded. "
             "The prompt asks the main thread to call the Agent tool exactly once with a one-line brief, "
             "with the model parameter set to the alias of the requested model, and then stop.\n")
    L.append("A run counts as valid only when its subagent ran on the requested model and the deferred tools "
             "announced to its main thread and to its subagent match the reference set of that thread, which is "
             "the set most runs on the requested subagent model received, or the smaller set on a tie. `run.sh` "
             "reruns invalid runs in place for a bounded number of rounds; a run still invalid after the last "
             "round is kept in the per-run table but left out of the consistency and difference tables.\n")

    L.append("## First-request input per run\n")
    L.append("| Group | Run | Main input | Main cache write | Main cache read | Main total | "
             "Subagent input | Subagent cache write | Subagent cache read | Subagent total | Main model | Subagent model | "
             "Valid | Discarded attempts |")
    L.append("|---|---|---|---|---|---|---|---|---|---|---|---|---|---|")
    for v, g in res["groups"].items():
        for i, r in enumerate(g["runs"], 1):
            m, s = r["stream"]["main"], r["stream"]["subagent"]
            L.append("| %s | %d | %s | %s | %s | %s | %s | %s | %s | %s | %s | %s | %s | %d |" % (
                v, i, _cell(m, "input_tokens"), _cell(m, "cache_creation_input_tokens"),
                _cell(m, "cache_read_input_tokens"), _cell(m, "total"),
                _cell(s, "input_tokens"), _cell(s, "cache_creation_input_tokens"),
                _cell(s, "cache_read_input_tokens"), _cell(s, "total"),
                _cell(m, "model"), _cell(s, "model"),
                _yes_no(r.get("valid", True)), r.get("discarded_attempts", 0)))
    L.append("")
    for v, g in res["groups"].items():
        for i, r in enumerate(g["runs"], 1):
            if r.get("invalid_reasons"):
                L.append("%s run %d is invalid: %s.\n" % (v, i, "; ".join(r["invalid_reasons"])))
    L.append("## Repeat consistency (valid runs)\n")
    L.append("| Group | Main totals | Subagent totals | Identical across valid runs |")
    L.append("|---|---|---|---|")
    for v, g in res["groups"].items():
        L.append("| %s | %s | %s | %s |" % (v, ", ".join(map(str, g["main_totals"])) or "n/a",
                                          ", ".join(map(str, g["subagent_totals"])) or "n/a",
                                          _yes_no(g["consistent"])))
    L.append("")
    L.append("## Differences between groups (first valid run of each group, totals)\n")
    L.append("| Comparison | Main thread | Subagent |")
    L.append("|---|---|---|")
    for k, d in res["deltas_first_valid_run"].items():
        L.append("| %s | %s | %s |" % (k.replace("_minus_", " minus "), _signed(d["main"]), _signed(d["subagent"])))
    L.append("")
    L.append("## Load checks\n")
    L.append("| Group | Run | Hook events in stream | Full playbook reaches main thread | "
             "Full playbook reaches subagent | CLAUDE.md bytes | Stream total equals transcript total |")
    L.append("|---|---|---|---|---|---|---|")
    for v, g in res["groups"].items():
        for i, r in enumerate(g["runs"], 1):
            same = all((r["stream"][w] or {}).get("total") == (r["transcript"][w] or {}).get("total")
                       for w in ("main", "subagent"))
            L.append("| %s | %d | %s | %s | %s | %d | %s |" % (
                v, i, ", ".join(r["hook_events"]) or "none",
                "yes" if r["playbook_in_main_transcript"] else "no",
                "yes" if r["playbook_in_subagent_transcript"] else "no",
                r["claude_md_bytes"], "yes" if same else "no"))
    L.append("")
    L.append("## Environment\n")
    L.append("| Item | Value |")
    L.append("|---|---|")
    L.append("| Claude Code version | %s |" % res["claude_code_version"])
    L.append("| Requested model (main thread and subagent) | %s |" % res["model"])
    L.append("| Date (UTC) | %s |" % res["date_utc"])
    L.append("| Repeats per group | %d |" % res["repeats"])
    L.append("")
    L.append("## Rerun\n")
    L.append("Export `CLAUDE_CODE_OAUTH_TOKEN` (from `claude setup-token`) or `ANTHROPIC_API_KEY`, then run "
             "`bash eval/static-context/run.sh` from the repository root. The script reruns invalid runs for up to "
             "`SC_RETRIES` rounds (default 3), rewrites `results.json` and this file, and prints the temp "
             "directory that keeps the raw stream and transcript logs.\n")
    L.append("## Limitations\n")
    L.append("These numbers cover only first-request input as defined at the top of this file. They do not "
             "represent the cost of a whole task, because later requests add tool results and conversation "
             "history on top of it. Token counts are not billed amounts either, since cache reads are "
             "billed at a fraction of the base input price and a repeat run usually reads the prefix that the "
             "previous run wrote; for that reason the split between cache write and cache read may differ across "
             "repeats while the total stays the same. The measurement uses one model, one Claude Code version "
             "and one general-purpose subagent. Claude Code's own system prompt and tool definitions change "
             "from version to version, so the absolute numbers hold only for the version in the Environment "
             "table, and another version needs a rerun of `run.sh`. The playbook load check looks for the playbook's final heading in the "
             "attachments the model receives, the SessionStart hook context in H and the CLAUDE.md instructions "
             "in N, so a playbook that Claude Code cut to a preview counts as not delivered.\n")
    return "\n".join(L)


def _main(argv):
    cmd = argv[1] if len(argv) > 1 else ""
    if cmd in ("stream", "transcript") and len(argv) == 3:
        lines = _read_lines(argv[2])
        result = first_calls(lines) if cmd == "stream" else first_transcript_call(lines)
        json.dump(result, sys.stdout, indent=2)
        sys.stdout.write("\n")
        return 0
    if cmd == "run" and len(argv) == 5:
        out, problems = summarize_run(argv[2], argv[3], int(argv[4]))
        json.dump(out, sys.stdout, indent=2)
        sys.stdout.write("\n")
        if problems:
            sys.stderr.write("STOP %s: %s; result: %s\n" % (argv[2], "; ".join(problems), out["result"]))
            return 4
        return 0
    if cmd == "check" and len(argv) == 4:
        for name, why in check_reasons(argv[2], argv[3]).items():
            sys.stderr.write("%s: %s\n" % (name, "; ".join(why)))
            sys.stdout.write(name + "\n")
        return 0
    if cmd == "aggregate" and len(argv) in (8, 9):
        res = aggregate(argv[2], argv[5], argv[6], int(argv[7]), *argv[8:9])
        with open(argv[3], "w", encoding="utf-8") as f:
            json.dump(res, f, indent=2)
            f.write("\n")
        with open(argv[4], "w", encoding="utf-8") as f:
            f.write(render_md(res))
        return 0
    sys.stderr.write(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(_main(sys.argv))
