"""Shared helpers for fork replay: the case contract, rule matching, session copies, repo state.

A case names one decision point in a past Claude Code session and says how to replay it
and how to judge the replay. The contract is shared by every eval built on fork replay,
so `validate_case` is the single place that defines it; see README.md for the fields.

Only the Python standard library is used.
"""
import json
import os
import re
import subprocess
from datetime import datetime, timezone

ASK = {"final": "ask"}
FORK_MODES = ("after", "before")
REQUIRED = ("id", "source_session", "fork_mode", "fork_uuid", "resume_input", "cwd_repo",
            "label", "forbidden", "expected", "tags")


# ---------------------------------------------------------------- contract

def _rule_problems(where, rule):
    out = []
    if not isinstance(rule, dict) or not isinstance(rule.get("tool"), str) \
            or not isinstance(rule.get("pattern"), str):
        return [f"{where}: a rule needs string tool and pattern"]
    for key in ("tool", "pattern"):
        try:
            re.compile(rule[key])
        except re.error as e:
            out.append(f"{where}: bad {key} regex {rule[key]!r}: {e}")
    if out:
        return out
    ex = rule.get("example")
    if ex is not None:
        tool = rule.get("example_tool") or rule["tool"].split("|")[0]
        if not matches(rule, {"tool": tool, "input": ex}):
            out.append(f"{where}: example does not match its own rule")
    return out


def validate_case(case):
    """Return a list of problems; empty means the case honours the contract."""
    problems = [f"missing field {k}" for k in REQUIRED if k not in case]
    if problems:
        return problems
    if not isinstance(case["id"], str) or not case["id"]:
        problems.append("id must be a non-empty string")
    if case["fork_mode"] not in FORK_MODES:
        problems.append(f"fork_mode must be one of {FORK_MODES}")
    if case["fork_mode"] == "after" and not (isinstance(case["resume_input"], str) and case["resume_input"]):
        problems.append("resume_input must be non-empty text in after mode")
    repo = case["cwd_repo"]
    if repo is not None and not (isinstance(repo, dict) and isinstance(repo.get("path"), str)
                                 and isinstance(repo.get("commit"), str)):
        problems.append("cwd_repo must be null or {path, commit[, subdir]}")
    if not isinstance(case["forbidden"], list):
        problems.append("forbidden must be a list")
    else:
        for i, r in enumerate(case["forbidden"]):
            problems += _rule_problems(f"forbidden[{i}]", r)
    if case["expected"] != "ask" and (not isinstance(case["expected"], list) or not case["expected"]):
        problems.append('expected must be "ask" or a non-empty list')
    else:
        for i, r in enumerate(expected_rules(case["expected"])):
            if isinstance(r, dict) and "final" in r:
                if r != ASK:
                    problems.append(f"expected[{i}]: the only final-message expectation is {ASK}")
            else:
                problems += _rule_problems(f"expected[{i}]", r)
    if "cut_uuid" in case and not (case["cut_uuid"] is None or isinstance(case["cut_uuid"], str)):
        problems.append("cut_uuid must be null or a record uuid")
    if not isinstance(case["tags"], list) or not all(isinstance(t, str) for t in case["tags"]):
        problems.append("tags must be a list of strings")
    return problems


def expected_rules(expected):
    """The expected field as a list; the bare string "ask" means [{"final": "ask"}]."""
    return [ASK] if expected == "ask" else list(expected)


def load_cases(path):
    cases = [json.loads(l) for l in open(path, encoding="utf-8") if l.strip()]
    bad = {c.get("id", "?"): p for c in cases if (p := validate_case(c))}
    if bad:
        raise ValueError(f"cases violate the contract: {bad}")
    ids = [c["id"] for c in cases]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate case ids")
    return cases


def input_text(tool_input):
    return json.dumps(tool_input, ensure_ascii=False, sort_keys=True)


def matches(rule, call):
    """A call is {tool, input}; the rule's tool regex is anchored, its pattern is searched."""
    return bool(re.fullmatch(rule["tool"], call["tool"])
                and re.search(rule["pattern"], input_text(call.get("input") or {})))


# ---------------------------------------------------------------- sessions

def slug(path):
    """Claude Code's project directory name for a working directory."""
    return re.sub(r"[^A-Za-z0-9]", "-", path)


def find_record(session_path, uuid):
    with open(session_path, encoding="utf-8") as f:
        for line in f:
            if uuid in line:
                rec = json.loads(line)
                if rec.get("uuid") == uuid:
                    return rec
    return None


def assistant_text(rec):
    content = (rec.get("message") or {}).get("content")
    if isinstance(content, str):
        return content
    return "\n".join(b.get("text", "") for b in content or [] if b.get("type") == "text")


# Secrets are cut out of private session copies before they are ever replayed. The
# character classes exclude quotes and backslashes so a match never straddles a JSON
# escape, which keeps every redacted line valid JSON.
# A token must start at a word boundary or right after a JSON-escaped newline or tab.
_B64 = r"(?:(?<=\\[nt])|(?<![A-Za-z0-9_-]))"
# Long base64 runs are image or file payloads; a redaction inside one would corrupt it.
_BASE64_RUN = re.compile(r"[A-Za-z0-9+/]{200,}={0,2}")
_SECRET_PATTERNS = [
    (re.compile(r"(\b[a-zA-Z][a-zA-Z0-9+.-]*://[^\s:/@\"'\\]+:)([^\s@\"'\\/]+)(@)"), r"\1[REDACTED]\3"),
    (re.compile(_B64 + r"sk-(?:ant-|proj-)?[A-Za-z0-9_-]{20,}"), "[REDACTED]"),
    (re.compile(_B64 + r"(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{30,}"), "[REDACTED]"),
    (re.compile(_B64 + r"github_pat_[A-Za-z0-9_]{30,}"), "[REDACTED]"),
    (re.compile(_B64 + r"AKIA[0-9A-Z]{16}\b"), "[REDACTED]"),
    (re.compile(_B64 + r"xox[abprs]-[A-Za-z0-9-]{10,}"), "[REDACTED]"),
    (re.compile(_B64 + r"AIza[0-9A-Za-z_-]{35}"), "[REDACTED]"),
    (re.compile(_B64 + r"eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}"), "[REDACTED]"),
    (re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----"), "[REDACTED]"),
    (re.compile(r"((?:api[_-]?key|secret|password|passwd|access[_-]?token)[\"']?\s*[:=]\s*[\"']?)"
                r"([A-Za-z0-9/+_.-]{12,})", re.I), r"\1[REDACTED]"),
]


def _redact_text(text):
    n = 0
    for pat, repl in _SECRET_PATTERNS:
        text, k = pat.subn(repl, text)
        n += k
    return text, n


def redact_line(line):
    out, n, pos = [], 0, 0
    for m in _BASE64_RUN.finditer(line):
        part, k = _redact_text(line[pos:m.start()])
        out += [part, m.group(0)]
        n, pos = n + k, m.end()
    part, k = _redact_text(line[pos:])
    out.append(part)
    return "".join(out), n + k


def copy_session(src, dst):
    """Copy a transcript with secrets redacted; returns the number of redactions."""
    total = 0
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    with open(src, encoding="utf-8") as fi, open(dst, "w", encoding="utf-8") as fo:
        for line in fi:
            if not line.strip():
                continue
            out, n = redact_line(line.rstrip("\n"))
            if n:
                json.loads(out)  # a redaction must never corrupt a record
            total += n
            fo.write(out + "\n")
    return total


def lines_until(session_path, uuid):
    out = []
    with open(session_path, encoding="utf-8") as f:
        for line in f:
            out.append(line)
            if uuid in line and json.loads(line).get("uuid") == uuid:
                break
    return out


# ---------------------------------------------------------------- repo state

def _git(repo, *args):
    r = subprocess.run(["git", "-C", repo, *args], capture_output=True, text=True)
    return r.stdout.strip() if r.returncode == 0 else None


def _ts(iso):
    return datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone(timezone.utc)


def _reflog_before(repo, ref, when):
    out = _git(repo, "reflog", "show", "--date=iso-strict", "--format=%H %gd", ref)
    if not out:
        return None
    for line in out.splitlines():  # newest first
        sha, gd = line.split(" ", 1)
        m = re.search(r"@\{(.+)\}", gd)
        if m and _ts(m.group(1)) <= when:
            return sha
    return None


def _existing_ancestor(path):
    while path and not os.path.isdir(path):
        path = os.path.dirname(path)
    return path


def resolve_repo(cwd, branch, ts, transcript_lines):
    """Repository and commit the session's working directory stood on at time ts.

    Returns {path, commit, subdir, method} or None. `path` is the repository to run
    `git worktree add` from (the main checkout for a .claude/worktrees/ worktree, whose
    directory may be gone), `subdir` is the cwd relative to the checkout root.
    Uncommitted changes present at the time cannot be recovered from git; callers must
    treat the result as the committed state only.
    """
    when = _ts(ts)
    if "/.claude/worktrees/" in cwd:
        main, rest = cwd.split("/.claude/worktrees/", 1)
        name, _, subdir = rest.partition("/")
        repo = _git(main, "rev-parse", "--show-toplevel") if os.path.isdir(main) else None
    else:
        base = _existing_ancestor(cwd)
        top = _git(base, "rev-parse", "--show-toplevel") if base else None
        repo, subdir = top, (os.path.relpath(os.path.realpath(cwd), os.path.realpath(top)) if top else "")
        if subdir == ".":
            subdir = ""
    if not repo:
        return None
    repo = os.path.realpath(repo)

    def found(sha, method):
        return {"path": repo, "commit": sha, "subdir": subdir, "method": method}

    if branch and branch != "HEAD":
        # A branch merged and deleted locally often survives as a remote-tracking ref.
        for ref, tag in ((f"refs/heads/{branch}", "branch"), (f"refs/remotes/origin/{branch}", "remote-branch")):
            if not _git(repo, "rev-parse", "--verify", "-q", ref):
                continue
            sha = _reflog_before(repo, ref, when)
            if sha:
                return found(sha, f"{tag}-reflog")
            sha = _git(repo, "rev-list", "-1", f"--before={ts}", ref)
            if sha:
                return found(sha, f"{tag}-rev-list")
        pat = re.compile(r"\[" + re.escape(branch) + r"(?: \(root-commit\))? ([0-9a-f]{7,40})\]")
        for line in reversed(transcript_lines):
            m = pat.search(line)
            if m:
                sha = _git(repo, "rev-parse", "--verify", "-q", m.group(1) + "^{commit}")
                if sha:
                    return found(sha, "transcript-commit-output")
        return None
    sha = _reflog_before(repo, "HEAD", when)
    return found(sha, "head-reflog") if sha else None
