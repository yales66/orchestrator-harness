"""track_hook.py 的测试：pytest 直接跑；python3 test_track_hook.py 也可跑，打印 OK 即全过。"""
import json
import os
import subprocess
import sys
import tempfile

import track_hook

HERE = os.path.dirname(os.path.abspath(__file__))
NOW = "2026-10-20T10:00:00+11:00"


def _state():
    return tempfile.mkdtemp()


def _env(state, track="P1"):
    return {"SHARD_STATE": state, "SHARD_TRACK": track}


def _transcript(lines):
    d = tempfile.mkdtemp()
    path = os.path.join(d, "t.jsonl")
    with open(path, "w", encoding="utf-8") as f:
        for o in lines:
            f.write(json.dumps(o, ensure_ascii=False) + "\n")
    return path


def _usage(inp=0, read=0, create=0):
    return {"input_tokens": inp, "cache_read_input_tokens": read, "cache_creation_input_tokens": create}


def _assistant(text, mid="m1", usage=None, sidechain=False):
    msg = {"id": mid, "role": "assistant", "content": [{"type": "text", "text": text}]}
    if usage is not None:
        msg["usage"] = usage
    return {"type": "assistant", "uuid": "u-" + mid, "isSidechain": sidechain, "message": msg}


def _payload(event, transcript=None, **kw):
    p = {"hook_event_name": event, "session_id": "sid-1", "cwd": "/wt/P1"}
    if transcript:
        p["transcript_path"] = transcript
    p.update(kw)
    return p


def _status(state, track="P1"):
    return json.load(open(os.path.join(state, f"{track}.status.json"), encoding="utf-8"))


def _events(state):
    return [json.loads(l) for l in open(os.path.join(state, "events.jsonl"), encoding="utf-8")]


def test_no_shard_env_writes_nothing():
    state = _state()
    track_hook.handle(_payload("Stop"), {})
    track_hook.handle(_payload("Stop"), {"SHARD_STATE": state})
    track_hook.handle(_payload("Stop"), {"SHARD_TRACK": "P1"})
    assert os.listdir(state) == []


def test_agent_id_writes_nothing():
    state = _state()
    track_hook.handle(_payload("Stop", agent_id="a-1"), _env(state), now=lambda: NOW)
    assert os.listdir(state) == []


def test_start_stop_end_events_update_status_and_append_events():
    state = _state()
    t = _transcript([_assistant("状态：完成 feat/x", usage=_usage(100, 50, 10))])
    track_hook.handle(_payload("SessionStart", t), _env(state), now=lambda: NOW)
    s = _status(state)
    assert s["event"] == "start" and s["status"] == "未声明" and s["ended"] is False
    assert s["session_id"] == "sid-1" and s["cwd"] == "/wt/P1" and s["transcript_path"] == t
    track_hook.handle(_payload("Stop", t), _env(state), now=lambda: NOW)
    assert _status(state)["event"] == "stop" and _status(state)["status"] == "完成"
    track_hook.handle(_payload("SessionEnd", t), _env(state), now=lambda: NOW)
    s = _status(state)
    assert s["event"] == "end" and s["ended"] is True
    assert [e["event"] for e in _events(state)] == ["start", "stop", "end"]
    assert _events(state)[0] == {"track": "P1", "event": "start", "at": NOW, "status": "未声明", "session_id": "sid-1"}


def test_status_is_timestamped_with_timezone():
    import datetime
    state = _state()
    track_hook.handle(_payload("Stop"), _env(state))
    at = datetime.datetime.fromisoformat(_status(state)["at"])
    assert at.tzinfo is not None


def test_context_tokens_uses_last_main_thread_usage_like_watermark_gate():
    state = _state()
    t = _transcript([
        _assistant("一", mid="m1", usage=_usage(100, 50, 10)),
        _assistant("二", mid="m2", usage=_usage(9999, 9999, 9999), sidechain=True),
        _assistant("三", mid="m3", usage=_usage(200, 300, 0)),
        _assistant("四", mid="m4", usage=_usage(0, 0, 0)),
    ])
    track_hook.handle(_payload("Stop", t), _env(state), now=lambda: NOW)
    assert _status(state)["context_tokens"] == 500


def test_status_line_parsing_only_first_nonempty_line_counts():
    cases = [
        ("状态：完成 feat/x\n细节", "完成"),
        ("状态:待答", "待答"),
        ("\n\n状态：交接 /abs/HANDOFF.md", "交接"),
        ("前言\n状态：待答", "未声明"),
        ("状态：进行中", "未声明"),
        ("没有状态行", "未声明"),
    ]
    for text, want in cases:
        state = _state()
        t = _transcript([_assistant(text)])
        track_hook.handle(_payload("Stop", t), _env(state), now=lambda: NOW)
        assert _status(state)["status"] == want, (text, _status(state)["status"])


def test_status_line_keeps_first_line_text():
    state = _state()
    t = _transcript([_assistant("\n状态：待答\n问题一")])
    track_hook.handle(_payload("Stop", t), _env(state), now=lambda: NOW)
    assert _status(state)["status_line"] == "状态：待答"


def test_last_message_truncated_to_1500_chars():
    state = _state()
    t = _transcript([_assistant("字" * 2000)])
    track_hook.handle(_payload("Stop", t), _env(state), now=lambda: NOW)
    assert len(_status(state)["last_message"]) == 1500


def test_last_message_is_last_main_thread_message_with_all_text_blocks():
    state = _state()
    first = {"type": "assistant", "uuid": "u1", "isSidechain": False,
             "message": {"id": "m1", "role": "assistant", "content": [{"type": "text", "text": "第一块"}]}}
    second = {"type": "assistant", "uuid": "u2", "isSidechain": False,
              "message": {"id": "m1", "role": "assistant", "content": [{"type": "text", "text": "第二块"}]}}
    side = _assistant("子代理的话", mid="m9", sidechain=True)
    t = _transcript([first, second, side])
    track_hook.handle(_payload("Stop", t), _env(state), now=lambda: NOW)
    assert _status(state)["last_message"] == "第一块\n第二块"


def test_events_jsonl_appends_across_events():
    state = _state()
    track_hook.handle(_payload("SessionStart"), _env(state), now=lambda: NOW)
    track_hook.handle(_payload("Stop"), _env(state), now=lambda: NOW)
    with open(os.path.join(state, "events.jsonl"), encoding="utf-8") as f:
        assert len(f.read().splitlines()) == 2


def test_missing_or_garbage_transcript_is_tolerated():
    state = _state()
    track_hook.handle(_payload("Stop", "/no/such/file.jsonl"), _env(state), now=lambda: NOW)
    assert _status(state)["context_tokens"] == 0 and _status(state)["last_message"] == ""
    bad = tempfile.mkdtemp()
    path = os.path.join(bad, "t.jsonl")
    with open(path, "w", encoding="utf-8") as f:
        f.write("not json\n[1,2]\n" + json.dumps(_assistant("好", usage=_usage(7))) + "\n")
    track_hook.handle(_payload("Stop", path), _env(state), now=lambda: NOW)
    assert _status(state)["context_tokens"] == 7 and _status(state)["last_message"] == "好"


def test_bad_input_exits_zero_and_prints_nothing():
    state = _state()
    script = os.path.join(HERE, "track_hook.py")
    env = dict(os.environ, SHARD_STATE=state, SHARD_TRACK="P1")
    for stdin in ["not json", "[]", ""]:
        r = subprocess.run([sys.executable, script], input=stdin, capture_output=True, text=True, env=env)
        assert r.returncode == 0 and r.stdout == "", (stdin, r.stdout, r.stderr)
    assert os.listdir(state) == []


def test_valid_payload_through_subprocess_writes_and_stays_silent():
    state = _state()
    script = os.path.join(HERE, "track_hook.py")
    env = dict(os.environ, SHARD_STATE=state, SHARD_TRACK="P1")
    r = subprocess.run([sys.executable, script], input=json.dumps(_payload("Stop")), capture_output=True,
                       text=True, env=env)
    assert r.returncode == 0 and r.stdout == ""
    assert _status(state)["event"] == "stop"


def test_stop_prefers_last_assistant_message_from_payload():
    # Stop 钩子跑时本轮最后一条 assistant 行可能还没落盘，transcript 里读到的是上一条
    state = _state()
    t = _transcript([_assistant("状态：待答 旧问题", usage=_usage(100))])
    track_hook.handle(_payload("Stop", t, last_assistant_message="状态：完成 feat/x\n细节"), _env(state),
                      now=lambda: NOW, sleep=lambda s: None)
    s = _status(state)
    assert s["status"] == "完成" and s["last_message"].startswith("状态：完成 feat/x")


def test_stop_without_payload_message_waits_before_reading_transcript():
    state = _state()
    path = _transcript([_assistant("状态：待答 旧", mid="m1")])
    def late_flush(seconds):
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(_assistant("状态：完成 新", mid="m2"), ensure_ascii=False) + "\n")
    track_hook.handle(_payload("Stop", path), _env(state), now=lambda: NOW, sleep=late_flush)
    assert _status(state)["status"] == "完成"


def test_status_line_tolerates_markdown_emphasis():
    state = _state()
    for text, want in (("**状态：完成 feat/x**", "完成"), ("`状态：待答`", "待答"), ("*状态:交接 /a/H.md*", "交接")):
        t = _transcript([_assistant(text)])
        track_hook.handle(_payload("Stop", t), _env(state), now=lambda: NOW, sleep=lambda s: None)
        assert _status(state)["status"] == want, text


def _stop(state, text, session="sid-1"):
    t = _transcript([_assistant(text, usage=_usage(100))])
    track_hook.handle(_payload("Stop", t, session_id=session), _env(state), now=lambda: NOW, sleep=lambda s: None)


def test_keepalive_reply_keeps_the_declared_status_of_the_same_session():
    # 保活钩子在轨道交接后要它只回「完」或句点；这一轮不能盖掉上一轮声明的交接，否则父会话一直当它在跑
    for reply in ("完", ".", "。", " 完 \n"):
        state = _state()
        _stop(state, "状态：交接 /a/HANDOFF.md\n细节")
        _stop(state, reply)
        s = _status(state)
        assert s["status"] == "交接" and s["status_line"] == "状态：交接 /a/HANDOFF.md", repr(reply)
        assert _events(state)[-1]["status"] == "交接", repr(reply)


def test_keepalive_reply_from_a_new_session_is_undeclared():
    state = _state()
    _stop(state, "状态：完成 feat/x", session="sid-old")
    _stop(state, "完", session="sid-new")
    assert _status(state)["status"] == "未声明"


def test_other_short_replies_still_overwrite_the_status():
    state = _state()
    _stop(state, "状态：交接 /a/HANDOFF.md")
    _stop(state, "好的")
    assert _status(state)["status"] == "未声明"


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
    print("OK")
