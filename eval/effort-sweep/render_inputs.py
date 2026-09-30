"""Render cases.jsonl as a single static page for the inputs sign-off.

  python3 eval/effort-sweep/render_inputs.py --data "$DATA"    # writes $DATA/inputs.html
"""
from __future__ import annotations

import argparse
import html
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import EXCLUDE, TIER_LABELS, TIERS, load_cases  # noqa: E402

CSS = """
:root { --bg:#fbfaf7; --fg:#1f2328; --muted:#5d6570; --line:#d9d6cf; --card:#ffffff; --accent:#2f5d8a; --code:#f2f0ea; --tag:#e8eef5; }
@media (prefers-color-scheme: dark) { :root:not([data-theme="light"]) { --bg:#16181b; --fg:#e6e6e3; --muted:#a0a6ad; --line:#33373c; --card:#1d2024; --accent:#8db4dc; --code:#24282d; --tag:#243242; } }
:root[data-theme="dark"] { --bg:#16181b; --fg:#e6e6e3; --muted:#a0a6ad; --line:#33373c; --card:#1d2024; --accent:#8db4dc; --code:#24282d; --tag:#243242; }
* { box-sizing:border-box; }
body { margin:0; background:var(--bg); color:var(--fg); font:15px/1.6 -apple-system, "PingFang SC", "Noto Sans SC", sans-serif; }
main { max-width:980px; margin:0 auto; padding:24px 16px 64px; }
h1 { font-size:24px; margin:0 0 8px; } h2 { font-size:18px; margin:32px 0 8px; } h3 { font-size:16px; margin:0 0 6px; }
p { margin:6px 0; } .muted { color:var(--muted); }
table { border-collapse:collapse; width:100%; margin:8px 0; font-size:14px; }
th, td { border:1px solid var(--line); padding:6px 8px; text-align:left; vertical-align:top; }
th { background:var(--code); font-weight:600; }
.wrap { overflow-x:auto; }
section.case { background:var(--card); border:1px solid var(--line); border-radius:8px; padding:16px; margin:16px 0; }
.tag { display:inline-block; background:var(--tag); border-radius:4px; padding:0 6px; margin-right:6px; font-size:13px; }
code, pre { background:var(--code); border-radius:4px; font:13px/1.5 ui-monospace, SFMono-Regular, Menlo, monospace; }
code { padding:1px 4px; word-break:break-all; }
pre { padding:10px; white-space:pre-wrap; word-break:break-word; max-height:520px; overflow:auto; }
details { margin-top:8px; } summary { cursor:pointer; color:var(--accent); }
a { color:var(--accent); }
"""


def esc(s) -> str:
    return html.escape(str(s))


def tokens(u: dict) -> str:
    return f"{sum((u or {}).values()):,}"


def grading_block(c: dict) -> str:
    if c["tier"] == "impl":
        rows = "".join(
            f"<tr><td><code>{esc(cmd['run'])}</code></td><td>{esc(cmd.get('expect', 'exit0') == 'quiet' and '退出码 0 且无输出' or '退出码 0')}</td></tr>"
            for cmd in c["selfcheck"]["commands"])
        hidden = ""
        if c.get("hidden"):
            hrows = "".join(f"<code>{esc(h['run'])}</code><br>" for h in c["hidden"]["commands"])
            hidden = (f"<p>回放原提交的测试（只记入 checks）：{hrows}回放文件 "
                      + "、".join(f"<code>{esc(f)}</code>" for f in c["hidden"]["files"]) + "</p>")
        scope = "、".join(f"<code>{esc(s)}</code>" for s in c["scope"])
        deny = ("；不许改 " + "、".join(f"<code>{esc(s)}</code>" for s in c["scope_deny"])) if c.get("scope_deny") else ""
        return (f"<p><b>自验命令</b>（在工作区根目录执行，判分器逐条重跑）</p><div class=wrap><table><tr><th>命令</th><th>通过条件</th></tr>{rows}</table></div>"
                f"<p><b>未纳入判分的自验项</b>：{esc(c['selfcheck']['ungraded'])}</p>"
                f"<p><b>判分方式</b>：{esc(c['grading'])}</p><p><b>文件范围</b>：{scope}{deny}</p>{hidden}"
                f"<p class=muted>自检用的参照终态：基线提交 <code>{esc(c['base'])}</code> 上叠加提交 <code>{esc(c['oracle_commit'])}</code> 里范围内的 {len(c['oracle_files'])} 个文件。</p>")
    rows = "".join(
        f"<tr><td>{esc(k['id'])}</td><td>{esc(k['desc'])}</td><td><code>{'</code><br><code>'.join(esc(p) for p in k['any'])}</code></td></tr>"
        for k in c["checks"])
    forbid = "".join(
        f"<tr><td>{esc(k['id'])}</td><td>禁止出现：{esc(k['desc'])}</td><td><code>{'</code><br><code>'.join(esc(p) for p in k['any'])}</code></td></tr>"
        for k in c.get("forbid", []))
    files = ("；产物文件 " + "、".join(f"<code>{esc(f)}</code>" for f in c["answer_files"]) + " 与最终回报合并判分") if c.get("answer_files") else ""
    return (f"<p><b>自验命令</b>：无，只读派发。</p><p><b>判分方式</b>：{esc(c['grading'])}{files}</p>"
            f"<div class=wrap><table><tr><th>检查点</th><th>含义</th><th>任一正则命中即算（忽略大小写）</th></tr>{rows}{forbid}</table></div>"
            f"<p class=muted>结论出处：{esc(c['adopted_in'])}</p>")


def excluded_block(every_case: list[dict]) -> str:
    known = {c["id"]: c for c in every_case}
    rows = []
    for cid, reason in EXCLUDE.items():
        c = known.get(cid)
        tier = esc(TIER_LABELS[c["tier"]]) if c else "未收录"
        summary = esc(c["summary"]) if c else "未收录"
        rows.append(f"<tr><td><code>{esc(cid)}</code></td><td>{tier}</td><td>{summary}</td><td>{esc(reason)}</td></tr>")
    return (f"<h2 id='excluded'>剔除的案例</h2><p>以下 {len(EXCLUDE)} 个案例不参加运行，运行脚本、自检脚本与本页读取案例时都会跳过它们。</p>"
            f"<div class=wrap><table><tr><th>案例</th><th>层级</th><th>派发目标</th><th>剔除理由</th></tr>{''.join(rows)}</table></div>")


def render(cases: list[dict], every_case: list[dict]) -> str:
    counts = Counter(c["tier"] for c in cases)
    index = "".join(
        f"<tr><td><a href='#{esc(c['id'])}'>{esc(c['id'])}</a></td><td>{esc(TIER_LABELS[c['tier']])}</td><td>{esc(c['summary'])}</td></tr>"
        for c in cases)
    tier_rows = "".join(f"<tr><td>{esc(TIER_LABELS[t])}</td><td>{counts.get(t, 0)}</td></tr>" for t in TIERS)
    parts = [
        "<!doctype html><html lang=zh><head><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'>",
        f"<title>Effort Sweep 输入集</title><style>{CSS}</style></head><body><main>",
        "<h1>Effort Sweep 输入集</h1>",
        f"<p>同一份派发说明分别交给推理强度设为 high 和 medium 的子智能体，比较完成质量与花费。以下是参加运行的全部案例，取自 2026-09-16 至 2026-09-29 主会话里的真实派发；每个案例在派发当时的提交上建临时工作区运行。另有 {len(EXCLUDE)} 个案例已剔除，理由列在<a href='#excluded'>剔除的案例</a>一节。</p>",
        f"<div class=wrap><table><tr><th>层级</th><th>案例数</th></tr>{tier_rows}<tr><td>合计</td><td>{len(cases)}</td></tr></table></div>",
        "<p>单案的历史花费取自原子智能体记录里各次请求的用量之和（未缓存输入、输出、缓存读写合计），是历史值而不是试跑值；原记录的模型见各案。</p>",
        excluded_block(every_case),
        f"<h2>目录</h2><div class=wrap><table><tr><th>案例</th><th>层级</th><th>派发目标</th></tr>{index}</table></div>",
    ]
    for c in cases:
        h = c["history"]
        u = h.get("usage") or {}
        parts.append(
            f"<section class=case id='{esc(c['id'])}'><h3>{esc(c['id'])}</h3>"
            f"<p><span class=tag>{esc(TIER_LABELS[c['tier']])}</span><span class=tag>{esc(Path(c['repo']).name)}@{esc(c['base'])}</span>"
            f"<span class=tag>{esc(c['source']['ts'][:16].replace('T', ' '))} UTC</span></p>"
            f"<p><b>派发目标</b>：{esc(c['summary'])}</p>"
            + grading_block(c) +
            f"<p class=muted>历史用量：合计 {tokens(u)} 词元，其中输出 {u.get('output_tokens', 0):,}，缓存读 {u.get('cache_read_input_tokens', 0):,}；"
            f"工具调用 {h.get('tool_calls')} 次；原模型 {esc('、'.join(h.get('models') or {}))}。</p>"
            f"<details><summary>派发说明原文（{len(c['prompt'])} 字）</summary><pre>{esc(c['prompt'])}</pre></details>"
            "</section>")
    parts.append("</main></body></html>")
    return "".join(parts)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True, type=Path)
    args = ap.parse_args()
    cases = load_cases(args.data / "cases.jsonl")
    every_case = load_cases(args.data / "cases.jsonl", include_excluded=True)
    order = {t: i for i, t in enumerate(TIERS)}
    cases.sort(key=lambda c: (order[c["tier"]], c["id"]))
    (args.data / "inputs.html").write_text(render(cases, every_case), encoding="utf-8")
    print(f"wrote {args.data / 'inputs.html'} with {len(cases)} cases, {len(EXCLUDE)} excluded")
    return 0


if __name__ == "__main__":
    sys.exit(main())
