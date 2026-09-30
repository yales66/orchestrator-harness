# Reply gate replay results

These numbers come from replaying `en/hooks/reply-gate.sh` offline over the main-thread transcripts of one user's past Claude Code sessions and comparing its decisions with labels assigned blind from the reply text. The method, the commands and the limits are in README.md, and the labeling rules are in labeling-rules.md. This file holds aggregate numbers only.

## Population

| Item | Value |
|---|---|
| Transcript window | 2026-08-15 to 2026-09-29 (UTC), ending where the reply gate first ran in the transcripts |
| Claude Code versions in the transcripts | 2.1.229 to 2.1.284 |
| Hook script | file sha256 prefix `7cadf4d4638b`, replayed with REPLY_LANG=zh |
| Sessions with at least one pair | 252 |
| Pairs (final reply of a turn) | 2734 |
| Excluded | 17 non-interactive sessions, 15 interrupted turns, 23 stops that another Stop hook blocked, 16 turns after the gate went live, 294 duplicate records from resumed sessions |
| Stratum Q: reply ends with ? or ？ | 161 pairs, 150 sampled |
| Stratum R: every other reply | 2573 pairs, 100 sampled |
| Random seed | 20260929 |

## A1: closing offer

The gate fired A1 on 119 of the 2734 pairs (4.4%, Wilson 95% interval 3.6% to 5.2%).

| Measure | Estimate | Wilson 95% interval | n | Unweighted |
|---|---|---|---|---|
| Precision: should-have-just-done-it among fired | 68.5% | 59.3% to 76.4% | 111 fired and labeled (effective n 111.0) | 76 of 111, 68.5% |
| Recall: fired among should-have-just-done-it | 31.7% | 14.5% to 55.8% | 102 labeled should-have-just-done-it (effective n 16.2) | 76 of 102, 74.5% |
| Precision, out-of-goal offers counted as should-have-just-done-it | 84.7% | 76.8% to 90.2% | 111 (effective n 111.0) | 94 of 111 |
| Recall, out-of-goal offers counted as should-have-just-done-it | 30.6% | 15.0% to 52.5% | 123 (effective n 20.0) | 94 of 123 |

Weighted estimates count each labeled pair as 1.073 pairs in stratum Q and 25.73 pairs in stratum R. Unclear labels, excluded from all rates, numbered 0. The two sensitivity rows exist because whether an offered step lies beyond the goal of the turn is the least mechanical judgement in the labeling rules.

| Stratum | Labeled | should-have-just-done-it | rightly-asked | not-an-offer | Fired | Fired and should-have-just-done-it | Estimated should-have-just-done-it in the stratum |
|---|---|---|---|---|---|---|---|
| Q | 150 | 96 | 52 | 2 | 111 | 76 | 103 |
| R | 100 | 6 | 12 | 82 | 0 | 0 | 154 |

102 pairs were labeled should-have-just-done-it, 6 of them in stratum R. Recall depends mostly on stratum R, where each labeled pair stands for 25.7 pairs, so its interval rests on an effective sample of 16.2 pairs rather than on 102.

## A2: reply language

| Measure | Estimate | Wilson 95% interval | n |
|---|---|---|---|
| Firing rate over all pairs | 2.4% | 1.9% to 3.1% | 66 fired of 2734 |
| Precision: needs a Chinese rewrite among fired | 76.7% | 59.1% to 88.2% | 23 of 30 labeled |

A1 and A2 fired together on 2 pairs. A2 recall was not measured.

## Error patterns

False positives are pairs where A1 fired but the label is not should-have-just-done-it; false negatives are pairs labeled should-have-just-done-it where A1 did not fire. Counts are labeled sample pairs; the estimate scales them to all pairs by stratum.

| Kind | Pattern | Sample pairs | Estimated pairs |
|---|---|---|---|
| False positive | An offer of new work beyond the goal of the turn, written as a yes-or-no question offering one agent action | 16 | 17 |
| False positive | An offer of an external action such as merging, deploying, requesting review or changing production, written as a yes-or-no question offering one agent action | 6 | 6 |
| False positive | An offer of a choice that turns on the user's own preferences or facts, written as a question asking the user to pick between named options or actions | 3 | 3 |
| False positive | An offer of a paid call to a metered model API or data source, written as a yes-or-no question offering one agent action | 3 | 3 |
| False positive | An offer of a choice that turns on the user's own preferences or facts, written as a yes-or-no question offering one agent action | 2 | 2 |
| False negative | A yes-or-no question offering one agent action, where the offer is followed by further sentences | 5 | 104 |
| False negative | An offer written as a statement or conditional invitation, with no question, where the reply ends without a question mark | 2 | 51 |
| False negative | A yes-or-no question offering one agent action, where the question is worded without the gate's offer phrases | 12 | 13 |
| False negative | A question asking the user to pick between named options or actions, where the question is worded without the gate's offer phrases | 7 | 8 |

False positives total 35 sample pairs and false negatives 26.
