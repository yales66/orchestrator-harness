import pytest

import run

LIMIT_TEXT = "You've hit your session limit · resets 6:50pm (Australia/Sydney)"


def synthetic(error: str) -> dict:
    return {"type": "assistant", "error": error, "isApiErrorMessage": True,
            "message": {"model": "<synthetic>", "stop_reason": "stop_sequence",
                        "content": [{"type": "text", "text": LIMIT_TEXT}]}}


def served(text: str = "done") -> dict:
    return {"type": "assistant", "message": {"model": "claude-opus-5-5", "stop_reason": "end_turn",
                                             "content": [{"type": "text", "text": text}]}}


def limit_event(status: str) -> dict:
    return {"type": "rate_limit_event", "rate_limit_info": {"status": status, "rateLimitType": "five_hour"}}


RESULT_OK = {"type": "result", "is_error": False, "result": "ok"}
RESULT_429 = {"type": "result", "is_error": True, "api_error_status": 429, "result": LIMIT_TEXT}


@pytest.mark.parametrize("stream, sub, expected", [
    ([limit_event("allowed"), RESULT_OK], [served()], None),
    ([limit_event("allowed_warning"), RESULT_OK], [served()], None),
    ([limit_event("rejected"), RESULT_429], [served("half"), synthetic("rate_limit")], "rate_limited"),
    ([limit_event("rejected"), RESULT_429], [], "rate_limited"),
    ([RESULT_429], None, "rate_limited"),
    ([RESULT_OK], [served("half"), synthetic("server_error")], "api_error"),
], ids=["clean", "warning-only", "subagent-cut-by-limit", "rejected-before-dispatch",
        "no-subagent-transcript", "subagent-cut-by-other-api-error"])
def test_api_failure(stream, sub, expected):
    assert run.api_failure(stream, sub or []) == expected
