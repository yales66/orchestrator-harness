#!/bin/bash
# Stop hook（asyncRewake）: 上下文过 150k 的会话在用户离开 50 分钟后唤醒模型回一个句点，保住提示缓存。
#
# 会话的提示缓存 1 小时不用就过期，过期后下一轮要把整段上下文按写入价重新写一遍。
# 本钩子配 "asyncRewake": true 在后台跑：每轮结束都起一次 50 分钟的计时，计时期间会话有任何
# 新的一轮（用户发消息、后台通知、子智能体回报），这次计时就作废，新一轮结束时自会起新的计时；
# 一直没有活动才以退出码 2 唤醒模型，提示只要一个句点，把缓存续上。所以它只在用户离开时触发。
# 50 分钟让唤醒落在 1 小时有效期内，并给唤醒本身的排队与请求留出余量。
# 保活回合结束时又会触发本钩子，于是空闲期间每 50 分钟续一次。
# 唤醒前先探测 API 连得上才唤醒：唤醒请求一旦因断网失败，回合结束触发的是 StopFailure 而不是 Stop，
# StopFailure 的退出码被忽略、唤醒不了模型（https://code.claude.com/docs/en/hooks.md ），保活链就此断掉。
# 连不上时每 30 秒再探，直到钩子起跑后 57 分钟（缓存 1 小时有效期留 3 分钟余量）为止；过了这个截止
# 缓存已过期或来不及续，再唤醒就要按写入价重写整段上下文，比不保活还贵，所以放弃。探测连得上、
# 紧接着的唤醒请求却失败的情况补不上。
# 计时按墙钟比对：time.sleep 在 Mac 睡眠期间不走，合盖醒来可能已过截止，这时同样放弃。
# 下一次唤醒会超过 8 小时上限时，这一次唤醒改为最后一次：还有要交给新会话接着做的事就用 handoff 技能
# 写交接，趁缓存还热，读上下文只按缓存读价计费；任务已做完、只剩用户本人要做的事，或已有交接或计划
# 已写全剩余工作，交接只是重复，就只回句点。是否还有事要交接只有模型看得出，所以由提示交给它判断。
# 发过最后一次唤醒之后不再计时，直到用户本人再发消息。
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
#   3. 用户本人最后一条消息之后已发过最后一次唤醒：退出 0。
#   4. 睡到起跑后 KEEPALIVE_SLEEP 秒（默认 3000）。之后循环：transcript 被删、变短，或开睡前的末尾
#      之后多了时间戳不早于钩子起跑的 user／assistant 行，退出 0；已过起跑后 KEEPALIVE_DEADLINE 秒
#      （默认 3420），退出 0；探测 KEEPALIVE_PROBE_URL（默认 ANTHROPIC_BASE_URL，未设则
#      https://api.anthropic.com）得到任何 HTTP 响应（含 4xx/5xx）算连得上，跳出循环；否则睡
#      KEEPALIVE_RETRY 秒（默认 30）再来。这几个 KEEPALIVE_ 变量只给测试改。
#   5. 起跑时刻加两个 KEEPALIVE_SLEEP 距用户本人最后一条消息超过 8 小时（下一次唤醒会越过上限）：
#      向 stderr 写最后一次唤醒的提示，退出 2。
#   6. 其余向 stderr 写句点提示，退出 2。
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
HANDOFF_MARK = "最后一次保活"   # 最后一次唤醒提示里的字样，唤醒消息进 transcript 后据此认出已发过
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
handoff_at = None         # 最近一次「最后一次唤醒」消息的时间
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
            if MARK in txt and HANDOFF_MARK in txt:
                handoff_at = epoch(o.get("timestamp"))
            if not txt.lstrip().startswith(MARK) and not NOT_USER.match(txt):
                last_user_at = epoch(o.get("timestamp"))

if used < THRESHOLD or short_ttl or last_user_at is None or time.time() - last_user_at > MAX_IDLE:
    sys.exit(0)
if handoff_at is not None and handoff_at >= last_user_at:
    sys.exit(0)

SLEEP = float(os.environ.get("KEEPALIVE_SLEEP") or 3000)
DEADLINE = t0 + float(os.environ.get("KEEPALIVE_DEADLINE") or 3420)
RETRY = float(os.environ.get("KEEPALIVE_RETRY") or 30)
URL = os.environ.get("KEEPALIVE_PROBE_URL") or os.environ.get("ANTHROPIC_BASE_URL") or "https://api.anthropic.com"
final = t0 + 2 * SLEEP - last_user_at > MAX_IDLE

# 开睡前的末尾之后会话有了新的一轮，或 transcript 被删、变短
def active():
    if not os.path.isfile(tp) or os.path.getsize(tp) < start:
        return True
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
                    return True
    return False

def reachable():
    import urllib.error, urllib.request
    try:
        urllib.request.urlopen(urllib.request.Request(URL, method="HEAD"), timeout=10).close()
        return True
    except urllib.error.HTTPError:
        return True
    except Exception:
        return False

while time.time() < t0 + SLEEP:
    time.sleep(min(30, t0 + SLEEP - time.time()))
while True:
    if active() or time.time() > DEADLINE:
        sys.exit(0)
    if reachable():
        break
    time.sleep(RETRY)
sys.exit(3 if final else 2)
' 2>/dev/null
case $? in
  2) printf '%s' '[保活] 只回复一个句点，不做别的。' >&2; exit 2 ;;
  3) printf '%s' '[保活] 用户已离开近 8 小时，这是最后一次保活。本会话还有要交给新会话接着做的事，就用 handoff 技能交接，走完该技能的全部步骤就结束；只剩提交、推送、开 PR、合并等收尾，或在等用户答复、答复后还有工作，也算要交接，本回合不做这些收尾，也不重新提问。任务已做完，或剩下的只有用户本人能做、做完后不用会话接着做的事（如人工登录、人工审核），或已有的交接或计划文件已写全剩余工作且之后没有新进展，就只回一个句点。不做别的。' >&2; exit 2 ;;
esac
exit 0
}
