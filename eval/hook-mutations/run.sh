#!/usr/bin/env bash
# Hook mutation test: how many injected defects do the hook regression tests catch?
#
# Every row of mutations.tsv replaces one exact anchor in one hook under
# en/hooks. For each row the driver copies en/hooks (tests included) and
# en/orchestrator-playbook.md into a fresh temp dir, applies the edit to the
# copy, and runs that hook's own test file against it. A non-zero exit or a
# timeout kills the mutant; exit 0 means it survived. The repository files are
# only read, never written, except for results.md.
#
# Before any mutant runs, each hook's test file runs once against an unmutated
# copy. A hook whose tests already fail is reported "baseline red" and its
# mutants are skipped, because a red test would count every mutant as killed.
# A row whose anchor occurs zero times or more than once in the current hook
# is reported "stale", and a mutant whose hook no longer parses (bash -n or
# the embedded Python) is reported "invalid"; neither is run.
#
# A mutant's test run times out after the larger of HM_TIMEOUT (default 120 s)
# and five times the unmutated run of the same test, so a slow test on a busy
# machine is not mistaken for a hang; the unmutated run itself gets
# HM_BASELINE_TIMEOUT (default 600 s).
#
# Env knobs: HM_TIMEOUT, HM_BASELINE_TIMEOUT, HM_JOBS (parallel
# runs, default 4), HM_MANIFEST (default mutations.tsv next to this script),
# HM_OUT (default results.md next to this script), HM_KEEP=1 (keep the temp
# dir with every copy and test log, and print its path).
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$HERE/../.." && pwd)"
MANIFEST="${HM_MANIFEST:-$HERE/mutations.tsv}"
OUT="${HM_OUT:-$HERE/results.md}"
TIMEOUT="${HM_TIMEOUT:-120}"
BASELINE_TIMEOUT="${HM_BASELINE_TIMEOUT:-600}"
JOBS="${HM_JOBS:-4}"

for tool in python3 jq git; do
  if ! command -v "$tool" >/dev/null 2>&1; then
    echo "run.sh: $tool is required (the hooks or their tests call it)" >&2
    exit 2
  fi
done
[ -f "$MANIFEST" ] || { echo "run.sh: manifest not found: $MANIFEST" >&2; exit 2; }

WORK="$(mktemp -d "${TMPDIR:-/tmp}/hook-mutations.XXXXXX")"
if [ -n "${HM_KEEP:-}" ]; then
  echo "run.sh: keeping copies and logs in $WORK" >&2
else
  trap 'rm -rf "$WORK"' EXIT
fi

python3 - "$REPO" "$MANIFEST" "$OUT" "$WORK" "$TIMEOUT" "$BASELINE_TIMEOUT" "$JOBS" <<'PY'
import concurrent.futures, hashlib, os, re, shutil, signal, subprocess, sys, time

repo, manifest, out_path, work, timeout, base_timeout, jobs = sys.argv[1:8]
timeout, base_timeout, jobs = float(timeout), float(base_timeout), max(1, int(jobs))
hooks_dir = os.path.join(repo, "en", "hooks")
playbook = os.path.join(repo, "en", "orchestrator-playbook.md")
started = time.time()

# Hook settings read from the environment; a developer shell that exports one
# of them would change what the tests observe, so the test runs never see them.
HOOK_ENV = ("REPLY_LANG", "CONTEXT_WINDOW_TOKENS", "CONTEXT_WARN_PCT",
            "CONTEXT_HARD_PCT", "CONTEXT_REBLOCK_DELTA_PCT")
env = {k: v for k, v in os.environ.items() if k not in HOOK_ENV}
env["PYTHONDONTWRITEBYTECODE"] = "1"


def fail(msg):
    sys.stderr.write("run.sh: %s\n" % msg)
    sys.exit(2)


# ---- manifest -------------------------------------------------------------
mutants, seen = [], set()
with open(manifest, encoding="utf-8") as f:
    for lineno, line in enumerate(f, 1):
        line = line.rstrip("\n")
        if not line.strip() or line.startswith("#"):
            continue
        cols = line.split("\t")
        if cols[0] == "id":
            continue
        if len(cols) != 5:
            fail("%s:%d: expected 5 tab-separated columns, got %d" % (manifest, lineno, len(cols)))
        mid, hook, anchor, repl, rule = cols
        if not mid or mid in seen:
            fail("%s:%d: empty or duplicate id %r" % (manifest, lineno, mid))
        if not anchor or anchor == repl:
            fail("%s:%d: %s has an empty anchor or a replacement equal to it" % (manifest, lineno, mid))
        seen.add(mid)
        mutants.append({"id": mid, "hook": hook, "anchor": anchor, "repl": repl, "rule": rule})

hooks = sorted(n for n in os.listdir(hooks_dir) if n.endswith(".sh"))


def test_of(hook):
    return os.path.join(hooks_dir, "tests", hook[:-3] + ".test.sh")


def fingerprint(hook):
    h = hashlib.sha256()
    for p in (os.path.join(hooks_dir, hook), test_of(hook)):
        with open(p, "rb") as f:
            h.update(f.read())
    return h.hexdigest()[:12]


# ---- one isolated test run -------------------------------------------------
def run_copy(job, hook, limit, edit=None):
    """Copy en/hooks into work/job, optionally apply (anchor, repl) to the hook,
    run the hook's test file there with a limit of `limit` seconds and return
    ("pass" | "fail" | "timeout", wall-clock seconds)."""
    root = os.path.join(work, job)
    dst = os.path.join(root, "en", "hooks")
    shutil.copytree(hooks_dir, dst, symlinks=True,
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    if os.path.isfile(playbook):
        shutil.copy2(playbook, os.path.join(root, "en", "orchestrator-playbook.md"))
    if edit is not None:
        target = os.path.join(dst, hook)
        with open(target, encoding="utf-8") as f:
            src = f.read()
        with open(target, "w", encoding="utf-8") as f:
            f.write(src.replace(edit[0], edit[1], 1))
    test = os.path.join(dst, "tests", hook[:-3] + ".test.sh")
    with open(os.path.join(root, "test.log"), "wb") as log:
        t0 = time.time()
        proc = subprocess.Popen(["bash", test], cwd=root, env=env, stdin=subprocess.DEVNULL,
                                stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
        try:
            rc = proc.wait(timeout=limit)
            result = "pass" if rc == 0 else "fail"
        except subprocess.TimeoutExpired:
            result = "timeout"
        try:
            os.killpg(proc.pid, signal.SIGKILL)     # stragglers the test left behind
        except (ProcessLookupError, PermissionError):
            pass
        proc.wait()
    return result, time.time() - t0


# The hooks swallow stderr and allow on any error, so a mutant that no longer
# parses behaves like "always allow" and is killed without saying anything
# about the tests. Such mutants are reported as invalid and not run.
def syntax_error(mid, text):
    path = os.path.join(work, "syntax-" + mid + ".sh")
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    r = subprocess.run(["bash", "-n", path], stdin=subprocess.DEVNULL,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if r.returncode != 0:
        return "bash -n fails"
    for body in re.findall(r"python3 -c \x27(.*?)\x27", text, re.S):
        try:
            compile(body, mid, "exec")
        except SyntaxError as e:
            return "embedded Python does not compile: line %s" % e.lineno
    return ""


# ---- baseline ---------------------------------------------------------------
baseline, limits = {}, {}
with concurrent.futures.ThreadPoolExecutor(max_workers=jobs) as pool:
    futs = {}
    for hook in hooks:
        if not os.path.isfile(test_of(hook)):
            baseline[hook] = "no test"
            continue
        futs[pool.submit(run_copy, "baseline-" + hook[:-3], hook, base_timeout)] = hook
    for fut in concurrent.futures.as_completed(futs):
        r, secs = fut.result()
        baseline[futs[fut]] = "green" if r == "pass" else "red (%s)" % r
        limits[futs[fut]] = max(timeout, 5 * secs)

# ---- mutants ------------------------------------------------------------------
results = {}
with concurrent.futures.ThreadPoolExecutor(max_workers=jobs) as pool:
    futs = {}
    for m in mutants:
        path = os.path.join(hooks_dir, m["hook"])
        if m["hook"] not in hooks:
            results[m["id"]] = ("stale", "hook file not found")
            continue
        if baseline[m["hook"]] != "green":
            results[m["id"]] = ("skipped", "baseline " + baseline[m["hook"]])
            continue
        with open(path, encoding="utf-8") as f:
            src = f.read()
        n = src.count(m["anchor"])
        if n != 1:
            results[m["id"]] = ("stale", "anchor matches %d times" % n)
            continue
        err = syntax_error(m["id"], src.replace(m["anchor"], m["repl"], 1))
        if err:
            results[m["id"]] = ("invalid", err)
            continue
        futs[pool.submit(run_copy, "mutant-" + m["id"], m["hook"],
                          limits[m["hook"]], (m["anchor"], m["repl"]))] = m["id"]
    for fut in concurrent.futures.as_completed(futs):
        r = fut.result()[0]
        results[futs[fut]] = {"pass": ("survived", ""), "fail": ("killed", "test exited non-zero"),
                              "timeout": ("killed", "timeout")}[r]

# ---- report ---------------------------------------------------------------------
def cell(s):
    return s.replace("|", "\\|")


def count(pred):
    return sum(1 for m in mutants if pred(m, results[m["id"]][0]))


killed = count(lambda m, s: s == "killed")
survived = count(lambda m, s: s == "survived")
stale = count(lambda m, s: s == "stale")
skipped = count(lambda m, s: s == "skipped")
invalid = count(lambda m, s: s == "invalid")
evaluated = killed + survived
score = "%.1f%%" % (100.0 * killed / evaluated) if evaluated else "n/a"

L = []
L.append("# Hook mutation results")
L.append("")
L.append("Generated by `bash eval/hook-mutations/run.sh` from `%s`; "
         "do not edit by hand. Each mutant is one edit to a copy of a hook in `en/hooks`, and the hook's "
         "own test file ran against that copy, with a timeout of %g seconds or five times the unmutated "
         "run of that test, whichever is larger. A mutant is killed when the test exits non-zero or times "
         "out and survives when it exits 0. `README.md` describes the method and its limits."
         % (os.path.relpath(os.path.abspath(manifest), repo), timeout))
L.append("")
L.append("## Summary")
L.append("")
L.append("| Mutants | Evaluated | Killed | Survived | Stale | Invalid | Skipped (baseline red) | Mutation score |")
L.append("|---:|---:|---:|---:|---:|---:|---:|---:|")
L.append("| %d | %d | %d | %d | %d | %d | %d | %s |"
         % (len(mutants), evaluated, killed, survived, stale, invalid, skipped, score))
L.append("")
L.append("## Per hook")
L.append("")
L.append("The fingerprint is the first 12 hex digits of the SHA-256 of the hook followed by its test file, "
         "so a rerun on changed hooks or tests shows up here.")
L.append("")
L.append("| Hook | Baseline | Killed / evaluated | Stale | Fingerprint |")
L.append("|---|---|---:|---:|---|")
for hook in hooks:
    mine = [m for m in mutants if m["hook"] == hook]
    k = sum(1 for m in mine if results[m["id"]][0] == "killed")
    e = sum(1 for m in mine if results[m["id"]][0] in ("killed", "survived"))
    s = sum(1 for m in mine if results[m["id"]][0] == "stale")
    fp = fingerprint(hook) if os.path.isfile(test_of(hook)) else "no test"
    L.append("| `%s` | %s | %d / %d | %d | `%s` |" % (hook, baseline[hook], k, e, s, fp))
L.append("")
L.append("## Survivors")
L.append("")
surv = [m for m in mutants if results[m["id"]][0] == "survived"]
if surv:
    L.append("| Id | Hook | Rule the mutant breaks |")
    L.append("|---|---|---|")
    for m in surv:
        L.append("| %s | `%s` | %s |" % (m["id"], m["hook"], cell(m["rule"])))
else:
    L.append("None.")
L.append("")
L.append("## All mutants")
L.append("")
L.append("| Id | Hook | Result | Rule the mutant breaks |")
L.append("|---|---|---|---|")
for m in mutants:
    st, why = results[m["id"]]
    res = "%s (%s)" % (st, why) if why else st
    L.append("| %s | `%s` | %s | %s |" % (m["id"], m["hook"], cell(res), cell(m["rule"])))

with open(out_path, "w", encoding="utf-8") as f:
    f.write("\n".join(L) + "\n")

print("hook mutations: %d killed / %d evaluated (%s), %d survived, %d stale, %d invalid, %d skipped"
      % (killed, evaluated, score, survived, stale, invalid, skipped))
red = [h for h in hooks if baseline[h] not in ("green", "no test")]
if red:
    print("baseline red: " + ", ".join(red))
print("wrote %s in %.0f s" % (os.path.relpath(out_path, repo), time.time() - started))
PY
