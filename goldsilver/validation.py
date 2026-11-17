"""Sanity checks that must pass before anything is saved as a report or sent."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Optional

from .models import MetalData, Rate


@dataclass
class ValidationResult:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


def _page_age_days(page_date: Optional[str], today: date) -> Optional[int]:
    if not page_date:
        return None
    return (today - date.fromisoformat(page_date)).days


def _close(a: float, b: float, tolerance: float = 0.01) -> bool:
    return abs(a - b) <= tolerance * max(abs(a), abs(b), 1.0)


def _check_freshness(data: MetalData, now: datetime, max_age_days: int, result: ValidationResult) -> None:
    name = data.metal.capitalize()
    age = _page_age_days(data.page_date, now.date())
    if age is None:
        result.errors.append(f"{name}: page date could not be determined, so freshness cannot be verified")
    elif age > max_age_days:
        result.errors.append(
            f"{name}: page is dated {data.page_date}, {age} day(s) old "
            f"(limit {max_age_days}); the site may be serving a stale/cached page")
    elif age < -1:
        result.errors.append(f"{name}: page date {data.page_date} is in the future")


def _positive(rate: Rate) -> bool:
    return rate.price is not None and rate.price > 0


def _check_weight_scaling(data: MetalData, result: ValidationResult) -> None:
    """Rows for N grams should be ~N x the 1 g price (same label)."""
    base = {r.label: r.price for r in data.rates_by_weight if r.weight_grams == 1 and r.price}
    for r in data.rates_by_weight:
        unit_price = base.get(r.label)
        if not unit_price or not r.price or not r.weight_grams or r.weight_grams == 1:
            continue
        if not _close(r.price, unit_price * r.weight_grams, tolerance=0.02):
            result.warnings.append(
                f"{data.metal.capitalize()} {r.label}: {r.weight_grams:g} g price {r.price:g} "
                f"is not ~{r.weight_grams:g} x the 1 g price {unit_price:g}")


def _check_headline_vs_table(data: MetalData, result: ValidationResult) -> None:
    table = {(r.label, r.weight_grams): r.price for r in data.rates_by_weight if r.price}
    for h in data.headline_rates:
        shown = table.get((h.label, h.weight_grams))
        if shown and h.price and not _close(h.price, shown, tolerance=0.001):
            result.errors.append(
                f"{data.metal.capitalize()} {h.label}: headline price {h.price:g} disagrees "
                f"with table price {shown:g}")


def validate_gold(data: MetalData, now: datetime, max_age_days: int) -> ValidationResult:
    result = ValidationResult()
    current = {r.label: r for r in data.current_rates}
    for label in ("24K", "22K"):
        if label not in current or not _positive(current[label]):
            result.errors.append(f"Gold: no valid {label} price found")
    if "18K" not in current:
        result.warnings.append("Gold: 18K price not found")
    p24, p22, p18 = (current.get(k) for k in ("24K", "22K", "18K"))
    if p24 and p22 and _positive(p24) and _positive(p22) and not p24.price > p22.price:  # type: ignore[operator]
        result.errors.append("Gold: 24K price is not higher than 22K price")
    if p22 and p18 and _positive(p22) and _positive(p18) and not p22.price > p18.price:  # type: ignore[operator]
        result.errors.append("Gold: 22K price is not higher than 18K price")
    _check_headline_vs_table(data, result)
    _check_weight_scaling(data, result)
    _check_freshness(data, now, max_age_days, result)
    return result


def validate_silver(data: MetalData, now: datetime, max_age_days: int) -> ValidationResult:
    result = ValidationResult()
    gram = next((r for r in data.current_rates if r.weight_grams == 1), None)
    kilo = next((r for r in data.current_rates if r.weight_grams == 1000), None)
    if not ((gram and _positive(gram)) or (kilo and _positive(kilo))):
        result.errors.append("Silver: no valid per-gram or per-kg price found")
    if gram and kilo and _positive(gram) and _positive(kilo) and not _close(gram.price * 1000, kilo.price):  # type: ignore[operator]
        result.errors.append(
            f"Silver: per-kg price {kilo.price:g} is inconsistent with per-gram price {gram.price:g}")
    _check_headline_vs_table(data, result)
    _check_weight_scaling(data, result)
    _check_freshness(data, now, max_age_days, result)
    return result


def validate_pair(gold: MetalData, silver: MetalData, now: datetime, max_age_days: int) -> ValidationResult:
    result = ValidationResult()
    for sub in (validate_gold(gold, now, max_age_days), validate_silver(silver, now, max_age_days)):
        result.errors.extend(sub.errors)
        result.warnings.extend(sub.warnings)
    if gold.city and silver.city and gold.city.lower() != silver.city.lower():
        result.errors.append(f"City mismatch: gold page is '{gold.city}', silver page is '{silver.city}'")
    if gold.page_date and silver.page_date and gold.page_date != silver.page_date:
        result.warnings.append(
            f"Gold page date ({gold.page_date}) differs from silver page date ({silver.page_date})")
    return result
