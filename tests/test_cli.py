import json
from pathlib import Path

import pytest

import goldsilver.cli as cli
from goldsilver.fetcher import FetchedPage, FetchError

from .conftest import GOLD_URL, SILVER_URL

TOKEN = "123456789:" + "B" * 35


class SpyTelegram:
    instances: list = []

    def __init__(self, **kwargs):
        self.kwargs, self.sent = kwargs, None
        SpyTelegram.instances.append(self)

    def send_messages(self, messages):
        self.sent = messages
        return len(messages)


@pytest.fixture
def env(tmp_path, monkeypatch, frozen_now, gold_html, silver_html_today):
    for k in ("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID", "TELEGRAM_DISABLE_NOTIFICATION"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("OUTPUT_DIR", str(tmp_path / "out"))
    monkeypatch.setenv("LOG_DIR", str(tmp_path / "logs"))
    monkeypatch.setattr(cli, "now_ist", lambda: frozen_now)
    monkeypatch.setattr(cli, "TelegramClient", SpyTelegram)
    SpyTelegram.instances.clear()
    pages = {GOLD_URL: gold_html, SILVER_URL: silver_html_today}

    def fake_fetch(session, url, settings):
        body = pages[url]
        if isinstance(body, Exception):
            raise body
        return FetchedPage(url, url, 200, body.encode("utf-8"), frozen_now, 0.1)

    monkeypatch.setattr(cli, "fetch_html", fake_fetch)
    return pages, tmp_path / "out"


def set_telegram(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", TOKEN)
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "-1001234567890")


def test_success_sends_and_saves(env, monkeypatch, capsys):
    set_telegram(monkeypatch)
    _, out = env
    assert cli.main([]) == 0
    msg = capsys.readouterr().out
    assert "saved" in msg and "delivered to Telegram (1 message(s))" in msg
    assert SpyTelegram.instances[0].sent and "GOLD (INR per gram)" in SpyTelegram.instances[0].sent[0]
    data = json.loads((out / "gold_silver_latest.json").read_text(encoding="utf-8"))
    assert data["gold"]["current_rates"][0]["price"] == 13604
    assert "₹13,604" in (out / "gold_silver_latest.txt").read_text(encoding="utf-8")


@pytest.mark.parametrize("flag", ["--dry-run", "--no-telegram"])
def test_flags_skip_telegram_but_save(env, monkeypatch, capsys, flag):
    set_telegram(monkeypatch)
    _, out = env
    assert cli.main([flag]) == 0
    assert SpyTelegram.instances == []
    assert (out / "gold_silver_latest.json").exists()
    printed = capsys.readouterr().out
    assert ("GOLD & SILVER RATES" in printed) == (flag == "--dry-run")


def test_dry_run_needs_no_telegram_settings(env):
    assert cli.main(["--dry-run"]) == 0


def test_missing_telegram_settings_fail_before_any_fetch(env, capsys):
    assert cli.main([]) == cli.EXIT_CONFIG
    assert "TELEGRAM_BOT_TOKEN is not set" in capsys.readouterr().err
    assert SpyTelegram.instances == []


def test_one_source_failing_sends_nothing(env, monkeypatch, capsys):
    set_telegram(monkeypatch)
    pages, out = env
    pages[SILVER_URL] = FetchError("boom", status_code=503, content=b"<html>down</html>")
    assert cli.main([]) == cli.EXIT_EXTRACTION
    assert SpyTelegram.instances == []                      # nothing created, nothing sent
    assert "FAILED" in capsys.readouterr().err
    diag = list((out / "diagnostics").iterdir())[0]
    assert (diag / "gold.html").exists() and (diag / "silver_error_body.html").exists()
    assert not (out / "gold_silver_latest.json").exists()


def test_stale_data_is_not_sent(env, monkeypatch, silver_html):
    set_telegram(monkeypatch)
    pages, _ = env
    pages[SILVER_URL] = silver_html                         # dated 27 Oct
    assert cli.main([]) == cli.EXIT_EXTRACTION
    assert SpyTelegram.instances == []


def test_telegram_failure_keeps_files_and_exits_nonzero(env, monkeypatch, capsys):
    from goldsilver.telegram_client import TelegramError

    class Failing(SpyTelegram):
        def send_messages(self, messages):
            raise TelegramError("Forbidden", delivered=0, total=len(messages))

    set_telegram(monkeypatch)
    monkeypatch.setattr(cli, "TelegramClient", Failing)
    _, out = env
    assert cli.main([]) == cli.EXIT_TELEGRAM
    assert (out / "gold_silver_latest.txt").exists()
    assert "delivery FAILED" in capsys.readouterr().err
