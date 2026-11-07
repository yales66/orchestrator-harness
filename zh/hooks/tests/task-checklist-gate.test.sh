#!/bin/bash
# 回归测试: task-checklist-gate.sh
# 跑法: bash hooks/tests/task-checklist-gate.test.sh
HOOK="$(dirname "$0")/../task-checklist-gate.sh"
PASS=0; FAIL=0
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
export CHECKLIST_DIR="$TMP"
unset CHECKLIST_CAP

# stop_json <session_id> [agent_id] [background_tasks 的 JSON] [session_crons 的 JSON] —— 造 Stop 钩子输入
stop_json() {
  SID="$1" AID="${2:-}" BG="${3:-[]}" CR="${4:-[]}" python3 -c '
import json, os
p = {"session_id": os.environ["SID"], "hook_event_name": "Stop",
     "transcript_path": "/nonexistent/transcript.jsonl",
     "stop_hook_active": False, "last_assistant_message": "好了。",
     "background_tasks": json.loads(os.environ["BG"]), "session_crons": json.loads(os.environ["CR"])}
if os.environ["AID"]:
    p["agent_id"] = os.environ["AID"]
print(json.dumps(p))
'
}

# write_list <session_id> <item 规格...>，每个规格写成 id:status:标题
write_list() {
  local sid="$1"; shift
  python3 - "$TMP/$sid.json" "$@" <<'PY'
import json, sys
items = []
for spec in sys.argv[2:]:
    i, s, t = spec.split(":", 2)
    items.append({"id": i, "status": s, "title": t})
json.dump({"task": "测试任务", "items": items}, open(sys.argv[1], "w"), ensure_ascii=False)
PY
}

# run <输入JSON> —— 输出 allow，或 block 后跟 reason
run() {
  printf '%s' "$1" | bash "$HOOK" 2>/dev/null | python3 -c '
import json,sys
raw=sys.stdin.read().strip()
if not raw: print("allow"); raise SystemExit
try: o=json.loads(raw)
except Exception: print("allow"); raise SystemExit
print("block " + o.get("reason","") if o.get("decision")=="block" else "allow")
'
}

# check <描述> <期望 allow|block> <输入JSON> [reason 必含子串...]
check() {
  local desc="$1" want="$2" payload="$3"; shift 3
  local got verdict ok=1 miss=""
  got=$(run "$payload"); verdict="${got%% *}"
  [ "$verdict" = "$want" ] || ok=0
  for s in "$@"; do
    case "$got" in *"$s"*) ;; *) ok=0; miss="$miss [缺:$s]";; esac
  done
  if [ "$want" = block ] && printf '%s' "$got" | grep -Eq '%|[Tt]oken'; then ok=0; miss="$miss [含 token/百分比]"; fi
  if [ $ok = 1 ]; then
    PASS=$((PASS+1)); printf '  ✅ %-44s [%s]\n' "$desc" "$verdict"
  else
    FAIL=$((FAIL+1)); printf '  ❌ %-44s 期望=%s 实际=%s%s\n' "$desc" "$want" "$got" "$miss"
  fi
}

echo "── 放行 ──"
write_list sub "a:todo:写测试"
check "子智能体放行" allow "$(stop_json sub agent-1)"
check "无清单放行" allow "$(stop_json nolist)"
printf '{not json' > "$TMP/bad.json"
check "坏 JSON 放行" allow "$(stop_json bad)"
printf '[1,2]' > "$TMP/arr.json"
check "结构不对（顶层数组）放行" allow "$(stop_json arr)"
printf '{"task":"x","items":"oops"}' > "$TMP/noitems.json"
check "结构不对（items 非数组）放行" allow "$(stop_json noitems)"
write_list alldone "a:done:写测试" "b:blocked:等审批"
check "全 done/blocked 放行" allow "$(stop_json alldone)"
write_list bg "a:todo:写测试"
check "background_tasks 非空放行" allow "$(stop_json bg '' '[{"id":"t1","type":"shell","status":"running","description":"x"}]')"
write_list cron "a:todo:写测试"
check "session_crons 非空放行" allow "$(stop_json cron '' '[]' '[{"id":"c1","schedule":"0 9 * * *","recurring":true,"prompt":"x"}]')"
check "空输入放行" allow ''
check "非 JSON 输入放行" allow 'not json'

echo "── 拦下 ──"
write_list one "a:done:建目录" "b:todo:写实现" "c:doing:跑测试" "d:weird:未知状态项"
check "有 todo 时拦下并点名" block "$(stop_json one)" \
  "任务清单里还有未完成项：b 写实现、c 跑测试、d 未知状态项。" "status 改成 blocked" "（清单：$TMP/one.json）"

echo "── 续跑上限 ──"
write_list cap "a:todo:写实现"
check "第 1 次拦" block "$(stop_json cap)"
check "第 2 次拦" block "$(stop_json cap)"
check "第 3 次拦" block "$(stop_json cap)"
check "同一清单第 4 次放行" allow "$(stop_json cap)"
check "之后仍放行" allow "$(stop_json cap)"
write_list cap "a:done:写实现" "b:todo:写文档"
check "清单改动后重新拦" block "$(stop_json cap)" "b 写文档"
check "改动后第 2 次拦" block "$(stop_json cap)"
check "改动后第 3 次拦" block "$(stop_json cap)"
check "改动后第 4 次放行" allow "$(stop_json cap)"
write_list cap2 "a:todo:写实现"
check "CHECKLIST_CAP=1 第 1 次拦" block "$(stop_json cap2)"
got=$(stop_json cap2 | CHECKLIST_CAP=1 bash "$HOOK" 2>/dev/null)
[ -z "$got" ] && { PASS=$((PASS+1)); echo "  ✅ CHECKLIST_CAP=1 第 2 次放行"; } || { FAIL=$((FAIL+1)); echo "  ❌ CHECKLIST_CAP=1 第 2 次应放行: $got"; }

echo "── 超过 8 项 ──"
write_list many i1:todo:一 i2:todo:二 i3:todo:三 i4:todo:四 i5:todo:五 i6:todo:六 i7:todo:七 i8:todo:八 i9:todo:九 i10:doing:十
check "列 8 项后写 等 2 项" block "$(stop_json many)" "i1 一、i2 二、i3 三、i4 四、i5 五、i6 六、i7 七、i8 八等 2 项。"

echo
echo "PASS=$PASS FAIL=$FAIL"
[ "$FAIL" -eq 0 ]
