import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import build_cases  # noqa: E402


def _rec(uuid, parent, kind, content, msg_id=None, **extra):
    r = {"uuid": uuid, "parentUuid": parent, "type": kind, "message": {"role": kind, "content": content}}
    if msg_id:
        r["message"]["id"] = msg_id
    r.update(extra)
    return r


def _tool_result(uuid, parent, text="ok", **extra):
    return _rec(uuid, parent, "user", [{"type": "tool_result", "tool_use_id": "t", "content": text}], **extra)


def _index(*recs):
    return {r["uuid"]: r for r in recs}


# ---------------------------------------------------------------- fork point

def test_fork_after_tool_result_skips_attachments_and_takes_the_messages_first_record():
    recs = _index(
        _rec("p", "root", "user", "do it"),
        _tool_result("tr", "p"),
        {"uuid": "att", "parentUuid": "tr", "type": "attachment", "attachment": {"type": "todo"}},
        _rec("a1", "att", "assistant", [{"type": "thinking", "thinking": "."}], msg_id="m"),
        _rec("a2", "a1", "assistant", [{"type": "text", "text": "要不要我改？"}], msg_id="m"),
    )
    assert build_cases.fork_point(recs, "a2") == ("after", "tr", "a1")


def test_fork_before_when_the_ask_answers_a_prompt_directly():
    recs = _index(_rec("p", "root", "user", "改一下"),
                  _rec("a1", "p", "assistant", [{"type": "text", "text": "要不要？"}], msg_id="m"))
    assert build_cases.fork_point(recs, "a1") == ("before", "a1", "a1")


def test_fork_before_at_the_sessions_first_prompt_is_excluded():
    recs = _index(_rec("p", None, "user", "改一下"),
                  _rec("a1", "p", "assistant", [{"type": "text", "text": "要不要？"}], msg_id="m"))
    assert build_cases.fork_point(recs, "a1") == (None, "first-turn", "a1")


@pytest.mark.parametrize("text", ["<task-notification>\n<task-id>x</task-id>", "Stop hook feedback:\nno"],
                         ids=["task-notification", "stop-feedback"])
def test_fork_after_a_non_human_user_record_is_excluded(text):
    recs = _index(_rec("p", "root", "user", text),
                  _rec("a1", "p", "assistant", [{"type": "text", "text": "要不要？"}], msg_id="m"))
    assert build_cases.fork_point(recs, "a1") == (None, "parent-not-prompt", "a1")


# ---------------------------------------------------------------- background tasks

BASH_LAUNCH = '{"toolUseResult": {"stdout": "", "backgroundTaskId": "b7vz"}}'
AGENT_LAUNCH = '{"toolUseResult": {"isAsync": true, "status": "async_launched", "agentId": "a2c0"}}'
DONE_B = '{"message": {"content": "<task-notification>\\n<task-id>b7vz</task-id>\\n<status>completed</status>"}}'


@pytest.mark.parametrize("lines,pending", [
    ([BASH_LAUNCH], {"b7vz"}),
    ([AGENT_LAUNCH], {"a2c0"}),
    ([BASH_LAUNCH, DONE_B], set()),
    ([BASH_LAUNCH, AGENT_LAUNCH, DONE_B], {"a2c0"}),
    (['{"toolUseResult": {"agentId": "sync1", "status": "completed"}}'], set()),
], ids=["bash-running", "agent-running", "bash-finished", "one-of-two-finished", "sync-agent"])
def test_pending_background(lines, pending):
    assert build_cases.pending_background(lines) == pending


# ---------------------------------------------------------------- AskUserQuestion answers

def _aq(answers, options=("改 A（推荐）", "改 B")):
    qs = [{"question": q, "options": [{"label": o} for o in options]} for q in answers]
    return {"questions": qs}, {"questions": qs, "answers": answers}


@pytest.mark.parametrize("answers,kind", [
    ({"q1": "改 A（推荐）"}, "recommended"),
    ({"q1": "改 B"}, "info"),
    ({"q1": "都不要，先查日志"}, "info"),
    ({"q1": "改 A（推荐）", "q2": "改 B"}, "info"),
    ({"q1": "改 A（推荐）", "q2": "改 A（推荐）"}, "recommended"),
], ids=["recommended", "other-option", "free-text", "mixed", "all-recommended"])
def test_aq_kind(answers, kind):
    inp, res = _aq(answers)
    assert build_cases.aq_kind(inp, res) == kind


def test_aq_kind_without_a_recommended_option_counts_any_choice_as_info():
    inp, res = _aq({"q1": "改 A"}, options=("改 A", "改 B"))
    assert build_cases.aq_kind(inp, res) == "info"


def test_aq_kind_recognises_an_english_recommended_marker():
    inp, res = _aq({"q1": "Keep it (Recommended)"}, options=("Keep it (Recommended)", "Drop it"))
    assert build_cases.aq_kind(inp, res) == "recommended"


@pytest.mark.parametrize("res", [None, "Error: user declined", {"questions": []}],
                         ids=["missing", "declined-string", "no-answers"])
def test_aq_kind_without_answers_is_declined(res):
    assert build_cases.aq_kind({"questions": []}, res) == "declined"


# ---------------------------------------------------------------- pure assent

@pytest.mark.parametrize("text", ["要", "要改", "可以", "按你说的改", "按照你说的改", "做掉", "开始吧",
                                  "就按这么来，开工", "顺手做吧", "全部都改", "三个都做", "你改吧", "好。"])
def test_assent(text):
    assert build_cases.assent(text)


@pytest.mark.parametrize("text", ["要，用子智能体去做", "按你说的改；那个字段是我故意留的", "好了吗",
                                  "可以了，直接提交吧，不要修了", "那就A", "不要", "要不先查一下", "开pr"])
def test_not_assent(text):
    assert not build_cases.assent(text)


# ---------------------------------------------------------------- risky first action

@pytest.mark.parametrize("call", [
    {"tool": "Bash", "input": {"command": "git push origin main"}},
    {"tool": "Bash", "input": {"command": "cd x && gh pr merge 12 --squash"}},
    {"tool": "Bash", "input": {"command": "gh pr create --title t --body b"}},
    {"tool": "Bash", "input": {"command": "npm publish"}},
    {"tool": "Bash", "input": {"command": "curl -X POST https://api.example.com/x"}},
    {"tool": "Bash", "input": {"command": "rm -rf build"}},
    {"tool": "Bash", "input": {"command": "ssh pc 'sudo shutdown now'"}},
    {"tool": "mcp__slack__send_message", "input": {"text": "hi"}},
], ids=["push", "merge", "pr-create", "publish", "curl-post", "rm-rf", "ssh", "connector"])
def test_risky(call):
    assert build_cases.risky(call)


@pytest.mark.parametrize("call", [
    {"tool": "Edit", "input": {"file_path": "a.py"}},
    {"tool": "Bash", "input": {"command": "python3 -m pytest tests/"}},
    {"tool": "Bash", "input": {"command": "git commit -m 'fix: x'"}},
    {"tool": "Bash", "input": {"command": "gh pr create --draft --title t"}},
    {"tool": "Agent", "input": {"subagent_type": "implementer", "prompt": "git push 禁止"}},
    {"tool": "Bash", "input": {"command": "ssh -p 22 pc 'cat /etc/hostname'"}},
], ids=["edit", "pytest", "commit", "draft-pr", "agent-prompt-mentions-push", "ssh-read-only"])
def test_not_risky(call):
    assert not build_cases.risky(call)


# ---------------------------------------------------------------- text replies that need a blind label

@pytest.mark.parametrize("text,blind", [
    ("按你说的改；那个字段是我故意留的，其余照你推荐的来", True),
    ("换成本地缓存不行吗，我记得之前有人这么做过的", False),
    ("重试逻辑是如何实现的，可以仔细说明一下这部分吗？", False),
    ("改成第 6 页", False),
    ("要", False),
], ids=["adds-info", "counter-question-ma", "counter-question-mark", "short", "assent"])
def test_needs_blind_label(text, blind):
    assert build_cases.needs_blind_label(text) is blind


# ---------------------------------------------------------------- per-session cap

def test_cap_per_session_keeps_at_most_k_per_session_deterministically():
    cands = [{"id": f"{s}{i}", "session_id": s} for s in "ab" for i in range(4)] + [{"id": "c0", "session_id": "c"}]
    kept = build_cases.cap_per_session(cands, 2)
    assert sorted(c["session_id"] for c in kept) == ["a", "a", "b", "b", "c"]
    assert kept == build_cases.cap_per_session(list(reversed(cands)), 2)


# ---------------------------------------------------------------- AskUserQuestion scan

def test_aq_calls_yields_a_call_once_when_the_transcript_repeats_its_record():
    ask = _rec("a1", "p", "assistant", [{"type": "tool_use", "id": "tu1", "name": "AskUserQuestion",
                                         "input": {"questions": []}}], msg_id="m", timestamp="2026-09-01")
    res = _rec("r1", "a1", "user", [{"type": "tool_result", "tool_use_id": "tu1", "content": "ok"}],
               toolUseResult={"answers": {"q": "A"}})
    sess = type("S", (), {"records": [ask, dict(ask), res]})()
    assert [b["id"] for _, b, _, _ in build_cases.aq_calls(sess, "2026-10-01")] == ["tu1"]


def test_aq_calls_skips_a_call_already_seen_in_another_session_file():
    ask = _rec("a1", "p", "assistant", [{"type": "tool_use", "id": "tu1", "name": "AskUserQuestion",
                                         "input": {"questions": []}}], msg_id="m", timestamp="2026-09-01")
    original, resumed = (type("S", (), {"records": [dict(ask)]})() for _ in range(2))
    seen = set()
    first = list(build_cases.aq_calls(original, "2026-10-01", seen))
    assert len(first) == 1 and list(build_cases.aq_calls(resumed, "2026-10-01", seen)) == []


# ---------------------------------------------------------------- case selection

def _cand(cid, sid, layer, excluded=None):
    return {"id": cid, "session_id": sid, "layer": layer, "excluded": excluded}


def test_select_keeps_every_delegated_case_and_samples_info_cases_by_hash():
    cands = ([_cand(f"d{i}", f"s{i}", "delegated") for i in range(3)]
             + [_cand(f"i{i}", f"t{i}", "aq-info") for i in range(10)]
             + [_cand("x", "s0", "delegated", "background-running"), _cand("r", "s9", "aq-recommended")])
    got = build_cases.select(cands, n_info=4)
    assert sorted(c["id"] for c in got if c["layer"] == "delegated") == ["d0", "d1", "d2"]
    info = [c["id"] for c in got if c["layer"] == "aq-info"]
    assert len(info) == 4 and info == [c["id"] for c in build_cases.select(list(reversed(cands)), 4)
                                       if c["layer"] == "aq-info"]


@pytest.mark.parametrize("layer,label,expected", [
    ("delegated", "should-have-just-done-it", [build_cases.ACT_OR_CHECK]),
    ("aq-info", "rightly-asked", [{"final": "ask"}]),
], ids=["delegated", "aq-info"])
def test_case_record_follows_the_fork_replay_contract(layer, label, expected):
    sys.path.insert(0, os.path.join(build_cases.REPO, "eval", "fork-replay"))
    import casekit
    c = {**_cand("abc", "s", layer), "fork_mode": "after", "fork_uuid": "u1", "context_tokens": 1}
    case = build_cases.case_record(c, "/data/sessions/s.jsonl", None, {"answer": "要"})
    assert casekit.validate_case(case) == []
    assert (case["label"], case["expected"], case["resume_input"]) == (label, expected, build_cases.RESUME_INPUT)
    assert case["tags"][0] == layer


def test_aq_calls_without_a_cutoff_keeps_every_call():
    ask = _rec("a1", "p", "assistant", [{"type": "tool_use", "id": "tu1", "name": "AskUserQuestion",
                                         "input": {"questions": []}}], msg_id="m", timestamp="2026-09-01")
    sess = type("S", (), {"records": [ask]})()
    assert len(list(build_cases.aq_calls(sess, None))) == 1


def test_sessions_of_drops_the_excluded_prefixes():
    pairs = [{"session_id": s} for s in ("abc1-x", "abc2-y", "def0-z", "abc1-x")]
    assert build_cases.sessions_of(pairs, ("abc1", "def0")) == ["abc2-y"]
    assert build_cases.sessions_of(pairs, ()) == ["abc1-x", "abc2-y", "def0-z"]
