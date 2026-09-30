#!/bin/bash
# PreToolUse(Edit|Write|NotebookEdit|MultiEdit|Bash) hook: researcher 子智能体只能新建文件。
#
# researcher 是只读调研、审查、取证、诊断类任务的自定义代理（agents/researcher.md）。
# 这类派发的产出是结论与修改建议，改已有文件的决定权留在主线程：调研者看到的只是
# 任务切片，顺手改动会绕过编排者对文件范围的控制。新建报告文件不碰任何既有内容，放行。
#
# 判据要求 agent_id 存在：agent_id 只在 hook 从子智能体内触发时出现，
# 用 --agent researcher 启动的会话主线程只带 agent_type，不受此限。
#
# Edit/MultiEdit/NotebookEdit 一律拒绝；Write 只在目标已存在时拒绝。
# Bash 同样能改文件，只拦 Edit/Write 等于留了后门。按 && || ; | 与换行拆成子命令逐段判断，
# 命令替换 $(...) 与反引号里的命令也拆出来判断，bash/sh/zsh -c 的命令串与 eval 的参数当作
# 命令同样逐段判断（最多嵌套 3 层），拒绝：
#   sed -i、perl -i 原地改写；> >> 与 tee 写到已存在的文件（/dev/null 与新路径放行）；
#   rm、mv、truncate、chmod、ln -f；cp 的目标已存在；
#   改工作区、暂存区、引用或远端的 git 子命令，以及 git branch -d/-D；
#   内联解释器代码里出现写文件原语，不论目标是否已存在。代码指 python -c、node -e/-p、
#   perl -e、ruby -e 的参数，<<< 的内容，以及喂给这几个解释器的 heredoc 正文；原语是
#   python 以 w/a/x/+ 模式调用的 open 与 Path.open、write_text/write_bytes、os.remove/unlink/
#   rename/replace/rmdir/removedirs/renames、shutil.move/copy*/rmtree、Path 的 unlink/rename/
#   replace/touch，node fs 的 writeFile*/appendFile*/rm*/unlink*/rename*/copyFile*/cp/truncate
#   与 createWriteStream，perl 以 > 或 >> 打开、unlink、rename，ruby 的 File.write/binwrite/
#   delete/unlink/rename、IO.write、以 w/a/+ 打开的 File.open/File.new、FileUtils。
#   写新文件同样拒绝，报告文件改用 Write 工具新建。python3 script.py 这类执行脚本文件的
#   调用看不到代码，不在判断范围内。
# 相对路径按输入里的 cwd 解析，并跟随同一条命令里前面以 && || ; 或换行相接的 cd/pushd；
# cd 的目标不是字面量（含 $ 或反引号，或是 cd -）时，之后的相对写入目标一律按已存在算。
# 任何异常一律放行，hook 不该卡死会话。
python3 -c '
import json, os, re, shlex, sys

try:
    p = json.load(sys.stdin)
except Exception:
    sys.exit(0)
if not isinstance(p, dict):
    sys.exit(0)
if p.get("agent_type") != "researcher" or not str(p.get("agent_id") or "").strip():
    sys.exit(0)

tool = p.get("tool_name")
ti = p.get("tool_input") if isinstance(p.get("tool_input"), dict) else {}
cwd = str(p.get("cwd") or os.getcwd())         # 当前段的工作目录；None 表示无从确定

def resolve(path):
    path = os.path.expanduser(path)
    if os.path.isabs(path):
        return path
    return None if cwd is None else os.path.join(cwd, path)

def exists(path):
    r = resolve(path)
    return True if r is None else os.path.lexists(r)

EXISTING = "只读派发只能新建报告文件，不改已有文件；把要改的内容与位置写进回传，由主线程修改。"
INLINE = ("只读派发不用内联解释器代码写文件：报告文件用 Write 工具新建；"
          "要改已有文件，把内容与位置写进回传，由主线程修改。")

def deny(reason=EXISTING):
    print(json.dumps({"hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "permissionDecision": "deny",
        "permissionDecisionReason": reason
    }}))
    sys.exit(0)

GIT_WRITES = {"checkout", "switch", "reset", "restore", "commit", "push", "stash", "clean",
              "apply", "am", "rebase", "merge", "cherry-pick", "revert", "tag"}
GIT_VALUED = {"-C", "-c", "--git-dir", "--work-tree", "--namespace", "--exec-path", "--config-env"}
ALWAYS = {"rm", "mv", "truncate", "chmod"}
DEVICES = {"/dev/null", "/dev/stdout", "/dev/stderr", "/dev/tty"}
SHELLS = {"bash", "sh", "zsh", "dash", "ksh"}
MAX_DEPTH = 3

MODE = r"[\x27\"][rbtU]*[wax+][rbtUwax+]*[\x27\"]"   # 整个字面量都是模式字符，"a.png" 不算
WRITES = {
    "python": [r"\bopen\s*\((?:[^()\n;]|\([^()\n]*\))*?(?:,\s*|mode\s*=\s*)" + MODE,
               r"\.open\s*\(\s*(?:mode\s*=\s*)?" + MODE,
               r"\.write_(?:text|bytes)\s*\(",
               r"\bos\.(?:remove|unlink|rename|replace|rmdir|removedirs|renames)\s*\(",
               r"\bshutil\.(?:move|copy\w*|rmtree)\s*\(",
               r"\.(?:unlink|touch)\s*\(",
               r"\bPath\s*\((?:[^()\n]|\([^()\n]*\))*\)\s*\.(?:rename|replace)\s*\("],
    "node": [r"\b(?:writeFile|appendFile|rmdir|rmSync|unlink|rename|copyFile|createWriteStream)\w*\s*\(",
             r"(?:\bfs\w*|\bpromises|\))\.(?:rm|cp|truncate)\w*\s*\("],
    "perl": [r"\bopen\s*\(?\s*(?:my\s+|local\s+)?[\$\*]?\w+\s*,\s*[\x27\"]\s*\+?>",
             r"\b(?:unlink|rename)\b"],
    "ruby": [r"\bFile\.(?:write|binwrite|delete|unlink|rename)\b",
             r"\bIO\.(?:write|binwrite)\b",
             r"\bFile\.(?:open|new)\s*\(?[^;\n)]*?,\s*[\x27\"][rbt]*[wa+]",
             r"\bFileUtils\b"],
}

def code_writes(lang, code):
    if any(re.search(rx, code) for rx in WRITES[lang]):
        return True
    if lang == "python":                        # p = Path(...) 之后的 p.rename/p.replace
        for n in re.findall(r"\b(\w+)\s*=\s*(?:pathlib\.)?Path\s*\(", code):
            if re.search(r"\b" + re.escape(n) + r"\s*\.\s*(?:rename|replace)\s*\(", code):
                return True
    return False

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
            code.append(a[3:] or nxt)
        elif a == "--" or not a.startswith("-") or a == "-":
            break
        elif lang == "python" and (a == "-c" or re.fullmatch(r"-[bBdEiIOqsSuvR]*c", a)):
            code.append(nxt); i += 1
        elif lang == "python" and a in ("-W", "-X"):
            i += 1
        elif lang == "python" and a == "-m":
            break
        elif lang == "node" and (a in ("-e", "--eval", "-p", "--print", "-pe")):
            code.append(nxt); i += 1
        elif lang == "node" and a.split("=", 1)[0] in ("--eval", "--print") and "=" in a:
            code.append(a.split("=", 1)[1])
        elif lang == "node" and a in ("-r", "--require", "--import", "--loader"):
            i += 1
        elif lang in ("perl", "ruby") and a in ("-r", "-I", "-C", "-x"):
            i += 1
        elif lang in ("perl", "ruby") and a[:2] not in ("-M", "-m", "-I", "-r", "-F", "-x") \
                and re.fullmatch(r"-\w*[eE]", a):
            code.append(nxt); i += 1
        i += 1
    return "\n".join(code) if code else None

def inline_command(name, args):
    # eval 把参数拼成一条命令；bash -c 与 -lc 这类合写取第一个非选项参数
    if name == "eval":
        return " ".join(args)
    c_seen, i = False, 0
    while i < len(args):
        a = args[i]
        if len(a) > 1 and a[0] in "-+" and not a.startswith("--"):
            c_seen = c_seen or "c" in a[1:]
            if "o" in a[1:] or "O" in a[1:]:
                i += 1
        elif not a.startswith("--"):
            return a if c_seen else None
        i += 1
    return None

def tokens(seg):
    try:
        return shlex.split(seg)
    except ValueError:
        return seg.split()

def split_cmd(s, ops=None):
    # 引号外遇到 ; | 换行 括号 反引号与后台 & 就断开；>& 与 &> 属于重定向，不断开。
    # 传入 ops 时依次记下每段后面的分隔符（&& 与 || 各算一个），末段记空串
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
            op = s[i:i + 2] if s[i:i + 2] in ("&&", "||") else c
            segs.append("".join(cur)); cur = []
            if ops is not None:
                ops.append(op)
            i += len(op); continue
        else:
            cur.append(c)
        i += 1
    segs.append("".join(cur))
    if ops is not None:
        ops.append("")
    return segs

def short_has(args, letter):
    return any(a.startswith("-") and not a.startswith("--") and letter in a[1:] for a in args)

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
            out.pop()                           # 2> 与 &> 里的文件描述符前缀
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
        if seg[i:j].strip("\"\x27"):
            targets.append(seg[i:j].strip("\"\x27"))
        i = j
    return "".join(out), targets

def writes_existing(seg, depth):
    # 改已有文件返回 True；解释器代码写文件与 -c/eval 里命中的规则返回对应的拒绝理由
    seg, targets = strip_redirects(seg)
    args = tokens(seg)
    if any(t not in DEVICES and exists(t) for t in targets):
        return True
    while args and re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", args[0]):
        args = args[1:]
    if not args:
        return False
    name, rest = os.path.basename(args[0]), args[1:]
    if name in ("sudo", "command", "exec", "nohup", "time", "env"):
        return writes_existing(" ".join(shlex.quote(a) for a in rest), depth)
    if name in SHELLS or name == "eval":
        code = inline_command(name, rest)
        return code is not None and depth < MAX_DEPTH and scan(code, depth + 1, cwd)
    lang = interpreter(name)
    if lang:
        code = inline_code(lang, rest)
        if code is not None and code_writes(lang, code):
            return INLINE
    if name in ALWAYS:
        return True
    if name in ("sed", "gsed"):
        return short_has(rest, "i") or any(a.startswith("--in-place") for a in rest)
    if name == "perl":
        return short_has(rest, "i")
    if name == "ln":
        return short_has(rest, "f") or "--force" in rest
    if name == "tee":
        return any(not a.startswith("-") and a not in DEVICES and exists(a) for a in rest)
    if name == "cp":
        pos, tdir, j = [], None, 0
        while j < len(rest):
            a = rest[j]
            if a == "-t" or a == "--target-directory":
                tdir = rest[j + 1] if j + 1 < len(rest) else None; j += 2; continue
            if a.startswith("--target-directory="):
                tdir = a.split("=", 1)[1]
            elif not a.startswith("-"):
                pos.append(a)
            j += 1
        if tdir is None:
            if len(pos) < 2:
                return False
            tdir, pos = pos[-1], pos[:-1]
            if resolve(tdir) is not None and not os.path.isdir(resolve(tdir)):
                return exists(tdir)
        return any(exists(os.path.join(tdir, os.path.basename(s.rstrip("/")))) for s in pos)
    if name == "git":
        j = 0
        while j < len(rest):                    # 跳过 git 全局选项，定位子命令
            a = rest[j]
            if a in GIT_VALUED: j += 2; continue
            if a.startswith("-"): j += 1; continue
            break
        if j >= len(rest):
            return False
        sub, sargs = rest[j], rest[j + 1:]
        if sub in GIT_WRITES:
            return True
        if sub == "branch":
            return "--delete" in sargs or any(
                a.startswith("-") and not a.startswith("--") and ("d" in a or "D" in a) for a in sargs)
    return False

def next_cwd(seg, op, where):
    # cd/pushd 之后各段的当前目录；进管道或后台的 cd 不影响后面。目标不是字面量时为 None
    if op in ("|", "&"):
        return where
    t = tokens(seg)
    if not t or t[0] not in ("cd", "pushd", "popd"):
        return where
    if t[0] == "popd" or op in ("(", "`"):                # cd $(...) 与 cd `...` 的目标要运行时才知道
        return None
    args = [a for a in t[1:] if (a == "-" or not a.startswith("-")) and not re.match(r"\d*[<>]", a)]
    if not args:
        return os.path.expanduser("~") if t[0] == "cd" else None
    d = args[0]
    if d == "-" or "$" in d or "`" in d or d.startswith("+"):
        return None
    d = os.path.expanduser(d)
    if os.path.isabs(d):
        return os.path.normpath(d)
    return None if where is None else os.path.normpath(os.path.join(where, d))

HEREDOC = re.compile(r"(?<![<\w])<<-?[ \t]*([\x27\"]?)([A-Za-z_][A-Za-z0-9_]*)\1[^\n]*\n(.*?)"
                     r"(?:\n[ \t]*\2[ \t]*(?=\n|$)|\Z)", re.S)

def scan(cmd, depth, where):
    global cwd
    # heredoc 喂给解释器的正文就是它要跑的代码
    for m in HEREDOC.finditer(cmd):
        start = cmd.rfind("\n", 0, m.start()) + 1
        end = cmd.find("\n", m.start())
        for seg in split_cmd(cmd[start:end]):
            t = [a for a in tokens(seg) if not re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", a)]
            while t and t[0] in ("sudo", "command", "exec", "nohup", "time", "env"):
                t = t[1:]
            lang = interpreter(os.path.basename(t[0])) if t else None
            if lang and code_writes(lang, m.group(3)):
                return INLINE
    ops, start = [], where
    segs = split_cmd(cmd, ops)
    stack, in_bt = [], False
    for seg, op in zip(segs, ops):
        cwd = where
        r = seg.strip() and writes_existing(seg, depth)
        if r:
            return EXISTING if r is True else r
        where = next_cwd(seg, op, where)
        if op == "(" or (op == "`" and not in_bt):    # 子 shell 里的 cd 不带到外面
            stack.append(where)
        elif op in (")", "`") and stack:
            where = stack.pop()
        in_bt = in_bt != (op == "`")
    inner = re.findall(r"\$\(([^()]*)\)", cmd) + re.findall(r"`([^`]*)`", cmd)
    for x in [x for body in inner for x in split_cmd(body)]:
        cwd = start
        r = x.strip() and writes_existing(x, depth)
        if r:
            return EXISTING if r is True else r
    return None

if tool in ("Edit", "MultiEdit", "NotebookEdit"):
    deny()
if tool == "Write":
    fp = ti.get("file_path")
    if isinstance(fp, str) and fp.strip() and exists(fp):
        deny()
    sys.exit(0)                                 # 新建报告文件，放行
if tool == "Bash":
    cmd = ti.get("command")
    if not isinstance(cmd, str):
        sys.exit(0)
    reason = scan(cmd, 0, cwd)
    if reason:
        deny(reason)
sys.exit(0)
' 2>/dev/null
exit 0
