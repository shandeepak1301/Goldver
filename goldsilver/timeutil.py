"""Time helpers. IST has no DST, so a fixed offset avoids needing tzdata on Windows."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

IST = timezone(timedelta(hours=5, minutes=30), "IST")


def now_ist() -> datetime:
    return datetime.now(IST)
