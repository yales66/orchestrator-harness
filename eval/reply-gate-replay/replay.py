#!/usr/bin/env python3
"""Replay the reply-gate Stop hook over every extracted pair.

Runs the real hook script once per pair with REPLY_LANG=zh, feeding it the same JSON a
Stop event carries, and records whether rule A1 (closing offer) and rule A2 (reply
language) fired. The two rules share one reason string, so each is recognised by its
own marker sentence, the same markers the hook's regression test uses.

Writes into the private data directory:
  replay.jsonl       id, a1_fired, a2_fired for every pair
  replay-meta.json   hook file hash, counts
  a2-sample.jsonl    up to 30 pairs where A2 fired, drawn with a fixed seed
  label-view/a2.md   those pairs for labeling: start of the earlier user message, start and end of the reply

Usage: python3 replay.py --data DIR [--repo PATH]
"""
import argparse
import concurrent.futures
import hashlib
import json
import os
import random
import re
import subprocess

SEED = 20260929
A2_CAP = 30
A1_MARK = "直接做完再汇报"
A2_MARK = "用中文重写"
HOOK_REL = os.path.join("en", "hooks", "reply-gate.sh")


def run_hook(hook, text):
    payload = json.dumps({
        "hook_event_name": "Stop",
        "stop_hook_active": False,
        "transcript_path": "/nonexistent/transcript.jsonl",
        "last_assistant_message": text,
    })
    env = dict(os.environ, REPLY_LANG="zh")
    out = subprocess.run(["bash", hook], input=payload.encode("utf-8"), env=env,
                         stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, check=False).stdout
    raw = out.decode("utf-8").strip()
    if not raw:
        return False, False
    try:
        obj = json.loads(raw)
    except ValueError:
        return False, False
    if obj.get("decision") != "block":
        return False, False
    reason = obj.get("reason", "")
    return A1_MARK in reason, A2_MARK in reason


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data", required=True, help="private data directory written by extract.py")
    ap.add_argument("--repo", default=os.path.dirname(os.path.dirname(here)))
    a = ap.parse_args()
    hook = os.path.join(a.repo, HOOK_REL)

    pairs = [json.loads(l) for l in open(os.path.join(a.data, "pairs.jsonl"), encoding="utf-8")]
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda p: run_hook(hook, p["assistant"]), pairs))

    rows = [{"id": p["id"], "a1_fired": r[0], "a2_fired": r[1]} for p, r in zip(pairs, results)]
    with open(os.path.join(a.data, "replay.jsonl"), "w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, sort_keys=True) + "\n")

    a2_ids = sorted(r["id"] for r in rows if r["a2_fired"])
    pick = a2_ids if len(a2_ids) <= A2_CAP else sorted(random.Random(SEED).sample(a2_ids, A2_CAP))
    with open(os.path.join(a.data, "a2-sample.jsonl"), "w", encoding="utf-8") as fh:
        for i in pick:
            fh.write(json.dumps({"id": i}) + "\n")
    by_id = {p["id"]: p for p in pairs}
    os.makedirs(os.path.join(a.data, "label-view"), exist_ok=True)
    lines = []
    for k, i in enumerate(pick):
        text = by_id[i]["assistant"]
        body = re.sub(r"\n+", " / ", text)
        lines += [
            "##### [%d] %s len=%d fences=%d" % (k, i, len(text), len(re.findall(r"```", text)) // 2),
            "GOAL: " + (by_id[i]["prev_user"] or "(none)").replace("\n", " / ")[:220],
            "HEAD: " + body[:350],
            "TAIL: " + body[-250:],
            "",
        ]
    with open(os.path.join(a.data, "label-view", "a2.md"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")

    with open(hook, "rb") as fh:
        hook_sha = hashlib.sha256(fh.read()).hexdigest()[:12]
    meta = {
        "hook_sha256_12": hook_sha,
        "reply_lang": "zh",
        "pairs": len(rows),
        "a1_fired": sum(r["a1_fired"] for r in rows),
        "a2_fired": sum(r["a2_fired"] for r in rows),
        "both_fired": sum(r["a1_fired"] and r["a2_fired"] for r in rows),
        "a2_sample": len(pick),
    }
    with open(os.path.join(a.data, "replay-meta.json"), "w", encoding="utf-8") as fh:
        json.dump(meta, fh, indent=2, sort_keys=True)
        fh.write("\n")
    print(json.dumps(meta, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
