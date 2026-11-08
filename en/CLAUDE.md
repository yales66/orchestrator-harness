# General rules

This file records only the deltas from Claude Code's default behaviour.

## Keys and credentials

- Never read the contents of private keys, secrets or credentials: SSH private keys, `.env*`, tokens, API keys, the password in a connection string. Do not open them with Read, and do not view them with cat/head/sed/grep. Once the user or a permission has denied reading a file, that denial holds for every tool; do not get around it with a different shell command.
- Do not write commands or scripts that output, print, echo or log these values in plain text (`cat <private key>`, `echo $SECRET`, printing a connection string to stdout).
- Identify or match key files only by non-sensitive metadata: file name, mtime, public-key fingerprint (`ssh-keygen -lf <file>.pub`). To use an SSH key, handle only its path: `ssh -i <path>`, and let ssh read it.
- When a secret value is needed, the user injects it in a `! command` or does the step by hand on the machine; I never handle the plain text. When wiring up a new interface that needs a key, create an empty, separate env file for the user to fill in, run commands after loading it with `set -a; source <file>; set +a`, and have the code put the value into the request only through a reader function.

## Producing prose

Before drafting or revising any text output meant for humans to read (documents, reports, explanations, artifacts, interface copy (including button, prompt and error text written into code or i18n files), video scripts and subtitles, emails, résumés and the like), load the prose-discipline skill and write by it; this does not apply to conversation replies or rule files.

## Changing existing code

- Before touching anything, run git log/blame on the relevant lines (micro-why); if the repo has docs/adr/, ls that directory and read in full every file whose name matches the task at hand (macro-why). If you retrieve a reason and it agrees with this change, make the change along it and cite the source in your report; if the retrieved reason shows the current state is intentional and this change conflicts with it, ask first and cite the source in the question; if you cannot retrieve a reason and the change would alter that spot's behaviour, then when the change is required by the task's goal, first add characterisation tests that pin the current state and then change it, state in the commit message that the original reason was not found and that the change can be reverted, and list it in your report; when it is not required, leave that spot untouched. When the change touches a business threshold whose source cannot be found in the repository, leave that spot untouched, do the rest, and list separately in your report its location and the question the user needs to answer. A spot the user names for change in this turn is changed directly.

## Testing

- New code with logic is test-first (tdd-watch-it-fail); if you cannot write a test that "turns red when the code is wrong", do not write the test.
- Before removing or refactoring behaviour that no test covers, first add characterisation tests that pin the current state (watch them go green), and they must still be green after the change.
- The second time the same setup appears, extract it into a helper/fixture; when the same assertion is repeated with different inputs, use `parametrize` (with `ids=`).
- During development, run only the test files related to the change, not the full suite. "Related" is measured by the reference surface of the changed exported symbols: first search out every test file that references them, then run those; do not go by similar file names.

## Sources and verification

- A binding limit, count or business threshold written into a design or code comes only from measurement, user data or an official source; a widely accepted default of the language or framework is used as is, with that default noted as its source. Literature that gives only a direction does not count as a source for the number. Where some value is needed for the thing to run, pick one and mark it "to be measured"; do not write it up as a grounded decision.
- Do not take your own program's output as ground truth by default: before using it as a judge, gold standard or acceptance criterion, state which parts are precise and which are rough, give a way to calibrate it against an external source, and turn the rough parts into checkable items rather than hiding them behind a looser tolerance.
- When proposing a plan or drawing a conclusion, say whether it was measured; mark anything unmeasured "assumption, not measured", and schedule any audit, rollout or write-up that depends on it after the measurement.

## Docker

This covers only Docker on the local machine; containers on remote hosts and demo machines are out of scope.

- Main thread: when the task is done with Docker, clean up without asking. First remove what this task started: for a compose stack, run `down -v` with the same `-p`/`-f` arguments used to bring it up; for a container started with `docker run`, run `docker rm -f -v <container name>`. Then run `docker system prune -a --volumes -f && docker volume prune -a -f` to clear every other unused image, container, volume and build cache. A stack already running when the task started was not started by this task and is not brought down; containers another session is running survive the prune. "Done with" means this task no longer needs it: a stack left for the user to check locally is cleaned up after the user has checked it.
- Subagent: remove only the stacks and containers you started (not those the brief says to keep), do not run the global prune, and state in your report what you removed and what you kept.
