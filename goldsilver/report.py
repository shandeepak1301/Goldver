"""Plain-text report construction and Telegram-safe message packing."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Optional

from .models import MetalData, NA, Rate

# Telegram's hard limit is 4096 characters; keep a margin and room for "[Part i/n]".
SAFE_MESSAGE_LIMIT = 4000
PART_LABEL_RESERVE = 20


class ReportError(Exception):
    pass


@dataclass
class Block:
    """An atomic chunk of the report. ``lines[0]`` is its heading."""
    lines: list[str]

    @property
    def heading(self) -> str:
        return self.lines[0]

    @property
    def text(self) -> str:
        return "\n".join(self.lines)


# --------------------------------------------------------------------------- formatting
def fmt_weight(grams: Optional[float]) -> str:
    if grams is None:
        return NA
    if grams >= 1000 and grams % 1000 == 0:
        return f"{int(grams // 1000)} kg"
    return f"{grams:g} g"


def _price(rate: Rate) -> str:
    return rate.price_text or NA


def _change(rate: Rate) -> str:
    if rate.change_text is None:
        return NA
    if rate.change is not None and rate.change < 0:
        return f"🔴 {rate.change_text}"
    if rate.change is not None and rate.change > 0:
        return f"🟢 {rate.change_text}"
    return rate.change_text


def _short_date(iso: Optional[str], fallback: Optional[str]) -> str:
    if iso:
        return date.fromisoformat(iso).strftime("%d %b %Y")
    return fallback or NA


def _group_by_weight(rates: list[Rate]) -> list[tuple[Optional[float], list[Rate]]]:
    groups: dict[Optional[float], list[Rate]] = {}
    for r in rates:
        groups.setdefault(r.weight_grams, []).append(r)
    return list(groups.items())


# --------------------------------------------------------------------------- blocks
def _header_block(gold: MetalData, silver: MetalData, now: datetime) -> Block:
    cities = {c for c in (gold.city, silver.city) if c}
    city = ", ".join(sorted(cities)) if cities else NA
    return Block([
        f"GOLD & SILVER RATES - {city.upper()}",
        f"Report date: {now.strftime('%A, %d %B %Y')}",
        f"Report time: {now.strftime('%H:%M')} IST (UTC+05:30)",
    ])


def _gold_blocks(g: MetalData) -> list[Block]:
    top = [
        "GOLD (INR per gram)",
        f"Location: {g.city or NA}",
        f"Source page date: {_short_date(g.page_date, g.page_date_text)}",
    ]
    for r in g.current_rates:
        top.append(f"{r.label} | Price: {_price(r)} | Change: {_change(r)}")
    blocks = [Block(top)]

    if g.rates_by_weight:
        lines = ["GOLD - PRICE BY WEIGHT"]
        for grams, rates in _group_by_weight(g.rates_by_weight):
            if grams not in (8, 10):
                continue
            lines.append(f"{fmt_weight(grams)}: " + " | ".join(f"{r.label} {_price(r)} ({_change(r)})" for r in rates))
        if len(lines) > 1:
            blocks.append(Block(lines))

    return blocks


def _silver_blocks(s: MetalData) -> list[Block]:
    top = [
        "SILVER (INR)",
        f"Location: {s.city or NA}",
        f"Source page date: {_short_date(s.page_date, s.page_date_text)}",
    ]
    for r in s.current_rates:
        top.append(
            f"{fmt_weight(r.weight_grams)} | Price: {_price(r)} | "
            f"Previous: {r.previous_price_text or NA} | Change: {_change(r)}")
    blocks = [Block(top)]

    if s.rates_by_weight:
        lines = ["SILVER - PRICE BY WEIGHT"]
        for r in s.rates_by_weight:
            if r.weight_grams not in (8, 10):
                continue
            lines.append(
                f"{fmt_weight(r.weight_grams)}: {_price(r)} | Yesterday: "
                f"{r.previous_price_text or NA} | Change: {_change(r)}")
        if len(lines) > 1:
            blocks.append(Block(lines))

    return blocks


def build_blocks(gold: MetalData, silver: MetalData, now: datetime) -> list[Block]:
    blocks = [_header_block(gold, silver, now)]
    blocks += _gold_blocks(gold)
    blocks += _silver_blocks(silver)
    notes = [*gold.notes, *(n for n in silver.notes if n not in gold.notes)]
    if notes:
        blocks.append(Block(["NOTES", *notes]))
    blocks.append(Block(["SOURCES", f"Gold: {gold.source_url}", f"Silver: {silver.source_url}"]))
    return blocks


def render_text(blocks: list[Block]) -> str:
    return "\n\n".join(b.text for b in blocks) + "\n"


# --------------------------------------------------------------------------- packing
def pack_messages(blocks: list[Block], limit: int = SAFE_MESSAGE_LIMIT) -> list[str]:
    """Pack blocks into messages <= ``limit`` chars without splitting a line.

    A block that fits is never split. An oversized block is split between lines and each
    continuation repeats its heading with "(continued)". Parts are labelled "[Part i/n]".
    """
    budget = limit - PART_LABEL_RESERVE
    messages: list[str] = []
    current = ""

    def flush() -> None:
        nonlocal current
        if current:
            messages.append(current)
            current = ""

    for block in blocks:
        text = block.text
        candidate = f"{current}\n\n{text}" if current else text
        if len(candidate) <= budget:
            current = candidate
            continue
        if len(text) <= budget:
            flush()
            current = text
            continue

        # Oversized block: split by lines.
        flush()
        continuation = f"{block.heading} (continued)"
        lines: list[str] = []
        for line in block.lines:
            if len(line) > budget or len(continuation) + 1 + len(line) > budget:
                raise ReportError(f"A single report line is longer than the message limit: {line[:60]!r}...")
            trial = "\n".join([*lines, line])
            if lines and len(trial) > budget:
                messages.append("\n".join(lines))
                lines = [continuation, line]
            else:
                lines.append(line)
        current = "\n".join(lines)
    flush()

    if len(messages) > 1:
        total = len(messages)
        messages = [f"[Part {i}/{total}]\n{m}" for i, m in enumerate(messages, 1)]
    return messages
