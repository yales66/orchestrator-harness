"""spawn_tracks.py 的测试：pytest 直接跑；python3 test_spawn_tracks.py 也可跑，打印 OK 即全过。
claude 与 git 以外不调用外部命令；claude 用 FakeClaude 注入，等待不真睡，父会话标记写进临时目录。"""
import contextlib
import io
import json
import os
import subprocess
import tempfile
from unittest import mock

import spawn_tracks

SAMPLE = """# x 启动清单

| 轨道 | 预算 | 开工第一句 |
|---|---|---|
| P1 冻结 | 25万 | 读 A.md |
| P2 双标 | 250000 | 读 "B.md" |

| 轨道 | 预算 | 待拉起的开工第一句 |
|---|---|---|
| G1 评测 | 10万 | 读 G.md |
"""


class FakeClaude:
    """模拟 claude --bg：从 --settings 读出轨道代号，登记一个 agents 条目，并像状态钩子那样写 start 的 status.json。"""

    def __init__(self, write_status=True, fail=(), timeout=(), pids=None):
        self.calls = []
        self.entries = []
        self.write_status = write_status
        self.fail, self.timeout = set(fail), set(timeout)
        self.pids = pids or {}

    def run(self, args, cwd):
        self.calls.append((args, cwd))
        name = args[args.index("--name") + 1]
        settings = json.load(open(args[args.index("--settings") + 1], encoding="utf-8"))
        track = settings["env"]["SHARD_TRACK"]
        if name in self.timeout:
            raise subprocess.TimeoutExpired(cmd=args, timeout=90)
        if name in self.fail:
            return subprocess.CompletedProcess(args, 0, "Workspace not trusted", "")
        bg = f"bg{len(self.calls)}"
        sid = f"sid-{name}"
        self.entries.append({"id": bg, "name": name, "sessionId": sid, "pid": self.pids.get(name)})
        if self.write_status:
            state = settings["env"]["SHARD_STATE"]
            with open(os.path.join(state, f"{track}.status.json"), "w", encoding="utf-8") as f:
                json.dump({"track": track, "session_id": sid, "event": "start", "cwd": cwd}, f)
        return subprocess.CompletedProcess(args, 0, f"backgrounded · {bg} · {name}\n", "")

    def agents(self):
        return list(self.entries)


def _tracks():
    return spawn_tracks.select(spawn_tracks.parse_launch(SAMPLE), [])


def _spawn(fake, state, parents, tracks=None, **kw):
    kw.setdefault("repo", tempfile.mkdtemp())
    return spawn_tracks.spawn(tracks or _tracks(), change_id=kw.pop("change_id", "x"), state=state,
                              parent="demo-8b", parent_session="psid-1", permission_mode="auto",
                              run=fake.run, agents=fake.agents, sleep=lambda s: None, parents_dir=parents, **kw)


def _read(path):
    return json.load(open(path, encoding="utf-8"))


def test_budget_accepts_wan_and_plain_numbers():
    assert [b for *_, b in spawn_tracks.parse_launch(SAMPLE)] == [250000, 250000, 100000]


def test_budget_column_missing_exits():
    bad = SAMPLE.replace("| 预算 |", "| 备注 |", 1)
    try:
        spawn_tracks.parse_launch(bad)
    except SystemExit as e:
        assert "预算" in str(e)
    else:
        raise AssertionError("missing 预算 column should exit")


def test_unparseable_budget_exits():
    try:
        spawn_tracks.parse_launch(SAMPLE.replace("25万", "很多"))
    except SystemExit as e:
        assert "P1" in str(e)
    else:
        raise AssertionError("bad budget should exit")


def test_pending_tracks_only_with_only():
    tracks = spawn_tracks.parse_launch(SAMPLE)
    assert [t for t, *_ in spawn_tracks.select(tracks, [])] == ["P1", "P2"]
    assert spawn_tracks.select(tracks, ["G1"]) == [("G1", "读 G.md", 100000)]


def test_live_same_name_session_refuses_and_launches_nothing():
    fake = FakeClaude(pids={"x-P2": os.getpid()})
    fake.entries.append({"id": "old", "name": "x-P1", "sessionId": "s", "pid": os.getpid()})
    st, parents = tempfile.mkdtemp(), tempfile.mkdtemp()
    try:
        _spawn(fake, st, parents)
    except SystemExit as e:
        assert "x-P1" in str(e)
    else:
        raise AssertionError("live same-name session should refuse")
    assert fake.calls == []


def test_dead_same_name_session_does_not_block():
    fake = FakeClaude()
    fake.entries.append({"id": "old", "name": "x-P1", "sessionId": "s", "pid": 999999})
    st, parents = tempfile.mkdtemp(), tempfile.mkdtemp()
    assert _spawn(fake, st, parents) == 0


def test_settings_file_content_percentages_hooks_and_absolute_paths():
    st = tempfile.mkdtemp()
    s = spawn_tracks.settings_for(st, "P2", 250000)
    assert s["env"]["CONTEXT_WARN_PCT"] == "20.0" and s["env"]["CONTEXT_HARD_PCT"] == "25.0"
    assert s["env"]["SHARD_STATE"] == st and s["env"]["SHARD_TRACK"] == "P2"
    assert spawn_tracks.settings_for(st, "P2", 123456)["env"]["CONTEXT_HARD_PCT"] == "12.3"
    assert set(s["hooks"]) == {"SessionStart", "Stop", "SessionEnd"}
    cmd = s["hooks"]["Stop"][0]["hooks"][0]["command"]
    assert cmd == f"python3 '{spawn_tracks.TRACK_HOOK}'" and os.path.isabs(spawn_tracks.TRACK_HOOK)
    text = json.dumps(s)
    assert "$HOME" not in text and "~" not in text


def test_bg_command_arguments_list():
    args = spawn_tracks.bg_args("x-P1", "auto", "sonnet", "/s/P1.settings.json", "读 A")
    assert args == ["claude", "--bg", "-w", "x-P1", "--name", "x-P1", "--permission-mode", "auto",
                    "--model", "sonnet", "--settings", "/s/P1.settings.json", "读 A\n\n" + spawn_tracks.CONTRACT]
    no_model = spawn_tracks.bg_args("x-P1", "auto", None, "/s/P1.settings.json", "读 A")
    assert "--model" not in no_model


def test_contract_is_appended_after_blank_line_and_names_status_values():
    text = spawn_tracks.bg_args("x-P1", "auto", None, "/s/P1.settings.json", "读 A")[-1]
    assert text.startswith("读 A\n\n收尾约定：")
    for word in ("状态：完成", "状态：待答", "状态：交接"):
        assert word in text


def test_success_records_session_and_parent_marker():
    fake = FakeClaude()
    st, parents, repo = tempfile.mkdtemp(), tempfile.mkdtemp(), tempfile.mkdtemp()
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        rc = _spawn(fake, st, parents, tracks=_tracks()[:1], repo=repo)
    assert rc == 0 and "P1 已拉起 x-P1 (bg1)" in out.getvalue()
    data = _read(os.path.join(st, "tracks.json"))
    assert data["change_id"] == "x" and data["parent_session"] == "psid-1" and data["permission_mode"] == "auto"
    p1 = data["tracks"]["P1"]
    assert p1["bg_id"] == "bg1" and p1["session_id"] == "sid-x-P1" and p1["budget_tokens"] == 250000
    assert p1["settings"] == os.path.join(os.path.abspath(st), "P1.settings.json") and p1["relays"] == []
    assert os.path.exists(p1["settings"])
    assert _read(os.path.join(parents, "psid-1.json"))["state"] == os.path.abspath(st)
    args, cwd = fake.calls[0]
    assert cwd == os.path.abspath(repo) and args[:3] == ["claude", "--bg", "-w"]


def test_failed_bg_id_is_recorded_and_next_track_still_launches():
    fake = FakeClaude(fail={"x-P1"})
    st, parents = tempfile.mkdtemp(), tempfile.mkdtemp()
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        rc = _spawn(fake, st, parents, tracks=_tracks()[:2])
    assert rc == 1
    assert "P1 失败：" in out.getvalue() and "Workspace not trusted" in out.getvalue()
    assert "P2 已拉起 x-P2" in out.getvalue()
    assert set(_read(os.path.join(st, "tracks.json"))["tracks"]) == {"P2"}


def test_bg_timeout_is_a_recorded_failure():
    fake = FakeClaude(timeout={"x-P1"})
    st, parents = tempfile.mkdtemp(), tempfile.mkdtemp()
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        rc = _spawn(fake, st, parents, tracks=_tracks()[:1])
    assert rc == 1 and "超过 90 秒" in out.getvalue()


def test_unverified_start_gives_up_after_60_seconds():
    fake = FakeClaude(write_status=False)
    slept = []
    st, parents = tempfile.mkdtemp(), tempfile.mkdtemp()
    out = io.StringIO()
    kw = dict(repo=tempfile.mkdtemp())
    with contextlib.redirect_stdout(out):
        rc = spawn_tracks.spawn(_tracks()[:1], change_id="x", state=st, parent="n", parent_session="s",
                                permission_mode="auto", run=fake.run, agents=fake.agents, sleep=slept.append,
                                parents_dir=parents, **kw)
    assert rc == 1 and "60 秒内没核对到" in out.getvalue()
    assert sum(slept) == 60


def test_dry_run_writes_nothing_and_runs_nothing():
    fake = FakeClaude()
    base = tempfile.mkdtemp()
    st, parents = os.path.join(base, "st"), os.path.join(base, "parents")
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        assert _spawn(fake, st, parents, dry_run=True) == 0
    assert fake.calls == [] and not os.path.exists(st) and not os.path.exists(parents)
    assert "claude --bg" in out.getvalue()


def _spawned_state(fake=None):
    fake = fake or FakeClaude()
    st, parents = tempfile.mkdtemp(), tempfile.mkdtemp()
    _spawn(fake, st, parents, tracks=_tracks()[:1])
    return fake, st, parents


def test_relay_refuses_while_old_session_alive():
    fake, st, parents = _spawned_state()
    fake.entries[0]["pid"] = os.getpid()
    try:
        spawn_tracks.relay("P1", "接力", st, run=fake.run, agents=fake.agents, sleep=lambda s: None)
    except SystemExit as e:
        assert "claude stop bg1" in str(e)
    else:
        raise AssertionError("live old session should refuse relay")
    assert len(fake.calls) == 1


def test_relay_uses_status_cwd_and_numbers_names_from_one():
    fake, st, parents = _spawned_state()
    wt = "/wt/x-P1"
    status_path = os.path.join(st, "P1.status.json")
    status = _read(status_path)
    status["cwd"] = wt
    json.dump(status, open(status_path, "w", encoding="utf-8"))
    assert spawn_tracks.relay("P1", "接力一", st, run=fake.run, agents=fake.agents, sleep=lambda s: None) == 0
    assert spawn_tracks.relay("P1", "接力二", st, run=fake.run, agents=fake.agents, sleep=lambda s: None) == 0
    relay_calls = fake.calls[1:]
    assert [c[1] for c in relay_calls] == [wt, wt]
    assert all("-w" not in c[0] for c in relay_calls)
    names = [c[0][c[0].index("--name") + 1] for c in relay_calls]
    assert names == ["x-P1R1", "x-P1R2"]
    data = _read(os.path.join(st, "tracks.json"))
    assert [r["name"] for r in data["tracks"]["P1"]["relays"]] == ["x-P1R1", "x-P1R2"]
    assert data["tracks"]["P1"]["session_id"] == "sid-x-P1R2"


def test_relay_dry_run_runs_nothing():
    fake, st, parents = _spawned_state()
    n = len(fake.calls)
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        assert spawn_tracks.relay("P1", "接力", st, dry_run=True, run=fake.run, agents=fake.agents) == 0
    assert len(fake.calls) == n and "x-P1R1" in out.getvalue()


def test_adopt_rewrites_parent_and_markers():
    fake, st, parents = _spawned_state()
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        assert spawn_tracks.adopt(st, "new-name", "new-sid", parents_dir=parents) == 0
    data = _read(os.path.join(st, "tracks.json"))
    assert data["parent"] == "new-name" and data["parent_session"] == "new-sid"
    assert _read(os.path.join(parents, "new-sid.json"))["state"] == os.path.abspath(st)
    assert not os.path.exists(os.path.join(parents, "psid-1.json"))
    assert "父会话改为 new-name" in out.getvalue()
    assert len(fake.calls) == 1


def test_adopt_without_tracks_json_exits():
    try:
        spawn_tracks.adopt(tempfile.mkdtemp(), "n", "s", parents_dir=tempfile.mkdtemp())
    except SystemExit as e:
        assert isinstance(e.code, str) and "tracks.json" in e.code
    else:
        raise AssertionError("missing tracks.json should exit")


def test_main_adopt_without_tracks_json_exits_with_message():
    try:
        spawn_tracks.main(["--adopt", "--state", tempfile.mkdtemp(), "--parent", "n", "--parent-session", "s"],
                          parents_dir=tempfile.mkdtemp())
    except SystemExit as e:
        assert "tracks.json" in str(e.code)
    else:
        raise AssertionError("adopt without tracks.json should exit 1")


def test_parents_dir_default_honors_env_override():
    old = os.environ.get("SHARDING_PARENTS_DIR")
    os.environ["SHARDING_PARENTS_DIR"] = "/tmp/xyz-parents"
    try:
        assert spawn_tracks.default_parents_dir() == "/tmp/xyz-parents"
    finally:
        if old is None:
            del os.environ["SHARDING_PARENTS_DIR"]
        else:
            os.environ["SHARDING_PARENTS_DIR"] = old


def test_run_claude_uses_cwd_devnull_stdin_and_timeout():
    with mock.patch.object(spawn_tracks.subprocess, "run") as run:
        run.return_value = subprocess.CompletedProcess([], 0, "", "")
        spawn_tracks.run_claude(["claude", "--bg"], "/repo")
    kw = run.call_args.kwargs
    assert kw["cwd"] == "/repo" and kw["stdin"] == subprocess.DEVNULL and kw["timeout"] == 90


def test_state_inside_repo_is_added_to_git_exclude():
    repo = os.path.realpath(tempfile.mkdtemp())
    subprocess.run(["git", "init", "-q", repo], check=True)
    fake = FakeClaude()
    st = os.path.join(repo, ".claude", "stages", "x-1")
    _spawn(fake, st, tempfile.mkdtemp(), tracks=_tracks()[:1], repo=repo)
    exclude = open(os.path.join(repo, ".git", "info", "exclude"), encoding="utf-8").read()
    assert exclude.count("/.claude/stages/") == 1


def test_main_requires_spawn_arguments():
    try:
        spawn_tracks.main(["x.md", "--repo", "/r"])
    except SystemExit as e:
        assert "--change-id" in str(e.code) and "--parent-session" in str(e.code)
    else:
        raise AssertionError("missing arguments should exit")


def test_main_dry_run_reads_launch_list_and_writes_nothing():
    base = tempfile.mkdtemp()
    launch = os.path.join(base, "LAUNCH.md")
    with open(launch, "w", encoding="utf-8") as f:
        f.write(SAMPLE)
    fake = FakeClaude()
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        rc = spawn_tracks.main([launch, "--repo", base, "--change-id", "x", "--state", os.path.join(base, "st"),
                                "--parent", "n", "--parent-session", "s", "--permission-mode", "auto",
                                "--only", "P2", "--dry-run"], run=fake.run, agents=fake.agents,
                               parents_dir=os.path.join(base, "parents"))
    assert rc == 0 and fake.calls == [] and not os.path.exists(os.path.join(base, "st"))
    assert "P2" in out.getvalue() and "P1" not in out.getvalue()


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
    print("OK")
