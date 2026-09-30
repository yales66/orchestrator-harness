#!/bin/bash
# 回归测试: worktree-symlink-claudemd.sh
# 跑法: bash hooks/tests/worktree-symlink-claudemd.test.sh
# 该 hook 会 rm -f 工作树里的 CLAUDE.md，重点钉住三件事：只在预期条件下删
# （工作树的 CLAUDE.md 与 HEAD 一致、链接目标确实存在）；删后建的符号链接按物理
# 路径指向主工作树的同名文件；异常输入一律放行。
# 所有仓库都建在临时目录里，git 全局与系统配置被隔离，HOME 也指向临时目录。
# 下面 bash -c 的脚本体有意用单引号。
# shellcheck disable=SC2016
HOOK="$(cd "$(dirname "$0")/.." && pwd)/worktree-symlink-claudemd.sh"
PASS=0; FAIL=0
# macOS 的 mktemp 在 /var 下，/var 是指向 /private/var 的链接；取物理路径，
# 使传给 hook 的路径与 git worktree list 打印的路径一致
TMP=$(cd "$(mktemp -d)" && pwd -P)
trap 'rm -rf "$TMP"' EXIT

mkdir -p "$TMP/home"
: > "$TMP/gitconfig"
export HOME="$TMP/home" GIT_CONFIG_GLOBAL="$TMP/gitconfig" GIT_CONFIG_NOSYSTEM=1 \
  GIT_CEILING_DIRECTORIES="$TMP"

ok()  { PASS=$((PASS+1)); printf '  ✅ %s\n' "$1"; }
bad() { FAIL=$((FAIL+1)); printf '  ❌ %s%s\n' "$1" "${2:+ （$2）}"; }

# expect <描述> <命令...>: 命令退出 0 即通过
expect() {
  local desc="$1"; shift
  if "$@" >/dev/null 2>&1; then ok "$desc"; else bad "$desc"; fi
}

# git_q <参数...>: 在隔离配置下跑 git，并关掉提交钩子
git_q() { git -c user.name=t -c user.email=t@example.com -c core.hooksPath=/dev/null "$@"; }

# mkrepo <名字> [主工作树里要提交的文件...]: 建 $TMP/<名字>/main 仓库，提交给定文件
# （内容为 "main <文件名>"），再在同级 wt 建一个链接工作树。打印 <名字> 的目录
mkrepo() {
  local root="$TMP/$1" f; shift
  mkdir -p "$root/main"
  git_q init -q "$root/main"
  printf 'readme\n' > "$root/main/README"
  for f in "$@"; do printf 'main %s\n' "$f" > "$root/main/$f"; done
  git_q -C "$root/main" add -A
  git_q -C "$root/main" commit -qm init
  git_q -C "$root/main" worktree add -q "$root/wt"
  echo "$root"
}

# run_hook <输入 JSON> [PATH 取值]: 把输入喂给 hook，stdout 写进 $TMP/out，返回 hook 退出码
run_hook() {
  if [ -n "${2:-}" ]; then
    printf '%s' "$1" | PATH="$2" "$BASH" "$HOOK" > "$TMP/out" 2>/dev/null
  else
    printf '%s' "$1" | bash "$HOOK" > "$TMP/out" 2>/dev/null
  fi
}

# links_to <链接> <期望的链接文本>: 是符号链接，且 readlink 原文等于期望值
links_to() { [ -L "$1" ] && [ "$(readlink "$1")" = "$2" ]; }

# regular_with <文件> <内容>: 是普通文件（不是链接），且内容等于给定值
regular_with() { [ -f "$1" ] && [ ! -L "$1" ] && [ "$(cat "$1")" = "$2" ]; }

# out_is_empty / out_mentions <文本>: 检查 hook 的 stdout
out_is_empty() { [ ! -s "$TMP/out" ]; }
out_mentions() {
  python3 -c '
import json,sys
msg=json.load(open(sys.argv[1]))["systemMessage"]
sys.exit(0 if sys.argv[2] in msg else 1)
' "$TMP/out" "$1"
}

# path_without <命令>: 只含 hook 所需工具、但缺 <命令> 的 PATH 目录
path_without() {
  local d="$TMP/path-without-$1" tool src
  mkdir -p "$d"
  for tool in awk basename bash cat git jq ln python3 rm; do
    [ "$tool" = "$1" ] && continue
    src="$(command -v "$tool")" || continue
    ln -sf "$src" "$d/$tool"
  done
  echo "$d"
}

# alias_of <目录>: 打印一条经过符号链接目录、指向 <目录> 的字面路径。macOS 上
# /var 是 /private/var 的链接，直接去掉 /private；没有这种路径的系统在 $TMP 里
# 建一个指向 <目录> 的链接目录模拟
alias_of() {
  if [ "${1#/private/}" != "$1" ] && [ "${1#/private}" -ef "$1" ]; then
    echo "${1#/private}"
  else
    ln -s "$1" "$1-alias"; echo "$1-alias"
  fi
}

echo "── 正常路径：受版本控制的 CLAUDE.md 被换成指向主工作树的相对链接 ──"
R=$(mkrepo basic CLAUDE.md)
run_hook "{\"path\":\"$R/wt\"}"
expect "hook 退出 0" [ $? -eq 0 ]
expect "工作树的 CLAUDE.md 变成链接，链接文本是 ../main/CLAUDE.md" links_to "$R/wt/CLAUDE.md" ../main/CLAUDE.md
expect "链接解析到主工作树的 CLAUDE.md" cmp "$R/wt/CLAUDE.md" "$R/main/CLAUDE.md"
expect "主工作树的 CLAUDE.md 原样保留为普通文件" regular_with "$R/main/CLAUDE.md" "main CLAUDE.md"
expect "工作树里给 CLAUDE.md 打上 skip-worktree" \
  bash -c '[ "$(git -C "$0" ls-files -v CLAUDE.md)" = "S CLAUDE.md" ]' "$R/wt"
expect "git status 看不到这次替换" bash -c '[ -z "$(git -C "$0" status --porcelain)" ]' "$R/wt"
expect "systemMessage 报出建的链接" out_mentions "CLAUDE.md → ../main/CLAUDE.md"
expect "systemMessage 带工作树目录名" out_mentions "worktree wt:"

echo "── 幂等：已是链接的不再动 ──"
run_hook "{\"path\":\"$R/wt\"}"
expect "第二次运行不输出" out_is_empty
expect "第二次运行后链接不变" links_to "$R/wt/CLAUDE.md" ../main/CLAUDE.md
R=$(mkrepo custom-link CLAUDE.md)
rm "$R/wt/CLAUDE.md"; printf 'mine\n' > "$R/wt/own.md"; ln -s own.md "$R/wt/CLAUDE.md"
run_hook "{\"path\":\"$R/wt\"}"
expect "用户自建的 CLAUDE.md 链接不被改指向" links_to "$R/wt/CLAUDE.md" own.md
expect "链接目标文件原样保留" regular_with "$R/wt/own.md" mine

echo "── 工作树的 CLAUDE.md 与 HEAD 不一致时保留：skip-worktree 会让 git status 看不到这次替换 ──"
R=$(mkrepo dirty CLAUDE.md)
mkdir -p "$R/main/node_modules"
printf 'edited in worktree\n' > "$R/wt/CLAUDE.md"
run_hook "{\"path\":\"$R/wt\"}"
expect "有未提交改动的 CLAUDE.md 保持普通文件、内容不变" regular_with "$R/wt/CLAUDE.md" "edited in worktree"
expect "不给它打 skip-worktree" \
  bash -c '[ "$(git -C "$0" ls-files -v CLAUDE.md)" = "H CLAUDE.md" ]' "$R/wt"
expect "git status 仍能看到这处改动" \
  bash -c '[ "$(git -C "$0" status --porcelain -- CLAUDE.md)" = " M CLAUDE.md" ]' "$R/wt"
expect "主工作树的 CLAUDE.md 不受影响" regular_with "$R/main/CLAUDE.md" "main CLAUDE.md"
expect "其余目标照常建链接" links_to "$R/wt/node_modules" ../main/node_modules
expect "systemMessage 说明保留了 CLAUDE.md 及原因" out_mentions "kept CLAUDE.md: it differs from HEAD"
expect "systemMessage 仍列出建的链接" out_mentions "symlinked node_modules → ../main/node_modules"
R=$(mkrepo staged CLAUDE.md)
printf 'staged in worktree\n' > "$R/wt/CLAUDE.md"; git_q -C "$R/wt" add CLAUDE.md
run_hook "{\"path\":\"$R/wt\"}"
expect "已暂存未提交的改动同样保留" regular_with "$R/wt/CLAUDE.md" "staged in worktree"
expect "只有保留原因时 systemMessage 照样输出" out_mentions "kept CLAUDE.md: it differs from HEAD"

echo "── 工作树路径经过符号链接目录：git 打印物理路径，链接按物理路径算 ──"
R=$(mkrepo via-symlink CLAUDE.md)
mkdir -p "$R/main/node_modules"
L=$(alias_of "$R")
run_hook "{\"path\":\"$L/wt\"}"
expect "对照：字面路径与物理路径不同、指向同一目录" bash -c '[ "$0" != "$1" ] && [ "$0" -ef "$1" ]' "$L/wt" "$R/wt"
expect "CLAUDE.md 链接文本是 ../main/CLAUDE.md" links_to "$R/wt/CLAUDE.md" ../main/CLAUDE.md
expect "CLAUDE.md 链接不悬空，解析到主工作树的 CLAUDE.md" cmp "$R/wt/CLAUDE.md" "$R/main/CLAUDE.md"
expect "node_modules 链接同样按物理路径算" links_to "$R/wt/node_modules" ../main/node_modules
expect "systemMessage 报出的链接文本按物理路径算" out_mentions "CLAUDE.md → ../main/CLAUDE.md"
R=$(mkrepo via-symlink-main CLAUDE.md)
L=$(alias_of "$R")
run_hook "{\"path\":\"$L/main\"}"
expect "经链接目录传入主工作树时，主工作树的 CLAUDE.md 原样保留" regular_with "$R/main/CLAUDE.md" "main CLAUDE.md"
expect "经链接目录传入主工作树时不输出" out_is_empty
R=$(mkrepo bad-relpath CLAUDE.md)
mkdir -p "$TMP/fake-python"
printf '#!/bin/sh\necho ../elsewhere/CLAUDE.md\n' > "$TMP/fake-python/python3"
chmod +x "$TMP/fake-python/python3"
run_hook "{\"path\":\"$R/wt\"}" "$TMP/fake-python:$(path_without python3)"
expect "算出的链接目标不存在时，不删工作树的 CLAUDE.md" regular_with "$R/wt/CLAUDE.md" "main CLAUDE.md"
expect "算出的链接目标不存在时不输出" out_is_empty

echo "── 不该删的情形：工作树的 CLAUDE.md 保持原样 ──"
R=$(mkrepo no-main-claude)
printf 'local only\n' > "$R/wt/CLAUDE.md"
run_hook "{\"path\":\"$R/wt\"}"
expect "主工作树没有 CLAUDE.md 时，不动工作树里的 CLAUDE.md" regular_with "$R/wt/CLAUDE.md" "local only"
expect "主工作树没有 CLAUDE.md 时不输出" out_is_empty
R=$(mkrepo is-main CLAUDE.md)
run_hook "{\"path\":\"$R/main\"}"
expect "路径就是主工作树时不动它的 CLAUDE.md" regular_with "$R/main/CLAUDE.md" "main CLAUDE.md"
expect "路径就是主工作树时不输出" out_is_empty
mkdir -p "$TMP/plain"; printf 'plain\n' > "$TMP/plain/CLAUDE.md"
run_hook "{\"path\":\"$TMP/plain\"}"
expect "不在 git 仓库里的目录不动" regular_with "$TMP/plain/CLAUDE.md" plain
expect "不在 git 仓库里的目录不输出" out_is_empty
R=$(mkrepo restricted-path CLAUDE.md)
run_hook "{\"path\":\"$R/wt\"}" "$(path_without none)"
expect "对照：受限 PATH 里工具齐全时照常建链接" links_to "$R/wt/CLAUDE.md" ../main/CLAUDE.md
R=$(mkrepo no-python CLAUDE.md)
run_hook "{\"path\":\"$R/wt\"}" "$(path_without python3)"
expect "缺 python3 算不出相对路径时，不删工作树的 CLAUDE.md" regular_with "$R/wt/CLAUDE.md" "main CLAUDE.md"
expect "缺 python3 时不输出" out_is_empty

echo "── 各种输入字段都能取到工作树路径 ──"
for field in '.worktree' '.tool_response.path' '.tool_response.worktree_path' \
             '.tool_response.cwd' '.tool_input.path' '.tool_input.target'; do
  R=$(mkrepo "field$(printf '%s' "$field" | tr '.' '-')" CLAUDE.md)
  payload=$(jq -n --arg p "$R/wt" --arg f "$field" 'setpath($f | ltrimstr(".") | split("."); $p)')
  run_hook "$payload"
  expect "取 $field 后建链接" links_to "$R/wt/CLAUDE.md" ../main/CLAUDE.md
done

echo "── node_modules 与 .env*：只补缺，不覆盖真文件，跳过模板 ──"
R=$(mkrepo extras CLAUDE.md .env.example)
mkdir -p "$R/main/node_modules/pkg"
for f in .env .env.local .env.sample .env.schema .env.template; do printf 'main %s\n' "$f" > "$R/main/$f"; done
run_hook "{\"path\":\"$R/wt\"}"
expect "node_modules 链到主工作树" links_to "$R/wt/node_modules" ../main/node_modules
expect ".env 链到主工作树" links_to "$R/wt/.env" ../main/.env
expect ".env.local 链到主工作树" links_to "$R/wt/.env.local" ../main/.env.local
expect "受版本控制的 .env.example 保持普通文件" regular_with "$R/wt/.env.example" "main .env.example"
expect ".env.sample、.env.schema、.env.template 不建链接" \
  bash -c '[ ! -e "$0/.env.sample" ] && [ ! -e "$0/.env.schema" ] && [ ! -e "$0/.env.template" ]' "$R/wt"
expect "systemMessage 列出全部四个链接" out_mentions \
  "CLAUDE.md → ../main/CLAUDE.md, node_modules → ../main/node_modules, .env → ../main/.env, .env.local → ../main/.env.local"
R=$(mkrepo extras-real)
mkdir -p "$R/main/node_modules" "$R/wt/node_modules/own"
printf 'main env\n' > "$R/main/.env"; printf 'wt env\n' > "$R/wt/.env"
run_hook "{\"path\":\"$R/wt\"}"
expect "工作树里真实的 node_modules 目录不被覆盖" bash -c '[ ! -L "$0/node_modules" ] && [ -d "$0/node_modules/own" ]' "$R/wt"
expect "工作树里真实的 .env 不被覆盖" regular_with "$R/wt/.env" "wt env"
expect "没有新建链接时不输出" out_is_empty

echo "── 输入异常一律放行：退出 0、不输出 ──"
# allows <描述> <输入 JSON>
allows() {
  run_hook "$2"
  expect "$1" bash -c '[ "$0" -eq 0 ] && [ ! -s "$1" ]' "$?" "$TMP/out"
}
allows "非 JSON 输入" 'not json at all'
allows "空输入" ''
allows "空对象" '{}'
allows "path 为空串" '{"path":""}'
allows "path 为 null" '{"path":null}'
allows "path 指向不存在的目录" "{\"path\":\"$TMP/nope\"}"

echo
echo "PASS=$PASS FAIL=$FAIL"
[ "$FAIL" -eq 0 ]
