"""Killgate commercial catalog.

Owner-controlled Google Play product IDs stay in environment variables. This
module describes only the entitlement each server-verified SKU grants.
"""
from __future__ import annotations

import os
from dataclasses import dataclass

FOUNDER_PRO_MONTHLY_CREDITS = 9

@dataclass(frozen=True)
class CatalogProduct:
    sku_env: str
    kind: str  # venture_pass | evidence_run | founder_topup | subscription
    list_price_usd: str
    wallet_credits: int
    venture_passes: int
    credits_per_pass: int
    period_days: int
    title: str
    blurb: str
    requires_family: bool = False
    requires_active_subscription: bool = False


PRODUCTS: tuple[CatalogProduct, ...] = (
    CatalogProduct(
        sku_env="GOOGLE_PLAY_VENTURE_PASS_PRODUCT_ID",
        kind="venture_pass",
        list_price_usd="19.99",
        wallet_credits=0,
        venture_passes=1,
        credits_per_pass=3,
        period_days=365,
        title="Venture Pass",
        blurb=(
            "One complete validation cycle for one idea family: up to three live research "
            "passes, including legitimate pivot children."
        ),
    ),
    CatalogProduct(
        sku_env="GOOGLE_PLAY_EVIDENCE_RUN_PRODUCT_ID",
        kind="evidence_run",
        list_price_usd="7.99",
        wallet_credits=0,
        venture_passes=1,
        credits_per_pass=1,
        period_days=365,
        title="Extra Evidence Run",
        blurb="One additional live research pass bound to this same idea family. It cannot be moved to a new idea.",
        requires_family=True,
    ),
    CatalogProduct(
        sku_env="GOOGLE_PLAY_FOUNDER_PRO_PRODUCT_ID",
        kind="subscription",
        list_price_usd="59.99",
        wallet_credits=FOUNDER_PRO_MONTHLY_CREDITS,
        venture_passes=0,
        credits_per_pass=0,
        period_days=30,
        title="Founder Pro",
        blurb=(
            f"{FOUNDER_PRO_MONTHLY_CREDITS} live research passes per billing month plus power-user workspace features. "
            "Unused monthly passes expire; there is no unlimited research."
        ),
    ),
    CatalogProduct(
        sku_env="GOOGLE_PLAY_FOUNDER_TOPUP_PRODUCT_ID",
        kind="founder_topup",
        list_price_usd="14.99",
        wallet_credits=3,
        venture_passes=0,
        credits_per_pass=0,
        period_days=0,
        title="Founder Pro 3-Run Top-Up",
        blurb="Three additional unbound research passes for an active Founder Pro member.",
        requires_active_subscription=True,
    ),
)


DEFAULT_PRODUCT_IDS = {
    "GOOGLE_PLAY_VENTURE_PASS_PRODUCT_ID": "killgate_venture_pass",
    "GOOGLE_PLAY_EVIDENCE_RUN_PRODUCT_ID": "killgate_evidence_run",
    "GOOGLE_PLAY_FOUNDER_PRO_PRODUCT_ID": "killgate_founder_pro",
    "GOOGLE_PLAY_FOUNDER_TOPUP_PRODUCT_ID": "killgate_founder_topup",
}


def product_id_from_env(sku_env: str) -> str:
    """Environment wins; otherwise use the public catalog ID documented for Play Console."""
    if sku_env == "GOOGLE_PLAY_FOUNDER_PRO_PRODUCT_ID":
        # Backward-compatible deployment alias while moving off the old generic name.
        return (
            os.getenv(sku_env, "").strip()
            or os.getenv("GOOGLE_PLAY_SUBSCRIPTION_PRODUCT_ID", "").strip()
            or DEFAULT_PRODUCT_IDS[sku_env]
        )
    return os.getenv(sku_env, "").strip() or DEFAULT_PRODUCT_IDS.get(sku_env, "")


def catalog_with_ids() -> list[dict]:
    rows = []
    for item in PRODUCTS:
        rows.append(
            {
                "sku_env": item.sku_env,
                "product_id": product_id_from_env(item.sku_env),
                "kind": item.kind,
                "list_price_usd": item.list_price_usd,
                "wallet_credits": item.wallet_credits,
                "venture_passes": item.venture_passes,
                "credits_per_pass": item.credits_per_pass,
                "period_days": item.period_days,
                "title": item.title,
                "blurb": item.blurb,
                "requires_family": item.requires_family,
                "requires_active_subscription": item.requires_active_subscription,
            }
        )
    return rows


def find_product(product_id: str) -> CatalogProduct | None:
    wanted = (product_id or "").strip()
    if not wanted:
        return None
    for item in PRODUCTS:
        configured = product_id_from_env(item.sku_env)
        if configured and configured == wanted:
            return item
    return None


def configured_product_ids() -> set[str]:
    return {row["product_id"] for row in catalog_with_ids() if row["product_id"]}


def hero_cta_order() -> tuple[str, ...]:
    return (
        "GOOGLE_PLAY_VENTURE_PASS_PRODUCT_ID",
        "GOOGLE_PLAY_EVIDENCE_RUN_PRODUCT_ID",
        "GOOGLE_PLAY_FOUNDER_PRO_PRODUCT_ID",
        "GOOGLE_PLAY_FOUNDER_TOPUP_PRODUCT_ID",
    )
