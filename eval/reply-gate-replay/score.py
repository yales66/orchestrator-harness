#!/usr/bin/env python3
"""Score the reply-gate replay against the blind labels and render results.md.

Reads from the private data directory: extract-meta.json, sample.jsonl, labels.jsonl,
replay.jsonl, replay-meta.json, pairs.jsonl (only the ending of each reply, to name the
mechanism of a miss), a2-sample.jsonl and labels-a2.jsonl. Writes results.md next to
this script. The output holds counts, rates and intervals only, never conversation text.

A1 precision and recall are weighted by stratum: every labeled pair stands for
size/sampled pairs of its stratum. Intervals are Wilson 95% intervals; for the weighted
rates the n inside the interval is Kish's effective sample size.

Usage: python3 score.py --data DIR [--out PATH]
"""
import argparse
import collections
import json
import math
import os
import re

SHD = "should-have-just-done-it"
Z = 1.96
MIN_SHD = 30

SHAPE = {
    "yes-no-offer": "yes-or-no question offering one agent action",
    "choice-offer": "question asking the user to pick between named options or actions",
    "menu-offer": "list of optional next steps followed by an invitation to pick",
    "statement-offer": "offer written as a statement or conditional invitation, with no question",
    "info-question": "question asking the user for information or material",
    "user-action-request": "request that the user do something themselves",
    "other-question": "rhetorical question or comprehension check",
    "no-question": "report or statement with no ask",
}
CRITERION = {
    "irreversible": "an action that cannot be taken back",
    "external": "an external action such as merging, deploying, requesting review or changing production",
    "paid": "a paid call to a metered model API or data source",
    "out-of-goal": "new work beyond the goal of the turn",
    "fork": "a choice that turns on the user's own preferences or facts",
    "checkpoint": "a step the user had asked to be consulted on",
}


def load_jsonl(path):
    with open(path, encoding="utf-8") as fh:
        return [json.loads(l) for l in fh if l.strip()]


def load_json(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def wilson(p, n):
    if not n:
        return None
    denom = 1 + Z * Z / n
    centre = (p + Z * Z / (2 * n)) / denom
    half = Z * math.sqrt(p * (1 - p) / n + Z * Z / (4 * n * n)) / denom
    return max(0.0, centre - half), min(1.0, centre + half)


def weighted_rate(items):
    """items: list of (weight, hit). Returns rate, Kish effective n, raw hits, raw n."""
    sw = sum(w for w, _ in items)
    if not sw:
        return None, 0, 0, 0
    rate = sum(w for w, h in items if h) / sw
    n_eff = sw * sw / sum(w * w for w, _ in items)
    return rate, n_eff, sum(1 for _, h in items if h), len(items)


def pct(x):
    return "n/a" if x is None else "%.1f%%" % (100 * x)


def ci(rate, n):
    iv = wilson(rate, n) if rate is not None else None
    return "n/a" if iv is None else "%s to %s" % (pct(iv[0]), pct(iv[1]))


def ending_kind(text):
    """How the reply ends, after the same stripping the gate applies to code and URLs."""
    t = re.sub(r"(?ms)^[ \t]*(```|~~~).*?^[ \t]*\1[^\n]*$", "", text)
    t = re.sub(r"(?ms)^[ \t]*(```|~~~).*\Z", "", t)
    t = re.sub(r"`[^`\n]*`", "", t)
    t = re.sub(r"https?://\S+|www\.\S+", "", t)
    t = t.strip().rstrip(" \t*_~>")
    return "question" if t and t[-1] in "?？吗" else "statement"


def article(phrase):
    return ("An " if phrase[0] in "aeiou" else "A ") + phrase


def miss_mechanism(label, text):
    if label["placement"] in ("last-paragraph", "earlier"):
        return "the offer is followed by further sentences"
    if ending_kind(text) == "statement":
        return "the reply ends without a question mark"
    return "the question is worded without the gate's offer phrases"


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data", required=True)
    ap.add_argument("--out", default=os.path.join(here, "results.md"))
    a = ap.parse_args()
    d = a.data

    em = load_json(os.path.join(d, "extract-meta.json"))
    rm = load_json(os.path.join(d, "replay-meta.json"))
    sample = {s["id"]: s["stratum"] for s in load_jsonl(os.path.join(d, "sample.jsonl"))}
    labels = {x["id"]: x for x in load_jsonl(os.path.join(d, "labels.jsonl"))}
    replay = {r["id"]: r for r in load_jsonl(os.path.join(d, "replay.jsonl"))}
    texts = {p["id"]: p["assistant"] for p in load_jsonl(os.path.join(d, "pairs.jsonl")) if p["id"] in sample}
    a2_ids = [x["id"] for x in load_jsonl(os.path.join(d, "a2-sample.jsonl"))]
    a2_labels = {x["id"]: x["a2"] for x in load_jsonl(os.path.join(d, "labels-a2.jsonl"))}

    missing = sorted(set(sample) - set(labels))
    if missing:
        raise SystemExit("%d sampled pairs have no label, e.g. %s" % (len(missing), missing[0]))
    strata = em["strata"]
    weight = {s: strata[s]["size"] / strata[s]["sampled"] for s in strata}

    # Per-stratum tallies
    tally = collections.defaultdict(collections.Counter)
    for pid, s in sample.items():
        lab = labels[pid]["a1"]
        fired = replay[pid]["a1_fired"]
        tally[s][lab] += 1
        tally[s]["fired"] += fired
        tally[s]["fired_" + lab] += fired
    fired_pop = collections.Counter()
    for pid, r in replay.items():
        if r["a1_fired"]:
            fired_pop["all"] += 1
    labeled = [pid for pid in sample if labels[pid]["a1"] != "unclear"]
    unclear = len(sample) - len(labeled)

    prec_items = [(weight[sample[p]], labels[p]["a1"] == SHD) for p in labeled if replay[p]["a1_fired"]]
    rec_items = [(weight[sample[p]], replay[p]["a1_fired"]) for p in labeled if labels[p]["a1"] == SHD]
    prec, prec_neff, prec_hits, prec_n = weighted_rate(prec_items)
    rec, rec_neff, rec_hits, rec_n = weighted_rate(rec_items)
    # Sensitivity: the out-of-goal criterion is the most judgement-laden one, so rerun both
    # rates with those offers counted as should-have-just-done-it.
    def positive_loose(p):
        return labels[p]["a1"] == SHD or labels[p]["criterion"] == "out-of-goal"
    sp, sp_neff, sp_hits, sp_n = weighted_rate(
        [(weight[sample[p]], positive_loose(p)) for p in labeled if replay[p]["a1_fired"]])
    sr, sr_neff, sr_hits, sr_n = weighted_rate(
        [(weight[sample[p]], replay[p]["a1_fired"]) for p in labeled if positive_loose(p)])
    raw_prec = prec_hits / prec_n if prec_n else None
    raw_rec = rec_hits / rec_n if rec_n else None
    shd_total = sum(1 for p in labeled if labels[p]["a1"] == SHD)
    shd_by = collections.Counter(sample[p] for p in labeled if labels[p]["a1"] == SHD)
    est_shd = {s: shd_by[s] * weight[s] for s in strata}

    # Error patterns
    fp = collections.Counter()
    fp_w = collections.Counter()
    fn = collections.Counter()
    fn_w = collections.Counter()
    for p in labeled:
        lab = labels[p]
        fired = replay[p]["a1_fired"]
        w = weight[sample[p]]
        if fired and lab["a1"] != SHD:
            if lab["a1"] == "rightly-asked":
                key = "An offer of %s, written as a %s" % (CRITERION[lab["criterion"]], SHAPE[lab["shape"]])
            else:
                key = article("%s that waits on no agent action, ending with an offer phrase" % SHAPE[lab["shape"]])
            fp[key] += 1
            fp_w[key] += w
        if not fired and lab["a1"] == SHD:
            key = article("%s, where %s" % (SHAPE[lab["shape"]], miss_mechanism(lab, texts[p])))
            fn[key] += 1
            fn_w[key] += w

    # A2
    n_pairs = rm["pairs"]
    a2_fire = rm["a2_fired"] / n_pairs
    a2_need = sum(1 for i in a2_ids if a2_labels.get(i) == "needs-chinese-rewrite")
    a2_n = sum(1 for i in a2_ids if i in a2_labels)
    a2_prec = a2_need / a2_n if a2_n else None

    L = []
    w = L.append
    w("# Reply gate replay results")
    w("")
    w("These numbers come from replaying `en/hooks/reply-gate.sh` offline over the main-thread transcripts of one user's past "
      "Claude Code sessions and comparing its decisions with labels assigned blind from the reply text. The method, the "
      "commands and the limits are in README.md, and the labeling rules are in labeling-rules.md. This file holds aggregate "
      "numbers only.")
    w("")
    w("## Population")
    w("")
    w("| Item | Value |")
    w("|---|---|")
    w("| Transcript window | %s to %s (UTC), ending where the reply gate first ran in the transcripts |" % (em["first"][:10], em["last"][:10]))
    w("| Claude Code versions in the transcripts | %s to %s |" % tuple(em["versions"]))
    w("| Hook script | file sha256 prefix `%s`, replayed with REPLY_LANG=%s |"
      % (rm["hook_sha256_12"], rm["reply_lang"]))
    w("| Sessions with at least one pair | %d |" % em["sessions"])
    w("| Pairs (final reply of a turn) | %d |" % em["pairs"])
    ex = em["excluded"]
    w("| Excluded | %d non-interactive sessions, %d interrupted turns, %d stops that another Stop hook blocked, %d turns after the gate went live, %d duplicate records from resumed sessions |"
      % (ex["sessions_noninteractive"], ex["turns_interrupted"], ex["stops_blocked_by_other_hook"],
         ex["turns_after_gate_cutoff"], ex["duplicate_records"]))
    w("| Stratum Q: reply ends with ? or ？ | %d pairs, %d sampled |" % (strata["Q"]["size"], strata["Q"]["sampled"]))
    w("| Stratum R: every other reply | %d pairs, %d sampled |" % (strata["R"]["size"], strata["R"]["sampled"]))
    w("| Random seed | %d |" % em["seed"])
    w("")
    w("## A1: closing offer")
    w("")
    w("The gate fired A1 on %d of the %d pairs (%s, Wilson 95%% interval %s)."
      % (fired_pop["all"], n_pairs, pct(fired_pop["all"] / n_pairs), ci(fired_pop["all"] / n_pairs, n_pairs)))
    w("")
    w("| Measure | Estimate | Wilson 95% interval | n | Unweighted |")
    w("|---|---|---|---|---|")
    w("| Precision: should-have-just-done-it among fired | %s | %s | %d fired and labeled (effective n %.1f) | %d of %d, %s |"
      % (pct(prec), ci(prec, prec_neff), prec_n, prec_neff, prec_hits, prec_n, pct(raw_prec)))
    w("| Recall: fired among should-have-just-done-it | %s | %s | %d labeled should-have-just-done-it (effective n %.1f) | %d of %d, %s |"
      % (pct(rec), ci(rec, rec_neff), rec_n, rec_neff, rec_hits, rec_n, pct(raw_rec)))
    w("| Precision, out-of-goal offers counted as should-have-just-done-it | %s | %s | %d (effective n %.1f) | %d of %d |"
      % (pct(sp), ci(sp, sp_neff), sp_n, sp_neff, sp_hits, sp_n))
    w("| Recall, out-of-goal offers counted as should-have-just-done-it | %s | %s | %d (effective n %.1f) | %d of %d |"
      % (pct(sr), ci(sr, sr_neff), sr_n, sr_neff, sr_hits, sr_n))
    w("")
    w("Weighted estimates count each labeled pair as %.3f pairs in stratum Q and %.2f pairs in stratum R. "
      "Unclear labels, excluded from all rates, numbered %d. The two sensitivity rows exist because whether an "
      "offered step lies beyond the goal of the turn is the least mechanical judgement in the labeling rules."
      % (weight["Q"], weight["R"], unclear))
    w("")
    w("| Stratum | Labeled | should-have-just-done-it | rightly-asked | not-an-offer | Fired | Fired and should-have-just-done-it | Estimated should-have-just-done-it in the stratum |")
    w("|---|---|---|---|---|---|---|---|")
    for s in ("Q", "R"):
        t = tally[s]
        w("| %s | %d | %d | %d | %d | %d | %d | %.0f |" % (
            s, strata[s]["sampled"], t[SHD], t["rightly-asked"], t["not-an-offer"], t["fired"], t["fired_" + SHD], est_shd[s]))
    w("")
    if shd_total < MIN_SHD:
        w("Only %d pairs were labeled should-have-just-done-it, fewer than %d, so the recall above is not a reliable estimate." % (shd_total, MIN_SHD))
    else:
        w("%d pairs were labeled should-have-just-done-it, %d of them in stratum R." % (shd_total, shd_by["R"]))
        if est_shd["R"] > est_shd["Q"]:
            L[-1] += (" Recall depends mostly on stratum R, where each labeled pair stands for %.1f pairs, so its interval "
                      "rests on an effective sample of %.1f pairs rather than on %d." % (weight["R"], rec_neff, rec_n))
    w("")
    w("## A2: reply language")
    w("")
    w("| Measure | Estimate | Wilson 95% interval | n |")
    w("|---|---|---|---|")
    w("| Firing rate over all pairs | %s | %s | %d fired of %d |" % (pct(a2_fire), ci(a2_fire, n_pairs), rm["a2_fired"], n_pairs))
    w("| Precision: needs a Chinese rewrite among fired | %s | %s | %d of %d labeled |" % (pct(a2_prec), ci(a2_prec, a2_n), a2_need, a2_n))
    w("")
    w("A1 and A2 fired together on %d pairs. A2 recall was not measured." % rm["both_fired"])
    w("")
    w("## Error patterns")
    w("")
    w("False positives are pairs where A1 fired but the label is not should-have-just-done-it; false negatives are pairs labeled "
      "should-have-just-done-it where A1 did not fire. Counts are labeled sample pairs; the estimate scales them to all pairs by stratum.")
    w("")
    w("| Kind | Pattern | Sample pairs | Estimated pairs |")
    w("|---|---|---|---|")
    for kind, cnt, cw in (("False positive", fp, fp_w), ("False negative", fn, fn_w)):
        for key in sorted(cnt, key=lambda k: (-cw[k], -cnt[k], k))[:5]:
            w("| %s | %s | %d | %.0f |" % (kind, key, cnt[key], cw[key]))
    w("")
    w("False positives total %d sample pairs and false negatives %d." % (sum(fp.values()), sum(fn.values())))
    w("")

    with open(a.out, "w", encoding="utf-8") as fh:
        fh.write("\n".join(L))
    print("\n".join(L))


if __name__ == "__main__":
    main()
