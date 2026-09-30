#!/bin/bash
# 回归测试: reply-gate.sh
# 跑法: bash hooks/tests/reply-gate.test.sh
HOOK="$(dirname "$0")/../reply-gate.sh"
PASS=0; FAIL=0

# stop_json <回复正文> [stop_hook_active 真假] —— 造 Stop 钩子输入
stop_json() {
  MSG="$1" ACTIVE="${2:-false}" python3 -c '
import json, os
print(json.dumps({"hook_event_name": "Stop",
                  "stop_hook_active": os.environ["ACTIVE"] == "true",
                  "transcript_path": "/nonexistent/transcript.jsonl",
                  "last_assistant_message": os.environ["MSG"]}))
'
}

# check <期望 allow|ask|lang|ask+lang> <描述> <输入JSON> [环境变量赋值...]
# ask 表示命中收尾提议问句，lang 表示命中回复语言，按 reason 里各自的特征句判定
check() {
  local want="$1" desc="$2" payload="$3"; shift 3
  local got
  got=$(printf '%s' "$payload" | env -u REPLY_LANG "$@" bash "$HOOK" 2>/dev/null | python3 -c '
import json,sys
raw=sys.stdin.read().strip()
if not raw: print("allow"); raise SystemExit
try: o=json.loads(raw)
except Exception: print("allow"); raise SystemExit
if o.get("decision")!="block": print("allow"); raise SystemExit
r=o.get("reason","")
hits=[n for n,k in (("ask","直接做完再汇报"),("lang","用中文重写")) if k in r]
print("+".join(hits) or "block-without-known-reason")
')
  if [ "$got" = "$want" ]; then
    PASS=$((PASS+1)); printf '  ✅ %-50s [%s]\n' "$desc" "$got"
  else
    FAIL=$((FAIL+1)); printf '  ❌ %-50s 期望=%s 实际=%s\n' "$desc" "$want" "$got"
  fi
}

LONG_EN="I updated the parity script so that the settings file is compared after removing the language prefix, added the three hooks with their tests, and ran the whole suite on both copies. Everything passes and shellcheck is clean."
# 中文正文夹大量代码标识符：可见字符超过 150，中日韩占比仍在 0.2 以上
# 可见字符正好 150 的英文回复：长度线上，不查语言
EN_150="I updated the parity script, added the three hooks with their tests and ran the whole suite on both copies. Everything passes and shellcheck reports no warnings on the hooks at all."
MIXED_ZH="已把 check_parity 里的 settings_example 比较改成先用 sed 去掉 REPLY_LANG 前缀再 cmp，en 和 zh 两份现在只差这一处。reply_gate、secret_guard、subagent_readonly_guard 三个钩子都注册进了 PreToolUse 与 Stop，shellcheck 和 actionlint 均无输出，测试全部通过，改动留在工作区等你检查后提交。"

echo "── A1 收尾提议问句: 必须拦 ──"
check ask "中文 要我…吗？ 独立成段" "$(stop_json $'改好了，测试全绿。\n\n要我顺手把 README 也更新吗？')"
check ask "中文 需要我…吗 无问号" "$(stop_json '需要我现在提交吗')"
check ask "中文 要不要…？" "$(stop_json $'旧钩子还留着。\n\n要不要把旧的钩子一起删掉？')"
check ask "中文 是否需要…？" "$(stop_json '三份文件都已改好。是否需要同步到 ~/.claude？')"
check ask "中文 同段末句是提议" "$(stop_json '我已经改完并跑过测试。要我再跑一遍全套吗？')"
check ask "英文 Shall I" "$(stop_json $'Fixed.\n\nShall I push the branch?')"
check ask "英文 Would you like me to" "$(stop_json 'All green. Would you like me to open a PR?')"
check ask "英文 Do you want me to（加粗收尾）" "$(stop_json '**Do you want me to rerun CI?**')"
check ask "英文 want me to 小写" "$(stop_json 'Tests pass. want me to add one more case?')"
check ask "英文 Should I" "$(stop_json 'Done with the fix. Should I also bump the version?')"
check ask "代码块之后以提议收尾" "$(stop_json $'改法如下：\n\n```\nbash scripts/check-parity.sh\n```\n\n要我现在跑一遍吗？')"

echo "── A1 必须放行 ──"
check allow "陈述句收尾（含 要我 字样）" "$(stop_json '你要我改的地方都改完了。')"
check allow "无标点陈述收尾（含 要我 字样）" "$(stop_json '你要我改的地方都改完了')"
check allow "英文陈述句收尾" "$(stop_json 'I fixed the tests. Next I will update the docs.')"
check allow "问句在中间段落" "$(stop_json $'要我顺手改 README 吗？\n\n不用了，我已经顺手改好并跑过测试。')"
check allow "末段先问后陈述" "$(stop_json '要我改吗？我先去看日志。')"
check allow "问句在围栏代码块里" "$(stop_json $'提示文本如下：\n\n```\nShall I continue?\n```')"
check allow "问句在行内代码里" "$(stop_json '最后一行提示是 `要我继续吗？`')"
check allow "问句在 URL 里" "$(stop_json '参考 https://example.com/faq/要不要升级？')"
check allow "非提议的问句" "$(stop_json '这个方案对吗？')"
check allow "末段前句含 要我、末句是非提议问句" "$(stop_json '你要我改的都改了。这个方案对吗？')"
check allow "提议字样只在行内代码里的问句" "$(stop_json '`要我确认吗` 这个提示在哪个文件里？')"

echo "── A2 回复语言: 仅 REPLY_LANG=zh 时生效 ──"
check lang  "英文长回复 + REPLY_LANG=zh" "$(stop_json "$LONG_EN")" REPLY_LANG=zh
check allow "中文夹大量代码标识符" "$(stop_json "$MIXED_ZH")" REPLY_LANG=zh
check allow "英文短回复不查" "$(stop_json 'Done. All tests pass.')" REPLY_LANG=zh
check allow "英文回复可见字符正好 150 不查" "$(stop_json "$EN_150")" REPLY_LANG=zh
check allow "代码块剥掉后正文太短不查" "$(stop_json $'好了：\n\n```\n'"$LONG_EN"$'\n```')" REPLY_LANG=zh
check allow "未设 REPLY_LANG 时不查" "$(stop_json "$LONG_EN")"
check allow "REPLY_LANG=en 时不查" "$(stop_json "$LONG_EN")" REPLY_LANG=en

echo "── 两项同时命中 ──"
check ask+lang "英文长回复以提议收尾" "$(stop_json "$LONG_EN Would you like me to update the README too?")" REPLY_LANG=zh

echo "── 防循环与异常输入 ──"
check allow "stop_hook_active=true 放行" "$(stop_json $'改好了。\n\n要我提交吗？' true)"
check allow "stop_hook_active=true 放行（语言项）" "$(stop_json "$LONG_EN" true)" REPLY_LANG=zh
check allow "缺 last_assistant_message" '{"hook_event_name":"Stop","stop_hook_active":false}'
check allow "last_assistant_message 非字符串" '{"hook_event_name":"Stop","last_assistant_message":["x"]}'
check allow "非 JSON 输入" 'not json at all'
check allow "空输入" ''
check allow "JSON 数组" '[1,2]'

echo
echo "PASS=$PASS FAIL=$FAIL"
[ "$FAIL" -eq 0 ]
