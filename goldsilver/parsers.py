"""Extract gold/silver data from goodreturns.in pages.

The pages are server-rendered HTML, so requests + BeautifulSoup is enough. Tables are
located by their *header signature* (e.g. Gram | 24K | 22K | 18K) rather than CSS classes,
which makes the parser resilient to cosmetic markup changes.
"""

from __future__ import annotations

import logging
import re
from dataclasses import replace
from datetime import date, datetime
from typing import Callable, Optional, Union

from bs4 import BeautifulSoup, Tag

from .models import MetalData, Rate
from .timeutil import IST

log = logging.getLogger(__name__)

_AMOUNT = r"\d[\d,]*(?:\.\d+)?"
_MINUS = str.maketrans({"\u2212": "-", "\u2013": "-", "\u2014": "-"})


class ParseError(Exception):
    """The page was fetched but the expected data could not be extracted."""


# --------------------------------------------------------------------------- helpers
def clean(text: Optional[str]) -> str:
    return " ".join((text or "").replace("\xa0", " ").split())


def to_number(text: Optional[str]) -> Optional[float]:
    if not text:
        return None
    match = re.search(rf"[-+]?\s*{_AMOUNT}", text.translate(_MINUS))
    if not match:
        return None
    try:
        return float(re.sub(r"[\s,]", "", match.group(0)))
    except ValueError:
        return None


def parse_price_cell(text: str) -> tuple[Optional[str], Optional[float], Optional[str], Optional[float]]:
    """'₹13,604 (-76)' -> ('₹13,604', 13604.0, '-76', -76.0)."""
    t = clean(text).translate(_MINUS)
    price_match = re.match(rf"^\D*?({_AMOUNT})", t)
    if not price_match:
        return None, None, None, None
    price_text = t[: price_match.end()].strip()
    price = to_number(price_match.group(1))
    change_text: Optional[str] = None
    change: Optional[float] = None
    change_match = re.search(rf"\(\s*([+-]?\s*{_AMOUNT})\s*\)", t)
    if change_match:
        change_text = re.sub(r"\s", "", change_match.group(1))
        change = to_number(change_text)
    return price_text, price, change_text, change


def parse_table_date(text: str) -> Optional[date]:
    t = clean(text)
    for fmt in ("%b %d, %Y", "%B %d, %Y", "%d %B %Y", "%d %b %Y"):
        try:
            return datetime.strptime(t, fmt).date()
        except ValueError:
            continue
    return None


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", text.lower())


def _table_rows(table: Tag) -> list[list[str]]:
    rows: list[list[str]] = []
    for tr in table.find_all("tr"):
        cells = [clean(c.get_text(" ")) for c in tr.find_all(["th", "td"])]
        if any(cells):
            rows.append(cells)
    return rows


def _find_tables(soup: BeautifulSoup,
                 predicate: Callable[[list[str]], bool]) -> list[tuple[Tag, list[list[str]]]]:
    found = []
    for table in soup.find_all("table"):
        rows = _table_rows(table)
        if rows and predicate([_norm(h) for h in rows[0]]):
            found.append((table, rows))
    return found


def _make_soup(html: Union[bytes, str]) -> BeautifulSoup:
    return BeautifulSoup(html, "html.parser")


def _page_text(soup: BeautifulSoup) -> str:
    return clean(soup.get_text(" "))


def _extract_date(soup: BeautifulSoup) -> tuple[Optional[date], Optional[str]]:
    candidates: list[str] = []
    if soup.title and soup.title.string:
        candidates.append(soup.title.string)
    for attrs in ({"name": "description"}, {"property": "og:description"}, {"property": "og:title"}):
        meta = soup.find("meta", attrs=attrs)
        if meta and meta.get("content"):
            candidates.append(str(meta["content"]))
    for text in candidates:
        for m in re.finditer(r"\b(\d{1,2})\s+([A-Za-z]{3,9})\s+(\d{4})\b", text):
            raw = f"{m.group(1)} {m.group(2)} {m.group(3)}"
            parsed = parse_table_date(raw)
            if parsed:
                return parsed, raw
    return None, None


def _extract_meta_timestamp(soup: BeautifulSoup) -> tuple[Optional[int], Optional[str]]:
    for attrs in ({"property": "og:url"}, {"name": "og:url"}):
        meta = soup.find("meta", attrs=attrs)
        if meta and meta.get("content"):
            m = re.search(r"#(\d{9,11})$", str(meta["content"]).strip())
            if m:
                epoch = int(m.group(1))
                return epoch, datetime.fromtimestamp(epoch, IST).isoformat()
    return None, None


def _extract_city(soup: BeautifulSoup) -> Optional[str]:
    h1 = soup.find("h1")
    if h1:
        m = re.search(r"(?:rate|price)s?\s+in\s+(.+)$", clean(h1.get_text(" ")), re.I)
        if m:
            return m.group(1).strip()
    link = soup.find("link", attrs={"rel": "canonical"})
    if link and link.get("href"):
        slug = str(link["href"]).rstrip("/").rsplit("/", 1)[-1].removesuffix(".html")
        if slug:
            return slug.replace("-", " ").title()
    return None


def _extract_headline(soup: BeautifulSoup) -> Optional[str]:
    h1 = soup.find("h1")
    para = h1.find_next("p") if h1 else None
    return clean(para.get_text(" ")) or None if para else None


def _extract_notes(soup: BeautifulSoup) -> list[str]:
    note = soup.find(string=re.compile(r"indicative", re.I))
    if note:
        text = clean(str(note)).lstrip("* ").strip()
        if text:
            return [text]
    return []


def _base_fields(soup: BeautifulSoup, metal: str, url: str, final_url: Optional[str],
                 status: Optional[int], fetched_at_ist: Optional[str]) -> MetalData:
    page_date, page_date_text = _extract_date(soup)
    epoch, epoch_ist = _extract_meta_timestamp(soup)
    return MetalData(
        metal=metal,
        source_url=url,
        final_url=final_url,
        http_status=status,
        fetched_at_ist=fetched_at_ist,
        title=clean(soup.title.get_text(" ")) if soup.title else None,
        city=_extract_city(soup),
        page_date=page_date.isoformat() if page_date else None,
        page_date_text=page_date_text,
        page_meta_timestamp_epoch=epoch,
        page_meta_timestamp_ist=epoch_ist,
        headline=_extract_headline(soup),
        notes=_extract_notes(soup),
    )


# --------------------------------------------------------------------------- gold
def parse_gold(html: Union[bytes, str], url: str, final_url: Optional[str] = None,
               status: Optional[int] = None, fetched_at_ist: Optional[str] = None) -> MetalData:
    soup = _make_soup(html)
    data = _base_fields(soup, "gold", url, final_url, status, fetched_at_ist)
    text = _page_text(soup)

    # Headline: "₹13,604 per gram for 24 karat gold (99.9% purity)"
    purity_by_label: dict[str, str] = {}
    for m in re.finditer(
        rf"₹\s*({_AMOUNT})\s*per\s+gram\s+for\s+(\d{{1,2}})\s*karat\s+gold\s*\(\s*([\d.]+)\s*%\s*purity\s*\)",
        text, re.I,
    ):
        label = f"{m.group(2)}K"
        purity_by_label[label] = f"{m.group(3)}%"
        data.headline_rates.append(Rate(
            label=label, unit="gram", weight_grams=1.0,
            price=to_number(m.group(1)), price_text=f"₹{m.group(1)}", purity=f"{m.group(3)}%",
        ))

    # Price-per-weight table: Gram | 24K | 22K | 18K
    weight_tables = _find_tables(
        soup, lambda h: bool(h) and h[0] == "gram" and sum(bool(re.fullmatch(r"\d{1,2}k", x)) for x in h) >= 2)
    if weight_tables:
        _, rows = weight_tables[0]
        carat_cols = {i: clean(h).upper().replace(" ", "")
                      for i, h in enumerate(rows[0]) if re.fullmatch(r"\d{1,2}k", _norm(h))}
        for row in rows[1:]:
            grams = to_number(row[0])
            for idx, label in carat_cols.items():
                if idx >= len(row):
                    continue
                price_text, price, change_text, change = parse_price_cell(row[idx])
                if price is None:
                    continue
                data.rates_by_weight.append(Rate(
                    label=label, unit="gram", weight_grams=grams, price=price, price_text=price_text,
                    change=change, change_text=change_text, purity=purity_by_label.get(label),
                ))

    # Current rates: prefer the 1 g table row (it has the change), fall back to the headline.
    by_label: dict[str, Rate] = {}
    for rate in data.headline_rates:
        by_label[rate.label] = replace(rate)
    for rate in data.rates_by_weight:
        if rate.weight_grams == 1:
            by_label[rate.label] = replace(rate, purity=rate.purity or purity_by_label.get(rate.label))
    data.current_rates = sorted(by_label.values(), key=lambda r: -(to_number(r.label) or 0))

    if not data.current_rates:
        raise ParseError(
            "No gold prices found. The page layout may have changed, or the site served a "
            "JavaScript/bot-check page (in that case Playwright would be needed)."
        )
    log.info("Gold parsed: %d current rates, %d weight rows",
             len(data.current_rates), len(data.rates_by_weight))
    return data


# --------------------------------------------------------------------------- silver
def parse_silver(html: Union[bytes, str], url: str, final_url: Optional[str] = None,
                 status: Optional[int] = None, fetched_at_ist: Optional[str] = None) -> MetalData:
    soup = _make_soup(html)
    data = _base_fields(soup, "silver", url, final_url, status, fetched_at_ist)
    text = _page_text(soup)

    # Headline: "₹220 per gram and ₹2,20,000 per kilogram"
    headline_gram: Optional[Rate] = None
    headline_kg: Optional[Rate] = None
    m = re.search(rf"₹\s*({_AMOUNT})\s*per\s+gram\s+and\s+₹\s*({_AMOUNT})\s*per\s+kilogram", text, re.I)
    if m:
        headline_gram = Rate(label="Silver", unit="gram", weight_grams=1.0,
                             price=to_number(m.group(1)), price_text=f"₹{m.group(1)}")
        headline_kg = Rate(label="Silver", unit="kg", weight_grams=1000.0,
                           price=to_number(m.group(2)), price_text=f"₹{m.group(2)}")
        data.headline_rates = [headline_gram, headline_kg]

    # Table: Gram | Today | Yesterday | Change
    tables = _find_tables(soup, lambda h: bool(h) and h[0] == "gram" and "today" in h)
    if tables:
        _, rows = tables[0]
        header = [_norm(h) for h in rows[0]]
        i_today = header.index("today")
        i_prev = header.index("yesterday") if "yesterday" in header else None
        i_chg = header.index("change") if "change" in header else None
        for row in rows[1:]:
            grams = to_number(row[0])
            if grams is None or i_today >= len(row):
                continue
            price_text, price, _, _ = parse_price_cell(row[i_today])
            if price is None:
                continue
            prev_text = prev = None
            if i_prev is not None and i_prev < len(row):
                prev_text, prev, _, _ = parse_price_cell(row[i_prev])
            change_text = change = None
            if i_chg is not None and i_chg < len(row) and row[i_chg]:
                change_text = re.sub(r"\s", "", row[i_chg].translate(_MINUS))
                change = to_number(change_text)
            data.rates_by_weight.append(Rate(
                label="Silver", unit="kg" if grams >= 1000 else "gram", weight_grams=grams,
                price=price, price_text=price_text, previous_price=prev,
                previous_price_text=prev_text, change=change, change_text=change_text))

    # Current rates: 1 g and 1 kg, from the table when present, else from the headline.
    for grams, headline in ((1.0, headline_gram), (1000.0, headline_kg)):
        row = next((r for r in data.rates_by_weight if r.weight_grams == grams), None)
        if row is not None:
            data.current_rates.append(replace(row))
        elif headline is not None:
            data.current_rates.append(replace(headline))

    if not data.current_rates:
        raise ParseError(
            "No silver prices found. The page layout may have changed, or the site served a "
            "JavaScript/bot-check page (in that case Playwright would be needed)."
        )
    log.info("Silver parsed: %d current rates, %d weight rows",
             len(data.current_rates), len(data.rates_by_weight))
    return data
