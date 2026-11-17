"""Minimal Telegram Bot API client (sendMessage over HTTPS, plain text only)."""

from __future__ import annotations

import logging
import time
from typing import Any, Callable, Optional

import requests

from .logging_setup import redact

log = logging.getLogger(__name__)

API_BASE = "https://api.telegram.org"
MAX_RETRY_AFTER_SECONDS = 120


class TelegramError(Exception):
    """Delivery failed. ``delivered`` is the number of messages already sent."""

    def __init__(self, message: str, delivered: int = 0, total: int = 0) -> None:
        super().__init__(message)
        self.delivered = delivered
        self.total = total


def explain_api_error(code: Optional[int], description: str, parameters: Optional[dict]) -> str:
    desc = (description or "").lower()
    params = parameters or {}
    if code == 401:
        return "Unauthorized: the bot token is invalid or revoked. Re-check TELEGRAM_BOT_TOKEN."
    if code == 404:
        return "Not Found: this usually means TELEGRAM_BOT_TOKEN is malformed."
    if code == 400 and "chat not found" in desc:
        return ("Chat not found: check TELEGRAM_CHAT_ID (groups are negative numbers, supergroups "
                "usually start with -100) and make sure the bot has been added to the group.")
    if code == 400 and "upgraded to a supergroup" in desc:
        new_id = params.get("migrate_to_chat_id")
        return ("The group was upgraded to a supergroup; update TELEGRAM_CHAT_ID"
                + (f" to {new_id}." if new_id else "."))
    if code == 400 and "too long" in desc:
        return "Telegram rejected the message as too long (report splitting limit needs lowering)."
    if code == 403:
        return ("Forbidden: the bot is not a member of the chat, was removed/blocked, or is not "
                "allowed to post. Add the bot to the group and let it send messages.")
    return f"Telegram API error {code}: {description}"


class TelegramClient:
    def __init__(
        self,
        token: str,
        chat_id: str,
        disable_notification: bool = False,
        timeout: float = 20.0,
        max_retries: int = 3,
        backoff_seconds: float = 2.0,
        session: Optional[requests.Session] = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._token = token
        self._chat_id = chat_id
        self._disable_notification = disable_notification
        self._timeout = timeout
        self._max_attempts = max_retries + 1
        self._backoff = backoff_seconds
        self._session = session or requests.Session()
        self._sleep = sleep

    # -- public ---------------------------------------------------------------
    def send_messages(self, messages: list[str]) -> int:
        total = len(messages)
        delivered = 0
        for index, text in enumerate(messages, 1):
            try:
                self._send_one(text, index, total)
            except TelegramError as exc:
                raise TelegramError(str(exc), delivered=delivered, total=total) from None
            delivered += 1
        return delivered

    # -- internals ------------------------------------------------------------
    def _safe(self, text: str) -> str:
        return redact(text, [self._token])

    def _send_one(self, text: str, index: int, total: int) -> None:
        url = f"{API_BASE}/bot{self._token}/sendMessage"
        payload: dict[str, Any] = {
            "chat_id": self._chat_id,
            "text": text,
            "disable_notification": self._disable_notification,
            "disable_web_page_preview": True,
            # parse_mode is intentionally omitted: plain text only.
        }
        last_problem = "unknown error"
        for attempt in range(1, self._max_attempts + 1):
            wait = self._backoff * (2 ** (attempt - 1))
            try:
                response = self._session.post(url, json=payload, timeout=self._timeout)
            except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as exc:
                last_problem = f"network error: {self._safe(str(exc))}"
                log.warning("Telegram message %d/%d attempt %d/%d failed: %s",
                            index, total, attempt, self._max_attempts, last_problem)
                if attempt < self._max_attempts:
                    self._sleep(wait)
                continue
            except requests.exceptions.RequestException as exc:
                raise TelegramError(f"Request failed: {self._safe(str(exc))}") from None

            body: dict[str, Any] = {}
            try:
                parsed = response.json()
                if isinstance(parsed, dict):
                    body = parsed
            except ValueError:
                pass

            if response.status_code == 200 and body.get("ok") is True:
                log.info("Telegram message %d/%d delivered (%d chars)", index, total, len(text))
                return

            code = body.get("error_code", response.status_code)
            description = str(body.get("description", response.text[:200]))
            params = body.get("parameters") if isinstance(body.get("parameters"), dict) else {}

            if code == 429:
                retry_after = float(params.get("retry_after", wait))
                last_problem = f"rate limited (retry after {retry_after:g}s)"
                if retry_after > MAX_RETRY_AFTER_SECONDS:
                    raise TelegramError(f"Telegram asked to wait {retry_after:g}s - giving up")
                log.warning("Telegram message %d/%d attempt %d/%d: %s",
                            index, total, attempt, self._max_attempts, last_problem)
                if attempt < self._max_attempts:
                    self._sleep(retry_after + 1)
                continue
            if isinstance(code, int) and code >= 500:
                last_problem = f"Telegram server error {code}: {description}"
                log.warning("Telegram message %d/%d attempt %d/%d: %s",
                            index, total, attempt, self._max_attempts, last_problem)
                if attempt < self._max_attempts:
                    self._sleep(wait)
                continue

            # 4xx (other than 429) will not succeed on retry.
            raise TelegramError(explain_api_error(code, description, params))

        raise TelegramError(
            f"Giving up on message {index}/{total} after {self._max_attempts} attempts: {last_problem}")
