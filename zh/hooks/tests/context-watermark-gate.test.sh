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

echo "── 异常一律 fail-open ──"
check allow "transcript 路径不存在" '{"hook_event_name":"Stop","transcript_path":"/nope/x.jsonl"}'
check allow "transcript 无 usage 字段" "{\"hook_event_name\":\"Stop\",\"transcript_path\":\"$TMP/nousage.jsonl\"}"
check allow "缺 transcript_path" '{"hook_event_name":"Stop"}'
check allow "非 JSON 输入" 'not json at all'
check allow "空输入" ''

echo
echo "PASS=$PASS FAIL=$FAIL"
[ "$FAIL" -eq 0 ]
