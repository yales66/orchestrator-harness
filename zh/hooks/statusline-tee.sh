#!/bin/bash
# 状态栏包装：把 Claude Code 传给状态栏的 rate_limits 落盘到 ~/.claude/state/rate-limits.json，
# 再把 stdin 原样交给参数里的内层状态栏命令渲染；不带参数时不输出。
# 用法（settings.json 的 statusLine.command）：bash ~/.claude/hooks/statusline-tee.sh <原状态栏命令及参数>
# 限额暂停钩子（同目录 limit-pause-gate.sh）要读 5 小时用量，钩子 stdin 不带它；状态栏 stdin 的
# rate_limits 随每次模型响应更新，不额外发请求（https://code.claude.com/docs/en/statusline.md ）。
# 缺 five_hour 时不覆盖上一份：会话收到第一次响应前没有这个字段。
# 同一窗口（重置时刻相差不到 10 分钟）里比上一份低的不覆盖：每个会话的 rate_limits 来自它自己最近一次
# 模型响应，很久没发请求的会话重绘状态栏时带的是旧的低值，而窗口内用量只增不减。
# 同一窗口里用量第一次到 95% 时记下当时时刻为 pause_since，之后同窗口沿用；暂停钩子据此判断用户本人的
# 输入是不是在越过 95% 之后发的。阈值与 limit-pause-gate.sh 的 THRESHOLD 一致。
# 写临时文件再改名，多个会话同时写不会读到半份。
# 落盘出任何错都不影响状态栏照常渲染。
# STATUSLINE_RL_OUT 只给测试改落盘路径。
input=$(cat)
printf '%s' "$input" | python3 -c '
import json, os, sys, tempfile, time
out = os.environ.get("STATUSLINE_RL_OUT") or os.path.expanduser("~/.claude/state/rate-limits.json")
rl = json.load(sys.stdin).get("rate_limits") or {}
f = rl.get("five_hour") or {}
if f.get("used_percentage") is None or f.get("resets_at") is None:
    sys.exit(0)
since = None
try:
    prev = json.load(open(out))
    old = prev["five_hour"]
    if abs(float(old["resets_at"]) - float(f["resets_at"])) < 600:
        if float(f["used_percentage"]) < float(old["used_percentage"]):
            sys.exit(0)
        since = prev.get("pause_since")
except Exception:
    pass
if since is None and float(f["used_percentage"]) >= 95:
    since = time.time()
if since is not None:
    rl = dict(rl, pause_since=since)
os.makedirs(os.path.dirname(out), exist_ok=True)
fd, tmp = tempfile.mkstemp(dir=os.path.dirname(out))
with os.fdopen(fd, "w") as w:
    json.dump(rl, w)
os.replace(tmp, out)
' >/dev/null 2>&1
if [ "$#" -gt 0 ]; then
  printf '%s' "$input" | exec "$@"
fi
