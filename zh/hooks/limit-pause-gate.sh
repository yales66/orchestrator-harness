#!/bin/bash
# PreToolUse 钩子（所有工具，主线程与子智能体都走）：订阅 5 小时用量到 95% 且未到重置时间时，
# 把工具调用挂起到重置，期间每 50 分钟保活一次，免得用量撞满后正在跑的会话与子智能体报错中断。
#
# 钩子 stdin 不带用量，用量取自两个本地文件，读文件不发请求、不花额度：
#   ~/.claude/state/rate-limits.json：同目录 statusline-tee.sh 把 Claude Code 传给状态栏的 rate_limits 原样落盘
#     （five_hour.used_percentage 0–100、five_hour.resets_at Unix 秒），随每次模型响应更新，最及时。
#   ~/.claude/plugins/claude-hud/.usage-cache.json：claude-hud 插件查用量接口的缓存（data.fiveHour、
#     data.fiveHourResetAt），该接口限流，插件 5 分钟才查一次；状态栏数据缺失或损坏时靠它兜底。
# 两份里取未过重置时刻的最高值：同一 5 小时窗口内用量只增不减，较低的那份必是旧值。不按文件修改
# 时间挑：很久没发请求的会话重绘状态栏会把旧的低值写成最新，插件缓存也滞后且取整，按修改时间挑会
# 在 95% 上下来回跳，放过本该挂起的调用。过了重置时间的那份不算，所以不会被旧窗口的高值卡住。
#
# 按顺序取第一条成立的：
# 「放行」对暂停命令本身是输出 permissionDecision allow 跳过权限审批（`: 限额暂停` 是空命令；不跳过的话
# 交互会话会弹审批框，用户不在场时会话就卡在那里），对其余调用是无输出退出 0，照常走权限流程。
#   0. 手动开关 ~/.claude/state/limit-pause-off 存在：放行（用户 `! touch` 它即全局关掉暂停）。
#   1. 读不到用量（缓存缺失、损坏、字段缺失）、用量 < 95%，或已过重置时间：放行。
#   2. 主线程（stdin 无 agent_id）最近一条输入是用户本人在越过 95% 之后发的，或是最后一次保活唤醒：放行。
#      用户在场时不会拿剩下的额度做大事，由用户决定；最后一次保活要写交接，挂着就掉缓存。
#      「输入」是 transcript 里带 origin 的 user 行（回合开头）与 queued_command 附件（回合中途插进来的），
#      origin.kind 为 human 才是用户本人；后台通知、子智能体回报、保活唤醒各有别的 kind。只认最近一条：
#      本人回合中途插进通知之后，之后的调用照常挂起，不能借本人开的回合跑起自动任务。
#      越过 95% 的时刻取 statusline-tee.sh 记的 pause_since；没有就不放行。
#      越过之前就开始的回合（包括用户让它全自动跑的）照常挂起；子智能体一律照常挂起。
#   3. 睡到重置，最多睡 LIMIT_PAUSE_MAX_SLEEP 秒（默认 3000，只给测试改短），每 3 秒看一次。主线程挂起
#      期间用户发来消息（transcript 多出内容不像通知的 enqueue 行）就拦下本次调用并结束挂起：
#      排队的消息要等工具调用返回才送达，不结束就要等满一轮；要模型先处理用户消息、处理完就停。
#   4. 醒来已过重置时间：放行。
#   5. 否则拦下这次调用，要模型只调用 Bash 执行 `: 限额暂停`：这次模型请求就是保活，只读缓存、
#      输出极小；该调用又进本钩子挂起。睡 3000 秒是为了让保活请求落在提示缓存 1 小时有效期内。
#      不让模型原样重发被拦的调用，因为那要把整份工具输入（如 Write 的全文）再生成一遍。
# 离重置不到 50 分钟时只睡不保活：缓存撑得到重置。
# settings.json 里本钩子的 timeout 必须大于 3000 秒：PreToolUse 钩子超时会被取消并放行
# （https://code.claude.com/docs/en/hooks.md ，默认 600 秒）。
# 任何异常一律退出 0 放行：本钩子拦所有工具，出错不能卡死会话。
{
# shellcheck disable=SC2016  # python 代码里的反引号是拦截理由的文字，不是命令替换
python3 -c '
import json, os, sys, time
from datetime import datetime

THRESHOLD = 95
HUD = os.environ.get("LIMIT_PAUSE_CACHE") or os.path.expanduser("~/.claude/plugins/claude-hud/.usage-cache.json")
RL = os.environ.get("LIMIT_PAUSE_RL") or os.path.expanduser("~/.claude/state/rate-limits.json")
OFF = os.environ.get("LIMIT_PAUSE_OFF") or os.path.expanduser("~/.claude/state/limit-pause-off")
FINAL_MARK = "最后一次保活"   # 最后一次保活唤醒提示里的字样（keepalive-gate.sh）
NOT_HUMAN = ("<task-notification", "<agent-message", "Another Claude session")
max_sleep = float(os.environ.get("LIMIT_PAUSE_MAX_SLEEP") or 3000)
PAUSE_CMD = ": 限额暂停"

try:
    p = json.loads(sys.stdin.buffer.read().decode("utf-8"))
    is_pause = p.get("tool_name") == "Bash" and str((p.get("tool_input") or {}).get("command") or "").strip() == PAUSE_CMD
    tp = "" if str(p.get("agent_id") or "").strip() else str(p.get("transcript_path") or "")
except Exception:
    is_pause, tp = False, ""
if not os.path.isfile(tp):
    tp = ""                    # 子智能体内或拿不到 transcript：不看用户输入

def deny(reason):
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                             "permissionDecisionReason": reason}}, ensure_ascii=False))
    sys.exit(0)

def epoch(ts):
    try:
        return datetime.fromisoformat(str(ts).replace("Z", "+00:00")).timestamp()
    except Exception:
        return None

# 主线程最近一条输入：(origin.kind, 时间, 文字)
def last_input():
    last = None
    with open(tp, encoding="utf-8") as f:
        for line in f:
            try:
                o = json.loads(line)
            except Exception:
                continue
            if not isinstance(o, dict):
                continue
            if o.get("type") == "user" and isinstance(o.get("origin"), dict):
                c = (o.get("message") or {}).get("content")
                txt = c if isinstance(c, str) else json.dumps(c, ensure_ascii=False)
                last = (o["origin"].get("kind"), epoch(o.get("timestamp")), txt)
            elif o.get("type") == "attachment" and (o.get("attachment") or {}).get("type") == "queued_command":
                a = o["attachment"]
                last = ((a.get("origin") or {}).get("kind"), epoch(o.get("timestamp")), str(a.get("prompt") or ""))
    return last

# 挂起开始后 transcript 多出用户本人排队的消息
def human_queued(offset):
    with open(tp, "rb") as f:
        f.seek(offset)
        for line in f:
            try:
                o = json.loads(line.decode("utf-8"))
            except Exception:
                continue
            if isinstance(o, dict) and o.get("type") == "queue-operation" and o.get("operation") == "enqueue":
                if not str(o.get("content") or "").lstrip().startswith(NOT_HUMAN):
                    return True
    return False

def release():
    if is_pause:
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "allow",
                                                 "permissionDecisionReason": "限额暂停结束"}}, ensure_ascii=False))
    sys.exit(0)

def from_rl():
    f = json.load(open(RL))["five_hour"]
    return float(f["used_percentage"]), float(f["resets_at"])

def from_hud():
    d = json.load(open(HUD))["data"]
    return float(d["fiveHour"]), datetime.fromisoformat(str(d["fiveHourResetAt"]).replace("Z", "+00:00")).timestamp()

if os.path.exists(OFF):
    release()

readings = []                  # (用量%, 重置时刻)，只收未过重置的
for read in (from_rl, from_hud):
    try:
        r = read()
    except Exception:
        continue
    if r[1] > time.time():
        readings.append(r)
if not readings:
    release()
pct, reset = max(readings)
if pct < THRESHOLD:
    release()

since = None                   # 本窗口越过 95% 的时刻
try:
    d = json.load(open(RL))
    if abs(float(d["five_hour"]["resets_at"]) - reset) < 600:
        since = float(d["pause_since"])
except Exception:
    pass
if tp:
    try:
        kind, at, txt = last_input() or (None, None, "")
        if (kind == "human" and since is not None and at is not None and at >= since) or \
                ("[保活]" in txt and FINAL_MARK in txt):
            release()
        offset = os.path.getsize(tp)
    except Exception:
        tp = ""

until = min(time.time() + max_sleep, reset)
while time.time() < until:
    time.sleep(max(0, min(3, until - time.time())))
    if tp:
        try:
            if human_queued(offset):
                deny("[限额暂停] 用户发来了新消息，这个调用先不执行。先处理用户的消息；处理完就停，原来被暂停的"
                     "工作等 5 小时限额重置后再继续。")
        except Exception:
            pass
left = reset - time.time()
if left <= 0:
    release()
reason = ("[限额暂停] 5 小时用量已到 %d%%，离重置还有约 %d 分钟，刚才这个调用没有执行。现在只调用 Bash 执行 "
          "`%s`，不做别的；钩子会把它挂起到限额重置或下一次保活。它放行后，重新发起刚才被拦下的调用，"
          "继续原来的工作。" % (pct, max(1, round(left / 60)), PAUSE_CMD))
deny(reason)
' 2>/dev/null
exit 0
}
