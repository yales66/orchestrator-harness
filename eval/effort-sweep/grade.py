"""Deterministic graders for the effort sweep.

impl cases are graded on the end state of the workspace: the brief's own
self-verification commands must pass, at least one file inside the brief's
file scope must have changed, and nothing outside that scope may change.
Replaying the tests that landed with the original change ("hidden" tests) is
recorded as extra checks but does not decide `pass`.

lookup and judgement cases are graded on the final report: every conclusion
check (a regex set derived from the conclusion the main thread later adopted)
must match, no forbidden claim may appear, and the repository must be left
untouched apart from declared output files.

Both return {"grade": {"pass": 0|1, "checks": float}, "explanation": {...}, "detail": {...}}.
`checks` is the share of atomic checks satisfied, a continuous companion to `pass`.
"""
from __future__ import annotations

import re
from pathlib import Path

from common import changed_since, case_env, overlay, path_matches, run_shell

_PLACEHOLDER = re.compile(r"\{changed:([^}|]+)(?:\|([^}]*))?\}")


def expand_command(template: str, changed: list[str]) -> str | None:
    """Replace {changed:GLOB} or {changed:GLOB|PREFIX} with the changed files matching GLOB.

    PREFIX is stripped from each path, for commands that run from a subdirectory.
    Returns None when a placeholder matches no changed file: the brief asked the
    agent to run the tests it wrote, and there are none.
    """
    missing = False

    def repl(m):
        nonlocal missing
        glob, prefix = m.group(1), m.group(2) or ""
        hits = [p for p in changed if path_matches(p, [glob])]
        if not hits:
            missing = True
            return ""
        return " ".join(p[len(prefix):] if prefix and p.startswith(prefix) else p for p in hits)

    out = _PLACEHOLDER.sub(repl, template)
    return None if missing else out


def _cmd_ok(expect: str, res) -> bool:
    if res.timed_out or res.code != 0:
        return False
    if expect == "quiet":
        return res.out.strip() == ""
    return True


def _tail(text: str, n: int = 1200) -> str:
    return text if len(text) <= n else "…" + text[-n:]


def setup_ignores(case: dict) -> list[str]:
    """Paths the workspace setup created or that the case declares as tool output."""
    globs = list(case.get("ignore", []))
    for step in case.get("setup", []):
        if "clone" in step:
            globs.append(step["clone"].rstrip("/") + "/**")
    return globs


def grade_impl(case: dict, ws: Path, before: dict[str, str], run_hidden: bool = True) -> dict:
    ignores = setup_ignores(case)
    changed = [p for p in changed_since(ws, before) if not path_matches(p, ignores)]
    scope, deny = case["scope"], case.get("scope_deny", [])
    in_scope = [p for p in changed if path_matches(p, scope) and not path_matches(p, deny)]
    out_of_scope = [p for p in changed if p not in in_scope]
    env = case_env(case, ws)

    checks = []  # (id, ok, note)
    checks.append(("changed", bool(in_scope), f"{len(in_scope)} file(s) changed inside scope"))
    checks.append(("scope", not out_of_scope, "outside scope: " + ", ".join(out_of_scope) if out_of_scope else "ok"))

    self_ok = True
    runs = []
    for i, spec in enumerate(case["selfcheck"]["commands"]):
        cmd = expand_command(spec["run"], changed)
        if cmd is None:
            ok, note = False, "no changed file matches the placeholder in: " + spec["run"]
            runs.append({"cmd": spec["run"], "code": None, "ok": False, "out": note})
        else:
            res = run_shell(cmd, ws, env={**env, **spec.get("env", {})}, timeout=spec.get("timeout", 900))
            ok = _cmd_ok(spec.get("expect", "exit0"), res)
            note = f"exit {res.code}{' (timeout)' if res.timed_out else ''}"
            runs.append({"cmd": cmd, "code": res.code, "ok": ok, "seconds": round(res.seconds, 1), "out": _tail(res.out)})
        self_ok = self_ok and ok
        checks.append((f"selfcheck{i + 1}", ok, note))

    hidden_runs = []
    hidden = case.get("hidden")
    if hidden and run_hidden:
        overlay(case["repo"], case["oracle_commit"], hidden["files"], ws)
        for i, spec in enumerate(hidden["commands"]):
            res = run_shell(spec["run"], ws, env=env, timeout=spec.get("timeout", 900))
            ok = _cmd_ok(spec.get("expect", "exit0"), res)
            hidden_runs.append({"cmd": spec["run"], "code": res.code, "ok": ok, "seconds": round(res.seconds, 1), "out": _tail(res.out)})
            checks.append((f"hidden{i + 1}", ok, f"exit {res.code}"))

    passed = bool(in_scope) and not out_of_scope and self_ok
    return {
        "grade": {"pass": int(passed), "checks": sum(ok for _, ok, _ in checks) / len(checks)},
        "explanation": {
            "pass": "; ".join(f"{cid}={'ok' if ok else 'FAIL'} ({note})" for cid, ok, note in checks),
        },
        "detail": {
            "changed": changed,
            "out_of_scope": out_of_scope,
            "selfcheck": runs,
            "hidden": hidden_runs,
            "hidden_pass": (all(r["ok"] for r in hidden_runs) if hidden_runs else None),
        },
    }


def _normalise(text: str) -> str:
    # Full-width colon and backticks vary between phrasings of the same fact.
    return text.replace("：", ":").replace("`", "")


def _hit(patterns, text: str) -> str | None:
    for pat in patterns:
        m = re.search(pat, text, re.IGNORECASE | re.MULTILINE)
        if m:
            return m.group(0)
    return None


def grade_text(case: dict, answer: str, changed: list[str]) -> dict:
    text = _normalise(answer or "")
    allowed = case.get("allowed_outputs", [])
    stray = [p for p in changed if not path_matches(p, allowed)]
    readonly_ok = not stray
    no_answer = not text.strip()

    results = []
    for chk in case["checks"]:
        hit = None if no_answer else _hit(chk["any"], text)
        results.append((chk["id"], hit is not None, hit or "no match: " + chk["desc"]))
    for chk in case.get("forbid", []):
        hit = None if no_answer else _hit(chk["any"], text)
        results.append((chk["id"], hit is None and not no_answer, ("forbidden: " + hit) if hit else ("no answer" if no_answer else "absent")))
    results.append(("readonly", readonly_ok and not no_answer, "ok" if readonly_ok else "wrote: " + ", ".join(stray)))

    passed = all(ok for _, ok, _ in results)
    return {
        "grade": {"pass": int(passed), "checks": sum(ok for _, ok, _ in results) / len(results)},
        "explanation": {"pass": "; ".join(f"{cid}={'ok' if ok else 'FAIL'} ({note})" for cid, ok, note in results)},
        "detail": {"no_answer": no_answer, "readonly_ok": readonly_ok, "stray_writes": stray,
                   "checks": [{"id": cid, "ok": ok, "note": note} for cid, ok, note in results]},
    }
