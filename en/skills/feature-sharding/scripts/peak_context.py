#!/usr/bin/env python3
"""统计 Claude Code session transcript（JSONL）的峰值 context token。

用法：peak_context.py <transcript.jsonl> [more.jsonl ...]
每文件输出一行：<路径> <峰值>。峰值 = 单条 assistant 消息的
input + cache_read + cache_creation 三项之和的最大值。
"""
import json
import sys


def peak(path):
    m = 0
    for line in open(path):
        try:
            u = (json.loads(line).get("message") or {}).get("usage") or {}
        except Exception:
            continue
        m = max(m, u.get("input_tokens", 0)
                + u.get("cache_read_input_tokens", 0)
                + u.get("cache_creation_input_tokens", 0))
    return m


if __name__ == "__main__":
    for f in sys.argv[1:]:
        print(f, peak(f))
