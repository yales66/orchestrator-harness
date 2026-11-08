#!/bin/bash
# Stop hook: 会话登记的任务清单还有未完成项时拦下收工，点名剩余项让会话接着做。
#
# 清单在 ${CHECKLIST_DIR:-~/.claude/state/checklists}/<session_id>.json，格式
#   {"task": "...", "items": [{"id": "...", "title": "...", "status": "todo|doing|done|blocked", "note": "..."}]}
# status 为 done 或 blocked 的项算收住了，其余（含不认识的状态）都算未完成。
#
# 放行条件：子智能体（agent_id 存在，清单归主线程管）；没有清单或清单读不懂；
# 没有未完成项；background_tasks 或 session_crons 非空（后台任务完成或定时唤醒会让会话继续，
# 现在停只是暂停）。
#
# 防循环：同目录 <session_id>.state 记上次拦截时清单内容的 sha256 与连续拦截次数。
# 清单内容变了说明有进展，计数归零；同一份清单原样被拦满 ${CHECKLIST_CAP:-3} 次
# 说明会话真卡住了，放行交还给人。不看 stop_hook_active：它在续跑的那一轮恒为真，
# 靠它会让清单只拦一次；连续续跑另有 harness 的 8 次上限兜底。
# 任何异常一律放行，hook 不该卡死会话。
python3 -c '
import hashlib, json, os, sys

def allow():
    sys.exit(0)

try:
    p = json.loads(sys.stdin.buffer.read().decode("utf-8"))
except Exception:
    allow()
if not isinstance(p, dict):
    allow()
if str(p.get("agent_id") or "").strip():
    allow()
sid = p.get("session_id")
if not isinstance(sid, str) or not sid.strip() or "/" in sid or sid in (".", ".."):
    allow()

d = os.environ.get("CHECKLIST_DIR") or os.path.join(os.path.expanduser("~"), ".claude", "state", "checklists")
path = os.path.join(d, sid + ".json")
try:
    raw = open(path, "rb").read()
    lst = json.loads(raw.decode("utf-8"))
except Exception:
    allow()
items = lst.get("items") if isinstance(lst, dict) else None
if not isinstance(items, list) or not all(isinstance(it, dict) for it in items):
    allow()

pending = [it for it in items if it.get("status") not in ("done", "blocked")]
if not pending:
    allow()
if any(isinstance(p.get(k), list) and p.get(k) for k in ("background_tasks", "session_crons")):
    allow()

try:
    cap = int(os.environ.get("CHECKLIST_CAP") or 3)
except Exception:
    cap = 3
digest = hashlib.sha256(raw).hexdigest()
state_path = os.path.join(d, sid + ".state")
count = 0
try:
    st = json.load(open(state_path, encoding="utf-8"))
    if isinstance(st, dict) and st.get("hash") == digest and isinstance(st.get("count"), int):
        count = st["count"]
except Exception:
    pass
if count >= cap:
    allow()
try:
    with open(state_path, "w", encoding="utf-8") as f:
        json.dump({"hash": digest, "count": count + 1}, f)
except Exception:
    allow()

def label(it):
    parts = [str(it.get(k)).strip() for k in ("id", "title") if str(it.get(k) or "").strip()]
    return " ".join(parts) or "（未命名项）"

names = "、".join(label(it) for it in pending[:8])
if len(pending) > 8:
    names += "等 %d 项" % (len(pending) - 8)
reason = ("任务清单里还有未完成项：%s。接着做下一项；确实被阻塞的项把 status 改成 blocked "
          "并在 note 写明在等什么，全部完成或阻塞后再收尾。（清单：%s）" % (names, path))
print(json.dumps({"decision": "block", "reason": reason}, ensure_ascii=False))
sys.exit(0)
' 2>/dev/null
exit 0
