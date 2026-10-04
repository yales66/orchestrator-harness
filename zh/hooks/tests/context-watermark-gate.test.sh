#!/bin/bash
# 回归测试: context-watermark-gate.sh
# 跑法: bash hooks/tests/context-watermark-gate.test.sh
HOOK="$(dirname "$0")/../context-watermark-gate.sh"
PASS=0; FAIL=0
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT

# mktranscript <文件名> <总token> [cache_creation 份额，缺省 0] —— 造一条带 usage 的 assistant 行，
# 总量扣掉 input 的 2 与 cache_creation 份额后记在 cache_read 上
mktranscript() {
  local f="$TMP/$1" tot="$2" create="${3:-0}"
  printf '{"message":{"role":"user","content":"hi"}}\n' > "$f"
  printf '{"message":{"role":"assistant","usage":{"input_tokens":2,"cache_read_input_tokens":%d,"cache_creation_input_tokens":%d}}}\n' \
    $((tot-2-create)) "$create" >> "$f"
  echo "$f"
}

# reason_has <描述> <yes|no> <子串> <输入JSON>:断言拦截理由含或不含某个子串
reason_has() {
  local desc="$1" want="$2" sub="$3" payload="$4" got
  got=$(printf '%s' "$payload" | bash "$HOOK" 2>/dev/null | python3 -c '
import json,sys
sub=sys.argv[1]
try: r=json.loads(sys.stdin.read() or "{}").get("reason","")
except Exception: r=""
print("yes" if sub in r else "no")
' "$sub")
  if [ "$got" = "$want" ]; then
    PASS=$((PASS+1)); printf '  ✅ %-50s [%s]\n' "$desc" "$got"
  else
    FAIL=$((FAIL+1)); printf '  ❌ %-50s 期望=%s 实际=%s\n' "$desc" "$want" "$got"
  fi
}

# check <期望 allow|warn|block> <描述> <输入JSON> [环境变量赋值...]
check() {
  local want="$1" desc="$2" payload="$3"; shift 3
  local got
  got=$(printf '%s' "$payload" | env "$@" bash "$HOOK" 2>/dev/null | python3 -c '
import json,sys
raw=sys.stdin.read().strip()
if not raw: print("allow"); raise SystemExit
try: o=json.loads(raw)
except Exception: print("allow"); raise SystemExit
if o.get("decision")=="block": print("block")
elif o.get("hookSpecificOutput",{}).get("additionalContext"): print("warn")
else: print("allow")
')
  if [ "$got" = "$want" ]; then
    PASS=$((PASS+1)); printf '  ✅ %-50s [%s]\n' "$desc" "$got"
  else
    FAIL=$((FAIL+1)); printf '  ❌ %-50s 期望=%s 实际=%s\n' "$desc" "$want" "$got"
  fi
}

T_LOW=$(mktranscript low.jsonl 100000)      # 10%
T_WARN=$(mktranscript warn.jsonl 370000)    # 37%
T_HARD=$(mktranscript hard.jsonl 450000)    # 45%
T_EDGE=$(mktranscript edge.jsonl 350000)    # 35% 整,应触发 warn(>=)
T_HARD42=$(mktranscript hard42.jsonl 420000)  # 42%,默认硬线 40% 与 45% 之间
T_CREATE=$(mktranscript create.jsonl 450000 440000)  # 45%,大头在 cache_creation
printf '{"message":{"role":"assistant"}}\n' > "$TMP/nousage.jsonl"

echo "── 三档水位 ──"
check allow "10% 远低于提醒线" "{\"hook_event_name\":\"Stop\",\"transcript_path\":\"$T_LOW\"}"
check warn  "37% 过提醒线未过硬线" "{\"hook_event_name\":\"Stop\",\"transcript_path\":\"$T_WARN\"}"
check block "45% 过硬线" "{\"hook_event_name\":\"Stop\",\"transcript_path\":\"$T_HARD\"}"
check warn  "35% 边界纳入提醒" "{\"hook_event_name\":\"Stop\",\"transcript_path\":\"$T_EDGE\"}"
check block "42% 过默认硬线 40%" "{\"hook_event_name\":\"Stop\",\"transcript_path\":\"$T_HARD42\"}"
check block "cache_creation 计入水位" "{\"hook_event_name\":\"Stop\",\"transcript_path\":\"$T_CREATE\"}"

echo "── 防循环与作用域 ──"
check allow "过硬线但已拦过一次(stop_hook_active)" \
  "{\"hook_event_name\":\"Stop\",\"stop_hook_active\":true,\"transcript_path\":\"$T_HARD\"}"
check allow "subagent 内不受主线程水位管(agent_id)" \
  "{\"hook_event_name\":\"Stop\",\"agent_id\":\"a_01\",\"transcript_path\":\"$T_HARD\"}"
check block "agent_id 为空串等同缺席" \
  "{\"hook_event_name\":\"Stop\",\"agent_id\":\"\",\"transcript_path\":\"$T_HARD\"}"

echo "── 阈值可覆盖 ──"
check allow "硬线抬到 90% 后 45% 不再拦" \
  "{\"hook_event_name\":\"Stop\",\"transcript_path\":\"$T_HARD\"}" CONTEXT_WARN_PCT=80 CONTEXT_HARD_PCT=90
check block "窗口缩到 200K 后 100K 即过硬线" \
  "{\"hook_event_name\":\"Stop\",\"transcript_path\":\"$T_LOW\"}" CONTEXT_WINDOW_TOKENS=200000

echo "── 重复拦截抑制:硬线以上不该每轮都拦 ──"
SP="$TMP/scratchpad"; mkdir -p "$SP"
check block "首次过硬线正常拦" \
  "{\"hook_event_name\":\"Stop\",\"transcript_path\":\"$T_HARD\",\"scratchpad_dir\":\"$SP\"}"
if [ -f "$SP/.context-watermark-last-block" ]; then
  PASS=$((PASS+1)); printf '  ✅ %-50s [记下 %s]\n' "拦截时把水位记进 scratchpad" "$(cat "$SP/.context-watermark-last-block")"
else
  FAIL=$((FAIL+1)); printf '  ❌ %-50s 未生成标记文件\n' "拦截时把水位记进 scratchpad"
fi
check allow "同一水位再来一轮不重复拦" \
  "{\"hook_event_name\":\"Stop\",\"transcript_path\":\"$T_HARD\",\"scratchpad_dir\":\"$SP\"}"
T_NUDGE=$(mktranscript nudge.jsonl 480000)
check allow "再涨不足 5 个点不重拦" \
  "{\"hook_event_name\":\"Stop\",\"transcript_path\":\"$T_NUDGE\",\"scratchpad_dir\":\"$SP\"}"
T_HIGHER=$(mktranscript higher.jsonl 520000)
check block "水位再涨超过增量阈值才重新拦" \
  "{\"hook_event_name\":\"Stop\",\"transcript_path\":\"$T_HIGHER\",\"scratchpad_dir\":\"$SP\"}"
check block "无 scratchpad_dir 时退回每轮拦,不静默放行" \
  "{\"hook_event_name\":\"Stop\",\"transcript_path\":\"$T_HARD\"}"

SPR="$TMP/scratchpad-reblock"; mkdir -p "$SPR"
reason_has "首次拦截只要求做到断点,不要求立即落盘" no "现在就" \
  "{\"hook_event_name\":\"Stop\",\"transcript_path\":\"$T_HARD\",\"scratchpad_dir\":\"$SPR\"}"
reason_has "越线后再涨过阈值再拦时要求立即落盘" yes "现在就" \
  "{\"hook_event_name\":\"Stop\",\"transcript_path\":\"$T_HIGHER\",\"scratchpad_dir\":\"$SPR\"}"

echo "── 拦截理由指向 handoff 技能并附 transcript 路径 ──"
FIRST="{\"hook_event_name\":\"Stop\",\"transcript_path\":\"$T_HARD\"}"
reason_has "首次拦截指向 handoff 技能" yes "先用 handoff 技能落盘交接" "$FIRST"
reason_has "首次拦截不再指向 playbook §3" no "playbook §3" "$FIRST"
reason_has "首次拦截末尾附 transcript 路径" yes "（transcript: ${T_HARD}）" "$FIRST"
# again <scratchpad 名>：在一个新 scratchpad 里先拦一次，回传水位再涨过阈值时的输入
again() {
  local sp="$TMP/$1"; mkdir -p "$sp"
  printf '%s' "{\"hook_event_name\":\"Stop\",\"transcript_path\":\"$T_HARD\",\"scratchpad_dir\":\"$sp\"}" \
    | bash "$HOOK" >/dev/null 2>&1
  echo "{\"hook_event_name\":\"Stop\",\"transcript_path\":\"$T_HIGHER\",\"scratchpad_dir\":\"$sp\"}"
}
reason_has "再拦指向 handoff 技能" yes "现在就用 handoff 技能落盘交接" "$(again sp-h1)"
reason_has "再拦不再指向 playbook §3" no "playbook §3" "$(again sp-h2)"
reason_has "再拦末尾附 transcript 路径" yes "（transcript: ${T_HIGHER}）" "$(again sp-h3)"

SPW="$TMP/scratchpad-warn"; mkdir -p "$SPW"
check warn  "首次过提醒线提醒一次" \
  "{\"hook_event_name\":\"Stop\",\"transcript_path\":\"$T_WARN\",\"scratchpad_dir\":\"$SPW\"}"
check allow "同一会话提醒线不再重复提醒" \
  "{\"hook_event_name\":\"Stop\",\"transcript_path\":\"$T_WARN\",\"scratchpad_dir\":\"$SPW\"}"
check block "提醒过之后过硬线照样拦" \
  "{\"hook_event_name\":\"Stop\",\"transcript_path\":\"$T_HARD\",\"scratchpad_dir\":\"$SPW\"}"
check allow "压缩后水位回落到提醒线以下" \
  "{\"hook_event_name\":\"Stop\",\"transcript_path\":\"$T_LOW\",\"scratchpad_dir\":\"$SPW\"}"
check warn  "压缩后重新越过提醒线照常提醒" \
  "{\"hook_event_name\":\"Stop\",\"transcript_path\":\"$T_WARN\",\"scratchpad_dir\":\"$SPW\"}"
check block "压缩后重新越过硬线照常拦" \
  "{\"hook_event_name\":\"Stop\",\"transcript_path\":\"$T_HARD\",\"scratchpad_dir\":\"$SPW\"}"

echo "── 异常一律 fail-open ──"
check allow "transcript 路径不存在" '{"hook_event_name":"Stop","transcript_path":"/nope/x.jsonl"}'
check allow "transcript 无 usage 字段" "{\"hook_event_name\":\"Stop\",\"transcript_path\":\"$TMP/nousage.jsonl\"}"
check allow "缺 transcript_path" '{"hook_event_name":"Stop"}'
check allow "非 JSON 输入" 'not json at all'
check allow "空输入" ''

echo
echo "PASS=$PASS FAIL=$FAIL"
[ "$FAIL" -eq 0 ]
