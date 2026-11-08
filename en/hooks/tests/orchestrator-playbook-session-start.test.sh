#!/bin/bash
# 回归测试: orchestrator-playbook-session-start.sh
# 跑法: bash hooks/tests/orchestrator-playbook-session-start.test.sh
HOOK="$(dirname "$0")/../orchestrator-playbook-session-start.sh"
PLAYBOOK="$(dirname "$0")/../../orchestrator-playbook.md"
PASS=0; FAIL=0
export PLAYBOOK_PART_DELAY=0   # 分段延迟只为在会话里排序，测试里关掉
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT

report() {
  if [ "$1" = "$2" ]; then
    PASS=$((PASS+1)); printf '  ✅ %-56s [%s]\n' "$3" "$1"
  else
    FAIL=$((FAIL+1)); printf '  ❌ %-56s 期望=%s 实际=%s\n' "$3" "$2" "$1"
  fi
}

# check <描述> [环境变量赋值...] —— 不带参数时注入内容须与 hook 同级上一层的 playbook 逐字相等
check() {
  local desc="$1"; shift
  local got
  got=$(env "$@" bash "$HOOK" </dev/null 2>/dev/null | python3 -c '
import json,sys
want=open(sys.argv[1],encoding="utf-8").read()
try: o=json.load(sys.stdin)["hookSpecificOutput"]
except Exception: print("bad-json"); raise SystemExit
if o.get("hookEventName")!="SessionStart": print("wrong-event")
elif o.get("additionalContext")!=want: print("content-mismatch")
else: print("ok")
' "$PLAYBOOK")
  report "$got" ok "$desc"
}

# parts <hook> <playbook> —— 依次跑 --part 1..6，核对：每段不超过 9500 个 UTF-16 码元，
# 段号连续、标签里的总段数一致、去掉标签后按序拼接与 playbook 逐字相等，超出总段数的段号不输出。
# 输出 ok:<段数> 或首个不符的原因。
parts() {
  local hook="$1" pb="$2" dir="$TMP/out.$RANDOM" i
  mkdir -p "$dir"
  for i in 1 2 3 4 5 6; do bash "$hook" --part "$i" </dev/null >"$dir/$i" 2>/dev/null || echo "exit-$i" >"$dir/err"; done
  python3 - "$dir" "$pb" <<'PY'
import json, os, re, sys
d, pb = sys.argv[1], sys.argv[2]
if os.path.exists(os.path.join(d, "err")):
    print("nonzero-" + open(os.path.join(d, "err")).read().strip()); sys.exit()
want = open(pb, encoding="utf-8").read()
L = lambda s: len(s.encode("utf-16-le")) // 2
got, total = [], None
for i in range(1, 7):
    raw = open(os.path.join(d, str(i)), encoding="utf-8").read()
    if not raw.strip():
        break
    ctx = json.loads(raw)["hookSpecificOutput"]["additionalContext"]
    if L(ctx) > 9500:
        print("part-%d-too-long-%d" % (i, L(ctx))); sys.exit()
    m = re.match(r"\[orchestrator playbook, part (\d+) of (\d+)\]\n", ctx)
    if m:
        if int(m.group(1)) != i or (total and int(m.group(2)) != total):
            print("bad-label-%d" % i); sys.exit()
        total = int(m.group(2)); ctx = ctx[m.end():]
    elif i > 1 or L(want) > 9500:
        print("missing-label-%d" % i); sys.exit()
    got.append(ctx)
n = len(got)
for j in range(n + 1, 7):
    if open(os.path.join(d, str(j)), encoding="utf-8").read().strip():
        print("output-past-end-%d" % j); sys.exit()
if total is not None and total != n:
    print("label-total-%d-vs-%d" % (total, n)); sys.exit()
print("ok:%d" % n if "".join(got) == want else "concat-mismatch")
PY
}

# mkpb <名字> <生成 playbook 的 python 表达式> —— 在 $TMP/<名字>/ 下搭 hooks/ 与 playbook，回 hook 路径
mkpb() {
  mkdir -p "$TMP/$1/hooks"
  cp "$HOOK" "$TMP/$1/hooks/"
  python3 -c "import sys; open(sys.argv[1],'w',encoding='utf-8').write($2)" "$TMP/$1/orchestrator-playbook.md"
  echo "$TMP/$1/hooks/$(basename "$HOOK")"
}

echo "── 不带参数：注入 playbook 全文 ──"
check "默认环境下注入的内容与 playbook 逐字相等"
check "HOME 指向空目录时仍从脚本所在仓库读 playbook" HOME="$TMP"

echo "── --part N：按段注入，每段不超过 9500 ──"
r=$(parts "$HOOK" "$PLAYBOOK"); report "${r%%:*}" ok "本仓 playbook 分段拼回全文"
# 仓库里有 settings.example.json 时，段数不得超过它为本钩子注册的 --part 个数
SETTINGS="$(dirname "$0")/../../settings.example.json"
if [ -f "$SETTINGS" ]; then
  reg=$(grep -c 'orchestrator-playbook-session-start.sh --part' "$SETTINGS")
  n=${r#ok:}; [ "$r" != "$n" ] && report "$([ "$n" -le "$reg" ] && echo fits || echo over)" fits "本仓 playbook 不超过 settings 注册的段数"
fi

h=$(mkpb short '"# P\n\n## 一\n\n短手册。\n"')
r=$(parts "$h" "$TMP/short/orchestrator-playbook.md"); report "$r" ok:1 "短手册只出 1 段且不加标签"

h=$(mkpb sections '"# P\n\n" + "".join("## S%d\n\n" % i + ("x" * 3000) + "\n\n" for i in range(8))')
r=$(parts "$h" "$TMP/sections/orchestrator-playbook.md"); report "${r%%:*}" ok "多节手册按节切段"
first=$(bash "$h" --part 2 | python3 -c 'import json,sys; c=json.load(sys.stdin)["hookSpecificOutput"]["additionalContext"]; print(c.split("\n",1)[1][:5])')
report "$first" "## S3" "第 2 段从节标题起头"

h=$(mkpb bigsec '"# P\n\n## 大节\n\n" + "".join(("段落%d " % i) * 400 + "\n\n" for i in range(6))')
r=$(parts "$h" "$TMP/bigsec/orchestrator-playbook.md"); report "${r%%:*}" ok "单节超长时按空行切"

h=$(mkpb bigline '"# P\n\n" + "y" * 20000 + "\n"')
r=$(parts "$h" "$TMP/bigline/orchestrator-playbook.md"); report "${r%%:*}" ok "单行超长时硬切"

h=$(mkpb emoji '"# P\n\n" + "😀" * 12000 + "\n"')
r=$(parts "$h" "$TMP/emoji/orchestrator-playbook.md"); report "${r%%:*}" ok "按 UTF-16 码元计长、不劈开代理对"

out=$(bash "$HOOK" --part 0 </dev/null 2>/dev/null); rc=$?
report "$rc:${#out}" "0:0" "非法段号不输出、退出 0"

echo
echo "PASS=$PASS FAIL=$FAIL"
[ "$FAIL" -eq 0 ]
