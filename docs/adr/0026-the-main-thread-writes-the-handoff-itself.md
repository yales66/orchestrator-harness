# ADR 0026: The main thread writes the handoff itself, and the session launches its own relay

## Status

Accepted. In effect since 15 October 2026; the relay branches and the wording added on 23 and 24 October 2026 are included. It amends the steps of the handoff skill set by [ADR 0010](0010-handoffs-are-generated-whole-by-the-handoff-skill.md): the Generate and Review steps, the `researcher` that drafts, and the routing file are removed, and the steps are renumbered 0 to 4 with a relay step at the end. ADR 0010's rules that `HANDOFF.md` is generated whole and only through the skill, that the extraction reads every form of the user's input from the transcript, that `finalize.sh` puts the file in place and archives the old one, and that `handoff-guard.sh` denies hand edits all stand. The exception of [ADR 0019](0019-keepalive-probes-the-network-before-waking-and-hands-off-at-its-last-wake-up.md) to step 0 is now case B of step 0. The playbook's old instruction to tell the user to switch sessions with a start instruction is replaced by step 4.

## Context

Under ADR 0010 the main thread extracted the user's input and wrote a brief, a fresh `researcher` drafted `HANDOFF.new.md` and a routing file from it, and the main thread reviewed the draft. In the author's sessions from 7 to 14 October 2026, 69 handoffs cost a median of $2.57 each. The drafting subagent accounted for $1.30 of that and the main thread's review and placement for $0.89, so drafting and review were most of the cost.

A replay on two handoff cases from private projects tested what the review bought. The cases' briefs held 5 known errors; the receiving session, once it started work, caught 4 of them itself, against 2 to 3 caught by the drafting `researcher` across its runs. The receiver reads the premises of each item when it works on that item, so an error in the handoff is mostly found where it matters.

At handoff time the main thread's context had a median of about 360,000 tokens, each call cost about $0.09 at the API-equivalent price, and a handoff took a median of 11 calls, as measured from the author's transcripts and recorded on 13 October 2026. Every call the main thread makes at that point rereads the whole context.

Once the handoff was written, the session told the user to start a new session with a one-line instruction, so the work waited until the user came back.

## Decision

The handoff skill runs these steps:

| Step | What it does |
|---|---|
| 0. Self-check | Takes the first case that holds. A: nothing is left for a session and no question awaits the user; stop wake-ups, close the task checklist, and write no handoff, or only an opening line and ⑤ when an old `HANDOFF.md` exists. B: the user asked for a handoff, the watermark gate stopped the session again, or the last keepalive wake-up judges one needed; go on. C: only wrap-up is left; finish it without a handoff. D: a type B question has a large block of work behind it; ask in text, finish what does not depend on it, and wait with a background `sleep 3000`. E: otherwise go on |
| 1. Directory | The task's working directory, or the directory of an existing `HANDOFF.md` |
| 2. Generate | In one message, in parallel: (a) the main thread writes `HANDOFF.new.md` itself, in one go, with no drafting subagent and no separate review; (b) it adds `.handoff-archive/` to the repository's local git exclude, using an absolute path, and extracts into `<dir>/.handoff-archive/material/`; (d) it stops scheduled wake-ups and cron tasks. A context holding a compaction summary runs (b) first and reads the user's messages before writing (a). Then (c) persists what holds across tasks through `memory-audit`'s admission check |
| 3. Put in place | Fixes the draft for anything new since step 2, settles step 4's branch, updates the task checklist and runs `finalize.sh` |
| 4. Relay | Marks unfinished checklist items blocked with the handoff path, then takes the first case that holds. A: a sharding `PARENT.md` or a track's wrap-up contract specifies the relay; do that. B: every open item waits on a type B question, nothing is left for a session, or the user will open a new session; give the user the handoff path and start instruction and stop. C: the start-here item needs the output of a running task that will notify this session; wait for it, with a background `sleep 3000` as the limit, update that item, then launch per D. D: launch the relay session with `feature-sharding/scripts/launch_tracks.py` in a new Ghostty window, named `<repo dir name>-R<n>` |

Evidence follows the receiver rather than a reviewer. Numbers, paths and thresholds are those the session measured or read, those it did not check are marked "unverified", and no fresh evidence is gathered just to write the handoff. Constraints in ② quote the user's words even when they are already in project memory, and a constraint that survives only word for word, such as design taste or a rejected wording, has the user's words and the rejected text copied in full.

## Consequences

A handoff costs the main thread's own calls and no subagent. No measurement of the cost after this change is recorded here; the figures above are the cost of the removed steps.

No second reader checks the draft before it is placed, so an error the main thread writes reaches the receiver. The replay found that the receiver catches most known errors when it works on the affected item; it covered two cases, and an error in an item the receiver never works on is not caught.

The extraction lands inside the repository under `.handoff-archive/material/`, and the local exclude keeps the user's messages in full out of `git status` and out of commits. The exclude is per clone and is not committed.

The session continues the work without the user: unless the user must answer first or there is nothing left for a session, a relay session starts in a new window. Step 4 D depends on macOS and Ghostty, since `launch_tracks.py` drives Ghostty through AppleScript; when the launch fails, the session falls back to case B and shows the user the error. On other platforms every relay goes through case B.

`verify_refs.py`, which served the drafting `researcher`, was removed upstream with it and is not shipped.

## Sources

| Source | What it supports |
|---|---|
| Commit ce9b81b in the author's live harness (`~/.claude`), body | Removal of the drafting subagent and the review; 69 handoffs from 7 to 14 October 2026 at a median of $2.57, drafting $1.30 and review and placement $0.89; the replay with 5 known errors of which the receiver caught 4 and the drafter 2 to 3; extraction into `.handoff-archive/material/` with the local exclude; the evidence rule; steps renumbered 0 to 4; the routing file removed |
| Commit af126b8 in the author's live harness, body | Parallel calls in step 2; a median context of about 360,000 tokens, about $0.09 per call and a median of 11 calls per handoff |
| Commit e4d9442 in the author's live harness, body | Step 4 C: waiting for a running task the start-here item needs |
| Commit 6f9d65e in the author's live harness, body | The local exclude path taken as an absolute path |
| Commit bb43311 in the author's live harness, body | The relay branches and `launch_tracks.py --sentence` for launching a single relay session |
| Commit bb18ad1 in the author's live harness, body | Step 4 B gives the start instruction and asks the user to answer in a new session |
| Commit be75595 in the author's live harness, body | ② quotes the user's words for persisted constraints and copies taste constraints in full |
| `en/skills/handoff/SKILL.md`, steps 0 to 4 and "Handoff structure" | The steps, branches, evidence rule and the structure of ② |
| `en/skills/feature-sharding/scripts/launch_tracks.py`, module docstring | The relay window is opened in Ghostty through AppleScript |
| `en/orchestrator-playbook.md`, section 3 | The handoff timing and relay per step 4 of the handoff skill |
| [ADR 0010](0010-handoffs-are-generated-whole-by-the-handoff-skill.md) and [ADR 0019](0019-keepalive-probes-the-network-before-waking-and-hands-off-at-its-last-wake-up.md) | The steps this ADR amends and the step 0 exception it keeps |
