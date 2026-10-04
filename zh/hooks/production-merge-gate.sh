#!/bin/bash
# PreToolUse(Bash) hook: 仓库 git config 里 claude.production=true 时，`gh pr merge` 要用户当场同意。
# 标记放在 git config 而不是仓库文件：不进任何会话的上下文，且同一仓库的所有工作树共用。
# 仓库目录取钩子输入的 cwd，命令里先 `cd <目录>` 的取该目录；`-R/--repo`、`GH_REPO=` 或 PR 网址
# 指向的不是该目录所在仓库、无法确认生产与否时按生产处理。
python3 -c '
import json, os, re, shlex, subprocess, sys

try:
    data = json.load(sys.stdin)
except Exception:
    sys.exit(0)
cmd = data.get("tool_input", {}).get("command", "") or ""
cwd = data.get("cwd") or "."

PR_URL = re.compile(r"^https?://[^/]+/([^/]+/[^/]+)/pull/\d+")

def merge_repo_args(toks):
    """toks 是 gh pr merge 时返回 (True, 指向的仓库列表)，否则 (False, [])。"""
    for i in range(len(toks) - 2):
        if toks[i] == "gh" and toks[i + 1] == "pr" and toks[i + 2] == "merge":
            repos = [t.split("=", 1)[1] for t in toks[:i] if t.startswith("GH_REPO=")]
            rest = toks[i + 3:]
            for j, t in enumerate(rest):
                if t in ("-R", "--repo") and j + 1 < len(rest):
                    repos.append(rest[j + 1])
                elif t.startswith("--repo="):
                    repos.append(t.split("=", 1)[1])
                elif t.startswith("-R") and len(t) > 2:
                    repos.append(t[2:])
                elif PR_URL.match(t):
                    repos.append(PR_URL.match(t).group(1))
            return True, repos
    return False, []

def git(d, *args):
    try:
        r = subprocess.run(["git", "-C", d, *args], capture_output=True, text=True, timeout=5)
    except Exception:
        return None
    return r.stdout.strip() if r.returncode == 0 else None

def slug(s):
    """owner/name 小写形式；认 OWNER/REPO、HOST/OWNER/REPO、https 与 ssh 地址。"""
    s = re.sub(r"\.git$", "", s.strip().rstrip("/"))
    parts = [p for p in re.split(r"[/:]", s) if p]
    return "/".join(parts[-2:]).lower() if len(parts) >= 2 else None

def repo_slugs(d):
    out = git(d, "remote") or ""
    slugs = set()
    for name in out.split():
        url = git(d, "remote", "get-url", name)
        if url and slug(url):
            slugs.add(slug(url))
    return slugs

def toks_of(part):
    try:
        return shlex.split(part)
    except ValueError:
        return part.split()

flat = cmd.replace("$(", " ").replace("`", " ").replace(")", " ")
here, hits = cwd, []
for part in re.split(r"(?:&&|\|\||[;&|\n])", flat):
    toks = toks_of(part)
    if len(toks) >= 2 and toks[0] == "cd":
        here = os.path.join(here, os.path.expanduser(toks[1]))
        continue
    is_merge, repos = merge_repo_args(toks)
    if is_merge:
        hits.append((here, repos))
if not hits:
    sys.exit(0)

production = False
for d, repos in hits:
    if (git(d, "config", "--get", "claude.production") or "").lower() == "true":
        production = True
    mine = repo_slugs(d) if repos else set()
    for repo in repos:
        if slug(repo) is None or slug(repo) not in mine:
            production = True   # 指向别的仓库，无法确认其生产标记

if production:
    print(json.dumps({"hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "permissionDecision": "ask",
        "permissionDecisionReason": "该仓库为生产模式，合并需用户当场同意 / Production repository: merging needs the user\x27s approval"
    }}, ensure_ascii=False))
sys.exit(0)
' 2>/dev/null
exit 0
