"""Shared helpers for the effort sweep: case loading, workspaces, commands.

A workspace is an isolated clone of the case's repository in a fresh
directory under the system temp directory, cut back to the commit the brief was written
against: one branch, `main`, points at that commit, every other ref, tag and
remote is deleted, reflogs are expired and unreachable objects pruned, so no
later commit is left in it. The original checkout is only read, and the clone
is removed afterwards.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

TIERS = ("impl", "lookup", "judgement")
TIER_LABELS = {
    "impl": "判断已写死的实现",
    "lookup": "只读检索和抽取",
    "judgement": "判断密集的审查、诊断",
}
# The system temp directory, resolved because on macOS it sits behind a symlink.
WORK_ROOT = Path(os.path.realpath(tempfile.gettempdir()))

# Files that tools create as a side effect of running tests or linters. They
# never count as a change made by the agent.
NOISE_PATTERNS = (
    "**/__pycache__/**",
    "**/*.pyc",
    "**/.pytest_cache/**",
    "**/.ruff_cache/**",
    "**/.mypy_cache/**",
    "**/.DS_Store",
    "**/*.tsbuildinfo",
    "**/.vite/**",
    "**/.next/**",
)

# Cases dropped from the sweep, each with its reason. Every tier keeps one case
# per repository and task type, so a brief that repeats another case's
# repository, template and problem class adds cost without adding a kind of
# dispatch. The filter sits in load_cases, so the runner, the self-test and the
# inputs page all skip these ids even when a rebuilt cases.jsonl still holds them.
EXCLUDE: dict[str, str] = {
    "impl-aggregator-providers": "与 impl-workday-paging 同仓库、同为改一个外部数据源的抓取代码，重复",
    "lookup-obs-api": "与 lookup-obs-external 同为后端可观测性盘点，同一派发模板",
    "lookup-obs-worker": "与 lookup-obs-external 同为后端可观测性盘点，同一派发模板",
    "judge-recheck-r4-r11": "「在 main 上复核根治项」同模板同仓库共 5 条，与 judge-recheck-r5 问题类别重叠",
    "judge-recheck-r5": "「在 main 上复核根治项」同模板同仓库共 5 条，与 judge-recheck-r4-r11 问题类别重叠",
}


def load_cases(path: Path, include_excluded: bool = False) -> list[dict]:
    """Cases in `path`, leaving out the ids in EXCLUDE unless `include_excluded` is set."""
    cases = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                cases.append(json.loads(line))
    ids = [c["id"] for c in cases]
    if len(ids) != len(set(ids)):
        raise SystemExit("duplicate case ids in " + str(path))
    if include_excluded:
        return cases
    return [c for c in cases if c["id"] not in EXCLUDE]


# ---------------------------------------------------------------- globbing

def glob_to_regex(pattern: str) -> re.Pattern:
    """Translate a path glob where `**` spans directories and `*` does not."""
    out = []
    i = 0
    while i < len(pattern):
        ch = pattern[i]
        if pattern.startswith("**/", i):
            out.append("(?:.*/)?")
            i += 3
        elif pattern.startswith("**", i):
            out.append(".*")
            i += 2
        elif ch == "*":
            out.append("[^/]*")
            i += 1
        elif ch == "?":
            out.append("[^/]")
            i += 1
        else:
            out.append(re.escape(ch))
            i += 1
    return re.compile("^" + "".join(out) + "$")


def path_matches(path: str, patterns) -> bool:
    return any(glob_to_regex(p).match(path) for p in patterns)


def is_noise(path: str) -> bool:
    return path_matches(path, NOISE_PATTERNS)


# ---------------------------------------------------------------- commands

@dataclass
class CmdResult:
    cmd: str
    code: int | None
    out: str
    seconds: float
    timed_out: bool = False


def run_shell(cmd: str, cwd: Path, env: dict | None = None, timeout: float = 900) -> CmdResult:
    full_env = dict(os.environ)
    if env:
        full_env.update(env)
    start = time.monotonic()
    try:
        proc = subprocess.run(
            ["/bin/bash", "-c", cmd], cwd=cwd, env=full_env, capture_output=True,
            text=True, timeout=timeout, start_new_session=True,
        )
        out = (proc.stdout or "") + (proc.stderr or "")
        return CmdResult(cmd, proc.returncode, out, time.monotonic() - start)
    except subprocess.TimeoutExpired as exc:
        out = (exc.stdout or b"").decode(errors="replace") if isinstance(exc.stdout, bytes) else (exc.stdout or "")
        return CmdResult(cmd, None, out, time.monotonic() - start, timed_out=True)


def git(repo: str | Path, *args: str, check: bool = True) -> str:
    proc = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True)
    if check and proc.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed in {repo}: {proc.stderr.strip()}")
    return proc.stdout


# ---------------------------------------------------------------- workspaces

def new_workspace_dir(tag: str) -> Path:
    stamp = time.strftime("%Y%m%d-%H%M%S")
    base = WORK_ROOT / f"effort-sweep-{tag}-{stamp}-{os.getpid()}"
    path = base
    n = 1
    while path.exists():
        n += 1
        path = Path(f"{base}-{n}")
    return path


BRANCH = "main"


def make_clone(repo: str, commit: str, dest: Path) -> None:
    """Clone `repo` into `dest` holding only `commit` and its history, on branch `main`.

    The mirror clone brings every ref of the source, so a base commit reachable
    only from a remote-tracking ref is still found; everything but `main` is then
    deleted and pruned. `git remote remove` runs first because a mirror's refspec
    covers refs/heads and would take `main` with it.
    """
    dest.mkdir(parents=True)
    subprocess.run(["git", "clone", "--no-local", "--no-hardlinks", "--mirror", "--quiet", repo, str(dest / ".git")],
                   check=True, capture_output=True)
    git(dest, "config", "core.bare", "false")
    full = git(repo, "rev-parse", "--verify", f"{commit}^{{commit}}").strip()
    if subprocess.run(["git", "-C", str(dest), "cat-file", "-e", full], capture_output=True).returncode != 0:
        # A commit on a branch deleted after a squash merge is reachable from no
        # ref, so the clone lacks it. Copy exactly its history: a pack built from
        # the commit's ancestry can hold nothing made after it.
        packer = subprocess.Popen(["git", "-C", repo, "pack-objects", "--revs", "--stdout", "--quiet"],
                                  stdin=subprocess.PIPE, stdout=subprocess.PIPE)
        indexer = subprocess.Popen(["git", "-C", str(dest), "index-pack", "--stdin"], stdin=packer.stdout,
                                   stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        packer.stdin.write((full + "\n").encode())
        packer.stdin.close()
        packer.stdout.close()
        _, err = indexer.communicate()
        if packer.wait() != 0 or indexer.returncode != 0:
            raise RuntimeError(f"could not copy the history of {full[:12]} into the clone: {err.decode()[-400:]}")
    git(dest, "remote", "remove", "origin")
    for ref in git(dest, "for-each-ref", "--format=%(refname)").split():
        git(dest, "update-ref", "-d", ref)
    git(dest, "update-ref", f"refs/heads/{BRANCH}", full)
    git(dest, "symbolic-ref", "HEAD", f"refs/heads/{BRANCH}")
    for leftover in ("FETCH_HEAD", "ORIG_HEAD", "MERGE_HEAD", "logs"):
        target = dest / ".git" / leftover
        if target.is_dir():
            shutil.rmtree(target)
        elif target.exists():
            target.unlink()
    git(dest, "reflog", "expire", "--expire=now", "--expire-unreachable=now", "--all")
    git(dest, "gc", "--prune=now", "--quiet")
    git(dest, "checkout", "--force", "--quiet", BRANCH)


def remove_workspace(dest: Path) -> None:
    shutil.rmtree(dest, ignore_errors=True)


def later_commits(case: dict) -> list[str]:
    """Commits that must not exist in the workspace: the landed change and every source tip past the base."""
    repo, base = case["repo"], case["base"]
    probes = set()
    if case.get("oracle_commit"):
        probes.add(git(repo, "rev-parse", f"{case['oracle_commit']}^{{commit}}").strip())
    for tip in set(git(repo, "for-each-ref", "--format=%(objectname)", "refs/heads", "refs/remotes").split()):
        if git(repo, "cat-file", "-t", tip, check=False).strip() != "commit":
            continue
        is_ancestor = subprocess.run(["git", "-C", repo, "merge-base", "--is-ancestor", tip, base]).returncode == 0
        if not is_ancestor:
            probes.add(tip)
    return sorted(probes)


def leak_check(case: dict, ws: Path) -> list[str]:
    """Problems that would let the agent see work done after the dispatch; empty when the clone is clean."""
    problems = []
    head = git(ws, "rev-parse", "HEAD").strip()
    base = git(case["repo"], "rev-parse", f"{case['base']}^{{commit}}").strip()
    if head != base:
        problems.append(f"HEAD is {head[:12]}, not the dispatch commit {base[:12]}")
    base_ct = int(git(ws, "log", "-1", "--format=%ct", head).strip())
    listed = git(ws, "log", "--all", "--format=%H %ct").split("\n")
    history = set(git(ws, "rev-list", head).split())
    for line in filter(None, listed):
        sha, ct = line.split()
        if int(ct) > base_ct:
            problems.append(f"git log --all lists {sha[:12]}, newer than the dispatch commit")
        if sha not in history:
            problems.append(f"git log --all lists {sha[:12]}, not in the dispatch commit's history")
    refs = git(ws, "for-each-ref", "--format=%(refname)").split()
    if refs != [f"refs/heads/{BRANCH}"]:
        problems.append(f"refs left: {refs}")
    if git(ws, "remote").strip():
        problems.append("a remote is still configured")
    for sha in later_commits(case):
        if subprocess.run(["git", "-C", str(ws), "cat-file", "-e", sha], capture_output=True).returncode == 0:
            problems.append(f"later commit {sha[:12]} is still present")
    return problems


def overlay(repo: str, commit: str, files, ws: Path) -> None:
    """Write each file as it is at `commit` into the workspace; delete files absent there."""
    for rel in files:
        target = ws / rel
        proc = subprocess.run(["git", "-C", repo, "show", f"{commit}:{rel}"], capture_output=True)
        if proc.returncode != 0:
            if target.exists():
                target.unlink()
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(proc.stdout)


def run_setup(case: dict, ws: Path) -> list[CmdResult]:
    """Prepare untracked dependencies the brief's commands expect.

    `clone` copies a directory from the original checkout with APFS clonefile
    (`cp -c`), so the workspace gets its own copy-on-write tree and nothing the
    agent installs can reach the original. `run` executes a shell command in the
    workspace.
    """
    results = []
    for step in case.get("setup", []):
        if "clone" in step:
            rel = step["clone"]
            src = Path(case["repo"]) / rel
            dst = ws / rel
            if not src.exists():
                raise RuntimeError(f"setup source missing: {src}")
            dst.parent.mkdir(parents=True, exist_ok=True)
            res = run_shell(f"cp -c -R {shq(str(src))} {shq(str(dst))}", ws, timeout=900)
        else:
            res = run_shell(step["run"], ws, env=case_env(case, ws), timeout=step.get("timeout", 900))
        if res.code != 0:
            raise RuntimeError(f"setup step failed ({res.cmd}): {res.out[-800:]}")
        results.append(res)
    return results


def shq(s: str) -> str:
    return "'" + s.replace("'", "'\"'\"'") + "'"


def case_env(case: dict, ws: Path) -> dict:
    env = {}
    for k, v in (case.get("env") or {}).items():
        env[k] = v.replace("{ws}", str(ws))
    return env


def prepare_workspace(case: dict, tag: str) -> Path:
    """Base commit, plus the context the main thread had on disk at dispatch time, plus setup."""
    ws = new_workspace_dir(f"{case['id']}-{tag}")
    try:
        make_clone(case["repo"], case["base"], ws)
        if case.get("pre_overlay"):
            overlay(case["repo"], case["oracle_commit"], case["pre_overlay"], ws)
        run_setup(case, ws)
    except Exception:
        remove_workspace(ws)
        raise
    return ws


def dirty_manifest(ws: Path) -> dict[str, str]:
    """Map every path git reports as modified or untracked to a hash of its content."""
    out = subprocess.run(
        ["git", "-C", str(ws), "status", "--porcelain=v1", "-z", "--untracked-files=all"],
        capture_output=True, check=True,
    ).stdout.decode("utf-8", errors="replace")
    manifest = {}
    entries = out.split("\0")
    i = 0
    while i < len(entries):
        entry = entries[i]
        i += 1
        if not entry:
            continue
        status, path = entry[:2], entry[3:]
        if status.startswith("R") or status.startswith("C"):
            i += 1  # the next field is the rename source
        if is_noise(path):
            continue
        full = ws / path
        if full.is_file():
            manifest[path] = hashlib.sha1(full.read_bytes()).hexdigest()
        else:
            manifest[path] = "<deleted>"
    return manifest


def changed_since(ws: Path, before: dict[str, str]) -> list[str]:
    after = dirty_manifest(ws)
    changed = set()
    for path, digest in after.items():
        if before.get(path) != digest:
            changed.add(path)
    for path in before:
        if path not in after:
            changed.add(path)  # reverted to the committed version
    return sorted(changed)


# ---------------------------------------------------------------- prompts

def rewrite_prompt(case: dict, ws: Path, out_dir: Path) -> str:
    """Point every absolute path in the brief at the workspace instead of the original checkout."""
    text = case["prompt"]
    pairs = [(case["repo"].rstrip("/"), str(ws))]
    for src, dst in case.get("rewrites", []):
        pairs.append((src, dst.replace("{ws}", str(ws)).replace("{out}", str(out_dir))))
    pairs.sort(key=lambda p: -len(p[0]))
    for src, dst in pairs:
        text = text.replace(src, dst)
    return text


def materialize_attachments(case: dict, out_dir: Path) -> None:
    """Write input files the brief reads from outside the repository into the run's output dir.

    The originals lived in session scratch directories that do not survive, so
    cases.jsonl carries them (gzip + base64) and `rewrites` points the brief at
    the copies under {out}/inputs/.
    """
    import base64
    import gzip

    for att in case.get("attachments", []):
        target = out_dir / "inputs" / att["name"]
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(gzip.decompress(base64.b64decode(att["gz_b64"])))


def read_answer_files(case: dict, ws: Path, out_dir: Path) -> str:
    parts = []
    for tmpl in case.get("answer_files", []):
        p = Path(tmpl.replace("{ws}", str(ws)).replace("{out}", str(out_dir)))
        if p.is_file():
            parts.append(f"\n\n[{p.name}]\n" + p.read_text(encoding="utf-8", errors="replace"))
    return "".join(parts)


def sha256_files(paths) -> str:
    h = hashlib.sha256()
    for p in paths:
        p = Path(p)
        h.update(p.name.encode())
        h.update(p.read_bytes())
    return h.hexdigest()


def wilson(k: float, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return (0.0, 0.0)
    p = k / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * ((p * (1 - p) / n + z * z / (4 * n * n)) ** 0.5) / denom
    return (max(0.0, centre - half), min(1.0, centre + half))

