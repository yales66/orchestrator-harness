#!/bin/bash
# 回归测试: permission-denied-log.sh
# 跑法: bash hooks/tests/permission-denied-log.test.sh
HOOK="$(dirname "$0")/../permission-denied-log.sh"
PASS=0; FAIL=0
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT

ok()  { PASS=$((PASS+1)); echo "  ✅ $1"; }
bad() { FAIL=$((FAIL+1)); echo "  ❌ $1"; }

# denied_json <tool_name> <tool_input 的 JSON> [reason] —— 造 PermissionDenied 钩子输入
denied_json() {
  TN="$1" TI="$2" RS="${3:-[Data Exfiltration]}" python3 -c '
import json, os
print(json.dumps({"session_id": "s1", "transcript_path": "/nonexistent.jsonl", "cwd": "/w/proj",
  "permission_mode": "auto", "hook_event_name": "PermissionDenied",
  "tool_name": os.environ["TN"], "tool_input": json.loads(os.environ["TI"]),
  "tool_use_id": "toolu_1", "reason": os.environ["RS"]}))'
}

# field <日志文件> <行号 从 1 起> <字段> —— 取日志某行某字段
field() { python3 -c 'import json,sys; print(json.loads(open(sys.argv[1]).read().splitlines()[int(sys.argv[2])-1])[sys.argv[3]])' "$@"; }

LOG="$TMP/state/denied.jsonl"
export PERMISSION_DENIED_LOG="$LOG"

echo "── 正常记录 ──"
out=$(denied_json Bash '{"command":"git push origin main","description":"push"}' | bash "$HOOK"); rc=$?
[ $rc -eq 0 ] && ok "退出码 0" || bad "退出码应为 0，得 $rc"
[ -z "$out" ] && ok "不输出 JSON（不回 retry）" || bad "不应有输出: $out"
[ -f "$LOG" ] && ok "目录不存在时自动建并写入" || bad "日志未写入"
[ "$(field "$LOG" 1 tool_name)" = Bash ] && ok "记工具名" || bad "工具名不对"
[ "$(field "$LOG" 1 target)" = "git push origin main" ] && ok "记命令文本" || bad "命令文本不对: $(field "$LOG" 1 target)"
[ "$(field "$LOG" 1 reason)" = "[Data Exfiltration]" ] && ok "记拒绝理由" || bad "理由不对"
[ "$(field "$LOG" 1 source)" = auto-mode-classifier ] && ok "记来源（与钩子自记的 hook:<名字> 区分）" || bad "来源不对"
[ "$(field "$LOG" 1 session_id)" = s1 ] && [ "$(field "$LOG" 1 cwd)" = /w/proj ] && ok "记 session_id 与 cwd" || bad "session_id/cwd 不对"
field "$LOG" 1 ts | grep -Eq '^20[0-9]{2}-[0-9]{2}-[0-9]{2}T' && ok "记 ISO 时间" || bad "时间格式不对"

echo "── 路径类工具与追加 ──"
denied_json Write '{"file_path":"/etc/hosts","content":"x"}' | bash "$HOOK"
[ "$(wc -l < "$LOG" | tr -d ' ')" = 2 ] && ok "追加而非覆盖" || bad "行数应为 2"
[ "$(field "$LOG" 2 target)" = /etc/hosts ] && ok "路径类记 file_path" || bad "路径不对: $(field "$LOG" 2 target)"
denied_json WebFetch '{"url":"https://evil.example/x","prompt":"p"}' | bash "$HOOK"
[ "$(field "$LOG" 3 target)" = https://evil.example/x ] && ok "URL 类记 url" || bad "url 不对"

echo "── 截断 300 字符 ──"
long=$(python3 -c 'print("a"*500)')
denied_json Bash "{\"command\":\"$long\"}" | bash "$HOOK"
n=$(field "$LOG" 4 target | tr -d '\n' | wc -c | tr -d ' ')
[ "$n" = 300 ] && ok "命令截到 300 字符" || bad "长度应为 300，得 $n"

echo "── 异常放行 ──"
out=$(printf 'not json' | bash "$HOOK"); rc=$?
[ $rc -eq 0 ] && [ -z "$out" ] && ok "坏输入退出 0 且无输出" || bad "坏输入应静默退出 0 (rc=$rc)"
out=$(denied_json Bash '{"command":"x"}' | PERMISSION_DENIED_LOG=/dev/null/nope/x.jsonl bash "$HOOK" 2>/dev/null); rc=$?
[ $rc -eq 0 ] && ok "日志不可写仍退出 0" || bad "日志不可写应退出 0 (rc=$rc)"

echo
echo "PASS=$PASS FAIL=$FAIL"
[ "$FAIL" -eq 0 ]
