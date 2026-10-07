#!/bin/bash
# Stop hook（asyncRewake）: 上下文过 150k 的会话在用户离开 50 分钟后唤醒模型回一个句点，保住提示缓存。
#
# 会话的提示缓存 1 小时不用就过期，过期后下一轮要把整段上下文按写入价重新写一遍。
# 本钩子配 "asyncRewake": true 在后台跑：每轮结束都起一次 50 分钟的计时，计时期间会话有任何
# 新的一轮（用户发消息、后台通知、子智能体回报），这次计时就作废，新一轮结束时自会起新的计时；
# 一直没有活动才以退出码 2 唤醒模型，提示只要一个句点，把缓存续上。所以它只在用户离开时触发。
# 50 分钟让唤醒落在 1 小时有效期内，并给唤醒本身的排队与请求留出余量。
# 保活回合结束时又会触发本钩子，于是空闲期间每 50 分钟续一次。
# 不用定时任务：定时任务按钟点触发，用户在场时也照样空跑；auto 模式分类器还会把设定时任务当作
# 持久化操作拒掉。
# 只在上下文 ≥ 150k 时计时：小上下文过期了重写也便宜，不值得空跑。
# 从用户本人最后一条消息起超过 8 小时就不再唤醒，防止被遗忘的会话一直在续缓存。用户回答选择题
# （AskUserQuestion）也算本人消息：它进 transcript 时是工具结果，但人就在场；无人回答、超时自动提交的
# 那条（toolUseResult 带 afkTimeoutMs）不算。
# 订阅额度用尽、改走用量计费后，Claude Code 把主对话的缓存降为 5 分钟 TTL
# （https://code.claude.com/docs/en/prompt-caching）：50 分钟一次的唤醒续不上缓存，还花付费额度，
# 所以这时不计时。
#
# 按顺序取第一条成立的：
#   1. -p 无头会话（CLAUDE_CODE_ENTRYPOINT 为 sdk-cli）或在子智能体内：退出 0。
#   2. 主线程上下文 < 150k、缓存为 5 分钟 TTL、或用户本人最后一条消息距今超过 8 小时（没有则同）：退出 0。
#   3. 睡 KEEPALIVE_SLEEP 秒（默认 3000，只给测试改短）；醒来时 transcript 被删、变短，
#      或开睡前的末尾之后多了时间戳不早于钩子起跑的 user／assistant 行：退出 0。
#   4. 其余向 stderr 写唤醒提示，退出 2。
# 「活动」只认 user／assistant 行：Stop 之后 Claude Code 自己会往 transcript 追加 stop_hook_summary、
# turn_duration，空闲几分钟后还会追加 away_summary，这些行不是会话里有了新的一轮。
# 上下文取 transcript 里主线程（非 isSidechain）最后一次 assistant 调用的 usage，
# 同 context-watermark-gate.sh：input + cache_read + cache_creation。
# TTL 取主线程最近一次有缓存写入的 assistant 调用的 usage.cache_creation：
# ephemeral_5m_input_tokens > 0 且 ephemeral_1h_input_tokens == 0 为 5 分钟；
# 字段缺失或两档都为 0 的调用跳过往前找，都找不到按 1 小时处理。
# 不看 stop_hook_active：Claude Code 把保活唤醒的那一轮记为 stop_hook_active 为真，别的 Stop 钩子
# 拦下后续跑的那一轮也是，看它就会在这两种回合后不再计时。本钩子在交互会话里只在后台计时、
# 不同步拦截，没有拦截循环可防。-p 无头会话里 asyncRewake 不转后台、会同步睡满 50 分钟卡住整次
# 运行，而无头会话跑完就退出，没有缓存可保，所以直接不计时。
# Claude Code 每 100 毫秒才把 transcript 写队列落盘一次，本轮最后一条 assistant 行常在钩子量完末尾之后
# 才落盘；它的时间戳早于钩子起跑，所以只把时间戳不早于起跑的行算新活动，没有时间戳的行照算。
# 整个脚本包在 { } 里：bash 边读边执行脚本，睡眠期间脚本被原地改写时，醒来会从旧偏移读新内容报错退出 2，
# 被当成一次唤醒；包起来后 bash 执行前已读完整个块。
# 任何异常一律退出 0，不唤醒。
{
python3 -c '
import json, os, re, sys, time
from datetime import datetime

MARK = "[保活]"
THRESHOLD = 150000
MAX_IDLE = 8 * 3600
# 子智能体回报、另一会话的消息、后台通知（保活唤醒也包成后台通知进 transcript）都以用户角色进
# transcript，不是用户本人输入
NOT_USER = re.compile(r"\s*(Another Claude session sent a message|<agent-message|<task-notification)")

try:
    p = json.loads(sys.stdin.buffer.read().decode("utf-8"))
except Exception:
    sys.exit(0)
if not isinstance(p, dict) or os.environ.get("CLAUDE_CODE_ENTRYPOINT") == "sdk-cli":
    sys.exit(0)
if str(p.get("agent_id") or "").strip():
    sys.exit(0)
tp = p.get("transcript_path") or ""
if not tp or not os.path.isfile(tp):
    sys.exit(0)
t0 = time.time()               # 钩子起跑时刻；时间戳早于它的行属于本轮，只是落盘晚
start = os.path.getsize(tp)    # 开睡前的末尾；读 transcript 期间追加的行也算在睡眠期间

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
short_ttl = False         # 最近一次有缓存写入的调用是 5 分钟 TTL
last_user_at = None       # 用户本人最后一条消息的时间
with open(tp, encoding="utf-8") as f:
    for line in f:
        try:
            o = json.loads(line)
        except Exception:
            continue
        m = o.get("message") if isinstance(o, dict) else None
        if not isinstance(m, dict) or o.get("isSidechain"):
            continue
        if m.get("role") == "assistant":
            u = m.get("usage")
            if isinstance(u, dict):
                t = (u.get("input_tokens") or 0) + (u.get("cache_read_input_tokens") or 0) + \
                    (u.get("cache_creation_input_tokens") or 0)
                if t:
                    used = t      # 同一 message.id 的续行带同一份 usage，取最后一行即可
                cc = u.get("cache_creation")
                if isinstance(cc, dict):
                    w5 = cc.get("ephemeral_5m_input_tokens") or 0
                    w1 = cc.get("ephemeral_1h_input_tokens") or 0
                    if w5 or w1:
                        short_ttl = w5 > 0 and w1 == 0
        elif m.get("role") == "user":
            tr = o.get("toolUseResult")
            if isinstance(tr, dict) and tr.get("questions"):
                if not tr.get("afkTimeoutMs"):    # 用户本人回答了选择题；带 afkTimeoutMs 的是无人回答超时自动提交
                    last_user_at = epoch(o.get("timestamp"))
                continue
            txt = text_of(m.get("content"))
            if txt is None or o.get("isMeta"):
                continue
            if not txt.lstrip().startswith(MARK) and not NOT_USER.match(txt):
                last_user_at = epoch(o.get("timestamp"))

if used < THRESHOLD or short_ttl or last_user_at is None or time.time() - last_user_at > MAX_IDLE:
    sys.exit(0)

time.sleep(float(os.environ.get("KEEPALIVE_SLEEP") or 3000))

if not os.path.isfile(tp) or os.path.getsize(tp) < start:
    sys.exit(0)
with open(tp, "rb") as f:
    f.seek(start)
    for line in f:
        try:
            o = json.loads(line.decode("utf-8"))
        except Exception:
            continue
        if isinstance(o, dict) and o.get("type") in ("user", "assistant"):
            ts = epoch(o.get("timestamp"))
            if ts is None or ts >= t0:
                sys.exit(0)
sys.exit(2)
' 2>/dev/null
if [ $? -eq 2 ]; then
  printf '%s' '[保活] 只回复一个句点，不做别的。' >&2
  exit 2
fi
exit 0
}
