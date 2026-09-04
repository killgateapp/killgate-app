from __future__ import annotations

from app.models.market_research import CompetitorType
from app.services.market_research import normalize_pricing, resolve_competitor


def test_normalize_pricing_keeps_currency_and_interval_explicit():
    monthly = normalize_pricing("$149/month", source_id="s1")
    annual = normalize_pricing("€1,200 annual plan", source_id="s2")
    one_time = normalize_pricing("£75 setup fee", source_id="s3")
    assert monthly and monthly.currency == "USD" and monthly.normalized_monthly_amount == 149
    assert annual and annual.currency == "EUR" and annual.normalized_monthly_amount == 100
    assert one_time and one_time.interval == "one_time" and one_time.normalized_monthly_amount is None


def test_normalize_pricing_does_not_invent_unobserved_amounts():
    assert normalize_pricing("Contact sales", source_id="s1") is None


def test_resolve_competitor_produces_stable_identity_and_deduped_sources():
    profile = resolve_competitor(
        "  Acme Scheduling  ",
        competitor_type=CompetitorType.DIRECT,
        aliases=["Acme", " Acme "],
        source_ids=["s1", "s1", "s2"],
    )
    assert profile.competitor_id == "acme-scheduling"
    assert profile.aliases == ["Acme", "Acme"]
    assert profile.source_ids == ["s1", "s2"]
