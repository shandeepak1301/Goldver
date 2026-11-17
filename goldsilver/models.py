"""Plain data containers for extracted prices. ``None`` means "not on the page"."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

NA = "N/A"


@dataclass
class Rate:
    label: str                                  # "24K", "22K", "Silver"
    unit: str                                   # "gram" or "kg"
    weight_grams: Optional[float] = None
    price: Optional[float] = None
    price_text: Optional[str] = None            # exactly as shown, e.g. "₹1,24,700"
    previous_price: Optional[float] = None
    previous_price_text: Optional[str] = None
    change: Optional[float] = None
    change_text: Optional[str] = None           # e.g. "-76", "0", "+55"
    purity: Optional[str] = None                # e.g. "99.9%"


@dataclass
class MetalData:
    metal: str                                  # "gold" | "silver"
    source_url: str
    final_url: Optional[str] = None
    http_status: Optional[int] = None
    fetched_at_ist: Optional[str] = None
    title: Optional[str] = None
    city: Optional[str] = None
    page_date: Optional[str] = None             # ISO date
    page_date_text: Optional[str] = None
    # Value after '#' in <meta og:url>; looks like midnight-IST epoch of the page date.
    page_meta_timestamp_epoch: Optional[int] = None
    page_meta_timestamp_ist: Optional[str] = None
    headline: Optional[str] = None              # intro sentence under the H1
    headline_rates: list[Rate] = field(default_factory=list)
    current_rates: list[Rate] = field(default_factory=list)
    rates_by_weight: list[Rate] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
