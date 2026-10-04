#!/usr/bin/env python3
"""Extract what the user personally said in a Claude Code session, plus git state, for a handoff.

Writes into --out:
  user-messages.md  every input the user gave (typed messages, slash commands, choice answers,
                    tool-call rejections), numbered U1..Un in time order, full text
  git-state.md      branch, status, commits ahead of upstream and recent commits per --repo

Usage: python3 extract.py --out DIR --transcript PATH [--repo PATH ...]
--transcript is required: a parallel session in the same project can own the newest file.
Only the standard library is used.
"""
import argparse
import json
import os
import re
import subprocess
import sys

# User records that were not typed by the user, recognised by how their text starts.
# Newer transcripts also carry `origin.kind`; older ones only have the text.
AUTO_PREFIXES = (
    "<task-notification>", "<local-command-stdout>", "<local-command-stderr>",
    "<local-command-caveat>", "<bash-stdout>", "<bash-stderr>", "<bash-input>",
    "<ci-monitor-event>", "<system-reminder>", "<user-memory-input>", "<agent-message",
    "Another Claude session sent a message", "Stop hook feedback",
    "This session is being continued", "Caveat:",
)
INTERRUPT = "[Request interrupted by user"
# AskUserQuestion results open with either wording; both carry the answers as "question"="answer".
ANSWERED = ("Your questions have been answered", "The user answered:")
REJECTED = "The user doesn't want to proceed with this tool use"
USER_SAID = "the user said:"
SUMMARY_MAX = 120
STATUS_MAX = 40
SUMMARY_KEYS = ("command", "file_path", "notebook_path", "path", "url", "pattern", "query", "prompt")


def load(path):
    rows = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            try:
                d = json.loads(line)
            except ValueError:
                continue
            if isinstance(d, dict):
                rows.append(d)
    return rows


def blocks(rec):
    content = (rec.get("message") or {}).get("content") if isinstance(rec.get("message"), dict) else None
    if isinstance(content, str):
        return [{"type": "text", "text": content}]
    return [b for b in content if isinstance(b, dict)] if isinstance(content, list) else []


def text_of(rec):
    parts = []
    for b in blocks(rec):
        if b.get("type") == "text":
            parts.append(b.get("text") or "")
        elif b.get("type") == "image":
            parts.append("[image]")
    return "\n".join(parts)


def result_text(block):
    c = block.get("content")
    if isinstance(c, str):
        return c
    if isinstance(c, list):
        return "\n".join(x.get("text") or "" for x in c if isinstance(x, dict))
    return ""


def is_typed(rec):
    """True for a user record the user typed (text or slash command), not an injection."""
    if rec.get("isMeta") or rec.get("isCompactSummary") or rec.get("isSidechain"):
        return False
    origin = rec.get("origin")
    if isinstance(origin, dict) and origin.get("kind") and origin.get("kind") != "human":
        return False
    stripped = text_of(rec).lstrip()
    if stripped.startswith(INTERRUPT) or stripped.startswith(AUTO_PREFIXES):
        return False
    return True


def typed_text(rec):
    text = text_of(rec)
    if "<command-name>" in text[:300]:
        name = re.search(r"<command-name>(.*?)</command-name>", text, re.S)
        args = re.search(r"<command-args>(.*?)</command-args>", text, re.S)
        name = (name.group(1) if name else "").strip().lstrip("/")
        return ("/" + name + " " + (args.group(1).strip() if args else "")).strip()
    return text


def summarize(inp):
    if not isinstance(inp, dict):
        s = str(inp)
    else:
        s = next((str(inp[k]) for k in SUMMARY_KEYS if inp.get(k)), json.dumps(inp, ensure_ascii=False))
    s = re.sub(r"\s+", " ", s).strip()
    return s if len(s) <= SUMMARY_MAX else s[:SUMMARY_MAX - 1] + "…"


def choice_body(rec, text):
    tur = rec.get("toolUseResult")
    pairs = []
    notes = {}
    if isinstance(tur, dict) and isinstance(tur.get("answers"), dict):
        pairs = list(tur["answers"].items())
        ann = tur.get("annotations")
        if isinstance(ann, dict):
            notes = {q: a.get("notes") for q, a in ann.items() if isinstance(a, dict) and a.get("notes")}
    if not pairs:
        pairs = re.findall(r'"(.*?)"="(.*?)"', text, re.S)
    if not pairs:
        return text
    lines = []
    for q, a in pairs:
        lines.append(f"问：{q}")
        lines.append(f"答：{a}")
        if q in notes:
            lines.append(f"备注：{notes[q]}")
    return "\n".join(lines)


def reject_body(tool, text):
    name = tool.get("name") if tool else None
    line = f"拒绝了 {name or '未知工具'} 调用"
    if tool:
        line += "：" + summarize(tool.get("input"))
    idx = text.find(USER_SAID)
    if idx >= 0 and text[idx + len(USER_SAID):].strip():
        line += "\n用户说明：" + text[idx + len(USER_SAID):].strip()
    return line


def collect(rows):
    """Return [(timestamp, kind, body)] in time order."""
    tools, seen, out = {}, set(), []
    for r in rows:
        if r.get("type") == "assistant":
            for b in blocks(r):
                if b.get("type") == "tool_use" and b.get("id"):
                    tools[b["id"]] = b
    for i, r in enumerate(rows):
        if r.get("type") != "user" or r.get("isSidechain"):
            continue
        uid = r.get("uuid")
        if uid:
            if uid in seen:
                continue
            seen.add(uid)
        ts = r.get("timestamp") or ""
        results = [b for b in blocks(r) if b.get("type") == "tool_result"]
        if results:
            for b in results:
                text = result_text(b)
                if text.lstrip().startswith(ANSWERED):
                    out.append((ts, i, "选择题回答", choice_body(r, text)))
                elif REJECTED in text:
                    out.append((ts, i, "拒绝工具调用", reject_body(tools.get(b.get("tool_use_id")), text)))
            continue
        if is_typed(r):
            out.append((ts, i, "", typed_text(r)))
    out.sort(key=lambda e: (e[0], e[1]))
    return [(ts, kind, body) for ts, _, kind, body in out]


def render_messages(transcript, items):
    lines = [f"# 用户输入", "", f"来源：`{transcript}`，共 {len(items)} 条。", ""]
    for n, (ts, kind, body) in enumerate(items, 1):
        lines.append(f"## U{n} · {ts}" + (f" · {kind}" if kind else ""))
        lines.append("")
        lines.append(body)
        lines.append("")
    return "\n".join(lines)


def git_out(repo, *args):
    p = subprocess.run(["git", "-C", repo, *args], capture_output=True, text=True)
    return p.returncode, p.stdout.rstrip("\n"), p.stderr.strip()


def fence(text):
    return ["```", text, "```"] if text else ["（无）"]


def render_repo(repo):
    lines = [f"## {repo}", ""]
    code, branch, err = git_out(repo, "rev-parse", "--abbrev-ref", "HEAD")
    if code != 0:
        return lines + [f"不是可读的 git 仓库：{err}", ""]
    if branch == "HEAD":
        _, sha, _ = git_out(repo, "rev-parse", "--short", "HEAD")
        branch = f"（分离头指针 {sha}）"
    lines += [f"分支：{branch}", "", "### git status -s", ""]
    _, status, _ = git_out(repo, "status", "-s")
    st = status.splitlines()
    lines += fence("\n".join(st[:STATUS_MAX]))
    if len(st) > STATUS_MAX:
        lines.append(f"（另有 {len(st) - STATUS_MAX} 行，已省略 {len(st) - STATUS_MAX} 行）")
    lines += ["", "### 领先上游的提交", ""]
    code, _, _ = git_out(repo, "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}")
    if code != 0:
        lines.append("无上游")
    else:
        _, ahead, _ = git_out(repo, "log", "--oneline", "@{u}..")
        lines += fence(ahead)
    lines += ["", "### 最近 5 个提交", ""]
    _, recent, _ = git_out(repo, "log", "--oneline", "-5")
    lines += fence(recent) + [""]
    return lines


def render_git(repos):
    lines = ["# git 状态", ""]
    if not repos:
        lines += ["未指定 --repo。", ""]
    for repo in repos:
        lines += render_repo(os.path.abspath(repo))
    return "\n".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", required=True)
    ap.add_argument("--transcript", required=True)
    ap.add_argument("--repo", action="append", default=[])
    args = ap.parse_args(argv)

    transcript = args.transcript
    if not os.path.isfile(transcript):
        print(f"找不到会话记录：{transcript}", file=sys.stderr)
        return 2

    os.makedirs(args.out, exist_ok=True)
    msgs_path = os.path.join(args.out, "user-messages.md")
    git_path = os.path.join(args.out, "git-state.md")
    with open(msgs_path, "w", encoding="utf-8") as fh:
        fh.write(render_messages(os.path.abspath(transcript), collect(load(transcript))))
    with open(git_path, "w", encoding="utf-8") as fh:
        fh.write(render_git(args.repo))
    print(msgs_path)
    print(git_path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
