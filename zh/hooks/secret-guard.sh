#!/bin/bash
# PreToolUse(Bash|Read) hook: 密钥值不进入模型上下文。
#
# 工具输出会原样进入上下文，随后留在会话记录里，还可能被写进报告或提交；密钥一旦
# 打印出来就等于已经外泄，事后无从收回。所以在调用前拦「会把值打印出来」的操作，
# 而不拦「用到值」的操作：source .env 后跑命令、curl 带上 $TOKEN、test -n 判断存在，
# 值都只在进程里流转，不会出现在输出里。
#
# Read：文件名是 .env 或 .env.* 就拒绝；.env.example/.sample/.template 是约定俗成的
#   无值样例，放行。文件名按小写比较，大小写不敏感的文件系统上 .ENV 就是 .env。
# Bash：按 && || ; | 与换行拆成子命令逐段判断，命令替换 $(...) 与反引号也拆开，
#   这样 git check-ignore .env 这类只提到文件名的命令不会因为别的片段被误伤。
#   bash/sh/zsh -c 的命令串与 eval 的参数当作命令同样逐段判断，最多嵌套 3 层。
#   heredoc 正文与单引号里的文字是数据，不当命令判：喂给 bash/sh/zsh 的正文照命令判；
#   定界符不带引号时正文里的 $(...) 与反引号会执行，照命令判；其余正文不看。
#   逐段只看命令名与它的参数：
#   打印文件内容类（cat/less/more/head/tail/bat/nl/awk/tac、非就地的 sed，以及
#   diff/sdiff/comm/sort/uniq/cut/rev/strings/xxd/od/hexdump/base64/paste/fold/column）
#   的文件参数或 < 重定向是 .env；
#   grep/rg 的文件参数是 .env 且没带只报计数、只报是否命中或只报文件名的选项；
#   递归的 grep（-r/-R/--recursive）与会搜点文件的 rg（--hidden、-.、-uu、-uuu）在搜索根
#   （目录参数，没有就是当前目录）下任意深度有 .env，同样没带上述只报计数类选项，且这个
#   .env 没被 --exclude、--exclude-dir、rg 的 -g/--glob 取反模式排掉，也没因 --include 或
#   rg 的正向 -g 落在搜索范围外。.git 与 node_modules 不查；遍历超过 20000 项就放行，
#   大目录树上的 hook 不能拖住每条命令。rg 默认跳过点文件，不带这些选项的 rg 不查目录；
#   echo/printf 展开名称含 KEY/SECRET/TOKEN/PASSWORD/PASSWD/CREDENTIAL 的变量；
#   printenv 不带参数或参数名含上述片段；env、export -p、set 不带命令或赋值地单独使用。
#   ${#VAR} 只给长度，不算展开。
#   相对的搜索根按输入里的 cwd 解析，并跟随同一条命令里前面以 && || ; 或换行相接的
#   cd/pushd；cd 的目标不是字面量（含 $ 或反引号，或是 cd -）时搜索根无从确定，按含 .env 算。
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
cwd = str(p.get("cwd") or os.getcwd())

SAMPLES = {".env.example", ".env.sample", ".env.template"}
SECRET = re.compile(r"KEY|SECRET|TOKEN|PASSWORD|PASSWD|CREDENTIAL", re.I)

def is_env_file(path):
    name = os.path.basename(str(path)).lower()
    if name in SAMPLES:
        return False
    return re.fullmatch(r"\.env(\..*|\*.*)?", name) is not None

def deny(reason):
    print(json.dumps({"hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "permissionDecision": "deny",
        "permissionDecisionReason": reason}}))
    sys.exit(0)

SAFE = ("需要确认的是「有没有」而不是「是什么」时，改用不打印值的写法："
        "看某项是否配置用 grep -c \x27^NAME=\x27 .env 或 grep -q NAME .env；"
        "看变量是否存在用 test -n \"$API_KEY\" && echo set 或 [ -n \"$TOKEN\" ]；"
        "要带着这些变量跑命令用 source .env 后直接执行，或 env FOO=1 cmd；"
        "递归搜索用 --exclude=\x27.env*\x27（rg 用 -g \x27!.env*\x27）把 .env 排掉；"
        "要了解有哪些配置项读 .env.example。")

if tool == "Read":
    fp = ti.get("file_path")
    if isinstance(fp, str) and is_env_file(fp):
        deny("密钥值不能进入模型上下文，不读取 .env 类文件。" + SAFE)
    sys.exit(0)
if tool != "Bash":
    sys.exit(0)
cmd = ti.get("command")
if not isinstance(cmd, str):
    sys.exit(0)

READERS = {"cat", "less", "more", "head", "tail", "bat", "nl", "awk", "gawk", "tac",
           "diff", "sdiff", "comm", "sort", "uniq", "cut", "rev", "strings", "xxd", "od",
           "hexdump", "base64", "paste", "fold", "column"}
GREPS = {"grep", "egrep", "fgrep", "rg"}
PREFIXES = {"sudo", "command", "builtin", "exec", "time", "nohup"}
SHELLS = {"bash", "sh", "zsh", "dash", "ksh"}
MAX_DEPTH = 3
WALK_LIMIT = 20000
VAR = re.compile(r"\$\{?([A-Za-z_][A-Za-z0-9_]*)")

def tokens(seg):
    try:
        return shlex.split(seg)
    except ValueError:
        return seg.split()

def glob_hit(glob, name, rel, is_dir, fold):
    # rg 的 glob 不含 / 时比名字，含 / 时比相对搜索根的路径；以 / 结尾只比目录
    if glob.endswith("/"):
        if not is_dir:
            return False
        glob = glob.rstrip("/")
    glob = glob.lstrip("/")
    while glob.startswith("**/"):
        glob = glob[3:]
    target = rel if "/" in glob else name
    if fold:
        glob, target = glob.lower(), target.lower()
    return fnmatch.fnmatchcase(target, glob)

def env_under(roots, searched):
    # 搜索根下有没有会被搜到的 .env；None 是无从确定的根，按有算
    seen = 0
    for root in roots:
        if root is None:
            return True
        if os.path.isfile(root):
            name = os.path.basename(root)
            if is_env_file(name) and searched(name, name, False):
                return True
            continue
        for dp, dns, fns in os.walk(root):
            seen += len(dns) + len(fns)
            if seen > WALK_LIMIT:
                return False
            base = os.path.relpath(dp, root)
            rel = (lambda n: n) if base == "." else (lambda n: base + "/" + n)
            dns[:] = [d for d in dns
                      if d not in (".git", "node_modules") and searched(d, rel(d), True)]
            if any(is_env_file(f) and searched(f, rel(f), False) for f in fns):
                return True
    return False

def root_path(path, where):
    path = os.path.expanduser(path)
    if os.path.isabs(path):
        return path
    return None if where is None else os.path.join(where, path)

def grep_prints(name, args, stdin_env, where):
    # 带 -c/-q/-l/-L（rg 的 -L 是跟随符号链接，不算）时只输出计数、退出码或文件名
    rg = name == "rg"
    safe_short = "cql" if rg else "cqlL"
    safe_long = {"--count", "--quiet", "--silent", "--files-with-matches", "--files-without-match"}
    valued = set("ABCmef") | (set("gtTrjMEd") if rg else set("dD"))
    valued_long = {"--regexp", "--file", "--exclude", "--include", "--exclude-dir", "--glob",
                   "--iglob", "--directories", "--devices", "--type", "--type-not", "--max-count",
                   "--context", "--after-context", "--before-context", "--replace", "--max-depth"}
    pattern_given, i = False, 0
    positional, end_opts = [], False
    recursive, unrestricted = False, 0
    excl, excl_dir, incl, globs = [], [], [], []
    while i < len(args):
        a = args[i]
        if end_opts or a == "-" or not a.startswith("-"):
            positional.append(a)
        elif a == "--":
            end_opts = True
        elif a.startswith("--"):
            opt, eq, val = a.partition("=")
            if opt in safe_long:
                return False
            if opt in valued_long and not eq:
                val = args[i + 1] if i + 1 < len(args) else ""
                i += 1
            if opt in ("--regexp", "--file"):
                pattern_given = True
            elif opt in ("--recursive", "--dereference-recursive", "--hidden"):
                recursive = True
            elif opt == "--directories" and val == "recurse":
                recursive = True
            elif opt == "--unrestricted":
                unrestricted += 1
            elif opt == "--exclude":
                excl.append(val)
            elif opt == "--exclude-dir":
                excl_dir.append(val)
            elif opt == "--include":
                incl.append(val)
            elif opt in ("--glob", "--iglob"):
                globs.append((val, opt == "--iglob"))
        else:
            letters = a[1:]
            for k, ch in enumerate(letters):
                if ch in safe_short:
                    return False
                if ch in valued:
                    val = letters[k + 1:]
                    if not val:
                        val = args[i + 1] if i + 1 < len(args) else ""
                        i += 1
                    if ch in "ef":
                        pattern_given = True
                    elif ch == "g" and rg:
                        globs.append((val, False))
                    elif ch == "d" and not rg and val == "recurse":
                        recursive = True
                    break
                if ch == "u":
                    unrestricted += 1
                elif ch in ("." if rg else "rR"):
                    recursive = True
        i += 1
    files = positional if pattern_given else positional[1:]
    if stdin_env or any(is_env_file(f) for f in files):
        return True
    if not (recursive or (rg and unrestricted >= 2)):
        return False
    neg = [(g[1:], f) for g, f in globs if g.startswith("!")]
    pos = [(g, f) for g, f in globs if not g.startswith("!")]

    def searched(n, rel, is_dir):
        if any(glob_hit(g, n, rel, is_dir, f) for g, f in neg):
            return False
        if is_dir:
            return not any(fnmatch.fnmatchcase(n, g) for g in excl_dir)
        if any(fnmatch.fnmatchcase(n, g) for g in excl):
            return False
        if incl and not any(fnmatch.fnmatchcase(n, g) for g in incl):
            return False
        return not pos or any(glob_hit(g, n, rel, is_dir, f) for g, f in pos)

    return env_under([root_path(f, where) for f in files] or [where], searched)

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

def prints_secret(seg, depth, where):
    redirected, rest, k = [], [], 0
    toks = tokens(seg)
    while k < len(toks):
        t = toks[k]
        if t == "<":                                    # cmd < .env 等同把 .env 当文件参数
            redirected += toks[k + 1:k + 2]; k += 2; continue
        if t.startswith("<") and not t.startswith("<<"):
            redirected.append(t[1:]); k += 1; continue
        if re.fullmatch(r"\d*>>?\|?", t):               # 输出重定向的目标是写入，不算读取
            k += 2; continue
        if re.match(r"\d*>", t):
            k += 1; continue
        rest.append(t); k += 1
    toks = rest
    while toks and (toks[0] in PREFIXES or re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", toks[0])):
        toks = toks[1:]
    if not toks:
        return False
    name, args = os.path.basename(toks[0]), toks[1:]
    env_in = any(is_env_file(f) for f in redirected)
    if name in READERS or (name in ("sed", "gsed") and not any(
            a == "--in-place" or a.startswith("--in-place=") or
            (a.startswith("-") and not a.startswith("--") and "i" in a) for a in args)):
        return env_in or any(is_env_file(a) for a in args if not a.startswith("-"))
    if name in GREPS:
        return grep_prints(name, args, env_in, where)
    if name in SHELLS or name == "eval":
        code = inline_command(name, args)
        return code is not None and depth < MAX_DEPTH and scan(code, depth + 1, where)
    if name in ("echo", "printf"):
        return any(SECRET.search(v) for v in VAR.findall(seg))
    if name == "printenv":
        names = [a for a in args if not a.startswith("-")]
        return not names or any(SECRET.search(n) for n in names)
    if name == "env":
        rest = list(args)
        while rest and (rest[0].startswith("-") or "=" in rest[0]):
            if rest[0] in ("-u", "--unset", "-C", "--chdir", "-S", "--split-string"):
                rest = rest[1:]
            rest = rest[1:]
        return not rest
    if name == "export":
        return not args or args == ["-p"]
    if name == "set":
        return not args
    return False

def split_cmd(s, ops=None):
    # 引号外遇到 ; & | 换行 括号 反引号就断开；引号内原样保留，grep 模式里的 a|b 不被拆。
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
SUBST = (re.compile(r"\$\(([^()]*)\)"), re.compile(r"`([^`]*)`"))

def outside_single_quotes(s):
    # 单引号里的 $(...) 与反引号只是文字，换成空格；双引号里的照样执行，保留
    out, q, i = [], None, 0
    while i < len(s):
        c = s[i]
        if c == "\\" and q != "\x27" and i + 1 < len(s):
            out.append(s[i:i + 2]); i += 2; continue
        if q == "\x27":
            q = None if c == "\x27" else q
            out.append(" ")
        else:
            if c == "\"":
                q = None if q else c
            elif c == "\x27" and not q:
                q = c
            out.append(c)
        i += 1
    return "".join(out)

def consumer(line):
    # heredoc 所在行最后一段的命令名，即读这段正文的命令
    t = tokens(split_cmd(line)[-1])
    while t and (t[0] in PREFIXES or re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", t[0])):
        t = t[1:]
    return os.path.basename(t[0]) if t else ""

def scan(cmd, depth, where):
    # heredoc 正文是喂给命令的数据，不当命令判：读它的是 shell 时正文就是脚本，照命令查；
    # 定界符不带引号时正文里的 $(...) 与反引号会先执行，单独取出来查；其余正文不看
    kept, last, inner = [], 0, []
    for m in HEREDOC.finditer(cmd):
        name = consumer(cmd[cmd.rfind("\n", 0, m.start()) + 1:m.start()])
        if name in SHELLS and depth < MAX_DEPTH and scan(m.group(3), depth + 1, where):
            return True
        if not m.group(1):
            inner += [x for r in SUBST for x in r.findall(m.group(3))]
        kept.append(cmd[last:m.start(3)])
        last = m.end()
    kept.append(cmd[last:])
    cmd = "".join(kept)
    ops, start = [], where
    segs = split_cmd(cmd, ops)
    stack, in_bt = [], False
    for seg, op in zip(segs, ops):
        if seg.strip() and prints_secret(seg, depth, where):
            return True
        where = next_cwd(seg, op, where)
        if op == "(" or (op == "`" and not in_bt):    # 子 shell 里的 cd 不带到外面
            stack.append(where)
        elif op in (")", "`") and stack:
            where = stack.pop()
        in_bt = in_bt != (op == "`")
    # 双引号里的命令替换 "$(cat .env)" 同样会执行，把替换体单独拿出来再判一遍
    inner += [x for r in SUBST for x in r.findall(outside_single_quotes(cmd))]
    return any(x.strip() and prints_secret(x, depth, start)
               for body in inner for x in split_cmd(body))

if scan(cmd, 0, cwd):
    deny("密钥值不能进入模型上下文，这条命令会把 .env 文件内容或密钥类环境变量的值打印出来。" + SAFE)
sys.exit(0)
' 2>/dev/null
exit 0
