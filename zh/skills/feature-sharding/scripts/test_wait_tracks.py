"""wait_tracks.py 的测试：PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 -m pytest -q -p no:cacheprovider test_wait_tracks.py

不真调用 claude，不真睡：查询、sleep、时钟、进程是否活着都注入假实现。
"""
import json
import os
import types

import pytest

import wait_tracks

INTERVAL, SETTLE = 30, 20
AT0 = "2026-10-20T10:00:00+08:00"


def write(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)


def read(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def make_state(tmp_path, tracks):
    state = str(tmp_path)
    write(os.path.join(state, "tracks.json"), {"change_id": "x", "tracks": tracks})
    return state


def track(name, bg, relays=None):
    return {"name": f"x-{name}", "bg_id": bg, "session_id": "s", "worktree": f"x-{name}",
            "relays": relays or []}


def set_status(state, name, *, event="stop", at=AT0, status="完成", ctx=123456, msg="done"):
    write(os.path.join(state, f"{name}.status.json"),
          {"track": name, "session_id": "s", "event": event, "at": at, "status": status,
           "context_tokens": ctx, "last_message": msg, "ended": False})


def agent(bg, state, pid=100):
    return {"id": bg, "pid": pid, "state": state, "name": bg}


class Harness:
    """假世界：agents 表由 hook 在每次 sleep 时改写；时钟随 sleep 前进。"""

    def __init__(self, state, agents, hook=None, fail_on=()):
        self.state = state
        self.agents = agents
        self.hook = hook
        self.fail_on = set(fail_on)  # 第几次查询（从 1 起）失败
        self.calls = 0
        self.now = 0.0
        self.sleeps = []
        self.lines = []

    def query(self):
        self.calls += 1
        if self.calls in self.fail_on:
            raise wait_tracks.AgentsQueryError("boom")
        return {k: dict(v) for k, v in self.agents.items()}

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.now += seconds
        if self.hook:
            self.hook(self, seconds)

    def clock(self):
        return self.now

    def wait(self, **kw):
        opts = dict(interval=INTERVAL, settle=SETTLE, max_hours=12, once=False)
        opts.update(kw)
        return wait_tracks.wait(self.state, query=self.query, alive=lambda pid: bool(pid),
                                sleep=self.sleep, clock=self.clock, out=self.lines.append, **opts)


def cursor_path(state):
    return os.path.join(state, ".wait-cursor.json")


def test_no_cursor_with_running_track_waits_then_exits_after_settle(tmp_path):
    state = make_state(tmp_path, {"P1": track("P1", "bg1"), "P2": track("P2", "bg2")})
    agents = {"bg1": agent("bg1", "working"), "bg2": agent("bg2", "working")}

    def hook(h, seconds):
        # 第二次轮询前 P1 完成；P2 始终在跑，不应出现在详情里
        if h.sleeps == [INTERVAL, INTERVAL]:
            h.agents["bg1"]["state"] = "done"
            set_status(state, "P1", msg="完成了")

    h = Harness(state, agents, hook)
    assert h.wait() == 0
    assert h.sleeps == [INTERVAL, INTERVAL, SETTLE]
    assert h.lines[0] == "在跑 1｜卡住 0｜完成 1｜待答 0｜交接 0｜停下未声明 0｜进程不在 0"
    assert h.lines[1:] == ["[完成] P1 x-P1 state=done status=完成 ctx=123k｜完成了"]
    assert read(cursor_path(state)) == {
        "P1": {"state": "done", "at": AT0},
        "P2": {"state": "working", "at": None},
    }


def test_change_during_settle_is_reported_together(tmp_path):
    state = make_state(tmp_path, {"P1": track("P1", "bg1"), "P2": track("P2", "bg2")})
    agents = {"bg1": agent("bg1", "working"), "bg2": agent("bg2", "working")}

    def hook(h, seconds):
        if h.sleeps == [INTERVAL, INTERVAL]:
            h.agents["bg1"]["state"] = "done"
            set_status(state, "P1", msg="P1 完")
        if seconds == SETTLE:
            h.agents["bg2"]["state"] = "done"
            set_status(state, "P2", status="待答", msg="P2 要问")

    h = Harness(state, agents, hook)
    assert h.wait() == 0
    assert h.sleeps == [INTERVAL, INTERVAL, SETTLE]
    assert h.lines[0] == "在跑 0｜卡住 0｜完成 1｜待答 1｜交接 0｜停下未声明 0｜进程不在 0"
    assert h.lines[1].startswith("[完成] P1 x-P1 state=done status=完成")
    assert h.lines[2].startswith("[待答] P2 x-P2 state=done status=待答")


def test_working_to_blocked_triggers_exit(tmp_path):
    state = make_state(tmp_path, {"P1": track("P1", "bg1"), "P2": track("P2", "bg2")})
    agents = {"bg1": agent("bg1", "working"), "bg2": agent("bg2", "working")}

    def hook(h, seconds):
        # 卡在权限确认：不会自己往前走，须唤醒父会话
        if h.sleeps == [INTERVAL]:
            h.agents["bg1"]["state"] = "blocked"

    h = Harness(state, agents, hook)
    assert h.wait() == 0
    assert h.sleeps == [INTERVAL, SETTLE]
    assert h.lines[0] == "在跑 1｜卡住 1｜完成 0｜待答 0｜交接 0｜停下未声明 0｜进程不在 0"
    assert h.lines[1].startswith("[卡住] P1 x-P1 state=blocked status=-")


def test_change_since_cursor_exits_at_once(tmp_path):
    state = make_state(tmp_path, {"P1": track("P1", "bg1")})
    set_status(state, "P1", msg="状态：完成 x")
    write(cursor_path(state), {"P1": {"state": "working", "at": "之前的时间"}})
    h = Harness(state, {"bg1": agent("bg1", "done"), "bg2": agent("bg2", "working")})
    assert h.wait() == 0
    assert h.sleeps == []
    assert h.lines[1] == "[完成] P1 x-P1 state=done status=完成 ctx=123k｜状态：完成 x"
    assert read(cursor_path(state))["P1"] == {"state": "done", "at": AT0}


def test_no_running_track_exits_immediately_with_all_details(tmp_path):
    state = make_state(tmp_path, {"P1": track("P1", "bg1")})
    set_status(state, "P1")
    h = Harness(state, {"bg1": agent("bg1", "done")})
    assert h.wait() == 0
    assert h.sleeps == []
    assert h.lines == [
        "在跑 0｜卡住 0｜完成 1｜待答 0｜交接 0｜停下未声明 0｜进程不在 0",
        "[完成] P1 x-P1 state=done status=完成 ctx=123k｜done",
    ]


def test_blocked_only_exits_immediately(tmp_path):
    state = make_state(tmp_path, {"P1": track("P1", "bg1")})
    h = Harness(state, {"bg1": agent("bg1", "blocked")})
    assert h.wait() == 0
    assert h.sleeps == []
    assert h.lines[0] == "在跑 0｜卡住 1｜完成 0｜待答 0｜交接 0｜停下未声明 0｜进程不在 0"


def test_timeout_outputs_marker_and_current_table(tmp_path):
    state = make_state(tmp_path, {"P1": track("P1", "bg1")})
    h = Harness(state, {"bg1": agent("bg1", "working")})
    # 0.01 小时 = 36 秒：第二次轮询（60 秒）时超时
    assert h.wait(max_hours=0.01) == 0
    assert h.sleeps == [INTERVAL, INTERVAL]
    assert "等待超时" in h.lines[0]
    assert h.lines[1] == "在跑 1｜卡住 0｜完成 0｜待答 0｜交接 0｜停下未声明 0｜进程不在 0"
    assert h.lines[2].startswith("[在跑] P1 x-P1 state=working status=-")
    assert os.path.exists(cursor_path(state))


def test_relay_uses_last_relay_bg_id(tmp_path):
    relays = [{"name": "x-P1R1", "bg_id": "r0"}, {"name": "x-P1R2", "bg_id": "r1"}]
    state = make_state(tmp_path, {"P1": track("P1", "old", relays=relays)})
    set_status(state, "P1", event="start", status="未声明", msg="接力")
    agents = {"old": agent("old", "done"), "r0": agent("r0", "done"), "r1": agent("r1", "working")}
    h = Harness(state, agents)
    assert h.wait(once=True) == 0
    assert h.lines[0] == "在跑 1｜卡住 0｜完成 0｜待答 0｜交接 0｜停下未声明 0｜进程不在 0"
    assert h.lines[1] == "[在跑] P1 x-P1R2 state=working status=未声明 ctx=123k｜接力"


def test_query_failure_is_treated_as_missing(tmp_path):
    state = make_state(tmp_path, {"P1": track("P1", "bg1")})

    def boom():
        raise OSError("claude 不存在")

    h = Harness(state, {})
    lines = []
    code = wait_tracks.wait(state, interval=INTERVAL, settle=SETTLE, max_hours=12, once=True,
                            query=boom, alive=lambda pid: bool(pid), sleep=h.sleep,
                            clock=h.clock, out=lines.append)
    assert code == 0
    assert lines == [
        "在跑 0｜卡住 0｜完成 0｜待答 0｜交接 0｜停下未声明 0｜进程不在 1",
        "[进程不在] P1 x-P1 state=missing status=- ctx=-｜",
    ]


def test_query_agents_failures_raise(monkeypatch):
    def not_found(*a, **k):
        raise FileNotFoundError("claude")

    monkeypatch.setattr(wait_tracks.subprocess, "run", not_found)
    with pytest.raises(wait_tracks.AgentsQueryError):
        wait_tracks.query_agents()

    def bad_json(*a, **k):
        return types.SimpleNamespace(returncode=0, stdout="不是 JSON", stderr="")

    monkeypatch.setattr(wait_tracks.subprocess, "run", bad_json)
    with pytest.raises(wait_tracks.AgentsQueryError):
        wait_tracks.query_agents()

    def bad_exit(*a, **k):
        return types.SimpleNamespace(returncode=2, stdout="[]", stderr="no")

    monkeypatch.setattr(wait_tracks.subprocess, "run", bad_exit)
    with pytest.raises(wait_tracks.AgentsQueryError):
        wait_tracks.query_agents()


def test_once_prints_everything_and_leaves_cursor_alone(tmp_path):
    state = make_state(tmp_path, {"P1": track("P1", "bg1"), "P2": track("P2", "bg2")})
    set_status(state, "P1")
    set_status(state, "P2")
    agents = {"bg1": agent("bg1", "working"), "bg2": agent("bg2", "done")}

    # 有游标时 --once 不改它
    write(cursor_path(state), {"P1": {"state": "idle", "at": "旧"}})
    h = Harness(state, agents)
    assert h.wait(once=True) == 0
    assert h.sleeps == []
    assert len(h.lines) == 3
    assert read(cursor_path(state)) == {"P1": {"state": "idle", "at": "旧"}}

    # 没有游标时 --once 也不创建
    os.remove(cursor_path(state))
    h = Harness(state, agents)
    h.wait(once=True)
    assert not os.path.exists(cursor_path(state))


def test_summary_counts_each_bucket(tmp_path):
    names = ["A", "B", "C", "D", "E", "F", "G"]
    state = make_state(tmp_path, {n: track(n, f"bg{n}") for n in names})
    set_status(state, "B", status="完成")
    set_status(state, "C", status="待答")
    set_status(state, "D", status="交接")
    # E 无状态文件；F 不在 agents 里；A 在跑，G 卡住
    agents = {
        "bgA": agent("bgA", "working"),
        "bgB": agent("bgB", "done"),
        "bgC": agent("bgC", "done"),
        "bgD": agent("bgD", "done"),
        "bgE": agent("bgE", "stopped"),
        "bgG": agent("bgG", "blocked"),
    }
    h = Harness(state, agents)
    h.wait(once=True)
    assert h.lines[0] == "在跑 1｜卡住 1｜完成 1｜待答 1｜交接 1｜停下未声明 1｜进程不在 1"
    assert len(h.lines) == 8


def test_detail_flattens_newlines_and_truncates_message(tmp_path):
    state = make_state(tmp_path, {"P1": track("P1", "bg1")})
    msg = "第一行\n状态：完成 https://x\n" + "甲" * 500
    set_status(state, "P1", msg=msg)
    h = Harness(state, {"bg1": agent("bg1", "done")})
    h.wait(once=True)
    line = h.lines[1]
    assert "\n" not in line
    tail = line.split("｜", 1)[1]
    assert len(tail) == 400
    assert tail.startswith("第一行 状态：完成 https://x 甲")


def test_single_query_failure_does_not_exit(tmp_path):
    # 第 2 次查询失败：沿用上一轮结果，不算变化；之后真正的变化才退出
    state = make_state(tmp_path, {"P1": track("P1", "bg1")})
    set_status(state, "P1", event="start", status="未声明", msg="")
    write(cursor_path(state), {"P1": {"state": "working", "at": AT0}})

    def hook(h, seconds):
        if len(h.sleeps) == 3:
            h.agents["bg1"]["state"] = "done"
            set_status(state, "P1", status="完成", msg="好")

    h = Harness(state, {"bg1": agent("bg1", "working")}, hook, fail_on={2})
    assert h.wait() == 0
    assert h.sleeps == [INTERVAL, INTERVAL, INTERVAL, SETTLE]
    assert not any(line.startswith("claude agents 查询连续失败") for line in h.lines)
    assert h.lines[-1].startswith("[完成] P1 x-P1 state=done status=完成")


def test_three_consecutive_failures_exit_with_note(tmp_path):
    state = make_state(tmp_path, {"P1": track("P1", "bg1")})
    set_status(state, "P1", event="start", status="未声明", msg="")
    write(cursor_path(state), {"P1": {"state": "working", "at": AT0}})
    h = Harness(state, {"bg1": agent("bg1", "working")}, fail_on={1, 2, 3})
    assert h.wait() == 0
    assert h.sleeps == [INTERVAL, INTERVAL]
    assert h.lines == [
        "在跑 0｜卡住 0｜完成 0｜待答 0｜交接 0｜停下未声明 0｜进程不在 1",
        "claude agents 查询连续失败：boom",
        "[进程不在] P1 x-P1 state=missing status=未声明 ctx=123k｜",
    ]


def test_recovery_after_two_failures_does_not_false_alarm(tmp_path):
    state = make_state(tmp_path, {"P1": track("P1", "bg1")})
    set_status(state, "P1", event="start", status="未声明", msg="")
    write(cursor_path(state), {"P1": {"state": "working", "at": AT0}})

    def hook(h, seconds):
        if len(h.sleeps) == 4:
            h.agents["bg1"]["state"] = "done"
            set_status(state, "P1", status="完成", msg="恢复后完成")

    h = Harness(state, {"bg1": agent("bg1", "working")}, hook, fail_on={1, 2})
    assert h.wait() == 0
    assert h.sleeps == [INTERVAL, INTERVAL, INTERVAL, INTERVAL, SETTLE]
    assert not any(line.startswith("claude agents 查询连续失败") for line in h.lines)
    assert h.lines[-1] == "[完成] P1 x-P1 state=done status=完成 ctx=123k｜恢复后完成"


def test_first_round_failure_without_cursor_waits_for_next_round(tmp_path):
    state = make_state(tmp_path, {"P1": track("P1", "bg1")})
    set_status(state, "P1")
    h = Harness(state, {"bg1": agent("bg1", "done")}, fail_on={1})
    assert h.wait() == 0
    assert h.sleeps == [INTERVAL]
    assert not any(line.startswith("claude agents 查询连续失败") for line in h.lines)
    assert h.lines == [
        "在跑 0｜卡住 0｜完成 1｜待答 0｜交接 0｜停下未声明 0｜进程不在 0",
        "[完成] P1 x-P1 state=done status=完成 ctx=123k｜done",
    ]


def test_blocked_after_declaring_question_counts_as_waiting_for_answer(tmp_path):
    # 实测 2.1.304：回合以提问结束时 claude agents 报 blocked，这是等答复，不是卡在权限确认上
    state = make_state(tmp_path, {"P1": track("P1", "bg1")})
    set_status(state, "P1", status="待答", msg="状态：待答 选 A 还是 B？")
    h = Harness(state, {"bg1": agent("bg1", "blocked")})
    assert h.wait() == 0
    assert h.lines[0] == "在跑 0｜卡住 0｜完成 0｜待答 1｜交接 0｜停下未声明 0｜进程不在 0"


def test_track_resuming_work_after_answer_does_not_wake_parent(tmp_path):
    # 父会话回复待答的轨道后，它从 blocked 回到 working：这不是要父会话处理的事
    state = make_state(tmp_path, {"P1": track("P1", "bg1")})
    set_status(state, "P1", status="待答", msg="状态：待答 选 A 还是 B？")
    write(cursor_path(state), {"P1": {"state": "blocked", "at": AT0}})

    def hook(h, seconds):
        if h.sleeps == [INTERVAL, INTERVAL]:
            h.agents["bg1"]["state"] = "done"
            set_status(state, "P1", msg="状态：完成 drill")

    h = Harness(state, {"bg1": agent("bg1", "working")}, hook)
    assert h.wait() == 0
    assert h.sleeps[:2] == [INTERVAL, INTERVAL]
    assert h.lines[0] == "在跑 0｜卡住 0｜完成 1｜待答 0｜交接 0｜停下未声明 0｜进程不在 0"


def test_blocked_without_pid_is_still_waiting_not_gone(tmp_path):
    # 实测：后台会话提问后约 1 小时没人回，supervisor 停掉进程，agents 仍报 blocked 但没有 pid
    state = make_state(tmp_path, {"P1": track("P1", "bg1"), "P2": track("P2", "bg2")})
    set_status(state, "P1", status="待答", msg="状态：待答 选 A 还是 B？")
    set_status(state, "P2", status="未声明", msg="要批准这条命令吗")
    gone1, gone2 = agent("bg1", "blocked"), agent("bg2", "blocked")
    gone1.pop("pid"); gone2.pop("pid")
    h = Harness(state, {"bg1": gone1, "bg2": gone2})
    assert h.wait() == 0
    assert h.lines[0] == "在跑 0｜卡住 1｜完成 0｜待答 1｜交接 0｜停下未声明 0｜进程不在 0"
