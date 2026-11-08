#!/bin/bash
# PermissionDenied 钩子：把每次自动模式拒绝追加一行 JSON 到日志，供事后复盘该补哪条 autoMode.environment 或 allow。
# 日志路径：${PERMISSION_DENIED_LOG:-$HOME/.claude/state/permission-denied.jsonl}
# 只记工具名、被拒对象（命令 / 路径 / URL）的前 300 字符与拒绝理由；不回 retry，任何异常静默退出 0。
# source 记 auto-mode-classifier：这个事件只在自动模式分类器拒绝时触发，secret-guard 与
# subagent-readonly-guard 拒绝时自己往同一文件写 source 为 hook:<钩子名> 的行，复盘时按 source 分桶。
# 拒绝规则命中没有事件可挂，不在这份日志里。
LOG="${PERMISSION_DENIED_LOG:-$HOME/.claude/state/permission-denied.jsonl}"
LOG="$LOG" python3 -I -c '
import json, os, sys, datetime
try:
    d = json.load(sys.stdin)
    ti = d.get("tool_input") or {}
    target = None
    if isinstance(ti, dict):
        for k in ("command", "file_path", "notebook_path", "path", "url", "pattern"):
            v = ti.get(k)
            if isinstance(v, str) and v:
                target = v
                break
    if target is None:
        target = json.dumps(ti, ensure_ascii=False)
    rec = {
        "ts": datetime.datetime.now().astimezone().isoformat(timespec="seconds"),
        "session_id": d.get("session_id"),
        "cwd": d.get("cwd"),
        "tool_name": d.get("tool_name"),
        "target": target[:300],
        "reason": d.get("reason"),
        "source": "auto-mode-classifier",
    }
    log = os.environ["LOG"]
    os.makedirs(os.path.dirname(log) or ".", exist_ok=True)
    with open(log, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
except Exception:
    pass
' 2>/dev/null
exit 0
