#!/bin/bash
# 回归测试: secret-guard.sh
# 跑法: bash hooks/tests/secret-guard.test.sh
HOOK="$(dirname "$0")/../secret-guard.sh"
PASS=0; FAIL=0
# 递归搜索的夹具：proj 顶层有 .env；nested 只在 src/config 下有 .env.production；
# clean 只有样例、.git 与 node_modules 里的 .env；big 的同一层目录超过遍历上限
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
# 拒绝时钩子会追加一行到拒绝日志；测试一律写到临时目录，不碰真实日志
export PERMISSION_DENIED_LOG="$TMP/state/denied.jsonl"
mkdir -p "$TMP/proj/src" "$TMP/nested/src/config" "$TMP/clean/src" "$TMP/clean/.git" \
         "$TMP/clean/node_modules/pkg" "$TMP/big/many"
for f in proj/.env nested/src/config/.env.production clean/.git/.env clean/node_modules/pkg/.env \
         big/many/.env; do
  echo 'API_KEY=x' > "$TMP/$f"
done
for f in proj/src/app.py nested/src/app.py clean/src/app.py clean/.env.example; do
  echo 'print(1)' > "$TMP/$f"
done
# SSH 与 Kamal 密钥夹具：home/.ssh 下私钥、公钥与 config；kproj 只在 .kamal 下有 secrets
mkdir -p "$TMP/home/.ssh" "$TMP/kproj/.kamal" "$TMP/kproj/src"
for f in home/.ssh/id_ed25519 kproj/.kamal/secrets.local; do echo 'FAKE_PRIVATE=x' > "$TMP/$f"; done
for f in home/.ssh/id_ed25519.pub home/.ssh/config kproj/src/app.py; do echo 'print(1)' > "$TMP/$f"; done
D="$TMP/big/many" python3 -c 'import os; [open(os.path.join(os.environ["D"], "f%d" % i), "w").close() for i in range(20001)]'

# bash_json <命令> [cwd] / read_json <路径> —— 造 PreToolUse 输入，命令原文不经 shell 转义；
# cwd 缺省是不含 .env 的 clean 目录
bash_json() {
  V="$1" CWD="${2-$TMP/clean}" python3 -c 'import json,os; print(json.dumps({"hook_event_name":"PreToolUse","tool_name":"Bash","cwd":os.environ["CWD"],"tool_input":{"command":os.environ["V"]}}))'
}
read_json() {
  V="$1" python3 -c 'import json,os; print(json.dumps({"hook_event_name":"PreToolUse","tool_name":"Read","tool_input":{"file_path":os.environ["V"]}}))'
}

# grep_json <path> <output_mode> [glob] —— 造 Grep 工具的 PreToolUse 输入，path 空串即缺省（用 cwd）
grep_json() {
  P="$1" M="$2" G="${3-}" CWD="$TMP/clean" python3 -c '
import json, os
ti = {"pattern": "KEY", "output_mode": os.environ["M"]}
if os.environ["P"]: ti["path"] = os.environ["P"]
if os.environ["G"]: ti["glob"] = os.environ["G"]
print(json.dumps({"hook_event_name":"PreToolUse","tool_name":"Grep","cwd":os.environ["CWD"],"tool_input":ti}))'
}

# check <期望 deny|allow> <描述> <hook 输入 JSON>
check() {
  local want="$1" desc="$2" payload="$3" got
  got=$(printf '%s' "$payload" | bash "$HOOK" 2>/dev/null | python3 -c '
import json,sys
try:
    print(json.load(sys.stdin).get("hookSpecificOutput",{}).get("permissionDecision","allow"))
except Exception:
    print("allow")
')
  desc=${desc//$'\n'/⏎}
  if [ "$got" = "$want" ]; then
    PASS=$((PASS+1)); printf '  ✅ %-56s [%s]\n' "$desc" "$got"
  else
    FAIL=$((FAIL+1)); printf '  ❌ %-56s 期望=%s 实际=%s\n' "$desc" "$want" "$got"
  fi
}
# deny_cmd / allow_cmd <命令>：描述即命令本身
deny_cmd()  { check deny  "$1" "$(bash_json "$1")"; }
allow_cmd() { check allow "$1" "$(bash_json "$1")"; }
# deny_in / allow_in <夹具目录名> <命令>：cwd 设为 $TMP 下的该目录
deny_in()  { check deny  "[$1] $2" "$(bash_json "$2" "$TMP/$1")"; }
allow_in() { check allow "[$1] $2" "$(bash_json "$2" "$TMP/$1")"; }

echo "── Read: .env 类文件拒绝，示例类放行 ──"
check deny  "Read .env"                 "$(read_json /repo/.env)"
check deny  "Read .env.local"           "$(read_json /repo/app/.env.local)"
check deny  "Read .env.production"      "$(read_json .env.production)"
check deny  "Read .ENV（大小写不敏感的文件系统）" "$(read_json /repo/.ENV)"
check allow "Read .env.example"         "$(read_json /repo/.env.example)"
check allow "Read .env.sample"          "$(read_json /repo/.env.sample)"
check allow "Read .env.template"        "$(read_json /repo/.env.template)"
check allow "Read 普通文件"             "$(read_json /repo/src/env.py)"
check allow "Read 目录名含 .env 的普通文件" "$(read_json /repo/.env.d/README.md)"

echo "── Bash: 读取 .env 内容的命令拒绝 ──"
deny_cmd 'cat .env'
deny_cmd 'cat ./config/.env.local'
deny_cmd 'cat ".env.production"'
deny_cmd 'less .env'
deny_cmd 'more .env'
deny_cmd 'head -n 5 .env'
deny_cmd 'tail -3 .env.local'
deny_cmd 'bat .env'
deny_cmd 'nl .env'
deny_cmd "sed -n '1,5p' .env"
deny_cmd "awk -F= '{print \$2}' .env"
deny_cmd 'cat .env*'
deny_cmd 'sudo cat .env'
deny_cmd 'cat < .env'
deny_cmd 'cd app && cat .env'
deny_cmd 'cat .env | grep -c KEY'
deny_cmd 'echo $(cat .env)'
deny_cmd 'echo "$(head -1 .env)"'
deny_cmd 'true || head .env'

echo "── Bash: 示例类 .env 与其他文件放行 ──"
allow_cmd 'cat .env.example'
allow_cmd 'head -20 .env.sample'
allow_cmd 'cat config/.env.template'
allow_cmd 'cat .gitignore'
allow_cmd 'cat .env.example > .env'
allow_cmd 'cat .env.example >>.env.local'
allow_cmd "sed -i 's/^DEBUG=.*/DEBUG=0/' .env"
allow_cmd "sed -i.bak -e 's/^DEBUG=1/DEBUG=0/' .env.local"

echo "── Bash: grep/rg 读 .env ──"
deny_cmd  'grep API_KEY .env'
deny_cmd  "grep -E '^(DB|API)_' .env.local"
deny_cmd  'rg TOKEN .env'
deny_cmd  'grep -e KEY -- .env'
deny_cmd  'grep -i key < .env'
allow_cmd "grep -c '^API_KEY=' .env"
allow_cmd 'grep -q API_KEY .env && echo present'
allow_cmd 'grep -l SECRET .env .env.local'
allow_cmd 'grep -L SECRET .env'
allow_cmd 'grep -qE "^TOKEN=" .env'
allow_cmd 'grep --count KEY .env'
allow_cmd 'rg -c KEY .env'
allow_cmd 'grep API_KEY .env.example'
allow_cmd 'grep .env .gitignore'
allow_cmd 'cat .gitignore | grep .env'

echo "── Bash: 递归 grep 与带 --hidden/-uu 的 rg，搜索根下有 .env ──"
deny_in  proj   'grep -r API_KEY .'
deny_in  proj   'grep -R KEY'
deny_in  proj   'grep --recursive -n KEY'
deny_in  .      'grep -rn KEY nested'
deny_in  clean  "grep -r KEY $TMP/nested"
deny_in  proj   'rg --hidden KEY'
deny_in  nested 'rg -uu KEY .'
deny_in  proj   'rg -uuu KEY'
deny_in  proj   'rg -. KEY'
deny_in  proj   'grep -r --exclude=*.py KEY .'
deny_in  nested 'grep -r --exclude=.env KEY .'
deny_in  proj   "rg --hidden -g '!*.md' KEY"
deny_in  proj   "bash -c 'grep -r KEY .'"
allow_in clean  'grep -r KEY .'
allow_in clean  'rg -uu KEY'
allow_in proj   'rg KEY .'
allow_in proj   'rg -u KEY'
allow_in proj   'grep -rc KEY .'
allow_in proj   'grep -rl KEY .'
allow_in proj   'grep -r KEY src'
allow_in proj   "grep -r --exclude='.env*' KEY ."
allow_in nested 'grep -r --exclude-dir=config KEY .'
allow_in proj   "grep -r --include='*.py' KEY ."
allow_in proj   "rg --hidden -g '!.env' KEY"
allow_in big    'grep -r KEY .'

echo "── Bash: cd/pushd 之后的相对搜索根 ──"
deny_in  .      'cd proj && grep -r KEY .'
deny_in  .      'pushd nested; grep -rn KEY src'
deny_in  clean  'cd "$DIR" && grep -r KEY .'
deny_in  clean  'cd $(git rev-parse --show-toplevel) && grep -r KEY .'
allow_in .      'cd clean && grep -r KEY .'
allow_in proj   'cd src && grep -r KEY .'
allow_in .      'cd proj | true; grep -r KEY clean'

echo "── Bash: 其他会打印文件内容的命令读 .env ──"
deny_cmd  'diff .env .env.example'
deny_cmd  'sdiff .env .env.example'
deny_cmd  'comm -3 .env .env.example'
deny_cmd  'sort .env'
deny_cmd  'sort < .env'
deny_cmd  'uniq .env.local'
deny_cmd  'cut -d= -f2 .env'
deny_cmd  'rev .env'
deny_cmd  'strings .env'
deny_cmd  'xxd .env'
deny_cmd  'od -c .env'
deny_cmd  'hexdump -C .env'
deny_cmd  'base64 .env'
deny_cmd  'paste -s .env'
deny_cmd  'fold -w 40 .env'
deny_cmd  'column -t -s= .env'
allow_cmd 'sort package.json'
allow_cmd 'diff .env.example .env.sample'
allow_cmd 'cut -d= -f1 .env.example'

echo "── Bash: bash -c / sh -c / zsh -c / eval 里的命令同样判断 ──"
deny_cmd  "bash -c 'cat .env'"
deny_cmd  'sh -c "grep KEY .env"'
deny_cmd  "zsh -c 'echo \$API_KEY'"
deny_cmd  "bash -lc 'sort .env'"
deny_cmd  'eval "cat .env"'
deny_cmd  'eval cat .env'
deny_cmd  "sudo sh -c 'head .env'"
deny_cmd  "bash -c \"sh -c 'cat .env'\""
allow_cmd "bash -c 'cat .env.example'"
allow_cmd "sh -c 'npm test'"
allow_cmd 'eval "$(ssh-agent -s)"'

echo "── Bash: echo/printf 展开密钥变量 ──"
deny_cmd  'echo $API_KEY'
deny_cmd  'echo "${OPENAI_API_KEY}"'
deny_cmd  'echo $github_token'
deny_cmd  'printf "%s\n" "$DB_PASSWORD"'
deny_cmd  'echo $MYSQL_PASSWD'
deny_cmd  'echo "$Client_Secret"'
deny_cmd  'echo $GOOGLE_APPLICATION_CREDENTIALS'
deny_cmd  'source .env && echo "$STRIPE_SECRET_KEY"'
deny_cmd  'echo "key: ${API_KEY:0:4}"'
allow_cmd 'echo $HOME'
allow_cmd 'echo "${#API_KEY}"'
allow_cmd 'test -n "$API_KEY" && echo set'
allow_cmd '[ -n "$TOKEN" ] && echo set || echo missing'
allow_cmd 'source .env && npm run deploy'
allow_cmd 'set -a; source .env; set +a; python app.py'
allow_cmd 'curl -H "Authorization: Bearer $API_TOKEN" https://api.example.com/v1/me'

echo "── Bash: printenv/env/export/set 打印环境 ──"
deny_cmd  'printenv'
deny_cmd  'printenv API_KEY'
deny_cmd  'printenv | grep -i key'
deny_cmd  'printenv aws_secret_access_key'
deny_cmd  'env'
deny_cmd  'env | sort'
deny_cmd  'env -0'
deny_cmd  'export -p'
deny_cmd  'export'
deny_cmd  'set'
deny_cmd  'set | grep KEY'
allow_cmd 'printenv HOME'
allow_cmd 'env FOO=1 npm test'
allow_cmd 'env -u DEBUG python app.py'
allow_cmd 'export FOO=bar'
allow_cmd 'set -euo pipefail'
# 只列变量名；env | cut -d= -f1 遇到多行值会把续行原样打出，仍拒绝
allow_cmd 'compgen -e'
deny_cmd  'env | cut -d= -f1'

echo "── Bash: git 操作里的 .env 字样放行 ──"
allow_cmd 'git status'
allow_cmd 'git check-ignore .env'
allow_cmd 'git add .env.example && git commit -m "add .env example"'
allow_cmd 'git log -p -- .env.example'

echo "── Bash: heredoc 正文与单引号里的文字不是命令 ──"
# 喂给 python3 的 heredoc 正文是 Python 代码，字符串字面量里的 `env` 只是 README 文字
IFS= read -r -d '' REPRO <<'CMD'
cd /p/repo && python3 - <<'EOF'
def sub(p, pairs):
    s=open(p).read()
    for a,b in pairs:
        assert s.count(a)==1,(p,a); s=s.replace(a,b)
    open(p,'w').write(s)
sub('README.md',[
("set `CONTEXT_WINDOW_TOKENS` to that window size in the `env` block of `~/.claude/settings.json`,",
 "set `CONTEXT_WINDOW_TOKENS` to that window size as a prefix on the watermark gate's command, for example `CONTEXT_WINDOW_TOKENS=200000 bash $HOME/.claude/hooks/context-watermark-gate.sh`,"),
])
EOF
git diff --stat; wc -l README.md zh/README.md
CMD
check allow "python3 heredoc 改 README（正文含 \`env\`）" "$(bash_json "$REPRO")"
allow_cmd $'cat <<\'EOF\'\nrun $(cat .env) to see\nEOF'
allow_cmd "git commit -m 'document the \`env\` block'"
# 命令前缀赋值只设变量，不打印值；名字里的 TOKENS 是词元数
# shellcheck disable=SC2016
allow_cmd 'CONTEXT_WINDOW_TOKENS=200000 bash $HOME/.claude/hooks/context-watermark-gate.sh'
deny_cmd  $'cat <<EOF\n$(cat .env)\nEOF'
deny_cmd  $'bash <<\'EOF\'\ncat .env\nEOF'
deny_cmd  $'sh <<EOF\nprintenv\nEOF'
# 双引号里的反引号会执行
# shellcheck disable=SC2016
deny_cmd  'git commit -m "document the `env` block"'

echo "── SSH 私钥与 Kamal secrets 同样是密钥文件 ──"
check deny  "Read ~/.ssh 私钥"           "$(read_json "$TMP/home/.ssh/id_ed25519")"
check deny  "Read ~/.ssh/*.key"           "$(read_json "$HOME/.ssh/ssh-key-2026-07-08.key")"
check deny  "Read .kamal/secrets.local"   "$(read_json /repo/.kamal/secrets.local)"
check deny  "Read .kamal/secrets"         "$(read_json /repo/.kamal/secrets)"
check allow "Read ~/.ssh 公钥"           "$(read_json "$TMP/home/.ssh/id_ed25519.pub")"
check allow "Read ~/.ssh/config"          "$(read_json "$HOME/.ssh/config")"
check allow "Read ~/.ssh/known_hosts"     "$(read_json "$HOME/.ssh/known_hosts")"
check allow "Read .kamal/hooks 下普通文件""$(read_json /repo/.kamal/hooks/pre-deploy)"
deny_cmd  'cat ~/.ssh/id_ed25519'
deny_cmd  'head -3 $HOME/.ssh/id_rsa'
deny_cmd  'cat .kamal/secrets.local'
deny_cmd  'base64 ~/.ssh/ssh-key-2026-07-08.key'
deny_in   kproj 'grep -r FAKE .'
deny_in   home  'grep -rn FAKE .'
allow_cmd 'cat ~/.ssh/id_ed25519.pub'
allow_cmd 'ssh-keygen -lf ~/.ssh/id_ed25519.pub'
allow_cmd 'ssh -i ~/.ssh/ssh-key-2026-07-08.key ubuntu@161.33.234.18 uptime'
allow_cmd 'cat ~/.ssh/config'
allow_in  kproj 'grep -r FAKE src'
allow_in  kproj 'ls -la .kamal'

echo "── Grep 工具：content 模式搜到密钥文件拒绝，只报文件名或计数放行 ──"
check deny  "Grep content 指向 .env"            "$(grep_json "$TMP/proj/.env" content)"
check deny  "Grep content 搜含 .env 的目录"     "$(grep_json "$TMP/proj" content)"
check deny  "Grep content 搜深层 .env.production" "$(grep_json "$TMP/nested" content)"
check deny  "Grep content glob 指向 .env*"      "$(grep_json "$TMP/nested" content '**/.env*')"
check deny  "Grep content 搜 .kamal"            "$(grep_json "$TMP/kproj" content)"
check deny  "Grep content 相对路径按 cwd 解析"  "$(grep_json ../proj content)"
check deny  "Grep content 花括号 glob 按命中算" "$(grep_json "$TMP/proj" content '*.{env,py}')"
check allow "Grep files_with_matches 搜含 .env 的目录" "$(grep_json "$TMP/proj" files_with_matches)"
check allow "Grep 缺省 output_mode"            "$(grep_json "$TMP/proj" '')"
check allow "Grep count 指向 .env"              "$(grep_json "$TMP/proj/.env" count)"
check allow "Grep content glob 排除 .env"       "$(grep_json "$TMP/proj" content '*.py')"
check allow "Grep content 搜无 .env 的目录"     "$(grep_json "$TMP/clean" content)"
check allow "Grep content 缺省 path（cwd 是 clean）" "$(grep_json '' content)"
check allow "Grep content 指向 .env.example"    "$(grep_json "$TMP/clean/.env.example" content)"

echo "── 拒绝写一行到拒绝日志，放行不写 ──"
rm -f "$PERMISSION_DENIED_LOG"
printf '%s' "$(bash_json 'ls -la')" | bash "$HOOK" >/dev/null 2>&1
[ ! -s "$PERMISSION_DENIED_LOG" ] && { PASS=$((PASS+1)); echo "  ✅ 放行不写日志"; } || { FAIL=$((FAIL+1)); echo "  ❌ 放行不应写日志"; }
printf '%s' "$(bash_json 'cat .env')" | bash "$HOOK" >/dev/null 2>&1
got=$(python3 -c '
import json, sys
try:
    r = [json.loads(l) for l in open(sys.argv[1], encoding="utf-8")]
    print(len(r), r[-1]["reason"], r[-1]["source"], r[-1]["tool_name"], r[-1]["target"])
except Exception as e:
    print("ERR", e)' "$PERMISSION_DENIED_LOG")
[ "$got" = "1 hook:secret-guard hook:secret-guard Bash cat .env" ] && { PASS=$((PASS+1)); echo "  ✅ 拒绝写一行（reason/source/tool_name/target）"; } || { FAIL=$((FAIL+1)); echo "  ❌ 日志行不对: $got"; }
out=$(printf '%s' "$(bash_json 'cat .env')" | PERMISSION_DENIED_LOG=/dev/null/nope/x.jsonl bash "$HOOK" 2>/dev/null | python3 -c 'import json,sys; print(json.load(sys.stdin)["hookSpecificOutput"]["permissionDecision"])' 2>/dev/null)
[ "$out" = deny ] && { PASS=$((PASS+1)); echo "  ✅ 日志不可写仍照常拒绝"; } || { FAIL=$((FAIL+1)); echo "  ❌ 日志不可写时应仍拒绝，得 $out"; }

echo "── 输入异常必须 fail-open ──"
check allow "非 JSON 输入" 'not json at all'
check allow "空输入" ''
check allow "tool_input 缺失" '{"tool_name":"Bash"}'
check allow "command 非字符串" '{"tool_name":"Bash","tool_input":{"command":["cat",".env"]}}'
check allow "未闭合引号" "$(bash_json "echo 'unterminated")"
check allow "其他工具" '{"tool_name":"Write","tool_input":{"file_path":".env","content":"x"}}'

echo
echo "PASS=$PASS FAIL=$FAIL"
[ "$FAIL" -eq 0 ]
