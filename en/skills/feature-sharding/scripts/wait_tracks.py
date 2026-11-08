"""等待后台轨道会话的状态变化：父会话在后台跑它，有轨道停下、卡住或状态有变就输出并退出，后台命令结束即唤醒父会话。

用法：
  python3 wait_tracks.py <state> [--interval 30] [--settle 20] [--max-hours 12] [--once]
<state> 为状态目录的绝对路径（内含 tracks.json、各轨道 *.status.json；游标 .wait-cursor.json 也在其中）。
--once 只输出一次当前全部轨道的状况，不等待、不改游标。
claude agents 查询失败时：单次失败沿用上一轮结果、不算变化；连续 MAX_FAIL 轮失败才当作会话缺失并输出。
"""
import argparse
import json
import os
import subprocess
import sys
import tempfile
import time

CURSOR = ".wait-cursor.json"
STATUSES = ("完成", "待答", "交接")
SUMMARY_BUCKETS = ("在跑", "卡住", "完成", "待答", "交接", "停下未声明", "进程不在")
MSG_LIMIT = 400
MAX_FAIL = 3
NOTE_LIMIT = 200


class AgentsQueryError(RuntimeError):
    """claude agents 查询失败：命令报错、超时或输出不是合法 JSON 数组。"""


def write_json(path, data):
    """先写同目录临时文件再改名，读者看不到写了一半的文件。"""
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), prefix=".tmp-", suffix=".json")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def read_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def load_optional(path):
    """文件缺失或损坏返回 None。"""
    try:
        return read_json(path)
    except (OSError, ValueError):
        return None


def query_agents():
    """返回 {bg_id: 会话记录}；查询失败抛 AgentsQueryError，由等待循环计数。"""
    try:
        r = subprocess.run(["claude", "agents", "--json", "--all"], capture_output=True,
                           text=True, timeout=60, stdin=subprocess.DEVNULL)
    except (OSError, subprocess.SubprocessError) as e:
        raise AgentsQueryError(str(e)) from e
    if r.returncode != 0:
        raise AgentsQueryError(f"退出码 {r.returncode}：{(r.stderr or '').strip()}")
    try:
        data = json.loads(r.stdout)
    except ValueError as e:
        raise AgentsQueryError(f"JSON 解析失败：{e}") from e
    if not isinstance(data, list):
        raise AgentsQueryError("输出不是 JSON 数组")
    return {a["id"]: a for a in data if isinstance(a, dict) and "id" in a}


def pid_alive(pid):
    # 无权限发信号说明进程存在，算活着
    if not isinstance(pid, int) or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def current(track):
    """返回 (会话名, bg_id)：最后一个 relay，否则轨道本身。"""
    relays = track.get("relays") or []
    last = relays[-1] if relays else track
    return last.get("name"), last.get("bg_id")


def agents_from_cursor(doc, cursor):
    """连首次查询都失败时，用游标里记的状态当作上一轮的 agents 结果。
    游标不记进程是否活着：working、blocked 视为活着，其余视为不在。"""
    if not cursor:
        return {}
    out = {}
    for name, track in (doc.get("tracks") or {}).items():
        entry = cursor.get(name)
        st = entry.get("state") if isinstance(entry, dict) else None
        if not st or st == "missing":
            continue
        _, bg = current(track)
        if bg:
            out[bg] = {"id": bg, "state": st, "pid": None,
                       "assumed_alive": st in ("working", "blocked")}
    return out


def observe(state, doc, agents, alive):
    rows = []
    for name, track in (doc.get("tracks") or {}).items():
        sess_name, bg_id = current(track)
        entry = agents.get(bg_id) if bg_id else None
        is_alive = bool(entry) and (bool(entry.get("assumed_alive")) or alive(entry.get("pid")))
        status_doc = load_optional(os.path.join(state, f"{name}.status.json"))
        if isinstance(status_doc, dict):
            status = status_doc.get("status", "未声明")
            at = status_doc.get("at")
            ctx = status_doc.get("context_tokens")
            msg = status_doc.get("last_message")
        else:
            status, at, ctx, msg = None, None, None, None
        rows.append({
            "track": name,
            "name": sess_name,
            "state": entry.get("state") if entry else "missing",
            "alive": is_alive,
            "status": status,
            "at": at,
            "context_tokens": ctx,
            "last_message": msg if isinstance(msg, str) else "",
        })
    return rows


def is_running(row):
    return row["alive"] and row["state"] == "working"


def bucket(row):
    # blocked 是会话在等输入：回合以提问结束时也报 blocked（2.1.304 实测），首行声明了待答就按待答；
    # 否则多半停在权限确认上，自己不会往前走，单列为卡住
    # 没人回复约 1 小时后 supervisor 会停掉进程，agents 仍报 blocked、只是没有 pid：还是在等，不是进程不在
    if row["state"] == "blocked":
        return "待答" if row["status"] == "待答" else "卡住"
    if is_running(row):
        return "在跑"
    if row["status"] in STATUSES:
        return row["status"]
    if not row["alive"]:
        return "进程不在"
    return "停下未声明"


def summary(rows):
    counts = {b: 0 for b in SUMMARY_BUCKETS}
    for r in rows:
        counts[bucket(r)] += 1
    return "｜".join(f"{b} {counts[b]}" for b in SUMMARY_BUCKETS)


def detail(row):
    ctx = row["context_tokens"]
    ctx_s = f"{ctx // 1000}k" if isinstance(ctx, int) else "-"
    msg = " ".join(row["last_message"].splitlines()).strip()[:MSG_LIMIT]
    return (f"[{bucket(row)}] {row['track']} {row['name'] or '-'} state={row['state']} "
            f"status={row['status'] or '-'} ctx={ctx_s}｜{msg}")


def fingerprint(row):
    return {"state": row["state"], "at": row["at"]}


def fingerprints(rows):
    return {r["track"]: fingerprint(r) for r in rows}


def changed_rows(rows, baseline):
    # 变回在跑（如父会话答复后轨道接着干）不用父会话处理，不算
    return [r for r in rows if fingerprint(r) != baseline.get(r["track"]) and bucket(r) != "在跑"]


def load_cursor(state):
    data = load_optional(os.path.join(state, CURSOR))
    return data if isinstance(data, dict) else None


def save_cursor(state, rows):
    write_json(os.path.join(state, CURSOR), fingerprints(rows))


def provisional(fails):
    """本轮查询失败但还没满 MAX_FAIL 次：沿用上一轮结果，不算变化，不下结论。"""
    return 0 < fails < MAX_FAIL


def wait(state, *, interval=30, settle=20, max_hours=12, once=False,
         query=query_agents, alive=pid_alive, sleep=time.sleep, clock=time.monotonic,
         out=lambda s: print(s, flush=True)):
    tracks_path = os.path.join(state, "tracks.json")
    doc = load_optional(tracks_path)
    if not isinstance(doc, dict):
        raise SystemExit(f"读不到 {tracks_path}；先运行 spawn_tracks.py")
    cursor = load_cursor(state)

    last_ok = None   # 上一次查询成功的 agents 结果
    fails = 0        # 连续失败轮数
    last_err = ""

    def look():
        nonlocal doc, last_ok, fails, last_err
        fresh = load_optional(tracks_path)
        if isinstance(fresh, dict):
            doc = fresh
        try:
            agents = query() or {}
        except Exception as e:
            fails += 1
            last_err = str(e)
            if fails >= MAX_FAIL:
                agents = {}
            elif last_ok is not None:
                agents = last_ok
            else:
                agents = agents_from_cursor(doc, cursor)
        else:
            last_ok, fails = agents, 0
        return observe(state, doc, agents, alive), fails

    def note():
        return f"claude agents 查询连续失败：{last_err[:NOTE_LIMIT]}"

    def finish(rows, changed, n_fail):
        out(summary(rows))
        if n_fail >= MAX_FAIL:
            out(note())
        for r in changed:
            out(detail(r))
        save_cursor(state, rows)
        return 0

    rows, fails = look()
    if once:
        out(summary(rows))
        for r in rows:
            out(detail(r))
        return 0

    start = clock()
    baseline = cursor
    started = False
    while True:
        if not provisional(fails):
            if not started:
                started = True
                if baseline is not None:
                    changed = changed_rows(rows, baseline)
                    if changed or not any(is_running(r) for r in rows):
                        return finish(rows, changed, fails)
                elif not any(is_running(r) for r in rows):
                    return finish(rows, rows, fails)
                baseline = fingerprints(rows)
            elif changed_rows(rows, baseline):
                # 变化出现后等 settle 秒，合并同时发生的变化
                sleep(settle)
                rows, fails = look()
                if not provisional(fails):
                    changed = changed_rows(rows, baseline)
                    if changed:
                        return finish(rows, changed, fails)
        if clock() - start >= max_hours * 3600:
            out(f"等待超时（超过 {max_hours:g} 小时），当前状况：")
            out(summary(rows))
            if fails >= MAX_FAIL:
                out(note())
            for r in rows:
                out(detail(r))
            save_cursor(state, rows)
            return 0
        sleep(interval)
        rows, fails = look()


def main(argv=None):
    p = argparse.ArgumentParser(description="等待后台轨道会话的状态变化")
    p.add_argument("state", help="状态目录的绝对路径")
    p.add_argument("--interval", type=float, default=30, help="轮询间隔（秒）")
    p.add_argument("--settle", type=float, default=20, help="发现变化后再等多久以合并同时发生的变化（秒）")
    p.add_argument("--max-hours", type=float, default=12, help="最长等待（小时）")
    p.add_argument("--once", action="store_true", help="只输出一次当前状况，不等待，不改游标")
    a = p.parse_args(argv)
    return wait(os.path.abspath(a.state), interval=a.interval, settle=a.settle,
                max_hours=a.max_hours, once=a.once)


if __name__ == "__main__":
    sys.exit(main())
