#!/bin/bash
# Stop hook: 上下文过 150k 的会话设一个保活定时任务，用户离开时提示缓存不过期。
#
# 会话的提示缓存 1 小时不用就过期，过期后下一轮要把整段上下文按写入价重新写一遍。
# 保活任务每 30 分钟触发一次只回一个句点，把缓存续上。间隔取 30 分钟而不是贴着 1 小时：
# cron 表达式只能按分钟字段列举，表达不了 55 分钟这种间隔；重复任务又可能晚到周期的 10%，
# 30 分钟加上抖动仍落在 1 小时有效期内。分钟避开 0 与 30，免得和整点、半点的任务挤在一起。
# 只在上下文 ≥ 150k 时设：小上下文过期了重写也便宜，不值得定时空跑。
# 从用户本人最后一条消息起最多保活 8 小时，防止被遗忘的会话一直在续缓存。
# 设定与撤销都由本钩子拦停时下达，不写进规则文本，规则文本会常驻每个会话的上下文。
#
# 按顺序取第一条成立的：
#   1. stop_hook_active 为真（上一轮已拦，正因此续跑）或在子智能体内：放行。
#   2. 本回合由保活触发，且用户本人最后一条消息已过 8 小时：拦下，要求删掉保活任务。
#   3. 主线程上下文 ≥ 150k 且 transcript 里没有仍有效的保活任务：拦下，要求设保活。
#   4. 其余放行。
# 上下文取 transcript 里主线程（非 isSidechain）最后一次 assistant 调用的 usage，
# 同 context-watermark-gate.sh：input + cache_read + cache_creation。
# 「仍有效」＝有一次 input.prompt 以 [保活] 开头的 CronCreate 成功返回，且其结果里的任务 id
# 之后没被 CronDelete 删掉。KEEPALIVE_NOW_EPOCH 只给测试固定当前时间。
# 任何异常一律放行，hook 不该卡死会话。
python3 -c '
import json, os, re, sys, time
from datetime import datetime

MARK = "[保活]"
THRESHOLD = 150000
MAX_IDLE = 8 * 3600
KEEP_PROMPT = (MARK + " 若本对话里找不到设定本任务的记录（例如已 /clear），用 CronList 找到以 "
               + MARK + " 开头的任务并 CronDelete；否则只回复一个句点，不做别的。")
# 子智能体回报、另一会话的消息与后台通知也以用户角色进 transcript，不是用户本人输入
NOT_USER = re.compile(r"\s*(Another Claude session sent a message|<agent-message|<task-notification)")

try:
    p = json.loads(sys.stdin.buffer.read().decode("utf-8"))
except Exception:
    sys.exit(0)
if not isinstance(p, dict) or p.get("stop_hook_active"):
    sys.exit(0)
if str(p.get("agent_id") or "").strip():
    sys.exit(0)
tp = p.get("transcript_path") or ""
if not tp or not os.path.isfile(tp):
    sys.exit(0)

def text_of(content):
    """用户角色消息的文字；只含工具结果的返回 None。"""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = [b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text"]
        if parts:
            return "".join(parts)
    return None

def epoch(ts):
    try:
        return datetime.fromisoformat(str(ts).replace("Z", "+00:00")).timestamp()
    except Exception:
        return None

used = 0
last_prompt = None        # 最后一条带文字的用户角色消息
last_user_at = None       # 用户本人最后一条消息的时间
creates = {}              # tool_use_id -> 结果文本（None 表示还没结果）
deleted = []              # CronDelete 删掉的任务 id
with open(tp, encoding="utf-8") as f:
    for line in f:
        try:
            o = json.loads(line)
        except Exception:
            continue
        m = o.get("message") if isinstance(o, dict) else None
        if not isinstance(m, dict) or o.get("isSidechain"):
            continue
        content = m.get("content")
        if m.get("role") == "assistant":
            u = m.get("usage")
            if isinstance(u, dict):
                t = (u.get("input_tokens") or 0) + (u.get("cache_read_input_tokens") or 0) + \
                    (u.get("cache_creation_input_tokens") or 0)
                if t:
                    used = t      # 同一 message.id 的续行带同一份 usage，取最后一行即可
            for b in content if isinstance(content, list) else ():
                if not isinstance(b, dict) or b.get("type") != "tool_use":
                    continue
                inp = b.get("input") if isinstance(b.get("input"), dict) else {}
                if b.get("name") == "CronCreate" and str(inp.get("prompt") or "").lstrip().startswith(MARK):
                    creates[b.get("id")] = None
                elif b.get("name") == "CronDelete":
                    jid = inp.get("id") or inp.get("job_id") or inp.get("jobId")
                    if jid:
                        deleted.append(str(jid))
        elif m.get("role") == "user":
            for b in content if isinstance(content, list) else ():
                if isinstance(b, dict) and b.get("type") == "tool_result" and b.get("tool_use_id") in creates:
                    if b.get("is_error"):
                        creates.pop(b.get("tool_use_id"))
                    else:
                        creates[b.get("tool_use_id")] = json.dumps([b.get("content"), o.get("toolUseResult")],
                                                                   ensure_ascii=False)
            txt = text_of(content)
            if txt is None or o.get("isMeta"):
                continue
            last_prompt = txt
            if not txt.lstrip().startswith(MARK) and not NOT_USER.match(txt):
                last_user_at = epoch(o.get("timestamp"))

now = float(os.environ.get("KEEPALIVE_NOW_EPOCH") or time.time())

if last_prompt is not None and last_prompt.lstrip().startswith(MARK):
    if last_user_at is None or now - last_user_at > MAX_IDLE:
        print(json.dumps({"decision": "block",
                          "reason": "保活已满 8 小时：用 CronList 找到以 [保活] 开头的任务并 CronDelete，然后结束。"},
                         ensure_ascii=False))
        sys.exit(0)

def alive(result):
    if result is None:    # 结果还没落进 transcript，按已设处理，免得重复设
        return True
    return not any(re.search(r"(?<![\w-])%s(?![\w-])" % re.escape(j), result) for j in deleted)

if used >= THRESHOLD and not any(alive(r) for r in creates.values()):
    a = time.localtime(now).tm_min % 30 or 1
    cron = "%d,%d * * * *" % (a, a + 30)
    print(json.dumps({"decision": "block", "reason": (
        "上下文已过 150k：用 CronCreate 设保活，cron 为 \"%d * * * *\" 与 \"%d * * * *\" 合并成 \"%s\""
        "（m 取当前分钟数，避开 0 与 30），recurring 为 true，prompt 原样为：%s设好后直接结束，不要回复别的。"
        % (a, a + 30, cron, KEEP_PROMPT))}, ensure_ascii=False))
sys.exit(0)
' 2>/dev/null
exit 0
