"""HTTP retrieval with timeouts and retries."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Optional
from urllib.parse import urlparse

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from .config import Settings
from .timeutil import now_ist

log = logging.getLogger(__name__)

MIN_EXPECTED_BYTES = 5_000
ALLOWED_HOST_SUFFIX = "goodreturns.in"


class FetchError(Exception):
    """A page could not be retrieved in a usable form."""

    def __init__(self, message: str, status_code: Optional[int] = None,
                 content: Optional[bytes] = None) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.content = content


@dataclass
class FetchedPage:
    url: str
    final_url: str
    status_code: int
    content: bytes
    fetched_at: datetime
    elapsed_seconds: float


def build_session(settings: Settings) -> requests.Session:
    session = requests.Session()
    retry = Retry(
        total=settings.max_retries,
        connect=settings.max_retries,
        read=settings.max_retries,
        status=settings.max_retries,
        backoff_factor=settings.backoff_seconds,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset({"GET"}),
        respect_retry_after_header=True,
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    session.headers.update({
        "User-Agent": settings.user_agent,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-IN,en;q=0.9",
    })
    return session


def fetch_html(session: requests.Session, url: str, settings: Settings) -> FetchedPage:
    log.info("GET %s", url)
    started = time.monotonic()
    try:
        response = session.get(
            url,
            timeout=(settings.connect_timeout, settings.read_timeout),
            allow_redirects=True,
        )
    except requests.exceptions.RequestException as exc:
        raise FetchError(f"Request to {url} failed after retries: {exc}") from exc
    elapsed = time.monotonic() - started

    if response.status_code != 200:
        raise FetchError(
            f"{url} returned HTTP {response.status_code}",
            status_code=response.status_code,
            content=response.content,
        )

    host = (urlparse(response.url).hostname or "").lower()
    if not host.endswith(ALLOWED_HOST_SUFFIX):
        raise FetchError(
            f"{url} redirected to unexpected host {host!r}",
            status_code=response.status_code,
            content=response.content,
        )
    if len(response.content) < MIN_EXPECTED_BYTES:
        raise FetchError(
            f"{url} returned only {len(response.content)} bytes - likely a block or error page",
            status_code=response.status_code,
            content=response.content,
        )

    log.info("Fetched %s: HTTP %s, %d bytes in %.2fs",
             url, response.status_code, len(response.content), elapsed)
    return FetchedPage(
        url=url,
        final_url=response.url,
        status_code=response.status_code,
        content=response.content,
        fetched_at=now_ist(),
        elapsed_seconds=elapsed,
    )
