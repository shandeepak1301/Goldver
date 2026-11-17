import os
import sys
from datetime import datetime
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ["GOLDSILVER_SKIP_DOTENV"] = "1"  # never read a developer's real .env in tests

from goldsilver.timeutil import IST  # noqa: E402

FIXTURES = Path(__file__).parent / "fixtures"
GOLD_URL = "https://www.goodreturns.in/gold-rates/chennai.html"
SILVER_URL = "https://www.goodreturns.in/silver-rates/chennai.html"


@pytest.fixture
def gold_html() -> str:
    return (FIXTURES / "gold_chennai.html").read_text(encoding="utf-8")


@pytest.fixture
def silver_html() -> str:
    return (FIXTURES / "silver_chennai.html").read_text(encoding="utf-8")


@pytest.fixture
def silver_html_today(silver_html: str) -> str:
    """Silver fixture re-dated to 17 Nov 2026 so it is 'fresh' on the frozen test day."""
    return (silver_html.replace("27 October 2026", "17 November 2026")
            .replace("Oct 27, 2026", "Nov 17, 2026"))


@pytest.fixture
def frozen_now() -> datetime:
    return datetime(2026, 11, 17, 14, 35, tzinfo=IST)


@pytest.fixture(autouse=True)
def _reset_root_logging():
    """cli.main() installs handlers on the root logger; remove them after every test."""
    import logging
    yield
    root = logging.getLogger()
    for handler in list(root.handlers):
        if type(handler).__name__ in {"StreamHandler", "RotatingFileHandler"} and handler not in getattr(
                root, "_pytest_handlers", []):
            if "pytest" in type(handler).__module__:
                continue
            root.removeHandler(handler)
            try:
                handler.close()
            except Exception:
                pass
