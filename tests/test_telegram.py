import logging

import pytest
import requests

from goldsilver.logging_setup import RedactingFilter, redact
from goldsilver.telegram_client import TelegramClient, TelegramError

TOKEN = "123456789:" + "A" * 35


class FakeResponse:
    def __init__(self, status, body=None, text=""):
        self.status_code, self._body, self.text = status, body, text

    def json(self):
        if self._body is None:
            raise ValueError("no json")
        return self._body


class FakeSession:
    def __init__(self, outcomes):
        self.outcomes, self.calls = list(outcomes), []

    def post(self, url, json=None, timeout=None):
        self.calls.append({"url": url, "json": json, "timeout": timeout})
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def ok():
    return FakeResponse(200, {"ok": True, "result": {}})


def client(session, **kw):
    return TelegramClient(TOKEN, "-1001234567890", session=session, sleep=lambda s: None, **kw)


def test_sends_plain_text_without_parse_mode():
    s = FakeSession([ok()])
    assert client(s, disable_notification=True).send_messages(["hello"]) == 1
    call = s.calls[0]
    assert call["url"].endswith("/sendMessage") and TOKEN in call["url"]
    assert call["json"] == {"chat_id": "-1001234567890", "text": "hello", "disable_notification": True,
                            "disable_web_page_preview": True}
    assert "parse_mode" not in call["json"] and call["timeout"] == 20


def test_retries_network_errors_then_succeeds():
    s = FakeSession([requests.exceptions.ConnectTimeout("t"), requests.exceptions.ConnectionError("c"), ok()])
    assert client(s, max_retries=3).send_messages(["x"]) == 1
    assert len(s.calls) == 3


def test_retries_429_and_5xx():
    s = FakeSession([FakeResponse(429, {"ok": False, "error_code": 429, "description": "Too Many Requests",
                                        "parameters": {"retry_after": 1}}),
                     FakeResponse(502, None, "bad gateway"), ok()])
    assert client(s).send_messages(["x"]) == 1


def test_gives_up_after_max_attempts():
    s = FakeSession([requests.exceptions.ReadTimeout("slow")] * 3)
    with pytest.raises(TelegramError, match="after 3 attempts"):
        client(s, max_retries=2).send_messages(["x"])


@pytest.mark.parametrize("code,desc,expect", [
    (401, "Unauthorized", "token is invalid"),
    (400, "Bad Request: chat not found", "Chat not found"),
    (403, "Forbidden: bot was kicked from the group chat", "not a member"),
])
def test_client_errors_are_not_retried_and_are_explained(code, desc, expect):
    s = FakeSession([FakeResponse(code, {"ok": False, "error_code": code, "description": desc})])
    with pytest.raises(TelegramError, match=expect):
        client(s).send_messages(["x"])
    assert len(s.calls) == 1


def test_partial_delivery_is_reported():
    s = FakeSession([ok(), FakeResponse(403, {"ok": False, "error_code": 403, "description": "Forbidden"})])
    with pytest.raises(TelegramError) as info:
        client(s).send_messages(["one", "two"])
    assert (info.value.delivered, info.value.total) == (1, 2)


def test_token_is_redacted_from_errors_and_logs(caplog):
    exc = requests.exceptions.ConnectionError(f"HTTPSConnectionPool: /bot{TOKEN}/sendMessage")
    s = FakeSession([exc] * 2)
    with pytest.raises(TelegramError) as info:
        client(s, max_retries=1).send_messages(["x"])
    assert TOKEN not in str(info.value)
    assert "bot<redacted>" not in "" and TOKEN not in redact(f"url /bot{TOKEN}/x", [TOKEN])
    record = logging.LogRecord("t", logging.ERROR, __file__, 1, "token %s", (TOKEN,), None)
    RedactingFilter([TOKEN]).filter(record)
    assert TOKEN not in record.msg
