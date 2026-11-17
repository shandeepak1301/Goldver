"""Console + rotating-file logging with secret redaction."""

from __future__ import annotations

import logging
import re
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Iterable

_BOT_URL_RE = re.compile(r"bot\d+:[A-Za-z0-9_-]+")


def redact(text: str, secrets: Iterable[str] = ()) -> str:
    """Remove bot tokens (and any explicitly supplied secrets) from text."""
    for secret in secrets:
        if secret:
            text = text.replace(secret, "<redacted>")
    return _BOT_URL_RE.sub("bot<redacted>", text)


class RedactingFilter(logging.Filter):
    def __init__(self, secrets: Iterable[str]) -> None:
        super().__init__()
        self._secrets = [s for s in secrets if s]

    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = redact(record.getMessage(), self._secrets)
        record.args = ()
        if record.exc_info:
            # Render the traceback ourselves so the token cannot leak through it.
            formatter = logging.Formatter()
            record.exc_text = redact(formatter.formatException(record.exc_info), self._secrets)
            record.exc_info = None
        return True


def setup_logging(log_dir: Path, level: str, secrets: Iterable[str] = ()) -> None:
    root = logging.getLogger()
    for handler in list(root.handlers):
        root.removeHandler(handler)
    root.setLevel(getattr(logging, level.upper(), logging.INFO))

    fmt = logging.Formatter("%(asctime)s | %(levelname)-7s | %(name)s | %(message)s")
    redactor = RedactingFilter(secrets)

    console = logging.StreamHandler(sys.stderr)
    console.setFormatter(fmt)
    console.addFilter(redactor)
    root.addHandler(console)

    try:
        log_dir.mkdir(parents=True, exist_ok=True)
        file_handler = RotatingFileHandler(
            log_dir / "gold_silver.log", maxBytes=1_000_000, backupCount=5, encoding="utf-8"
        )
        file_handler.setFormatter(fmt)
        file_handler.addFilter(redactor)
        root.addHandler(file_handler)
    except OSError as exc:  # logging to file is best-effort
        root.warning("Could not open log file in %s: %s", log_dir, exc)

    # urllib3 DEBUG lines contain the full request path, which includes the bot token.
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("requests").setLevel(logging.WARNING)
