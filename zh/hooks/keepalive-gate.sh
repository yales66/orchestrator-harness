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
# 下一次唤醒会超过 8 小时上限时，这一次唤醒改为最后一次：还有要交给新会话接着做的实质工作就用 handoff
# 技能写交接，趁缓存还热，读上下文只按缓存读价计费；有待用户答复的问题也走交接。只剩提交、推送、合并等收尾时，新会话从 git 状态
# 就看得出剩什么，整份交接（一次约 3 美元 API 等价）换不来更多信息，改为在进度源末尾记下收尾清单；
# 收尾本身仍不在用户离开时做，免得无人在场时推送、合并。任务已做完、只剩用户本人要做的事，或已有
# 交接或计划已写全剩余工作，交接只是重复，就只回句点。剩下的是哪一类只有模型看得出，所以由提示交给它判断。
# 发过最后一次唤醒之后不再计时，直到用户本人再发消息。
# 会话的任务已做完时续缓存是白花钱，可做没做完只有模型看得出；判断交给句点唤醒的提示，不进会话的初始上下文：
# 任务已做完、没有待用户答复的问题、没有在跑的后台任务，或本会话已用 handoff 技能交出去、剩余工作与待答问题
# 和在跑任务都写进了交接文件、之后没有新进展时，回「完」而不是句点。交接过的会话，用户的答复与后续工作都去接力会话，续本会话的缓存
# 是白花钱；只写「没有待答问题」时，交接时挂着问题的会话会一直回句点续到 8 小时上限。保活回合回了「完」之后不再计时，
# 直到用户本人再发消息。代价是做完后仍要花一次唤醒才停。
# 不用定时任务：定时任务按钟点触发，用户在场时也照样空跑；auto 模式分类器还会把设定时任务当作
# 持久化操作拒掉。
# 只在上下文 ≥ 150k 时计时（父会话有在跑的子会话时例外，见「按顺序」第 2 条）：小上下文过期了重写也便宜，不值得空跑。
# 从用户本人最后一条消息起超过 8 小时就不再唤醒，防止被遗忘的会话一直在续缓存。用户回答选择题
# （AskUserQuestion）也算本人消息：它进 transcript 时是工具结果，但人就在场；无人回答、超时自动提交的
# 那条（toolUseResult 带 afkTimeoutMs）不算。
# 订阅额度用尽、改走用量计费后，Claude Code 把主对话的缓存降为 5 分钟 TTL
# （https://code.claude.com/docs/en/prompt-caching）：50 分钟一次的唤醒续不上缓存，还花付费额度，
# 所以这时不计时。
#
# 按顺序取第一条成立的：
#   0. SessionEnd 事件：留下本会话已结束的标记，退出 0。
#   1. -p 无头会话（CLAUDE_CODE_ENTRYPOINT 为 sdk-cli）或在子智能体内：退出 0。
#   2. 主线程上下文 < 150k、缓存为 5 分钟 TTL、或用户本人最后一条消息距今超过 8 小时（没有则同）：退出 0。
#      父会话有在跑的子会话时上下文阈值不适用，最后活动改取子会话 status 文件 at 的较晚者：子会话结束时
#      一定会唤醒父会话，那时重写缓存（Opus 5.5 每百万：1 小时缓存写 $8、缓存读 $0.20）是缓存读的 40 倍，不如保活。
#   3. 用户本人最后一条消息之后已发过最后一次唤醒，或有保活回合回了「完」且没有在跑的子会话：退出 0。
#   4. 睡到起跑后 KEEPALIVE_SLEEP 秒（默认 3000），其间本会话已结束就退出 0。之后循环：本会话已结束，
#      或 transcript 被删、变短，或开睡前的末尾
#      之后多了时间戳不早于钩子起跑的 user／assistant 行，退出 0；已过起跑后 KEEPALIVE_DEADLINE 秒
#      （默认 3420），退出 0；探测 KEEPALIVE_PROBE_URL（默认 ANTHROPIC_BASE_URL，未设则
#      https://api.anthropic.com）得到任何 HTTP 响应（含 4xx/5xx）算连得上，跳出循环；否则睡
#      KEEPALIVE_RETRY 秒（默认 30）再来。这几个 KEEPALIVE_ 变量只给测试改。
#   5. 再读一遍 transcript，第 3 条的「完」成立：退出 0（保活回合的「完」常在起跑读 transcript 之后才落盘）。
#   6. 起跑时刻加两个 KEEPALIVE_SLEEP 距用户本人最后一条消息超过 8 小时（下一次唤醒会越过上限）：
#      向 stderr 写最后一次唤醒的提示，退出 2。
#   7. 其余向 stderr 写句点提示，退出 2。
# 解析消息与「活动」都只认 type 为 user／assistant 的行：Claude Code 2.1.300 起还写 api-request-blob 行，
# 带用户角色的 message 却没有时间戳，当成用户本人消息会把最后消息时间冲成空值，钩子就不再计时。
# 「活动」只认 user／assistant 行还因为：Stop 之后 Claude Code 自己会往 transcript 追加 stop_hook_summary、
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
# 计时绑在起跑时的会话上，而唤醒打进的是 Claude Code 进程里当下的会话：/clear 或 /resume 换了会话后，
# 旧会话的 transcript 不再变化，计时到点就会把唤醒打进新会话，让一个空会话白白初始化一次。所以本脚本
# 也挂在 SessionEnd 上：会话结束时在 KEEPALIVE_ENDED_DIR（默认 ~/.claude/state/keepalive-ended）下按
# session_id 留一个空文件，顺手删掉一天前的；计时期间与唤醒前见到本会话的标记就退出 0。
# 任何异常一律退出 0，不唤醒。
{
python3 -c '
import json, os, re, sys, time
from datetime import datetime

MARK = "[保活]"
HANDOFF_MARK = "最后一次保活"   # 最后一次唤醒提示里的字样，唤醒消息进 transcript 后据此认出已发过
DONE_REPLIES = {"完", "done"}  # 句点唤醒提示里约定的回复：中文安装为「完」，英文安装为 Done；两个都认，比较时不分大小写
DONE_STRIP = " \t\n「」。.\"\x27“”"  # 模型可能把提示里的引号、句末标点一起照抄
THRESHOLD = 150000
MAX_IDLE = 8 * 3600
# 子智能体回报、另一会话的消息、后台通知（保活唤醒也包成后台通知进 transcript）都以用户角色进
# transcript，不是用户本人输入
NOT_USER = re.compile(r"\s*(Another Claude session sent a message|<agent-message|<task-notification)")

try:
    p = json.loads(sys.stdin.buffer.read().decode("utf-8"))
except Exception:
    sys.exit(0)
if not isinstance(p, dict):
    sys.exit(0)
ENDED_DIR = os.environ.get("KEEPALIVE_ENDED_DIR") or os.path.expanduser("~/.claude/state/keepalive-ended")
sid = str(p.get("session_id") or "").strip()
if p.get("hook_event_name") == "SessionEnd":
    if sid and "/" not in sid:
        os.makedirs(ENDED_DIR, exist_ok=True)
        open(os.path.join(ENDED_DIR, sid), "w").close()
        for n in os.listdir(ENDED_DIR):
            f = os.path.join(ENDED_DIR, n)
            if time.time() - os.path.getmtime(f) > 86400:
                os.remove(f)
    sys.exit(0)
if os.environ.get("CLAUDE_CODE_ENTRYPOINT") == "sdk-cli":
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

def scan():
    """读一遍 transcript：(主线程上下文, 是否 5 分钟 TTL, 用户本人最后一条消息的时间,
    最近一次「最后一次唤醒」消息的时间, 用户本人最后一条消息之后有没有保活回合回了「完」)。"""
    used = 0
    short_ttl = False         # 最近一次有缓存写入的调用是 5 分钟 TTL
    last_user_at = None       # 用户本人最后一条消息的时间
    handoff_at = None         # 最近一次「最后一次唤醒」消息的时间
    in_wake = False           # 上一条用户角色的文字消息是保活唤醒
    done = False              # 用户本人最后一条消息之后，有保活回合回了「完」
    with open(tp, encoding="utf-8") as f:
        for line in f:
            try:
                o = json.loads(line)
            except Exception:
                continue
            m = o.get("message") if isinstance(o, dict) else None
            if not isinstance(m, dict) or o.get("isSidechain") or o.get("type") not in ("user", "assistant"):
                continue
            if m.get("role") == "assistant":
                reply = text_of(m.get("content"))   # 只含 thinking 或工具调用的续行为 None
                if in_wake and reply is not None:
                    done = reply.strip(DONE_STRIP).lower() in DONE_REPLIES
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
                        done = False
                    in_wake = False
                    continue
                txt = text_of(m.get("content"))
                if txt is None or o.get("isMeta"):
                    continue
                if MARK in txt and HANDOFF_MARK in txt:
                    handoff_at = epoch(o.get("timestamp"))
                in_wake = MARK in txt
                if not txt.lstrip().startswith(MARK) and not NOT_USER.match(txt):
                    last_user_at = epoch(o.get("timestamp"))
                    done = False
    return used, short_ttl, last_user_at, handoff_at, done

used, short_ttl, last_user_at, handoff_at, done = scan()

# 父会话（分片：调用 feature-sharding 的规划会话）有在跑的子会话：子会话结束时一定会唤醒父会话，
# 那时重写缓存的价格是缓存读的 40 倍，所以上下文阈值不适用；最后活动改取子会话 status 文件 at 的较晚者。
SHARD = os.environ.get("KEEPALIVE_SHARDING_DIR") or os.path.expanduser("~/.claude/state/sharding/parents")

def children():
    """(有没有在跑的子会话, 各子会话 status 文件 at 的最晚时间)；任何读失败按没有在跑处理。"""
    try:
        if not sid or "/" in sid or not os.path.isfile(os.path.join(SHARD, sid + ".json")):
            return False, None
        with open(os.path.join(SHARD, sid + ".json"), encoding="utf-8") as f:
            state = json.load(f)["state"]
        with open(os.path.join(state, "tracks.json"), encoding="utf-8") as f:
            tracks = json.load(f)["tracks"]
        if not isinstance(tracks, dict):
            return False, None
        running, latest, seen = False, None, set()
        for n in os.listdir(state):
            if not n.endswith(".status.json"):
                continue
            seen.add(n[:-len(".status.json")])
            try:
                with open(os.path.join(state, n), encoding="utf-8") as f:
                    s = json.load(f)
            except Exception:
                continue
            if not isinstance(s, dict):
                continue
            at = epoch(s.get("at"))
            if at is not None and (latest is None or at > latest):
                latest = at
            if not s.get("ended") and s.get("status") != "完成":
                running = True
        if any(str(t) not in seen for t in tracks):    # 轨道已登记但还没有 status 文件：刚拉起，算在跑
            running = True
        return running, latest
    except Exception:
        return False, None

kids, kid_at = children()
if kids and kid_at is not None and (last_user_at is None or kid_at > last_user_at):
    last_user_at = kid_at

if (used < THRESHOLD and not kids) or short_ttl or last_user_at is None or time.time() - last_user_at > MAX_IDLE:
    sys.exit(0)
if (done and not kids) or (handoff_at is not None and handoff_at >= last_user_at):
    sys.exit(0)

SLEEP = float(os.environ.get("KEEPALIVE_SLEEP") or 3000)
DEADLINE = t0 + float(os.environ.get("KEEPALIVE_DEADLINE") or 3420)
RETRY = float(os.environ.get("KEEPALIVE_RETRY") or 30)
URL = os.environ.get("KEEPALIVE_PROBE_URL") or os.environ.get("ANTHROPIC_BASE_URL") or "https://api.anthropic.com"
final = t0 + 2 * SLEEP - last_user_at > MAX_IDLE

def ended():
    return bool(sid) and "/" not in sid and os.path.exists(os.path.join(ENDED_DIR, sid))

# 本会话已结束，或开睡前的末尾之后会话有了新的一轮，或 transcript 被删、变短
def active():
    if ended():
        return True
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
    if ended():
        sys.exit(0)
    time.sleep(min(30, t0 + SLEEP - time.time()))
while True:
    if active() or time.time() > DEADLINE:
        sys.exit(0)
    if reachable():
        break
    time.sleep(RETRY)
if not kids and scan()[4]:     # 保活回合的「完」常在钩子起跑读 transcript 之后才落盘，唤醒前再读一遍
    sys.exit(0)
sys.exit(3 if final else 2)
' 2>/dev/null
rc=$?
# 约定的停止词随安装语言：REPLY_LANG=zh（中文安装）回「完」，其余回 Done
if [ "${REPLY_LANG:-}" = zh ]; then done_word='「完」字'; else done_word=' Done'; fi
case $rc in
  2) printf '%s%s%s' '[保活] 只回复一个句点，不做别的；下列任一成立时，改为只回一个' "$done_word" '，不带别的字：A. 本会话的任务已做完，没有待用户答复的问题，也没有在跑的后台任务或子智能体。B. 本会话已用 handoff 技能写出交接文件，把剩余工作交给别的会话：剩余工作、待用户答复的问题和仍在跑的任务都已写进交接文件，写完之后本会话没有新进展（交接里已登记的任务发来完成通知不算新进展）。' >&2; exit 2 ;;
  3) printf '%s' '[保活] 用户已离开近 8 小时，这是最后一次保活。本回合不做提交、推送、开 PR、合并等收尾，也不重新提问，按第一条成立的做完就结束：A. 还有要新会话接着做的实质工作，或有待用户答复的问题（不论答复后剩什么）：用 handoff 技能交接，走完该技能的全部步骤。B. 剩下的只有收尾（提交、推送、开 PR、合并、在跑任务回报后收尾），可夹带用户本人要做的事：在本任务的进度源末尾追加一节，逐条写剩下的动作和各自的核对命令，在跑任务写明产物路径，用户本人要做的事一并写进（没有进度源就在工作目录新建只追加的 PROGRESS.md），然后回一个句点。C. 任务已做完，或剩下的只有用户本人能做、做完后不用会话接着做的事（如人工登录、人工审核），或已有的交接或计划文件已写全剩余工作且之后没有新进展：只回一个句点。' >&2; exit 2 ;;
esac
exit 0
}
