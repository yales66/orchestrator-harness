#!/bin/bash
# 回归测试: statusline-tee.sh
# 跑法: bash hooks/tests/statusline-tee.test.sh
TEE="$(dirname "$0")/../statusline-tee.sh"
PASS=0; FAIL=0
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
OUT="$TMP/state/rate-limits.json"

# run <stdin> —— 跑包装脚本，内层状态栏命令作参数传入，换成「回显 stdin 字节数」，回传其输出
# shellcheck disable=SC2016  # 内层命令由包装脚本交给 bash -c 执行，变量到那时才展开
run() { printf '%s' "$1" | STATUSLINE_RL_OUT="$OUT" bash "$TEE" bash -c 'printf "inner:%s" "$(wc -c | tr -d " ")"' 2>"$TMP/err"; }

report() {  # report <期望> <实际> <描述>
  if [ "$1" = "$2" ]; then
    PASS=$((PASS+1)); printf '  ✅ %-40s [%s]\n' "$3" "$2"
  else
    FAIL=$((FAIL+1)); printf '  ❌ %-40s 期望=%s 实际=%s\n' "$3" "$1" "$2"
  fi
}
field() { python3 -c 'import json,sys;print(json.load(open(sys.argv[1]))["five_hour"]["used_percentage"])' "$OUT" 2>/dev/null || echo 无; }

IN='{"model":{"id":"x"},"rate_limits":{"five_hour":{"used_percentage":96.5,"resets_at":1791400000},"seven_day":{"used_percentage":40,"resets_at":1791900000}}}'
report "inner:${#IN}" "$(run "$IN")" "stdin 原样交给内层状态栏，输出原样返回"
report 96.5 "$(field)" "带 rate_limits 时落盘"
run '{"model":{"id":"x"}}' >/dev/null
report 96.5 "$(field)" "不带 rate_limits 时保留上一份"
run '{"rate_limits":{"seven_day":{"used_percentage":1,"resets_at":1}}}' >/dev/null
report 96.5 "$(field)" "缺 five_hour 时保留上一份"
run '{"rate_limits":{"five_hour":{"used_percentage":90,"resets_at":1791400000}}}' >/dev/null
report 96.5 "$(field)" "同一窗口的较低值是旧会话的旧值，不覆盖"
run '{"rate_limits":{"five_hour":{"used_percentage":97,"resets_at":1791400030}}}' >/dev/null
report 97 "$(field)" "同一窗口（重置时刻差几十秒）的更高值覆盖"
run '{"rate_limits":{"five_hour":{"used_percentage":3,"resets_at":1791418000}}}' >/dev/null
report 3 "$(field)" "进入新窗口时较低值也覆盖"
since() { python3 -c 'import json,sys;print(json.load(open(sys.argv[1])).get("pause_since","无"))' "$OUT" 2>/dev/null || echo 无; }
report 无 "$(since)" "用量 3% 不记越过 95% 的时刻"
run '{"rate_limits":{"five_hour":{"used_percentage":95.2,"resets_at":1791418000}}}' >/dev/null
s1=$(since); report yes "$(python3 -c "import time;print('yes' if abs(time.time()-float('$s1'))<5 else '$s1')")" "首次到 95% 记下当前时刻"
sleep 1.1
run '{"rate_limits":{"five_hour":{"used_percentage":98,"resets_at":1791418000}}}' >/dev/null
report "$s1" "$(since)" "同一窗口再涨，越过时刻不变"
run '{"rate_limits":{"five_hour":{"used_percentage":1,"resets_at":1791436000}}}' >/dev/null
report 无 "$(since)" "进入新窗口，越过时刻清掉"
report "inner:8" "$(run 'not json')" "stdin 不是 JSON 时内层照常运行"
report "" "$(cat "$TMP/err")" "不往 stderr 写东西"
rm -f "$OUT"
report "" "$(printf '%s' "$IN" | STATUSLINE_RL_OUT="$OUT" bash "$TEE" 2>&1)" "不带内层命令时不输出"
report 96.5 "$(field)" "不带内层命令时照样落盘"

echo
echo "PASS=$PASS FAIL=$FAIL"
[ "$FAIL" -eq 0 ]
