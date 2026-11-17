"""Configuration, read exclusively from environment variables (and an optional .env)."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent

DEFAULT_GOLD_URL = "https://www.goodreturns.in/gold-rates/chennai.html"
DEFAULT_SILVER_URL = "https://www.goodreturns.in/silver-rates/chennai.html"
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)

_TOKEN_RE = re.compile(r"^\d{5,}:[A-Za-z0-9_-]{20,}$")
_CHAT_ID_RE = re.compile(r"^(-?\d{1,20}|@[A-Za-z][A-Za-z0-9_]{4,31})$")
_TRUE = {"1", "true", "yes", "y", "on"}
_FALSE = {"0", "false", "no", "n", "off"}


class ConfigError(ValueError):
    """Raised when an environment variable has an unusable value."""


def _get(name: str, default: Optional[str] = None) -> Optional[str]:
    value = os.environ.get(name)
    if value is None:
        return default
    # Tolerate `set VAR="value"` in cmd.exe, which keeps the quotes.
    value = value.strip().strip('"').strip("'").strip()
    return value or default


def _get_bool(name: str, default: bool) -> bool:
    raw = _get(name)
    if raw is None:
        return default
    low = raw.lower()
    if low in _TRUE:
        return True
    if low in _FALSE:
        return False
    raise ConfigError(f"{name} must be true or false (got {raw!r})")


def _get_number(name: str, default: float, minimum: float, integer: bool = False) -> float:
    raw = _get(name)
    if raw is None:
        return default
    try:
        value = int(raw) if integer else float(raw)
    except ValueError:
        kind = "an integer" if integer else "a number"
        raise ConfigError(f"{name} must be {kind} (got {raw!r})") from None
    if value < minimum:
        raise ConfigError(f"{name} must be >= {minimum:g} (got {raw!r})")
    return value


def _resolve_dir(value: str) -> Path:
    path = Path(value).expanduser()
    return path if path.is_absolute() else PROJECT_ROOT / path


@dataclass(frozen=True)
class Settings:
    gold_url: str
    silver_url: str
    output_dir: Path
    log_dir: Path
    log_level: str
    connect_timeout: float
    read_timeout: float
    max_retries: int
    backoff_seconds: float
    user_agent: str
    max_data_age_days: int
    telegram_bot_token: Optional[str]
    telegram_chat_id: Optional[str]
    telegram_disable_notification: bool
    telegram_timeout: float
    telegram_max_retries: int

    @classmethod
    def from_env(cls, output_dir_override: Optional[str] = None) -> "Settings":
        if not os.environ.get("GOLDSILVER_SKIP_DOTENV"):
            load_dotenv(PROJECT_ROOT / ".env", override=False)
        return cls(
            gold_url=_get("GOLD_URL", DEFAULT_GOLD_URL) or DEFAULT_GOLD_URL,
            silver_url=_get("SILVER_URL", DEFAULT_SILVER_URL) or DEFAULT_SILVER_URL,
            output_dir=_resolve_dir(output_dir_override or _get("OUTPUT_DIR", "output") or "output"),
            log_dir=_resolve_dir(_get("LOG_DIR", "logs") or "logs"),
            log_level=(_get("LOG_LEVEL", "INFO") or "INFO").upper(),
            connect_timeout=_get_number("REQUEST_CONNECT_TIMEOUT", 10, 1),
            read_timeout=_get_number("REQUEST_READ_TIMEOUT", 30, 1),
            max_retries=int(_get_number("REQUEST_MAX_RETRIES", 3, 0, integer=True)),
            backoff_seconds=_get_number("REQUEST_BACKOFF_SECONDS", 2, 0),
            user_agent=_get("USER_AGENT", DEFAULT_USER_AGENT) or DEFAULT_USER_AGENT,
            max_data_age_days=int(_get_number("MAX_DATA_AGE_DAYS", 1, 0, integer=True)),
            telegram_bot_token=_get("TELEGRAM_BOT_TOKEN"),
            telegram_chat_id=_get("TELEGRAM_CHAT_ID"),
            telegram_disable_notification=_get_bool("TELEGRAM_DISABLE_NOTIFICATION", False),
            telegram_timeout=_get_number("TELEGRAM_TIMEOUT_SECONDS", 20, 1),
            telegram_max_retries=int(_get_number("TELEGRAM_MAX_RETRIES", 3, 0, integer=True)),
        )

    def telegram_problems(self) -> list[str]:
        """Human-readable problems with the Telegram settings (never includes secrets)."""
        problems: list[str] = []
        if not self.telegram_bot_token:
            problems.append("TELEGRAM_BOT_TOKEN is not set")
        elif not _TOKEN_RE.match(self.telegram_bot_token):
            problems.append(
                "TELEGRAM_BOT_TOKEN does not look like a bot token "
                "(expected '<digits>:<secret>' as issued by @BotFather)"
            )
        if not self.telegram_chat_id:
            problems.append("TELEGRAM_CHAT_ID is not set")
        elif not _CHAT_ID_RE.match(self.telegram_chat_id):
            problems.append(
                "TELEGRAM_CHAT_ID does not look like a chat ID "
                "(expected a number such as -1001234567890, or @channelusername)"
            )
        return problems

    def secrets(self) -> list[str]:
        return [s for s in (self.telegram_bot_token,) if s]
