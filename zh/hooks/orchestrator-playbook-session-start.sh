#!/usr/bin/env bash
# SessionStart hook: 把编排者 playbook 注入主线程 context。
# 仅主线程 —— subagent 走独立的 SubagentStart，不继承此注入（这正是编排规则
# 要放这里、不放 CLAUDE.md 的原因：CLAUDE.md 会灌进每个 subagent）。
# playbook 是唯一真源，本脚本只读它、不复述 —— 无第二份，无漂移面。
# 用 python3 json.dumps 生成，绕开手搓 bash 转义的控制字符坑。
#
# 用法：不带参数注入全文；--part N 只注入第 N 段（N 从 1 起），段号超出总段数时什么都不输出。
# Claude Code 把超过 10,000 字符（JavaScript 字符串长度，即 UTF-16 码元）的单个钩子
# additionalContext 存成文件、只给模型 2KB 预览；上限按单个钩子的输出算，同一事件注册的几个钩子
# 各自计数（2026-11-07 在 Claude Code 2.1.319 实测：两个各 9,500 字符的钩子都完整送达，
# 一个 12,000 字符的只剩预览）。所以 settings 里按段注册几次本钩子，每段不超过 9,500：
# 先按 "## " 节标题切，单节放不下按空行切，单段放不下按行切，单行放不下按字符硬切，不劈开代理对。
# 只有一段时原样输出全文；多段时每段以 "[orchestrator playbook, part i of n]" 一行起头，
# 去掉这行后按段号拼接即全文。
# 同一事件的几个钩子并行跑，模型看到的顺序是各钩子结束的先后（同一实测里 4 段按 4、1、3、2 到达），
# 所以第 N 段先等 (N-1)×DELAY 秒再输出，让各段按段号先后结束；DELAY 缺省 0.3。
set -euo pipefail

# playbook 与 hooks/ 同级：按脚本自身位置解析，仓库放在哪里都能找到
PLAYBOOK="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/orchestrator-playbook.md"

PART=""
if [ "${1:-}" = "--part" ]; then PART="${2:-}"; fi

exec python3 -I -c '
import json, re, sys

MAX = 9500  # 每段上限，UTF-16 码元，含标签行

def ulen(s):
    return len(s.encode("utf-16-le")) // 2

def hard_split(s, budget):
    out, cur, n = [], [], 0
    for ch in s:
        w = ulen(ch)
        if n + w > budget and cur:
            out.append("".join(cur)); cur, n = [], 0
        cur.append(ch); n += w
    if cur:
        out.append("".join(cur))
    return out

LEVELS = [r"(?m)(?=^## )", r"(?<=\n\n)", r"(?<=\n)"]

def pieces(s, budget, level=0):
    if ulen(s) <= budget:
        return [s]
    if level == len(LEVELS):
        return hard_split(s, budget)
    units = [u for u in re.split(LEVELS[level], s) if u]
    if len(units) == 1:
        return pieces(s, budget, level + 1)
    out = []
    for u in units:
        out.extend(pieces(u, budget, level + 1) if ulen(u) > budget else [u])
    return out

def pack(units, budget):
    chunks, cur = [], ""
    for u in units:
        if cur and ulen(cur) + ulen(u) > budget:
            chunks.append(cur); cur = ""
        cur += u
    if cur:
        chunks.append(cur)
    return chunks

def label(i, n):
    return "[orchestrator playbook, part %d of %d]\n" % (i, n)

def emit(text):
    sys.stdout.write(json.dumps({
        "hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": text}
    }))

try:
    content = open(sys.argv[1], encoding="utf-8").read()
except Exception as e:
    content = "Error reading orchestrator-playbook.md: " + str(e)

part = sys.argv[2]
if not part:
    emit(content); sys.exit(0)
if not part.isdigit() or int(part) < 1:
    sys.exit(0)
part = int(part)

if ulen(content) <= MAX:
    chunks = [content]
else:
    budget = MAX - ulen(label(99, 99))
    chunks = pack(pieces(content, budget), budget)
n = len(chunks)
if part > n:
    sys.exit(0)
if n > 1:
    import os, time
    try:
        time.sleep((part - 1) * float(os.environ.get("PLAYBOOK_PART_DELAY", "0.3")))
    except ValueError:
        pass
emit(chunks[0] if n == 1 else label(part, n) + chunks[part - 1])
' "$PLAYBOOK" "$PART"
