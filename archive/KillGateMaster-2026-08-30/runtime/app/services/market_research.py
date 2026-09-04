"""Deterministic normalization for competitor and pricing evidence."""

from __future__ import annotations

import re

from app.models.market_research import (
    CompetitorProfile,
    CompetitorType,
    PricingObservation,
)

_INTERVAL_MONTHS = {"month": 1.0, "monthly": 1.0, "year": 1 / 12, "yearly": 1 / 12, "annual": 1 / 12}


def normalize_pricing(
    raw_amount: str,
    *,
    source_id: str,
    billing_note: str = "",
) -> PricingObservation | None:
    """Parse an observed price without inventing FX rates or hidden discounts."""
    match = re.search(r"(?P<currency>[$€£])\s*(?P<amount>\d+(?:,\d{3})*(?:\.\d+)?)", raw_amount)
    if not match:
        return None
    symbols = {"$": "USD", "€": "EUR", "£": "GBP"}
    amount = float(match.group("amount").replace(",", ""))
    lowered = raw_amount.lower()
    interval = "one_time"
    monthly = None
    for marker, divisor in _INTERVAL_MONTHS.items():
        if marker in lowered:
            interval = "monthly" if divisor == 1.0 else "annual"
            monthly = round(amount * divisor, 2)
            break
    return PricingObservation(
        source_id=source_id,
        currency=symbols[match.group("currency")],
        amount=amount,
        interval=interval,
        billing_note=billing_note.strip(),
        normalized_monthly_amount=monthly,
    )


def resolve_competitor(
    name: str,
    *,
    competitor_type: CompetitorType,
    source_ids: list[str] | None = None,
    aliases: list[str] | None = None,
) -> CompetitorProfile:
    """Create a stable, human-auditable competitor identity from source text."""
    cleaned = " ".join(name.split()).strip()
    if not cleaned:
        raise ValueError("competitor name is required")
    competitor_id = re.sub(r"[^a-z0-9]+", "-", cleaned.lower()).strip("-")
    return CompetitorProfile(
        competitor_id=competitor_id,
        canonical_name=cleaned,
        competitor_type=competitor_type,
        aliases=[" ".join(alias.split()).strip() for alias in (aliases or []) if alias.strip()],
        source_ids=list(dict.fromkeys(source_ids or [])),
    )
