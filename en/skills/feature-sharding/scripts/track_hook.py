"""轨道会话的状态钩子：由轨道设置文件挂上（SessionStart / Stop / SessionEnd），把会话状态写进状态目录。

钩子 JSON 从 stdin 读入，由 claude 调用，不需手工运行。
环境变量 SHARD_STATE（状态目录）与 SHARD_TRACK（轨道代号）缺任一、或钩子带 agent_id（子智能体内）时什么都不写。
写两处：<轨道>.status.json 整份覆盖；events.jsonl 追加一行。
任何异常都退出 0 且不向 stdout 输出：SessionStart 的 stdout 会进上下文。
"""
import datetime
import json
import os
import re
import sys
import tempfile
import time

# 模型常给状态行加粗或加反引号，行首的这些标记不算内容
STATUS_RE = re.compile(r"^[\s`*_]*状态[:：]\s*(完成|待答|交接)")
LAST_MESSAGE_MAX = 1500
EVENTS = {"SessionStart": "start", "Stop": "stop", "SessionEnd": "end"}
UNDECLARED = "未声明"
# 保活钩子要轨道交接或做完后只回这几种字；这一轮不算新声明，沿用同一会话上一轮的状态
KEEPALIVE_REPLIES = {"完", ".", "。"}
USAGE_KEYS = ("input_tokens", "cache_read_input_tokens", "cache_creation_input_tokens")
# Claude Code 每 100 毫秒才把 transcript 写队列落盘一次，Stop 钩子起跑时本轮最后一条 assistant 行常还没写进去
FLUSH_WAIT = 1.0


def now_iso():
    return datetime.datetime.now().astimezone().isoformat(timespec="seconds")


def write_json(path, data):
    """先写同目录临时文件再改名，读者看不到写了一半的文件。"""
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), prefix=".tmp-", suffix=".json")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def transcript_stats(path):
    """返回 (主线程最后一次非零 usage 的上下文 token 数, 主线程最后一条 assistant 消息的 text 块拼接)。
    口径同 context-watermark-gate.sh：input + cache_read + cache_creation。
    同一条 assistant 消息会拆成多行（每个内容块一行，id 相同），故按 id 归并。"""
    ctx, last_id, texts = 0, None, []
    try:
        f = open(path, encoding="utf-8")
    except (OSError, TypeError):
        return 0, ""
    with f:
        for line in f:
            try:
                o = json.loads(line)
            except ValueError:
                continue
            if not isinstance(o, dict) or o.get("isSidechain"):
                continue
            m = o.get("message")
            if not isinstance(m, dict):
                continue
            u = m.get("usage")
            if isinstance(u, dict):
                t = sum((u.get(k) or 0) for k in USAGE_KEYS)
                if t:
                    ctx = t
            if m.get("role") != "assistant":
                continue
            # 没有 id 的行各自成一条消息，object() 保证它与任何别的 id 都不相等
            mid = m.get("id") or o.get("uuid") or object()
            if mid != last_id:
                last_id, texts = mid, []
            content = m.get("content")
            if isinstance(content, list):
                texts.extend(b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text")
    return ctx, "\n".join(texts)


def status_of(message, event):
    """返回 (首个非空行原文, 状态)。start 事件一律未声明；状态只认首个非空行。"""
    line = next((l.strip() for l in message.splitlines() if l.strip()), "")
    m = STATUS_RE.match(line)
    status = m.group(1) if m and event != "start" else UNDECLARED
    return line, status


def previous_status(path):
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def handle(payload, env, now=now_iso, sleep=time.sleep):
    state, track = env.get("SHARD_STATE"), env.get("SHARD_TRACK")
    if not state or not track or payload.get("agent_id"):
        return
    event = EVENTS.get(payload.get("hook_event_name"))
    if not event:
        return
    tp = payload.get("transcript_path")
    given = payload.get("last_assistant_message")
    if event == "stop" and not (isinstance(given, str) and given.strip()):
        sleep(FLUSH_WAIT)
    ctx, message = transcript_stats(tp)
    if event == "stop" and isinstance(given, str) and given.strip():
        message = given
    line, status = status_of(message, event)
    path = os.path.join(state, f"{track}.status.json")
    if event == "stop" and status == UNDECLARED and message.strip() in KEEPALIVE_REPLIES:
        prev = previous_status(path)
        if prev.get("session_id") == payload.get("session_id") and prev.get("status") not in (None, UNDECLARED):
            line, status, message = prev.get("status_line", ""), prev["status"], prev.get("last_message", "")
    at = now()
    write_json(path, {
        "track": track,
        "session_id": payload.get("session_id"),
        "transcript_path": tp,
        "cwd": payload.get("cwd"),
        "event": event,
        "at": at,
        "context_tokens": ctx,
        "status": status,
        "status_line": line,
        "last_message": message[:LAST_MESSAGE_MAX],
        "ended": event == "end",
    })
    with open(os.path.join(state, "events.jsonl"), "a", encoding="utf-8") as f:
        f.write(json.dumps({"track": track, "event": event, "at": at, "status": status,
                            "session_id": payload.get("session_id")}, ensure_ascii=False) + "\n")


def main():
    try:
        payload = json.loads(sys.stdin.read())
        if isinstance(payload, dict):
            handle(payload, os.environ)
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
