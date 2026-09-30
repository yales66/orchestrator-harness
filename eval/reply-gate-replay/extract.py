#!/usr/bin/env python3
"""Extract reply pairs from Claude Code main-thread transcripts and draw the labeling sample.

A pair is the assistant's final text message of a turn together with the next message
the user typed. The script writes everything that contains conversation text into the
private data directory given by --data, never into the repository:

  pairs.jsonl          one row per pair
  sample.jsonl         the labeling sample, with its stratum
  label-view/a1.md     the sample in a shuffled order, cut for blind labeling (no gate output)
  extract-meta.json    population counts, strata sizes, date and version ranges

Usage: python3 extract.py --data DIR [--projects ~/.claude/projects]
"""
import argparse
import collections
import glob
import hashlib
import json
import os
import random
import re
import sys

SEED = 20260929
Q_CAP = 150
REST_N = 100
VIEW_GOAL = 260   # characters of the earlier user message shown to the labeler
VIEW_TAIL = 500   # characters from the end of the reply
VIEW_NEXT = 160   # characters of the next user message
GATE_NAME = "reply-gate.sh"

# User records that are not typed by the user, recognised by how their text starts
# when the record carries no `origin` field (older Claude Code versions).
AUTO_PREFIXES = (
    "<task-notification>", "<local-command-stdout>", "<local-command-stderr>",
    "<local-command-caveat>", "<bash-stdout>", "<bash-stderr>", "<bash-input>",
    "<ci-monitor-event>", "<system-reminder>", "<user-memory-input>",
    "Stop hook feedback", "This session is being continued", "Caveat:",
)
INTERRUPT = "[Request interrupted by user"


def load(path):
    rows = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            try:
                d = json.loads(line)
            except ValueError:
                continue
            if isinstance(d, dict):
                rows.append(d)
    return rows


def content_text(msg):
    """Return (text, has_tool_result) for a message's content."""
    content = msg.get("content") if isinstance(msg, dict) else None
    if isinstance(content, str):
        return content, False
    if not isinstance(content, list):
        return "", False
    parts, tool = [], False
    for block in content:
        if not isinstance(block, dict):
            continue
        if block.get("type") == "tool_result":
            tool = True
        elif block.get("type") == "text":
            parts.append(block.get("text") or "")
        elif block.get("type") == "image":
            parts.append("[image]")
    return "\n".join(parts), tool


def classify_user(rec):
    """Kind of a non-tool_result user record: human, slash, interrupt, stop-feedback, auto, meta."""
    text, _ = content_text(rec.get("message"))
    stripped = text.lstrip()
    if stripped.startswith(INTERRUPT):
        return "interrupt"
    if stripped.startswith("Stop hook feedback"):
        return "stop-feedback"
    if rec.get("isMeta") or rec.get("isCompactSummary"):
        return "meta"
    origin = rec.get("origin")
    if isinstance(origin, dict) and origin.get("kind") and origin.get("kind") != "human":
        return "auto"
    if stripped.startswith(AUTO_PREFIXES):
        return "auto"
    if "<command-name>" in stripped[:200]:
        return "slash"
    return "human"


def human_text(rec):
    text, _ = content_text(rec.get("message"))
    if "<command-name>" in text[:200]:
        name = re.search(r"<command-name>(.*?)</command-name>", text, re.S)
        args = re.search(r"<command-args>(.*?)</command-args>", text, re.S)
        return ((name.group(1) if name else "") + " " + (args.group(1) if args else "")).strip()
    return text


def is_message(rec):
    return rec.get("type") in ("user", "assistant")


def gate_cutoff(files):
    """Earliest time the reply gate itself ran; later turns were already shaped by it."""
    first = None
    for f in files:
        for rec in load(f):
            if rec.get("type") == "system" and rec.get("subtype") == "stop_hook_summary":
                for h in rec.get("hookInfos") or []:
                    if GATE_NAME in str(h.get("command", "")):
                        ts = rec.get("timestamp")
                        if ts and (first is None or ts < first):
                            first = ts
    return first


def pairs_from_file(path, cutoff, stats):
    rows = [r for r in load(path) if not r.get("isSidechain")]
    if any(r.get("entrypoint") == "sdk-cli" for r in rows if r.get("type") == "user"):
        stats["sessions_noninteractive"] += 1
        return []
    msgs = [r for r in rows if is_message(r)]
    out = []
    last_human = None
    blocked_before = False
    for i, rec in enumerate(msgs):
        if rec.get("type") == "user":
            _, tool = content_text(rec.get("message"))
            if not tool and classify_user(rec) in ("human", "slash"):
                last_human = rec
                blocked_before = False
            continue
        msg = rec.get("message") or {}
        if msg.get("model") == "<synthetic>":
            continue
        content = msg.get("content")
        if not (isinstance(content, list) and content and content[-1].get("type") == "text"):
            continue
        nxt = msgs[i + 1] if i + 1 < len(msgs) else None
        if nxt is not None:
            if nxt.get("type") == "assistant":
                continue
            _, tool = content_text(nxt.get("message"))
            if tool:
                continue
            kind = classify_user(nxt)
        else:
            kind = "eof"
        # This is a stop: the model ended its output here.
        if kind == "stop-feedback":
            blocked_before = True
            stats["stops_blocked_by_other_hook"] += 1
            continue
        if kind == "interrupt":
            stats["turns_interrupted"] += 1
            continue
        ts = rec.get("timestamp") or ""
        if cutoff and ts >= cutoff:
            stats["turns_after_gate_cutoff"] += 1
            continue
        mid = msg.get("id")
        texts = []
        for prev in msgs[:i + 1]:
            if prev.get("type") == "assistant" and (prev.get("message") or {}).get("id") == mid:
                for block in (prev.get("message") or {}).get("content") or []:
                    if isinstance(block, dict) and block.get("type") == "text":
                        texts.append(block.get("text") or "")
        text = "\n\n".join(t for t in texts if t.strip())
        if not text.strip():
            stats["turns_empty_text"] += 1
            continue
        next_user, next_kind = None, kind
        for later in msgs[i + 1:]:
            if later.get("type") == "assistant":
                break
            if content_text(later.get("message"))[1]:
                continue
            if classify_user(later) in ("human", "slash"):
                next_user = human_text(later)
                break
        out.append({
            "uuid": rec.get("uuid"),
            "session_id": rec.get("sessionId"),
            "timestamp": ts,
            "version": rec.get("version"),
            "prev_user": human_text(last_human) if last_human else None,
            "assistant": text,
            "next_user": next_user,
            "next_kind": next_kind,
            "after_stop_block": blocked_before,
        })
        blocked_before = False
    return out


def ends_with_question(text):
    tail = text.rstrip().rstrip(" \t*_~>`")
    return bool(tail) and tail[-1] in "?？"


def excerpt(text, n):
    """First n characters of a message, blank lines collapsed and newlines shown as ' / '."""
    t = re.sub(r"\n{2,}", "\n\n", (text or "(none)").strip())
    t = t if len(t) <= n else t[:n] + "…"
    return t.replace("\n", " / ")


def write_views(data, sample, pairs_by_id):
    """One file with every sampled pair in a shuffled order, cut to what the labeler reads.

    The labeler sees the start of the earlier user message, the ending of the reply and
    the start of the next user message; the rule is about how the reply ends.
    """
    view_dir = os.path.join(data, "label-view")
    os.makedirs(view_dir, exist_ok=True)
    order = sorted(s["id"] for s in sample)
    random.Random(SEED + 1).shuffle(order)
    lines = []
    for k, pid in enumerate(order):
        p = pairs_by_id[pid]
        reply = p["assistant"].rstrip()
        ending = reply if len(reply) <= VIEW_TAIL else "…" + reply[-VIEW_TAIL:]
        lines += [
            "##### [%d] %s  len=%d" % (k, pid, len(reply)),
            "GOAL: " + excerpt(p["prev_user"], VIEW_GOAL),
            "END: " + ending,
            "NEXT(%s): %s" % (p["next_kind"], excerpt(p["next_user"], VIEW_NEXT)),
            "",
        ]
    with open(os.path.join(view_dir, "a1.md"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data", required=True, help="private output directory, outside the repository")
    ap.add_argument("--projects", default=os.path.expanduser("~/.claude/projects"))
    a = ap.parse_args()
    os.makedirs(a.data, exist_ok=True)

    files = sorted(glob.glob(os.path.join(a.projects, "*", "*.jsonl")))
    cutoff = gate_cutoff(files)
    stats = {k: 0 for k in ("sessions_noninteractive", "stops_blocked_by_other_hook", "turns_interrupted",
                            "turns_after_gate_cutoff", "turns_empty_text",
                            "duplicate_records")}
    pairs, seen = [], set()
    for f in files:
        for p in pairs_from_file(f, cutoff, stats):
            if p["uuid"] in seen:
                stats["duplicate_records"] += 1
                continue
            seen.add(p["uuid"])
            p["id"] = hashlib.sha1((str(p["session_id"]) + str(p["uuid"])).encode()).hexdigest()[:12]
            p["ends_q"] = ends_with_question(p["assistant"])
            pairs.append(p)
    pairs.sort(key=lambda p: (p["timestamp"], p["id"]))

    q_ids = sorted(p["id"] for p in pairs if p["ends_q"])
    r_ids = sorted(p["id"] for p in pairs if not p["ends_q"])
    rng = random.Random(SEED)
    q_pick = q_ids if len(q_ids) <= Q_CAP else sorted(rng.sample(q_ids, Q_CAP))
    r_pick = sorted(rng.sample(r_ids, min(REST_N, len(r_ids))))
    sample = [{"id": i, "stratum": "Q"} for i in q_pick] + [{"id": i, "stratum": "R"} for i in r_pick]

    with open(os.path.join(a.data, "pairs.jsonl"), "w", encoding="utf-8") as fh:
        for p in pairs:
            fh.write(json.dumps(p, ensure_ascii=False, sort_keys=True) + "\n")
    with open(os.path.join(a.data, "sample.jsonl"), "w", encoding="utf-8") as fh:
        for s in sample:
            fh.write(json.dumps(s, sort_keys=True) + "\n")
    write_views(a.data, sample, {p["id"]: p for p in pairs})

    versions = sorted({p["version"] for p in pairs if p["version"]},
                      key=lambda v: [int(x) if x.isdigit() else 0 for x in v.split(".")])
    meta = {
        "seed": SEED,
        "gate_cutoff": cutoff,
        "pairs": len(pairs),
        "sessions": len({p["session_id"] for p in pairs}),
        "strata": {"Q": {"size": len(q_ids), "sampled": len(q_pick)},
                   "R": {"size": len(r_ids), "sampled": len(r_pick)}},
        "first": pairs[0]["timestamp"] if pairs else None,
        "last": pairs[-1]["timestamp"] if pairs else None,
        "versions": [versions[0], versions[-1]] if versions else None,
        "excluded": stats,
        "next_input_kinds": dict(sorted(collections.Counter(p["next_kind"] for p in pairs).items())),
    }
    with open(os.path.join(a.data, "extract-meta.json"), "w", encoding="utf-8") as fh:
        json.dump(meta, fh, indent=2, sort_keys=True)
        fh.write("\n")
    json.dump(meta, sys.stdout, indent=2, sort_keys=True)
    print()


if __name__ == "__main__":
    main()
