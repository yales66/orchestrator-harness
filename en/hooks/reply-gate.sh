#!/bin/bash
# Stop hook: 回复出口检查，两项任一命中就拦一次，reason 合并写出命中项。
#
# A1 收尾提议问句：回复以「要我…吗」「Shall I …?」这类提议收尾，会把本可直接做完的
#    可逆动作变成一轮等待，用户还得回来说一句「做吧」。只看最后一个非空段落的末句，
#    问句出现在中间段落或末段后面还跟着陈述，说明动作已经决定，不算。
# A2 回复语言：用户要求中文沟通时，英文长回复需要重写。只在 REPLY_LANG=zh 时启用，
#    en/ 与 zh/ 的脚本逐字节相同，由注册命令里的环境变量区分两种安装。
#    正文夹代码标识符很正常，所以只算中日韩字符与拉丁字母之比，短回复不查。
#
# 两项都先剥掉围栏代码块、行内代码与 URL：代码与链接里的问号和英文不是回复本身的措辞。
# stop_hook_active 为真说明上一轮已因 Stop 钩子续跑，再拦就是循环，必须放行。
# 任何异常一律放行，hook 不该卡死会话。
python3 -c '
import json, os, re, sys

try:
    p = json.loads(sys.stdin.buffer.read().decode("utf-8"))
except Exception:
    sys.exit(0)
if not isinstance(p, dict) or p.get("stop_hook_active"):
    sys.exit(0)
msg = p.get("last_assistant_message")
if not isinstance(msg, str) or not msg.strip():
    sys.exit(0)

text = re.sub(r"(?ms)^[ \t]*(```|~~~).*?^[ \t]*\1[^\n]*$", "", msg)   # 围栏代码块
text = re.sub(r"(?ms)^[ \t]*(```|~~~).*\Z", "", text)                  # 未闭合的围栏延伸到末尾
text = re.sub(r"`[^`\n]*`", "", text)                                   # 行内代码
text = re.sub(r"https?://\S+|www\.\S+", "", text)                       # URL

ZH_OFFER = re.compile(r"需要我|要我|要不要|是否需要|是否要")
EN_OFFER = re.compile(r"\b(shall i|should i|want me to|would you like me to|do you want me to)\b", re.I)

def ends_with_offer(t):
    paras = [s for s in re.split(r"\n[ \t]*\n", t) if s.strip()]
    if not paras:
        return False
    tail = paras[-1].strip().rstrip(" \t*_~>")
    if not tail or tail[-1] not in "？?吗":
        return False
    body = tail[:-1] if tail[-1] in "？?" else tail
    last = re.split(r"[。！？!?；;\n]|(?<=\.)\s", body)[-1]
    return bool(ZH_OFFER.search(last) or EN_OFFER.search(last))

def wrong_language(t):
    if os.environ.get("REPLY_LANG") != "zh":
        return False
    if len(re.sub(r"\s", "", t)) <= 150:
        return False
    cjk = len(re.findall(r"[぀-ヿ㐀-䶿一-鿿가-힯豈-﫿]", t))
    latin = len(re.findall(r"[A-Za-z]", t))
    return cjk + latin > 0 and cjk / (cjk + latin) < 0.2

reasons = []
if ends_with_offer(text):
    reasons.append(
        "回复以提议问句收尾。动作若可逆、在用户当前目标之内、不产生费用也不对外发布，"
        "就直接做完再汇报；确实需要用户拍板时保留提问，但每个待定项写清背景、"
        "各选项对用户的影响和你的推荐，不引用会话内部编号或自造术语。")
if wrong_language(text):
    reasons.append(
        "用户要求中文沟通，用中文重写这条回复，代码、命令、路径和专有名词可保留原文。")
if reasons:
    if len(reasons) > 1:
        reasons = ["%d. %s" % (i + 1, r) for i, r in enumerate(reasons)]
    print(json.dumps({"decision": "block", "reason": "\n".join(reasons)}))
sys.exit(0)
' 2>/dev/null
exit 0
