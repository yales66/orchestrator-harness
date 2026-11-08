"""在当前运行的 Ghostty 里开一个新窗口，按轨道数切成网格分屏，每格运行 claude 并带上开工第一句。

只拉起一条会话（--sentence 与 --track 同给）：交互接力会话由 handoff 技能第 4 步用它拉起。
分屏经 Ghostty 的 AppleScript 在已运行的实例里创建，新终端继承 Ghostty 自己的环境，不带调用方会话的环境变量。
开工第一句先写进临时文件，格内由 $(cat 文件) 读入，句子里的引号与中文不经过 shell 转义。
--name-prefix 给了时会话以 claude -n <前缀>-<代号> 起名，拉起后最多等 45 秒核对该名字的会话出现。
--model、--permission-mode 原样传给 claude。
--minimize 再把拉起的窗口最小化：只在它位于层叠最上层、且辅助功能里的标题与它对得上时才动手，免得误收用户的窗口。

用法：
  python3 launch_tracks.py --sentence "<开工第一句>" --track <代号> [--repo <仓库目录>] [--name-prefix <前缀>]
                           [--permission-mode <模式>] [--model <模型>] [--minimize] [--dry-run]
--repo 缺省为当前目录；路径一律展开成绝对路径。--dry-run 只打印要执行的 AppleScript。
--pane-cmd 只供实测：用给定命令替换格内的 claude。
"""
import argparse
import json
import math
import os
import shlex
import subprocess
import sys
import tempfile
import time

OSASCRIPT_TIMEOUT = 60
SESSION_WAIT = 45
SESSION_POLL = 3

FOCUS_SAVE = [
    'tell application "Ghostty"',
    'set prevWinId to ""',
    'set prevTermId to ""',
    "if (count of windows) > 0 then",
    "set prevWinId to id of window 1",
    "set prevTermId to id of focused terminal of selected tab of window 1",
    "end if",
    "end tell",
    'tell application "System Events" to set prevApp to bundle identifier of first process whose frontmost is true',
]
# Ghostty 的 front window 在本应用不在前台时会指向别的窗口，层叠顺序取 window 1；新窗口要过片刻才排到最上层，故轮询。
MINIMIZE = [
    "set seenTop to false",
    "repeat 30 times",
    'tell application "Ghostty"',
    "set topId to id of window 1",
    "set wName to name of window id wid",
    "end tell",
    'tell application "System Events" to tell process "Ghostty" to set axTitle to title of window 1',
    "if topId is wid and axTitle is wName then",
    "set seenTop to true",
    'tell application "System Events" to tell process "Ghostty"',
    "try",
    'set value of attribute "AXMinimized" of window 1 to true',
    "end try",
    "end tell",
    "else if seenTop then",
    "exit repeat",
    "end if",
    "delay 0.1",
    "end repeat",
]
FOCUS_RESTORE = [
    "try",
    'if prevApp is "com.mitchellh.ghostty" then',
    'if prevWinId is not "" then',
    'tell application "Ghostty"',
    "activate window (window id prevWinId)",
    "focus (terminal id prevTermId)",
    "end tell",
    "end if",
    "else",
    "tell application id prevApp to activate",
    "end if",
    "end try",
]


def grid(n):
    """返回每列的格数，列数取 n 的平方根向上取整，多出的格从左边的列补起。"""
    cols = math.ceil(math.sqrt(n))
    base, extra = divmod(n, cols)
    return [base + (1 if c < extra else 0) for c in range(cols)]


def pane_script(repo, prompt_file, pane_cmd=None, name=None, permission_mode=None, model=None):
    """开头显式 cd：用户的 zsh 登录配置会把目录切走，Ghostty 的 initial working directory 拦不住。"""
    if pane_cmd:
        cmd = pane_cmd
    else:
        opts = ((f"-n {shlex.quote(name)} " if name else "")
                + (f"--permission-mode {shlex.quote(permission_mode)} " if permission_mode else "")
                + (f"--model {shlex.quote(model)} " if model else ""))
        cmd = f'claude {opts}"$(cat {shlex.quote(prompt_file)})"'
    return f"cd {shlex.quote(repo)} && {cmd}\n"


def session_name(prefix, track):
    return f"{prefix}-{track}" if prefix else None


def _as(text):
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _sh_single(path):
    return "'" + path.replace("'", "'\\''") + "'"


def _cfg(repo, pane_file):
    return f"{{initial working directory:{_as(repo)}, initial input:{_as('source ' + _sh_single(pane_file))} & return}}"


def _wrap(body, minimize):
    """body 为 tell Ghostty 块内的语句，须设好变量 w 与各终端变量；脚本返回 out：首行窗口 id，其后各终端 id。"""
    lines = FOCUS_SAVE + ['tell application "Ghostty"'] + body + ["set wid to id of w", "end tell"]
    return "\n".join(lines + (MINIMIZE if minimize else []) + FOCUS_RESTORE + ["return out"])


def applescript(repo, panes, minimize=False):
    """panes 为 [(轨道名, 该格要 source 的脚本路径)]，按行优先依次填进网格。
    脚本返回多行文本：首行窗口 id，其后按 panes 顺序每行一个终端 id。"""
    rows = grid(len(panes))
    cells = [(r, c) for r in range(max(rows)) for c in range(len(rows)) if r < rows[c]]
    pane_of = {cell: panes[i][1] for i, cell in enumerate(cells)}

    def cfg(cell):
        return _cfg(repo, pane_of[cell])

    body = [f"set w to new window with configuration {cfg((0, 0))}", "set t_0_0 to focused terminal of selected tab of w"]
    for c in range(1, len(rows)):
        body.append(f"set t_0_{c} to split t_0_{c - 1} direction right with configuration {cfg((0, c))}")
    for c, n in enumerate(rows):
        for r in range(1, n):
            body.append(f"set t_{r}_{c} to split t_{r - 1}_{c} direction down with configuration {cfg((r, c))}")
    body.append('perform action "equalize_splits" on t_0_0')
    body.append("set out to (id of w)" + "".join(f" & linefeed & (id of t_{r}_{c})" for r, c in cells))
    return _wrap(body, minimize)


def parse_ids(output, names):
    """osascript 输出 → (窗口 id, {轨道: 终端 id})。"""
    ids = [x.strip() for x in output.strip().splitlines() if x.strip()]
    if len(ids) != len(names) + 1:
        raise SystemExit(f"Ghostty 返回的 id 数目不对：要 1 个窗口加 {len(names)} 个终端，得到 {ids}")
    return ids[0], dict(zip(names, ids[1:]))


def osascript(script, call=subprocess.run):
    """call 可注入，测试时传假实现；失败与超时都以带原因的 SystemExit 结束。"""
    try:
        r = call(["osascript", "-"], input=script, text=True, capture_output=True, timeout=OSASCRIPT_TIMEOUT)
    except subprocess.TimeoutExpired:
        raise SystemExit(f"osascript 超过 {OSASCRIPT_TIMEOUT} 秒没有返回，Ghostty 分屏未完成")
    if r.returncode != 0:
        raise SystemExit(f"osascript 失败（退出码 {r.returncode}）：{r.stderr.strip()}")
    return r.stdout


def list_agents():
    """claude agents --json 的会话列表；查不到时返回空列表，由等待逻辑继续轮询。"""
    try:
        r = subprocess.run(["claude", "agents", "--json"], stdin=subprocess.DEVNULL, capture_output=True,
                           text=True, timeout=30)
        return json.loads(r.stdout) if r.returncode == 0 else []
    except (OSError, subprocess.TimeoutExpired, ValueError):
        return []


def wait_for_sessions(names, agents=list_agents, sleep=time.sleep):
    """最多等 SESSION_WAIT 秒，每 SESSION_POLL 秒查一次，直到 names 都出现；返回 {名字: sessionId}。"""
    found = {}
    attempts = SESSION_WAIT // SESSION_POLL + 1
    for i in range(attempts):
        for a in agents():
            if a.get("name") in names and a.get("name") not in found:
                found[a["name"]] = a.get("sessionId")
        if len(found) == len(names):
            return found
        if i < attempts - 1:
            sleep(SESSION_POLL)
    missing = next(n for n in names if n not in found)
    raise SystemExit(f"拉起后 {SESSION_WAIT} 秒内没看到会话 {missing}")


def prepare(repo, tracks, pane_cmd=None, name_prefix=None, permission_mode=None, model=None):
    """把开工第一句与格脚本写进临时目录，返回 [(轨道名, 格脚本路径)]。"""
    out = tempfile.mkdtemp(prefix="launch-tracks-")
    panes = []
    for track, sentence in tracks:
        prompt_file = os.path.join(out, f"{track}.txt")
        with open(prompt_file, "w", encoding="utf-8") as f:
            f.write(sentence)
        pane_file = os.path.join(out, f"{track}.sh")
        with open(pane_file, "w", encoding="utf-8") as f:
            f.write(pane_script(repo, prompt_file, pane_cmd, session_name(name_prefix, track), permission_mode, model))
        panes.append((track, pane_file))
    return panes


def launch(repo, tracks, pane_cmd=None, run=osascript, name_prefix=None, permission_mode=None, minimize=False,
           model=None, agents=list_agents, sleep=time.sleep):
    """在新 Ghostty 窗口里按网格拉起 tracks（[(轨道名, 开工第一句)]）。
    返回 {"window": 窗口 id, "tracks": {轨道: {"terminal", "window", "sentence"[, "session", "session_id"]}}}；
    给了 name_prefix 时等这些会话出现（最多 45 秒），拿到 sessionId 记入结果。"""
    repo = os.path.abspath(repo)
    panes = prepare(repo, tracks, pane_cmd, name_prefix, permission_mode, model)
    window, terms = parse_ids(run(applescript(repo, panes, minimize)), [t for t, _ in tracks])
    info = {t: {"terminal": terms[t], "window": window, "sentence": s} for t, s in tracks}
    if name_prefix:
        names = {t: session_name(name_prefix, t) for t in info}
        found = wait_for_sessions(list(names.values()), agents, sleep)
        for t, name in names.items():
            info[t]["session"] = name
            info[t]["session_id"] = found[name]
    return {"window": window, "tracks": info}


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--sentence", default=None)
    p.add_argument("--track", default=None)
    p.add_argument("--repo", default=os.getcwd())
    p.add_argument("--name-prefix", default=None)
    p.add_argument("--permission-mode", default=None)
    p.add_argument("--model", default=None)
    p.add_argument("--minimize", action="store_true")
    p.add_argument("--pane-cmd", default=None, help=argparse.SUPPRESS)
    p.add_argument("--dry-run", action="store_true")
    a = p.parse_args(argv)
    if not a.sentence:
        raise SystemExit("须给 --sentence 与 --track：开工第一句与代号缺一不可")
    if not a.track:
        raise SystemExit("--sentence 须同给 --track，代号用于会话名")
    tracks = [(a.track, a.sentence)]
    repo = os.path.abspath(a.repo)
    print(f"{a.track}: {a.sentence[:60]}…")
    if a.dry_run:
        panes = prepare(repo, tracks, a.pane_cmd, a.name_prefix, a.permission_mode, a.model)
        print(applescript(repo, panes, a.minimize))
        return
    r = launch(repo, tracks, pane_cmd=a.pane_cmd, name_prefix=a.name_prefix, permission_mode=a.permission_mode,
               minimize=a.minimize, model=a.model)
    print(f"窗口 {r['window']}")
    for t, v in r["tracks"].items():
        if "session" in v:
            print(f"{t} 会话名 {v['session']} sessionId {v['session_id']}")


if __name__ == "__main__":
    sys.exit(main())
