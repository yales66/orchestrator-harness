"""launch_tracks.py 的测试：pytest 直接跑；python3 test_launch_tracks.py 也可跑，打印 OK 即全过。
测试里不调用真实的 osascript 或 claude：外部调用全部以假实现注入，等待也不真睡。"""
import subprocess

import launch_tracks


def _fake_run(out):
    calls = []

    def run(script):
        calls.append(script)
        return out
    return run, calls


def _prompt_of(script):
    """script 为 AppleScript：先取格脚本，再取格脚本里 $(cat …) 指向的开工第一句文件。"""
    pane = script.split("source '")[1].split("'")[0]
    cmd = open(pane, encoding="utf-8").read()
    return open(cmd.split("$(cat ")[1].split(")")[0].strip("'"), encoding="utf-8").read()


def test_grid_shape():
    assert launch_tracks.grid(1) == [1]
    assert launch_tracks.grid(2) == [1, 1]
    assert launch_tracks.grid(3) == [2, 1]
    assert launch_tracks.grid(4) == [2, 2]
    assert launch_tracks.grid(6) == [2, 2, 2]


def test_applescript_opens_one_window_and_splits_it():
    panes = [("P1", "/t/P1.sh"), ("P2", "/t/P2.sh"), ("P3", "/t/P3.sh"), ("P4", "/t/P4.sh")]
    s = launch_tracks.applescript("/repo", panes)
    assert s.startswith('tell application "Ghostty"')
    assert s.count("new window") == 1
    assert s.count("direction right") == 1 and s.count("direction down") == 2
    assert 'perform action "equalize_splits"' in s
    for _, f in panes:
        assert f"source '{f}'" in s
    assert "claude" not in s


def test_applescript_escapes_quotes_in_paths():
    s = launch_tracks.applescript('/my "repo"', [("P1", "/t/P1.sh")])
    assert 'initial working directory:"/my \\"repo\\""' in s


def test_applescript_returns_window_then_terminal_ids():
    panes = [("P1", "/t/P1.sh"), ("P2", "/t/P2.sh"), ("P3", "/t/P3.sh")]
    s = launch_tracks.applescript("/r", panes)
    # grid(3) == [2, 1]：行优先填格，P1=t_0_0 P2=t_0_1 P3=t_1_0
    assert s.splitlines()[-1] == "return out"
    assert "set out to (id of w) & linefeed & (id of t_0_0) & linefeed & (id of t_0_1) & linefeed & (id of t_1_0)" in s


def test_applescript_restores_previous_focus_instead_of_activating():
    s = launch_tracks.applescript("/r", [("P1", "/t/P1.sh")])
    lines = s.splitlines()
    assert "activate" not in lines
    assert lines.index("set prevWinId to id of window 1") < next(i for i, l in enumerate(lines) if "new window" in l)
    assert "activate window (window id prevWinId)" in lines and "focus (terminal id prevTermId)" in lines
    assert "tell application id prevApp to activate" in lines
    assert "AXMinimized" not in s


def test_applescript_minimizes_target_window_only_when_asked():
    s = launch_tracks.applescript("/r", [("P1", "/t/P1.sh")], minimize=True)
    assert "if topId is wid and axTitle is wName then" in s
    assert 'set value of attribute "AXMinimized" of window 1 to true' in s
    lines = s.splitlines()
    assert lines.index('set value of attribute "AXMinimized" of window 1 to true') < lines.index("activate window (window id prevWinId)")


def test_pane_script_reads_prompt_from_file():
    sh = launch_tracks.pane_script("/my repo", "/t/P1.txt")
    assert sh == "cd '/my repo' && claude \"$(cat /t/P1.txt)\"\n"


def test_pane_script_sets_session_name_and_permission_mode():
    sh = launch_tracks.pane_script("/r", "/t/P1.txt", name="bench v4-P1", permission_mode="auto")
    assert sh == "cd /r && claude -n 'bench v4-P1' --permission-mode auto \"$(cat /t/P1.txt)\"\n"


def test_pane_script_passes_the_model():
    sh = launch_tracks.pane_script("/r", "/t/P1.txt", name="tw-P1", permission_mode="auto", model="sonnet")
    assert sh == "cd /r && claude -n tw-P1 --permission-mode auto --model sonnet \"$(cat /t/P1.txt)\"\n"


def test_pane_script_command_override_replaces_claude():
    sh = launch_tracks.pane_script("/r", "/t/P1.txt", pane_cmd="sleep 600")
    assert sh == "cd /r && sleep 600\n"


def test_parse_ids_maps_lines_to_tracks_in_order():
    w, terms = launch_tracks.parse_ids("W-1\nA\nB\n", ["P1", "P2"])
    assert w == "W-1" and terms == {"P1": "A", "P2": "B"}
    try:
        launch_tracks.parse_ids("W-1\nA\n", ["P1", "P2"])
    except SystemExit:
        pass
    else:
        raise AssertionError("missing terminal ids should exit")


def test_osascript_timeout_exits_with_reason():
    def call(*a, **kw):
        raise subprocess.TimeoutExpired(cmd="osascript", timeout=60)
    try:
        launch_tracks.osascript("x", call=call)
    except SystemExit as e:
        assert "60 秒" in str(e), str(e)
    else:
        raise AssertionError("timeout should exit")


def test_osascript_failure_carries_stderr_and_code():
    def call(*a, **kw):
        return subprocess.CompletedProcess(a, 1, stdout="", stderr="execution error: boom")
    try:
        launch_tracks.osascript("x", call=call)
    except SystemExit as e:
        assert "退出码 1" in str(e) and "boom" in str(e), str(e)
    else:
        raise AssertionError("failure should exit")


def test_osascript_returns_stdout_on_success():
    def call(*a, **kw):
        return subprocess.CompletedProcess(a, 0, stdout="W\nT\n", stderr="")
    assert launch_tracks.osascript("x", call=call) == "W\nT\n"


def test_launch_sentence_is_written_as_is_and_ids_recorded():
    run, calls = _fake_run("W1\nT-a\nT-b\n")
    r = launch_tracks.launch("/r", [("P1", "读 A"), ("P2", "读 B")], run=run)
    assert r["window"] == "W1" and r["tracks"]["P2"] == {"terminal": "T-b", "window": "W1", "sentence": "读 B"}
    assert len(calls) == 1
    assert _prompt_of(calls[0]) == "读 A"


def test_launch_without_name_prefix_does_not_wait_for_sessions():
    def agents():
        raise AssertionError("no session check without --name-prefix")
    run, _ = _fake_run("W1\nT-a")
    r = launch_tracks.launch("/r", [("M", "合流")], run=run, agents=agents)
    assert r["window"] == "W1"


def test_wait_for_sessions_gives_up_after_45_seconds():
    slept = []
    try:
        launch_tracks.wait_for_sessions(["bench-P1"], agents=lambda: [], sleep=slept.append)
    except SystemExit as e:
        assert "45 秒" in str(e) and "bench-P1" in str(e), str(e)
    else:
        raise AssertionError("missing session should exit")
    assert sum(slept) == 45


def test_wait_for_sessions_succeeds_when_seen_within_window():
    slept = []
    seen = [[], [{"name": "bench-P1", "sessionId": "sid-1"}]]
    calls = iter(seen)
    found = launch_tracks.wait_for_sessions(["bench-P1"], agents=lambda: next(calls), sleep=slept.append)
    assert found == {"bench-P1": "sid-1"}
    assert slept == [3]


def test_launch_with_name_prefix_records_session_id():
    run, calls = _fake_run("W1\nT-a")
    agents = lambda: [{"name": "bench-v4-P1", "sessionId": "sid-9"}]
    r = launch_tracks.launch("/r", [("P1", "读 A")], run=run, name_prefix="bench-v4", permission_mode="auto",
                             agents=agents, sleep=lambda s: None)
    assert r["tracks"]["P1"]["session"] == "bench-v4-P1" and r["tracks"]["P1"]["session_id"] == "sid-9"
    assert "claude -n bench-v4-P1 --permission-mode auto " in _prompt_pane(calls[0])


def _prompt_pane(script):
    src = script.split("source '")[1].split("'")[0]
    return open(src, encoding="utf-8").read()


def test_launch_passes_minimize_to_script():
    run, calls = _fake_run("W1\nT-a")
    launch_tracks.launch("/r", [("P1", "读 A")], run=run, minimize=True)
    assert "AXMinimized" in calls[0]
    run, calls = _fake_run("W1\nT-a")
    launch_tracks.launch("/r", [("P1", "读 A")], run=run)
    assert "AXMinimized" not in calls[0]


def test_main_sentence_dry_run_prints_script_without_launching():
    import io, contextlib
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        launch_tracks.main(["--sentence", "读 /r/HANDOFF.md 继续", "--track", "R1", "--repo", "/r",
                            "--name-prefix", "demo", "--permission-mode", "auto", "--dry-run"])
    text = out.getvalue()
    assert text.startswith("R1: 读 /r/HANDOFF.md 继续")
    assert "new window" in text


def test_main_requires_sentence_and_track():
    for argv, want in [(["--dry-run"], "--sentence"), (["--sentence", "x", "--dry-run"], "--track")]:
        try:
            launch_tracks.main(argv)
        except SystemExit as e:
            assert want in str(e), (want, str(e))
        else:
            raise AssertionError(f"{argv} should exit")


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
    print("OK")
