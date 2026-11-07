"""feature-sharding 的轨道拉起：按启动清单把每条轨道拉成一个 claude --bg 后台会话，并核对它真的开工。

用法：
  spawn_tracks.py <LAUNCH.md> --repo R --change-id ID --state DIR --parent NAME --parent-session SID
                  --permission-mode M [--model m] [--only A,B] [--dry-run]
  spawn_tracks.py --relay CODE --sentence S --state DIR [--dry-run]
  spawn_tracks.py --adopt --state DIR --parent NAME --parent-session SID

启动清单的表格：首列是轨道名（首个词为代号），必须有「预算」列，值如 25万、250000（该轨道的 token 预算）。
列名恰为「开工第一句」的表是可拉起的轨道，缺省全部拉起；列名为「待拉起的开工第一句」的表须 --only 点名。
每条轨道写一份设置文件（环境变量与三个状态钩子 track_hook.py），再以 claude --bg 拉起，
拉起后核对 bg 会话出现且 status 文件记到了它的 start；状态与 tracks.json 写在 --state 目录。
--relay 在轨道旧会话已停下后，于同一 worktree 拉起接力会话；--adopt 把状态目录的父会话交给新父会话。
路径一律展开成绝对路径。父会话标记目录可由环境变量 SHARDING_PARENTS_DIR 覆盖（测试用）。
"""
import argparse
import datetime
import json
import os
import re
import shlex
import subprocess
import sys
import tempfile
import time

COLUMN = "开工第一句"
PENDING_COLUMN = "待拉起的开工第一句"
BUDGET_COLUMN = "预算"
CONTRACT = (
    "收尾约定：你是后台会话，用户不在本会话里，不要停下来等用户回答。每次结束回合时，最后一条消息的第一行只写下列之一，"
    "不加粗、不加引号或反引号："
    "状态：完成 <PR 链接或分支名>（交付闸门通过、PR 已开）；状态：待答（有必须由用户或父会话拍板的问题，问题写在这条消息里，"
    "每项写背景、选项影响与推荐，发出前先做完一切不依赖答复的工作）；状态：交接 <交接文件绝对路径>"
    "（水位钩子要求交接时，用 handoff 技能在本 worktree 写好交接后）。父会话会读到这条消息并用消息回复你。"
)
HOOK_EVENTS = ("SessionStart", "Stop", "SessionEnd")
TRACK_HOOK = os.path.join(os.path.dirname(os.path.abspath(__file__)), "track_hook.py")
BG_RE = re.compile(r"backgrounded · (\S+) · ")
CHECK_WAIT = 60
CHECK_POLL = 3
CLAUDE_TIMEOUT = 90


class Failed(Exception):
    """单条轨道拉起或核对失败，原因写进消息，外层记失败后继续下一条。"""


class AgentsError(Exception):
    """claude agents 查询失败：拉起前的同名检查直接报错，等待核对中则当作本轮没查到。"""


def now_iso():
    return datetime.datetime.now().astimezone().isoformat(timespec="seconds")


def default_parents_dir():
    return os.environ.get("SHARDING_PARENTS_DIR") or os.path.expanduser("~/.claude/state/sharding/parents")


# ---------- 启动清单 ----------

def _cells(line):
    return [c.strip() for c in line.strip().strip("|").split("|")]


def parse_budget(text, track):
    """25万 → 250000；250000 → 250000；解析不了报错。"""
    s = text.strip().strip("`").replace(" ", "")
    m = re.fullmatch(r"(\d+(?:\.\d+)?)万", s)
    if m:
        return int(round(float(m.group(1)) * 10000))
    if re.fullmatch(r"\d+", s):
        return int(s)
    raise SystemExit(f"轨道 {track} 的预算「{text.strip()}」解析不了：写 25万 或 250000")


def parse_launch(text):
    """返回 [(轨道名, 开工第一句, 是否待拉起, 预算 token)]，轨道名取首列的第一个词。"""
    tracks, col, bcol, pending = [], None, None, False
    for line in text.splitlines():
        if not line.lstrip().startswith("|"):
            col = None
            continue
        cells = _cells(line)
        if col is None:
            col, pending = -1, False
            if COLUMN in cells:
                col = cells.index(COLUMN)
            elif PENDING_COLUMN in cells:
                col, pending = cells.index(PENDING_COLUMN), True
            if col >= 0:
                if BUDGET_COLUMN not in cells:
                    raise SystemExit("启动清单的表缺「预算」列：每条轨道要写 token 预算，如 25万")
                bcol = cells.index(BUDGET_COLUMN)
            continue
        if col < 0 or set("".join(cells)) <= set("-: "):
            continue
        track = cells[0].split()[0]
        if max(col, bcol) >= len(cells):
            raise SystemExit(f"启动清单里轨道 {track} 的行列数不够")
        tracks.append((track, cells[col].strip("`").strip(), pending, parse_budget(cells[bcol], track)))
    dups = sorted({t for t, *_ in tracks if [x[0] for x in tracks].count(t) > 1})
    if dups:
        raise SystemExit(f"启动清单里轨道名重复：{', '.join(dups)}；首列首个词须是各不相同的轨道代号")
    return tracks


def split_only(value):
    return [o.strip() for o in value.split(",") if o.strip()]


def select(tracks, only):
    """返回 [(轨道名, 开工第一句, 预算)]：不点名时取全部可拉起的轨道，点名时按清单顺序取点到的轨道。"""
    if not only:
        return [(t, s, b) for t, s, pending, b in tracks if not pending]
    known = {t for t, *_ in tracks}
    unknown = [o for o in only if o not in known]
    if unknown:
        raise SystemExit(f"启动清单里没有这些轨道：{', '.join(unknown)}；有的是 {', '.join(t for t, *_ in tracks)}")
    return [(t, s, b) for t, s, _, b in tracks if t in only]


# ---------- 设置文件与命令 ----------

def _sh_single(path):
    return "'" + path.replace("'", "'\\''") + "'"


def settings_path(state, track):
    return os.path.join(state, f"{track}.settings.json")


def settings_for(state, track, budget):
    """百分比按 1M 窗口：预算 250000 → HARD 25.0、WARN 20.0，与 context-watermark-gate.sh 读的变量一致。"""
    hook = f"python3 {_sh_single(TRACK_HOOK)}"
    return {
        "env": {
            "SHARD_STATE": state,
            "SHARD_TRACK": track,
            "CONTEXT_WARN_PCT": f"{budget * 0.8 / 1e4:.1f}",
            "CONTEXT_HARD_PCT": f"{budget / 1e4:.1f}",
        },
        "hooks": {ev: [{"hooks": [{"type": "command", "command": hook, "timeout": 10}]}] for ev in HOOK_EVENTS},
    }


def bg_args(name, permission_mode, model, settings, sentence, worktree=True):
    args = ["claude", "--bg"]
    if worktree:
        args += ["-w", name]
    args += ["--name", name, "--permission-mode", permission_mode]
    if model:
        args += ["--model", model]
    args += ["--settings", settings, sentence + "\n\n" + CONTRACT]
    return args


# ---------- 外部调用（可注入） ----------

def run_claude(args, cwd):
    return subprocess.run(args, cwd=cwd, stdin=subprocess.DEVNULL, capture_output=True, text=True,
                          timeout=CLAUDE_TIMEOUT)


def query_agents():
    try:
        r = subprocess.run(["claude", "agents", "--json", "--all"], stdin=subprocess.DEVNULL,
                           capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired) as e:
        raise AgentsError(f"claude agents 查询失败：{e}")
    if r.returncode != 0:
        raise AgentsError(f"claude agents 退出码 {r.returncode}：{_head(r.stderr)}")
    try:
        return json.loads(r.stdout)
    except ValueError:
        raise AgentsError("claude agents 输出不是 JSON")


def alive(entry):
    pid = entry.get("pid")
    if not isinstance(pid, int) or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        # 进程存在但不属于本用户：kill 报 PermissionError，仍算活着
        return True
    return True


def check_names_free(names, agents):
    live = {a.get("name") for a in agents() if alive(a)}
    clash = sorted(n for n in names if n in live)
    if clash:
        raise SystemExit(f"已有同名活会话：{', '.join(clash)}；先 claude stop 它们，或换 --change-id")


def _head(s):
    return (s or "").strip()[:300]


# ---------- 文件 ----------

def write_json(path, data):
    """先写同目录临时文件再改名，读者看不到写了一半的文件。"""
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), prefix=".tmp-", suffix=".json")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def read_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def load_tracks(state):
    path = os.path.join(state, "tracks.json")
    return read_json(path) if os.path.exists(path) else {"tracks": {}}


def save_tracks(state, data):
    write_json(os.path.join(state, "tracks.json"), data)


def read_status(state, track):
    path = os.path.join(state, f"{track}.status.json")
    if not os.path.exists(path):
        return None
    try:
        return read_json(path)
    except ValueError:
        return None


def write_parent(parents_dir, sid, state):
    os.makedirs(parents_dir, exist_ok=True)
    write_json(os.path.join(parents_dir, f"{sid}.json"), {"state": state, "registered_at": now_iso()})


def ensure_excluded(repo, state):
    """状态目录在 repo 内时，把它的上一级目录加进 repo 的 info/exclude（已有则不重复），返回加入的模式或 None。"""
    rel = os.path.relpath(os.path.abspath(state), repo)
    if rel == "." or rel.startswith(".."):
        return None
    pattern = "/" + (os.path.dirname(rel) or rel) + "/"
    r = subprocess.run(["git", "-C", repo, "rev-parse", "--git-path", "info/exclude"], capture_output=True, text=True)
    if r.returncode != 0:
        return None
    path = os.path.join(repo, r.stdout.strip())
    existing = open(path, encoding="utf-8").read() if os.path.exists(path) else ""
    if pattern in existing.splitlines():
        return None
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(("" if not existing or existing.endswith("\n") else "\n") + pattern + "\n")
    return pattern


# ---------- 拉起与核对 ----------

def start_bg(args, cwd, run):
    try:
        r = run(args, cwd)
    except subprocess.TimeoutExpired:
        raise Failed(f"claude --bg 超过 {CLAUDE_TIMEOUT} 秒未返回")
    except OSError as e:
        raise Failed(f"claude 无法运行：{e}")
    m = BG_RE.search(r.stdout or "")
    if r.returncode != 0 or not m:
        raise Failed(f"claude --bg 未拉起（退出码 {r.returncode}）：stdout {_head(r.stdout)}；stderr {_head(r.stderr)}")
    return m.group(1)


def _started(bg_id, state, track, agents):
    """bg 会话在 agents 里出现，且轨道 status 文件的 start 记录的 session_id 与之相符，返回 sessionId。"""
    try:
        entries = agents()
    except AgentsError:
        return None
    entry = next((a for a in entries if a.get("id") == bg_id and a.get("sessionId")), None)
    st = read_status(state, track) or {}
    if entry and st.get("event") == "start" and st.get("session_id") == entry["sessionId"]:
        return entry["sessionId"]
    return None


def verify(bg_id, state, track, agents, sleep):
    attempts = CHECK_WAIT // CHECK_POLL + 1
    for i in range(attempts):
        sid = _started(bg_id, state, track, agents)
        if sid:
            return sid
        if i < attempts - 1:
            sleep(CHECK_POLL)
    raise Failed(f"{CHECK_WAIT} 秒内没核对到后台会话 {bg_id} 的 start 记录；它可能仍在跑，可 claude stop {bg_id}")


def write_settings(state, track, budget):
    write_json(settings_path(state, track), settings_for(state, track, budget))


# ---------- 三种模式 ----------

def spawn(tracks, *, repo, change_id, state, parent, parent_session, permission_mode, model=None,
          dry_run=False, run=run_claude, agents=query_agents, sleep=time.sleep, parents_dir=None):
    repo, state = os.path.abspath(repo), os.path.abspath(state)
    parents_dir = parents_dir or default_parents_dir()
    names = {t: f"{change_id}-{t}" for t, _, _ in tracks}
    check_names_free(names.values(), agents)
    if dry_run:
        for t, sentence, budget in tracks:
            print(f"{t} 将写设置文件 {settings_path(state, t)}：")
            print(json.dumps(settings_for(state, t, budget), ensure_ascii=False, indent=2))
            print(f"{t} 将执行：{shlex.join(bg_args(names[t], permission_mode, model, settings_path(state, t), sentence))}")
        return 0
    os.makedirs(state, exist_ok=True)
    data = load_tracks(state)
    data.update(change_id=change_id, repo=repo, parent=parent, parent_session=parent_session,
                permission_mode=permission_mode, model=model)
    data.setdefault("tracks", {})
    save_tracks(state, data)
    write_parent(parents_dir, parent_session, state)
    ensure_excluded(repo, state)
    failed = False
    for t, sentence, budget in tracks:
        name, settings = names[t], settings_path(state, t)
        try:
            write_settings(state, t, budget)
            bg = start_bg(bg_args(name, permission_mode, model, settings, sentence), repo, run)
            sid = verify(bg, state, t, agents, sleep)
        except Failed as e:
            print(f"{t} 失败：{e}")
            failed = True
            continue
        data["tracks"][t] = {"name": name, "bg_id": bg, "session_id": sid, "worktree": name,
                             "budget_tokens": budget, "settings": settings, "launched_at": now_iso(), "relays": []}
        save_tracks(state, data)
        print(f"{t} 已拉起 {name} ({bg})")
    return 1 if failed else 0


def relay(code, sentence, state, *, dry_run=False, run=run_claude, agents=query_agents, sleep=time.sleep):
    state = os.path.abspath(state)
    if not os.path.exists(os.path.join(state, "tracks.json")):
        raise SystemExit(f"{state} 里没有 tracks.json：先用启动清单拉起过轨道")
    data = load_tracks(state)
    track = data.get("tracks", {}).get(code)
    if not track:
        raise SystemExit(f"tracks.json 里没有轨道 {code}")
    old = track["relays"][-1]["bg_id"] if track.get("relays") else track["bg_id"]
    if any(a.get("id") == old and alive(a) for a in agents()):
        raise SystemExit(f"先运行 claude stop {old}，等它退出再接力")
    cwd = (read_status(state, code) or {}).get("cwd")
    if not cwd:
        raise SystemExit(f"轨道 {code} 没有带 cwd 的状态记录，取不到 worktree 目录")
    name = f"{data['change_id']}-{code}R{len(track.get('relays', [])) + 1}"
    args = bg_args(name, data["permission_mode"], data.get("model"), track["settings"], sentence, worktree=False)
    if dry_run:
        print(f"{code} 将在 {cwd} 执行：{shlex.join(args)}")
        return 0
    try:
        bg = start_bg(args, cwd, run)
        sid = verify(bg, state, code, agents, sleep)
    except Failed as e:
        print(f"{code} 接力失败：{e}")
        return 1
    track.setdefault("relays", []).append({"name": name, "bg_id": bg, "launched_at": now_iso()})
    track["session_id"] = sid
    save_tracks(state, data)
    print(f"{code} 接力已拉起 {name} ({bg})")
    return 0


def adopt(state, parent, parent_session, parents_dir=None):
    state = os.path.abspath(state)
    parents_dir = parents_dir or default_parents_dir()
    if not os.path.exists(os.path.join(state, "tracks.json")):
        raise SystemExit(f"{state} 里没有 tracks.json，不是拉起过轨道的状态目录")
    data = load_tracks(state)
    old = data.get("parent_session")
    data.update(parent=parent, parent_session=parent_session)
    save_tracks(state, data)
    write_parent(parents_dir, parent_session, state)
    if old and old != parent_session:
        old_marker = os.path.join(parents_dir, f"{old}.json")
        if os.path.exists(old_marker):
            os.remove(old_marker)
    print(f"父会话改为 {parent}")
    return 0


def main(argv=None, run=run_claude, agents=query_agents, sleep=time.sleep, parents_dir=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("launch", nargs="?")
    p.add_argument("--repo", default=None)
    p.add_argument("--change-id", default=None)
    p.add_argument("--state", default=None)
    p.add_argument("--parent", default=None)
    p.add_argument("--parent-session", default=None)
    p.add_argument("--permission-mode", default=None)
    p.add_argument("--model", default=None)
    p.add_argument("--only", default="")
    p.add_argument("--relay", default=None)
    p.add_argument("--sentence", default=None)
    p.add_argument("--adopt", action="store_true")
    p.add_argument("--dry-run", action="store_true")
    a = p.parse_args(argv)
    try:
        if a.adopt:
            if not (a.state and a.parent and a.parent_session):
                raise SystemExit("--adopt 须同给 --state、--parent、--parent-session")
            return adopt(a.state, a.parent, a.parent_session, parents_dir)
        if a.relay:
            if not (a.sentence and a.state):
                raise SystemExit("--relay 须同给 --sentence 与 --state")
            return relay(a.relay, a.sentence, a.state, dry_run=a.dry_run, run=run, agents=agents, sleep=sleep)
        required = {"启动清单路径": a.launch, "--repo": a.repo, "--change-id": a.change_id, "--state": a.state,
                    "--parent": a.parent, "--parent-session": a.parent_session, "--permission-mode": a.permission_mode}
        missing = [k for k, v in required.items() if not v]
        if missing:
            raise SystemExit(f"拉起须给：{', '.join(missing)}")
        with open(a.launch, encoding="utf-8") as f:
            tracks = select(parse_launch(f.read()), split_only(a.only))
        if not tracks:
            raise SystemExit("启动清单里没有可拉起的轨道：列名为「开工第一句」的表格是空的，待拉起的轨道要用 --only 点名")
        return spawn(tracks, repo=a.repo, change_id=a.change_id, state=a.state, parent=a.parent,
                     parent_session=a.parent_session, permission_mode=a.permission_mode, model=a.model,
                     dry_run=a.dry_run, run=run, agents=agents, sleep=sleep, parents_dir=parents_dir)
    except AgentsError as e:
        raise SystemExit(str(e))


if __name__ == "__main__":
    sys.exit(main())
