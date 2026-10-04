#!/bin/bash
# PreToolUse(Edit|Write|MultiEdit|NotebookEdit|Bash) hook: HANDOFF.md 只由 handoff 技能生成。
#
# 交接文件要从会话记录里抽出的用户原话与仓库状态取证，旧版要归档；这两步都在
# handoff 技能里（extract.py 取证，finalize.sh 归档并把 HANDOFF.new.md 落位）。
# 手改 HANDOFF.md 会绕过取证与归档，接手的会话读到的就是没有来源的转述。
# 主线程与子智能体一律适用。
#
# 只认文件名恰为 HANDOFF.md（大小写敏感）；HANDOFF.new.md、HANDOFF-<轨道>.md、
# PROGRESS.md 不受限。含 HANDOFF 字样且能匹配到 HANDOFF.md 的通配符（HANDOFF*）同样算。
# Edit/Write/MultiEdit/NotebookEdit：目标文件名是 HANDOFF.md 就拒绝。
# Bash：先摘掉 heredoc 正文（那是数据，不是命令；喂给解释器或 shell 的正文另行检查），
#   再按 && || ; | 换行 括号与反引号拆成子命令逐段判断，bash/sh/zsh -c 的命令串与 eval
#   的参数同样逐段判断（最多嵌套 3 层）。拒绝：
#   > >> 重定向写到它；tee 写到它；sed -i、perl -i、awk -i inplace 改它；ed/ex 打开它；
#   truncate 它；cp/mv/rm/ln 以它为源或目标；git checkout/restore/rm/mv 指到它；
#   python/node/ruby/perl 的内联代码（-c/-e、<<<、heredoc 正文）里出现它。
#   其余命令只是读它或提到它（cat/head/grep/sed -n/wc/diff/git diff|log|show），放行；
#   bash …/skills/handoff/scripts/finalize.sh <dir> 不命中上面任何一条，同样放行。
# 任何异常一律放行，hook 不该卡死会话。
python3 -c '
import fnmatch, json, os, re, shlex, sys

try:
    p = json.load(sys.stdin)
except Exception:
    sys.exit(0)
if not isinstance(p, dict) or not isinstance(p.get("tool_input"), dict):
    sys.exit(0)
tool = p.get("tool_name")
ti = p["tool_input"]

NAME = "HANDOFF.md"
REASON = "交接文件只由 handoff 技能生成：写 `HANDOFF.new.md` 后运行 `finalize.sh`。"
MENTION = re.compile(r"(?<![\w.-])HANDOFF\.md(?![\w-]|\.\w)")
WRAPPERS = ("sudo", "command", "exec", "nohup", "time", "env")
SHELLS = {"bash", "sh", "zsh", "dash", "ksh"}
MAX_DEPTH = 3

def deny():
    print(json.dumps({"hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "permissionDecision": "deny",
        "permissionDecisionReason": REASON}}))
    sys.exit(0)

def is_handoff(path):
    base = os.path.basename(str(path).strip("\"\x27").rstrip("/"))
    if base == NAME:
        return True
    return "HANDOFF" in base and any(c in base for c in "*?[") and fnmatch.fnmatchcase(NAME, base)

def tokens(seg):
    try:
        return shlex.split(seg)
    except ValueError:
        return seg.split()

def split_cmd(s):
    # 引号外遇到 ; | & 换行 括号 反引号就断开；>& 与 &> 属于重定向，不断开
    segs, cur, q, i = [], [], None, 0
    while i < len(s):
        c = s[i]
        if c == "\\" and q != "\x27" and i + 1 < len(s):
            cur.append(s[i:i + 2]); i += 2; continue
        if q:
            if c == q:
                q = None
            cur.append(c)
        elif c in "\"\x27":
            q = c; cur.append(c)
        elif c == "&" and ((i > 0 and s[i - 1] == ">") or s[i + 1:i + 2] == ">"):
            cur.append(c)
        elif c in ";&|\n()`":
            segs.append("".join(cur)); cur = []
        else:
            cur.append(c)
        i += 1
    segs.append("".join(cur))
    return segs

def strip_redirects(seg):
    # 引号外的 > 才是重定向：摘出写入目标，剩下的交给 shlex；grep ">" 里的 > 是参数
    out, targets, q, i = [], [], None, 0
    while i < len(seg):
        c = seg[i]
        if c == "\\" and q != "\x27" and i + 1 < len(seg):
            out.append(seg[i:i + 2]); i += 2; continue
        if q:
            if c == q:
                q = None
            out.append(c); i += 1; continue
        if c in "\"\x27":
            q = c; out.append(c); i += 1; continue
        if c != ">":
            out.append(c); i += 1; continue
        while out and (out[-1].isdigit() or out[-1] == "&"):
            out.pop()
        i += 1
        while i < len(seg) and seg[i] in ">|":
            i += 1
        if seg[i:i + 1] == "&":                 # >&2 复制文件描述符，不写文件
            while i < len(seg) and not seg[i].isspace():
                i += 1
            continue
        while i < len(seg) and seg[i].isspace():
            i += 1
        j = i
        while j < len(seg) and not seg[j].isspace():
            j += 1
        targets.append(seg[i:j])
        i = j
    return "".join(out), targets

def interpreter(name):
    if re.fullmatch(r"python[0-9.]*", name):
        return "python"
    return {"node": "node", "nodejs": "node", "perl": "perl", "ruby": "ruby"}.get(name)

def inline_code(lang, args):
    # -c/-e 这类选项后的代码与 <<< 的内容；遇到脚本文件名就停，那是看不到代码的调用
    code, i = [], 0
    while i < len(args):
        a = args[i]
        nxt = args[i + 1] if i + 1 < len(args) else ""
        if a.startswith("<<<"):
            code.append(a[3:] or nxt); i += 1
        elif a == "--" or not a.startswith("-") or a == "-":
            break
        elif lang == "python" and re.fullmatch(r"-[bBdEiIOqsSuvR]*c", a):
            code.append(nxt); i += 1
        elif lang == "python" and a in ("-W", "-X"):
            i += 1
        elif lang == "python" and a == "-m":
            break
        elif lang == "node" and a in ("-e", "--eval", "-p", "--print", "-pe"):
            code.append(nxt); i += 1
        elif lang == "node" and a.split("=", 1)[0] in ("--eval", "--print") and "=" in a:
            code.append(a.split("=", 1)[1])
        elif lang in ("perl", "ruby") and a[:2] not in ("-M", "-m", "-I", "-r", "-F", "-x") \
                and re.fullmatch(r"-\w*[eE]", a):
            code.append(nxt); i += 1
        i += 1
    return "\n".join(code)

def inline_command(name, args):
    # eval 把参数拼成一条命令；bash -c 与 -lc 这类合写取第一个非选项参数
    if name == "eval":
        return " ".join(args)
    c_seen = False
    for a in args:
        if len(a) > 1 and a[0] in "-+" and not a.startswith("--"):
            c_seen = c_seen or "c" in a[1:]
        elif not a.startswith("--"):
            return a if c_seen else None
    return None

def short_has(args, letter):
    return any(a.startswith("-") and not a.startswith("--") and letter in a[1:] for a in args)

def operands(args):
    return [a for a in args if not a.startswith("-")]

def awk_inplace(args):
    for k, a in enumerate(args):
        if a in ("-i", "--include") and args[k + 1:k + 2] == ["inplace"]:
            return True
        if a in ("-iinplace", "--include=inplace"):
            return True
    return False

def seg_writes(seg, depth):
    seg, targets = strip_redirects(seg)
    if any(is_handoff(t) for t in targets):
        return True
    args = tokens(seg)
    while args and re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", args[0]):
        args = args[1:]
    while args and os.path.basename(args[0]) in WRAPPERS:
        args = args[1:]
        while args and (args[0].startswith("-") or re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", args[0])):
            args = args[1:]
    if not args:
        return False
    name, rest = os.path.basename(args[0]), args[1:]
    hit = any(is_handoff(a) for a in operands(rest))
    if name in SHELLS or name == "eval":
        code = inline_command(name, rest)
        return code is not None and depth < MAX_DEPTH and scan(code, depth + 1)
    lang = interpreter(name)
    if lang and MENTION.search(inline_code(lang, rest)):
        return True
    if name in ("tee", "ed", "ex", "truncate", "cp", "mv", "rm", "ln"):
        return hit
    if name in ("sed", "gsed"):
        return hit and (short_has(rest, "i") or any(a.startswith("--in-place") for a in rest))
    if name == "perl":
        return hit and short_has(rest, "i")
    if name in ("awk", "gawk"):
        return hit and awk_inplace(rest)
    if name == "git":
        sub = operands(rest)
        return hit and bool(sub) and sub[0] in ("checkout", "restore", "rm", "mv")
    return False

HEREDOC = re.compile(r"(?<![<\w])<<-?[ \t]*([\x27\"]?)([A-Za-z_][A-Za-z0-9_]*)\1[^\n]*\n(.*?)"
                     r"(?:\n[ \t]*\2[ \t]*(?=\n|$)|\Z)", re.S)

def scan(cmd, depth):
    # heredoc 正文是喂给命令的数据：给解释器的查代码里有没有它，给 shell 的当命令查，
    # 其余不看，免得正文里的 > 引用行或示例命令被当成写操作
    kept, last = [], 0
    for m in HEREDOC.finditer(cmd):
        start = cmd.rfind("\n", 0, m.start()) + 1
        for seg in split_cmd(cmd[start:m.start()]):
            t = [a for a in tokens(seg) if not re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", a)]
            while t and os.path.basename(t[0]) in WRAPPERS:
                t = t[1:]
            name = os.path.basename(t[0]) if t else ""
            if interpreter(name) and MENTION.search(m.group(3)):
                return True
            if name in SHELLS and depth < MAX_DEPTH and scan(m.group(3), depth + 1):
                return True
        kept.append(cmd[last:m.start(3)])
        last = m.end()
    kept.append(cmd[last:])
    cmd = "".join(kept)
    # 双引号里的 $(...) 与反引号不会被 split_cmd 拆开，单独取出来再查一遍
    inner = re.findall(r"\$\(([^()]*)\)", cmd) + re.findall(r"`([^`]*)`", cmd)
    segs = split_cmd(cmd) + [x for body in inner for x in split_cmd(body)]
    return any(seg.strip() and seg_writes(seg, depth) for seg in segs)

if tool in ("Edit", "Write", "MultiEdit", "NotebookEdit"):
    fp = ti.get("notebook_path" if tool == "NotebookEdit" else "file_path")
    if isinstance(fp, str) and os.path.basename(fp) == NAME:
        deny()
elif tool == "Bash":
    cmd = ti.get("command")
    if isinstance(cmd, str) and scan(cmd, 0):
        deny()
sys.exit(0)
' 2>/dev/null
exit 0
