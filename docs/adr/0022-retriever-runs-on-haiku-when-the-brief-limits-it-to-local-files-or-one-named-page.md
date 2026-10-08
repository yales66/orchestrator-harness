# ADR 0022: `retriever` runs on Haiku when the brief limits it to local files or one named page

## Status

Accepted. In effect since 9 October 2026. It amends the `retriever` row of [ADR 0021](0021-implementer-runs-on-haiku-when-tests-decide-every-change.md): a lookup that the brief limits to local files, session transcripts or one web page it names, and that the brief tells to report rather than look further when the answer is not there, runs on Haiku 5.5; every other lookup stays on Opus 5.5. The effort set by the `retriever` definition, `medium`, is unchanged.

## Context

ADR 0021 kept `retriever` on opus because no haiku effort met its competence rule for lookup, which applies the 5-point bar of [ADR 0008](0008-subagent-effort-per-kind-of-dispatch.md): the upper end of the 95% t interval on the paired checks difference, opus minus haiku, must be at most 5 percentage points, and no hard-band case may have opus passing both reps while haiku fails both. The follow-up recorded in the section "Lookup follow-up" of `eval/effort-sweep/README.md` added a checklist to the lookup briefs; it cleared once under checks revised after the original four arms were unblinded and failed a confirmation run with those checks frozen.

With six lookup cases the rule asks haiku to match opus on nearly every case, because the interval's width comes from how far the per-case differences spread. Under the checks of the second audit, revised after the original four arms were unblinded and frozen before the confirmation run, the point estimates lie between −2.6 and +4.3 while the intervals stay 13 to 20 points wide. Before that audit haiku `medium` stood at +8.2 and haiku `high` at +3.9, so the estimates near zero depend on it.

| Arm | Pass | Paired checks difference, opus − haiku, pp (95% CI) |
|---|---|---|
| opus medium | 7/12 | reference |
| haiku medium | 8/12 | +1.4 (−8.6 to +11.3) |
| haiku high | 6/12 | +4.3 (−3.7 to +12.3) |
| haiku high, brief with checklist, two runs | 8/12, 6/12 | −1.8 (−8.4 to +4.7), −0.4 (−9.4 to +8.5) |
| haiku xhigh | 7/12 | −2.6 (−10.5 to +5.3) |

The run records show one failure mode that separates haiku from opus. When an official page returns 403 or 404, or WebFetch cannot read a PDF and saves it instead, opus takes another route, such as running pdftotext on the saved file, while haiku at `high` and `medium` mostly stops there and cites a third-party article or reports the fact as not found. In the original four arms such a saved PDF came up in 4 opus attempts, 4 haiku `xhigh` attempts, 1 haiku `high` attempt and 2 haiku `medium` attempts; opus read it in all 4, haiku `xhigh` in 2 and haiku `high` and `medium` in none. The other haiku misses the sweep listed fall elsewhere: a required official source absent is this same failure, a wrong lower bound of support was a check that misread a correct sentence, and an archive declared missing was missed by opus as well, as facts that need proof of absence across sites are for both models. One check of the hardest lookup was met in none of the 14 attempts on that lookup across all arms, and the official sources disagree with the fact it asks for; it lowers every arm's pass rate alike and does not move the paired differences.

The two easy-band lookups avoid that failure mode. One extracts eight facts from four local design documents, the other reads three pricing facts from one vendor page the brief names. Under the second audit's checks every attempt of opus and of haiku at `medium`, `high` and `xhigh` passed both, 4 of 4 per arm, and the two checklist runs passed 4 of 4 and 3 of 4, the miss being one local fact the frozen checks did not find in the report. Before that audit opus passed 3 of 4 and haiku `medium` 2 of 4, on checks that misread table layouts and a correct sentence. Haiku `medium` cost $0.33 in total over its four attempts against $1.58 for opus.

The same checklist did not help opus. On the three lookups opus had failed, the paired checks difference, opus without the checklist minus opus with it, was −0.3 (−16.9 to +16.4) points, a negligible gain, at 1.40 times the subagent cost, so the checklist is not adopted.

## Decision

| Dispatch | Model | Effort | Condition |
|---|---|---|---|
| `retriever` | haiku | `medium`, from the definition | the brief limits the lookup to local files, session transcripts or one web page it names, not a PDF, and tells the subagent to report rather than follow links when the answer is not there |
| `retriever` | opus | `medium`, from the definition | every other lookup, including any that must find official sources across sites, read a PDF or show across sites that something does not exist, and a lookup haiku reported as not found within its limits |

The "Who" item of section 2 in the `en/` and `zh/` playbooks states the condition. The agent definitions are unchanged.

## Consequences

This decision does not meet the competence rule of ADR 0021, and says so. It rests on two easy-band cases with four attempts per arm, on point estimates between −2.6 and +4.3 across all lookups under checks revised after unblinding, and on the failure mode that separates haiku from opus not arising when the lookup is limited to files or one named web page. Session transcripts are local files as well and involve no 403 or PDF, but no case covered them, and a long transcript can push a haiku request past 100,000 prompt tokens, where it bills at five times the base rate.

The instruction to report rather than look further is a safeguard reasoned from that failure mode; the sweep neither tested it nor tested whether haiku follows it. A lookup that looked like one page and turns out to need a linked PDF or another site is the case most likely to go wrong on haiku, so the haiku branch requires the brief to limit the lookup to the named sources, and a report that the answer is not there sends the lookup again on opus, which then pays for two dispatches.

For these lookups the subagent costs about 0.21 of what it cost on opus at list price. The sweep's dispatching main thread, which runs one short isolated turn, added about $0.14 per dispatch on either model; with it, an easy lookup cost about 0.42 of opus. A production main thread carries a longer context, so its share differs.

A larger lookup case set would let the competence rule decide this split instead of judgement, and would show whether haiku at `xhigh` meets the rule for lookups across sites.

## Sources

| Source | What it supports |
|---|---|
| `eval/effort-sweep/README.md`, the sections "Haiku sweep (October 2026)" and "Lookup follow-up" | The competence rule, the arms, the second audit, the frozen checks, the confirmation run, the saved-PDF counts, the check met in no attempt, the opus checklist run and the easy-band results |
| `en/orchestrator-playbook.md`, section 2 | The routing of `retriever` by the condition above |
| `en/agents/retriever.md`, frontmatter | `retriever` sets effort `medium` and no model |
| [ADR 0021](0021-implementer-runs-on-haiku-when-tests-decide-every-change.md) | The sweep this decision builds on, its competence rule and the `retriever` row this decision amends |
| [ADR 0008](0008-subagent-effort-per-kind-of-dispatch.md) | The 5-point bar |
