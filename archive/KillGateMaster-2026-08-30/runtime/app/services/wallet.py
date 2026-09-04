"""Killgate research entitlement wallet.

Local development uses an atomic JSON file. Production uses Supabase RPCs so
credits, Venture Pass binding, subscription refills, and debits are durable and
atomic across Cloud Run instances.
"""
from __future__ import annotations

import json
import os
import secrets
import threading
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx

from app.services.catalog import CatalogProduct
from app.services.research_policy import beta_policy, is_beta_user, is_test_admin

WALLET_DIR = Path(__file__).resolve().parents[2] / "data" / "wallets"
_LOCAL_WALLET_LOCK = threading.RLock()


class WalletStoreUnavailable(RuntimeError):
    """The durable entitlement wallet could not be read or updated safely."""


def _now() -> datetime:
    return datetime.now(UTC)


def _parse(value: str) -> datetime | None:
    raw = (value or "").strip()
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).astimezone(UTC)
    except ValueError:
        return None


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _backend() -> str:
    return os.getenv("WALLET_BACKEND", os.getenv("STATE_BACKEND", "local")).strip().lower()


def _supabase_admin() -> tuple[str, str]:
    url = os.getenv("SUPABASE_URL", "").rstrip("/")
    secret = os.getenv("SUPABASE_SECRET_KEY", "").strip()
    if not url or not secret:
        raise WalletStoreUnavailable("Production wallet storage is not configured.")
    return url, secret


def _rpc(name: str, payload: dict[str, Any]) -> Any:
    url, secret = _supabase_admin()
    try:
        response = httpx.post(
            f"{url}/rest/v1/rpc/{name}",
            headers={"apikey": secret, "Authorization": f"Bearer {secret}", "Content-Type": "application/json"},
            json=payload,
            timeout=15,
        )
    except httpx.HTTPError as exc:
        raise WalletStoreUnavailable("Entitlement wallet storage could not be reached.") from exc
    if not 200 <= response.status_code < 300:
        raise WalletStoreUnavailable(f"Entitlement wallet RPC returned HTTP {response.status_code}.")
    try:
        return response.json()
    except ValueError as exc:
        raise WalletStoreUnavailable("Entitlement wallet RPC returned invalid data.") from exc


@dataclass
class VenturePass:
    pass_id: str
    credits_remaining: int
    credits_granted: int
    family_id: str = ""
    expires_at: datetime | None = None
    source_product: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "pass_id": self.pass_id,
            "credits_remaining": self.credits_remaining,
            "credits_granted": self.credits_granted,
            "family_id": self.family_id,
            "expires_at": _iso(self.expires_at),
            "source_product": self.source_product,
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> VenturePass:
        return cls(
            pass_id=str(raw.get("pass_id") or ""),
            credits_remaining=int(raw.get("credits_remaining") or 0),
            credits_granted=int(raw.get("credits_granted") or 0),
            family_id=str(raw.get("family_id") or ""),
            expires_at=_parse(str(raw.get("expires_at") or "")),
            source_product=str(raw.get("source_product") or ""),
        )


@dataclass
class Wallet:
    user_id: str
    wallet_credits: int = 0
    subscription_credits: int = 0
    subscription_credits_expire_at: datetime | None = None
    subscription_period_id: str = ""
    passes: list[VenturePass] = field(default_factory=list)
    seen_purchase_hashes: list[str] = field(default_factory=list)
    ledger: list[dict[str, Any]] = field(default_factory=list)

    def expire_subscription_credits(self, now: datetime | None = None) -> None:
        stamp = now or _now()
        if self.subscription_credits_expire_at and self.subscription_credits_expire_at <= stamp:
            if self.subscription_credits and _backend() != "supabase":
                self.ledger.append(
                    {"at": _iso(stamp), "kind": "subscription_expire", "amount": self.subscription_credits}
                )
            self.subscription_credits = 0
            self.subscription_credits_expire_at = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "user_id": self.user_id,
            "wallet_credits": self.wallet_credits,
            "subscription_credits": self.subscription_credits,
            "subscription_credits_expire_at": _iso(self.subscription_credits_expire_at),
            "subscription_period_id": self.subscription_period_id,
            "passes": [item.as_dict() for item in self.passes],
            "seen_purchase_hashes": list(self.seen_purchase_hashes),
            # Debit/cancellation receipts are durable idempotency records.
            "ledger": list(self.ledger),
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any], user_id: str) -> Wallet:
        passes = [VenturePass.from_dict(item) for item in raw.get("passes") or [] if isinstance(item, dict)]
        return cls(
            user_id=user_id,
            wallet_credits=int(raw.get("wallet_credits") or 0),
            subscription_credits=int(raw.get("subscription_credits") or 0),
            subscription_credits_expire_at=_parse(str(raw.get("subscription_credits_expire_at") or "")),
            subscription_period_id=str(raw.get("subscription_period_id") or ""),
            passes=passes,
            seen_purchase_hashes=[str(item) for item in raw.get("seen_purchase_hashes") or []],
            ledger=[item for item in raw.get("ledger") or [] if isinstance(item, dict)],
        )


def _path(user_id: str) -> Path:
    WALLET_DIR.mkdir(parents=True, exist_ok=True)
    safe = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in user_id)[:120]
    return WALLET_DIR / f"{safe}.json"


def load_wallet(user_id: str) -> Wallet:
    if _backend() == "supabase":
        raw = _rpc("killgate_wallet_snapshot", {"p_user_id": user_id})
        if raw is None:
            raw = {}
        if not isinstance(raw, dict):
            raise WalletStoreUnavailable("Entitlement wallet snapshot has an invalid shape.")
        wallet = Wallet.from_dict(raw, user_id)
        wallet.expire_subscription_credits()
        return wallet

    path = _path(user_id)
    if not path.exists():
        wallet = Wallet(user_id=user_id)
        wallet.expire_subscription_credits()
        return wallet
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        raw = {}
    if not isinstance(raw, dict):
        raw = {}
    wallet = Wallet.from_dict(raw, user_id)
    wallet.expire_subscription_credits()
    return wallet


def save_wallet(wallet: Wallet) -> None:
    if _backend() == "supabase":
        raise WalletStoreUnavailable("Production wallet changes must use atomic entitlement RPCs.")
    path = _path(wallet.user_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(wallet.as_dict(), indent=2), encoding="utf-8")
    os.replace(temp, path)


def available_credits(wallet: Wallet, family_id: str = "") -> int:
    wallet.expire_subscription_credits()
    bound = 0
    now = _now()
    for item in wallet.passes:
        if item.credits_remaining < 1:
            continue
        if item.expires_at and item.expires_at <= now:
            continue
        if family_id and item.family_id and item.family_id != family_id:
            continue
        if family_id and not item.family_id:
            continue
        if family_id and item.family_id == family_id:
            bound += item.credits_remaining
    unbound_passes = 0
    if not family_id:
        for item in wallet.passes:
            if item.credits_remaining < 1:
                continue
            if item.expires_at and item.expires_at <= now:
                continue
            if not item.family_id:
                unbound_passes += item.credits_remaining
    return wallet.wallet_credits + wallet.subscription_credits + bound + unbound_passes


def unbound_passes(wallet: Wallet) -> list[VenturePass]:
    now = _now()
    return [
        item
        for item in wallet.passes
        if item.credits_remaining > 0
        and not item.family_id
        and (item.expires_at is None or item.expires_at > now)
    ]


def bind_pass(wallet: Wallet, pass_id: str, family_id: str) -> bool:
    family_id = (family_id or "").strip()
    if not family_id:
        return False
    if _backend() == "supabase":
        value = _rpc(
            "killgate_wallet_bind_pass",
            {"p_user_id": wallet.user_id, "p_pass_id": pass_id, "p_family_id": family_id},
        )
        return value is True
    for item in wallet.passes:
        if item.pass_id == pass_id and not item.family_id and item.credits_remaining > 0:
            item.family_id = family_id
            wallet.ledger.append(
                {"at": _iso(_now()), "kind": "bind_pass", "pass_id": pass_id, "family_id": family_id}
            )
            save_wallet(wallet)
            return True
    return False


def family_credits(wallet: Wallet, family_id: str) -> int:
    now = _now()
    total = 0
    for item in wallet.passes:
        if item.family_id != family_id:
            continue
        if item.expires_at and item.expires_at <= now:
            continue
        total += max(0, item.credits_remaining)
    return total


def grant_product(
    wallet: Wallet,
    product: CatalogProduct,
    *,
    product_id: str,
    purchase_hash: str = "",
    family_id: str = "",
    subscription_period_id: str = "",
    subscription_expires_at: datetime | None = None,
    active_subscription: bool = False,
) -> dict[str, Any]:
    """Grant a verified Play product exactly once (or once per subscription period)."""
    family_id = (family_id or "").strip()
    if product.requires_family and not family_id:
        raise ValueError("This purchase must be attached to an idea family.")
    if product.requires_active_subscription and not active_subscription:
        raise ValueError("Founder Pro must be active before buying a top-up.")

    if _backend() == "supabase":
        value = _rpc(
            "killgate_wallet_grant",
            {
                "p_user_id": wallet.user_id,
                "p_product_id": product_id,
                "p_product_kind": product.kind,
                "p_purchase_hash": purchase_hash or None,
                "p_wallet_credits": product.wallet_credits,
                "p_venture_passes": product.venture_passes,
                "p_credits_per_pass": product.credits_per_pass,
                "p_period_days": product.period_days,
                "p_subscription_period_id": subscription_period_id or "",
                "p_subscription_expires_at": _iso(subscription_expires_at),
                "p_family_id": family_id,
                "p_requires_active_subscription": product.requires_active_subscription,
            },
        )
        if not isinstance(value, dict):
            raise WalletStoreUnavailable("Entitlement grant returned an invalid result.")
        return value

    now = _now()
    if product.kind == "subscription":
        period_id = subscription_period_id or now.strftime("%Y-%m")
        if wallet.subscription_period_id == period_id:
            return {"ok": True, "duplicate": True, "subscription_period_id": period_id}
        wallet.subscription_credits = product.wallet_credits
        wallet.subscription_credits_expire_at = subscription_expires_at or (now + timedelta(days=product.period_days or 30))
        wallet.subscription_period_id = period_id
        wallet.ledger.append(
            {
                "at": _iso(now),
                "kind": "subscription_refill",
                "product_id": product_id,
                "subscription_credits": product.wallet_credits,
                "period_id": period_id,
                "purchase_token_hash": purchase_hash,
            }
        )
        if purchase_hash and purchase_hash not in wallet.seen_purchase_hashes:
            wallet.seen_purchase_hashes.append(purchase_hash)
        save_wallet(wallet)
        return {"ok": True, "duplicate": False, "subscription_period_id": period_id}

    if purchase_hash and purchase_hash in wallet.seen_purchase_hashes:
        return {"ok": True, "duplicate": True}
    if purchase_hash:
        wallet.seen_purchase_hashes.append(purchase_hash)
        wallet.seen_purchase_hashes = wallet.seen_purchase_hashes[-500:]

    granted_passes: list[str] = []
    if product.venture_passes:
        expires = now + timedelta(days=product.period_days or 365)
        for _ in range(product.venture_passes):
            item = VenturePass(
                pass_id=f"P-{secrets.token_hex(6).upper()}",
                credits_remaining=product.credits_per_pass,
                credits_granted=product.credits_per_pass,
                family_id=family_id,
                expires_at=expires,
                source_product=product_id,
            )
            wallet.passes.append(item)
            granted_passes.append(item.pass_id)

    if product.wallet_credits:
        wallet.wallet_credits += product.wallet_credits

    wallet.ledger.append(
        {
            "at": _iso(now),
            "kind": "grant",
            "product_id": product_id,
            "product_kind": product.kind,
            "wallet_credits": product.wallet_credits,
            "passes": granted_passes,
            "family_id": family_id,
            "purchase_token_hash": purchase_hash,
        }
    )
    save_wallet(wallet)
    return {"ok": True, "duplicate": False, "passes": granted_passes}


def consume_research_credit(
    wallet: Wallet, family_id: str, research_run_id: str | None = None,
) -> dict[str, Any]:
    """Debit once per caller operation, including retries after a lost response."""
    run_id = str(uuid.UUID(research_run_id)) if research_run_id else str(uuid.uuid4())
    if _backend() == "supabase":
        return _consume_research_credit(wallet, family_id, run_id)
    with _LOCAL_WALLET_LOCK:
        return _consume_research_credit(load_wallet(wallet.user_id), family_id, run_id)


def _consume_research_credit(wallet: Wallet, family_id: str, research_run_id: str) -> dict[str, Any]:
    """Debit one paid research entitlement atomically; family-bound passes are preferred.

    The returned ``debit_id`` is a reservation receipt. If research is not
    delivered, pass it to :func:`refund_research_credit` so the debit can be
    restored exactly once.
    """
    family_id = (family_id or "").strip()
    if _backend() == "supabase":
        value = _rpc(
            "killgate_wallet_debit_once",
            {"p_user_id": wallet.user_id, "p_family_id": family_id, "p_research_run_id": research_run_id},
        )
        if not isinstance(value, dict):
            raise WalletStoreUnavailable("Entitlement debit returned an invalid result.")
        return value

    original = next((item for item in wallet.ledger if item.get("research_run_id") == research_run_id), None)
    if original:
        if original["kind"] == "cancel_research" or any(
            item.get("related_debit_id") == original.get("debit_id") and item.get("kind") == "refund_research"
            for item in wallet.ledger
        ):
            return {"ok": False, "error": "research_run_cancelled"}
        if original.get("family_id") != family_id:
            raise WalletStoreUnavailable("Research operation belongs to another idea family.")
        return {
            "ok": True, "duplicate": True, "debit_id": original["debit_id"],
            "source": {"debit_pass": "venture_pass", "debit_subscription": "subscription", "debit_wallet": "wallet"}[original["kind"]],
            "pass_id": original.get("pass_id"),
        }
    wallet.expire_subscription_credits()
    now = _now()
    debit_id = f"D-{secrets.token_hex(10).upper()}"
    for item in wallet.passes:
        if item.family_id != family_id:
            continue
        if item.credits_remaining < 1:
            continue
        if item.expires_at and item.expires_at <= now:
            continue
        item.credits_remaining -= 1
        wallet.ledger.append(
            {
                "at": _iso(now),
                "kind": "debit_pass",
                "debit_id": debit_id,
                "research_run_id": research_run_id,
                "pass_id": item.pass_id,
                "family_id": family_id,
            }
        )
        save_wallet(wallet)
        return {"ok": True, "source": "venture_pass", "pass_id": item.pass_id, "debit_id": debit_id}

    if wallet.subscription_credits > 0:
        wallet.subscription_credits -= 1
        wallet.ledger.append(
            {
                "at": _iso(now),
                "kind": "debit_subscription",
                "debit_id": debit_id,
                "research_run_id": research_run_id,
                "family_id": family_id,
                "period_id": wallet.subscription_period_id,
            }
        )
        save_wallet(wallet)
        return {
            "ok": True,
            "source": "subscription",
            "debit_id": debit_id,
            "period_id": wallet.subscription_period_id,
        }

    if wallet.wallet_credits > 0:
        wallet.wallet_credits -= 1
        wallet.ledger.append(
            {"at": _iso(now), "kind": "debit_wallet", "debit_id": debit_id, "family_id": family_id,
             "research_run_id": research_run_id}
        )
        save_wallet(wallet)
        return {"ok": True, "source": "wallet", "debit_id": debit_id}

    return {"ok": False, "error": "no_credits"}


def cancel_research_credit(wallet: Wallet, research_run_id: str) -> dict[str, Any]:
    """Reconcile an unknown debit outcome; also prevent a delayed debit from charging.

    A cancellation without a debit leaves a tombstone under the same operation
    ID. Whichever transaction wins the wallet lock, the net charge is zero.
    """
    run_id = str(uuid.UUID(research_run_id))
    if _backend() == "supabase":
        value = _rpc("killgate_wallet_cancel_research", {"p_user_id": wallet.user_id, "p_research_run_id": run_id})
        if not isinstance(value, dict) or value.get("ok") is not True:
            raise WalletStoreUnavailable("Research credit reconciliation was not confirmed.")
        return value
    with _LOCAL_WALLET_LOCK:
        current = load_wallet(wallet.user_id)
        original = next((item for item in current.ledger if item.get("research_run_id") == run_id), None)
        if original and original["kind"] != "cancel_research":
            return refund_research_credit(current, original)
        if not original:
            current.ledger.append({"at": _iso(_now()), "kind": "cancel_research", "research_run_id": run_id})
            save_wallet(current)
        return {"ok": True, "cancelled": True}


def refund_research_credit(wallet: Wallet, debit: dict[str, Any]) -> dict[str, Any]:
    with _LOCAL_WALLET_LOCK:
        return _refund_research_credit(wallet, debit)


def _refund_research_credit(wallet: Wallet, debit: dict[str, Any]) -> dict[str, Any]:
    """Restore an undelivered research debit exactly once.

    This is intentionally keyed to the debit receipt rather than to a product
    or family. That prevents retries from minting extra credits while allowing
    provider/storage failures to return the customer's paid entitlement.
    """
    debit_id = str(debit.get("debit_id") or "").strip()
    if not debit_id:
        raise WalletStoreUnavailable("Research debit cannot be refunded without a debit receipt.")

    if _backend() == "supabase":
        value = _rpc(
            "killgate_wallet_refund",
            {"p_user_id": wallet.user_id, "p_debit_id": debit_id},
        )
        if not isinstance(value, dict):
            raise WalletStoreUnavailable("Entitlement refund returned an invalid result.")
        return value

    current = load_wallet(wallet.user_id)
    if any(
        item.get("kind") == "refund_research"
        and str(item.get("related_debit_id") or "") == debit_id
        for item in current.ledger
    ):
        return {"ok": True, "duplicate": True, "debit_id": debit_id}

    original = next(
        (
            item
            for item in reversed(current.ledger)
            if str(item.get("debit_id") or "") == debit_id
            and item.get("kind") in {"debit_pass", "debit_subscription", "debit_wallet"}
        ),
        None,
    )
    if original is None:
        raise WalletStoreUnavailable("Research debit receipt was not found.")

    source = str(original.get("kind") or "")
    if source == "debit_pass":
        pass_id = str(original.get("pass_id") or "")
        target = next((item for item in current.passes if item.pass_id == pass_id), None)
        if target is None:
            raise WalletStoreUnavailable("Venture Pass for research refund was not found.")
        target.credits_remaining += 1
        refunded_to = "venture_pass"
    elif source == "debit_subscription":
        # If the billing period happened to expire while the provider was
        # failing, return a normal wallet credit rather than silently losing it.
        if (current.subscription_credits_expire_at and current.subscription_credits_expire_at > _now()
                and current.subscription_period_id == original.get("period_id")):
            current.subscription_credits += 1
            refunded_to = "subscription"
        else:
            current.wallet_credits += 1
            refunded_to = "wallet"
    elif source == "debit_wallet":
        current.wallet_credits += 1
        refunded_to = "wallet"
    else:  # defensive; guarded above
        raise WalletStoreUnavailable("Research debit source is not refundable.")

    current.ledger.append(
        {
            "at": _iso(_now()),
            "kind": "refund_research",
            "amount": 1,
            "related_debit_id": debit_id,
            "family_id": str(original.get("family_id") or ""),
            "pass_id": str(original.get("pass_id") or ""),
            "refunded_to": refunded_to,
        }
    )
    save_wallet(current)
    return {"ok": True, "duplicate": False, "debit_id": debit_id, "refunded_to": refunded_to}


def billing_enforced() -> bool:
    return os.getenv("BILLING_ENFORCED", "0").strip() == "1"


def research_access(user_id: str, family_id: str) -> dict[str, Any]:
    """Whether this user may start one live research run on the venture family."""
    wallet = load_wallet(user_id)
    family_id = (family_id or "").strip()
    bound = family_credits(wallet, family_id) if family_id else 0
    loose = wallet.wallet_credits + wallet.subscription_credits
    if is_test_admin(user_id):
        return {
            "ok": True,
            "wallet": wallet,
            "bound_credits": bound,
            "loose_credits": loose,
            "test_admin": True,
        }
    if bound > 0 or loose > 0:
        return {"ok": True, "wallet": wallet, "bound_credits": bound, "loose_credits": loose}
    if is_beta_user(user_id):
        policy = beta_policy()
        return {
            "ok": True,
            "wallet": wallet,
            "bound_credits": 0,
            "loose_credits": 0,
            "beta": True,
            "beta_max_runs": policy.max_runs,
            "beta_duration_days": policy.duration_days,
            "beta_expires_at": policy.end_at,
        }
    if not billing_enforced() and os.getenv("APP_ENV", "development").strip().lower() != "production":
        return {
            "ok": True,
            "wallet": wallet,
            "bound_credits": 0,
            "loose_credits": 0,
            "dev_bypass": True,
        }
    return {"ok": False, "wallet": wallet, "bound_credits": 0, "loose_credits": 0}
