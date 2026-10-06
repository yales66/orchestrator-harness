"""peak_context.py 的表征测试：python3 test_peak_context.py 直接跑，打印 OK 即全过。"""
import json
import os
import tempfile

import peak_context


def _tmp_jsonl(lines):
    f = tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False)
    f.write("\n".join(lines) + "\n")
    f.close()
    return f.name


def test_peak_is_max_of_three_field_sum():
    path = _tmp_jsonl([
        json.dumps({"message": {"usage": {"input_tokens": 10,
                                          "cache_read_input_tokens": 20,
                                          "cache_creation_input_tokens": 5}}}),  # 35
        json.dumps({"message": {"usage": {"input_tokens": 100}}}),  # 100，缺字段按 0
        json.dumps({"type": "no-message-here"}),  # 无 message，跳过
        "not valid json at all",  # 坏行，跳过
        json.dumps({"message": "plain string message"}),  # message 非 dict，跳过
    ])
    try:
        assert peak_context.peak(path) == 100, f"expected 100, got {peak_context.peak(path)}"
    finally:
        os.unlink(path)


def test_empty_file_gives_zero():
    path = _tmp_jsonl([])
    try:
        assert peak_context.peak(path) == 0
    finally:
        os.unlink(path)


if __name__ == "__main__":
    test_peak_is_max_of_three_field_sum()
    test_empty_file_gives_zero()
    print("OK")
