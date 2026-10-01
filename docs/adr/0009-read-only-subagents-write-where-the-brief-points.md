# ADR 0009: Read-only subagents write only where the brief points, and retriever leaves judgements open

## Status

Accepted. In effect since 1 October 2026. Supersedes the Limits of `researcher` and `retriever` in the decision table of [ADR 0008](0008-subagent-effort-per-kind-of-dispatch.md); the rest of ADR 0008, including each definition's effort and the work it takes, stands.

## Context

ADR 0008 let `researcher` and `retriever` create new files without saying where, and had `retriever` hold back only a judgement the brief did not ask for. Both limits leave a gap.

`subagent-readonly-guard.sh` denies a read-only subagent changes to existing files through the edit tools and shell commands, and allows creating a new file through Write or a shell redirect, because a read-only dispatch that writes its findings to disk needs to create that file. The playbook gives a read-only dispatch an output path only when its findings should go to disk (section 2, element 2). A dispatch without a path therefore left a subagent free to create notes or scratch scripts anywhere, including inside the user's repository, where they stay behind as untracked files.

`retriever` runs at `medium` because lookup lost nothing measurable there, and the judgement tier is the one the effort sweep could not clear at `medium`. A brief that asks a question whose answer is a judgement, such as whether a configuration is fit for production, still reaches `retriever` when the main thread misroutes it. With the earlier wording such a question counted as asked for, so `retriever` answered the judgement itself at `medium`: asked whether a configuration was ready for production, it gave the verdict.

## Decision

| Definition | Limits |
|---|---|
| `researcher` | creates a new file only at a path the brief names or under the system temp directory, and changes no existing file; without a path its findings go in its final report in the form the brief asks for |
| `retriever` | the same file limits as `researcher`; its report holds facts and their evidence, not verdicts, and when the brief asks something whose answer is a judgement it reports the facts that bear on it and names that judgement as open for the main thread |

The descriptions the main thread routes by state the same boundaries from both sides. `retriever` does not take questions of whether something is correct, safe or good, or searches whose answer could sit anywhere in a repository. `implementer` edits files and runs commands, and does not take work whose design is still open.

## Consequences

A read-only subagent given no output path is to leave no file in the user's repository, and a diagnosis can still write a reproduction script under the system temp directory. The hook does not enforce the path limit, which rests on the definitions' instructions, so a new file elsewhere is a definition failure the guard will not catch.

A judgement question that reaches `retriever` comes back as facts with the judgement named, and the main thread either makes it or dispatches `researcher`. That costs a second dispatch where the first was misrouted, in exchange for no judgement made at `medium` without the main thread seeing it. Asked the same question under this wording, `retriever` left it open in both of two runs.

## Sources

| Source | What it supports |
|---|---|
| `en/agents/researcher.md`, `en/agents/retriever.md`, `en/agents/implementer.md` | The file limits and report shape in each definition's body, and the routing boundaries in each description |
| `en/hooks/subagent-readonly-guard.sh`, header comment | What the guard denies and what it allows |
| `en/orchestrator-playbook.md`, §2, element 2 | A read-only dispatch gets an output path only when its findings go to disk |
| Commit `808960b`, message body | A `retriever` asked whether a config was production-ready answered the judgement under the earlier wording, and two runs under the new wording left it open |
| `docs/adr/0008-subagent-effort-per-kind-of-dispatch.md`, the decision table | The limits this ADR supersedes |
