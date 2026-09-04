"""Server-side Google Play subscription verification, RTDN handling, and entitlement storage."""
from __future__ import annotations

import base64
import hashlib
import json
import os
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import quote

import httpx

ANDROID_PUBLISHER_SCOPE = "https://www.googleapis.com/auth/androidpublisher"
class BillingUnavailable(RuntimeError):
    """Temporary billing/storage failure; never misreport this as an inactive subscription."""


ACTIVE_STATES = {
    "SUBSCRIPTION_STATE_ACTIVE",
    "SUBSCRIPTION_STATE_IN_GRACE_PERIOD",
    # A canceled subscription remains entitled until its expiry time.
    "SUBSCRIPTION_STATE_CANCELED",
}


@dataclass
class PlayEntitlement:
    product_id: str
    active: bool
    subscription_state: str
    expires_at: datetime | None
    acknowledgement_state: str
    purchase_token_hash: str
    raw: dict[str, Any]
    linked_purchase_token_hash: str = ""
    predecessor_token_hashes: tuple[str, ...] = ()


@dataclass(frozen=True)
class RTDNMessage:
    message_id: str
    package_name: str
    event_time_millis: int | None
    notification_kind: str
    notification_type: int | None
    purchase_token: str

    @property
    def purchase_token_hash(self) -> str:
        return hash_purchase_token(self.purchase_token) if self.purchase_token else ""


def billing_enabled() -> bool:
    return bool(
        os.getenv("GOOGLE_PLAY_PACKAGE_NAME", "").strip()
        and configured_product_id()
    )


def billing_enforced() -> bool:
    return os.getenv("BILLING_ENFORCED", "0").strip() == "1"


def configured_product_id() -> str:
    # Canonical subscription SKU is Founder Pro. Accept the old env name only as
    # a deployment compatibility alias while existing secrets are rotated.
    return (
        os.getenv("GOOGLE_PLAY_FOUNDER_PRO_PRODUCT_ID", "").strip()
        or os.getenv("GOOGLE_PLAY_SUBSCRIPTION_PRODUCT_ID", "").strip()
    )


def hash_purchase_token(purchase_token: str) -> str:
    return hashlib.sha256(purchase_token.encode("utf-8")).hexdigest()


def _credentials_info() -> dict[str, Any]:
    raw = os.getenv("GOOGLE_PLAY_SERVICE_ACCOUNT_JSON", "").strip()
    path = os.getenv("GOOGLE_PLAY_SERVICE_ACCOUNT_FILE", "").strip()
    try:
        if raw:
            payload = json.loads(raw)
        elif path:
            with open(path, "r", encoding="utf-8") as handle:
                payload = json.load(handle)
        else:
            raise BillingUnavailable("Google Play verification credential is not configured.")
    except (OSError, json.JSONDecodeError) as exc:
        raise BillingUnavailable("Google Play verification credential could not be loaded safely.") from exc
    if not isinstance(payload, dict):
        raise BillingUnavailable("Google Play verification credential has an invalid format.")
    return payload


def _google_access_token() -> str:
    from google.auth.transport.requests import Request as GoogleRequest
    from google.oauth2 import service_account

    try:
        credentials = service_account.Credentials.from_service_account_info(
            _credentials_info(), scopes=[ANDROID_PUBLISHER_SCOPE]
        )
        credentials.refresh(GoogleRequest())
    except BillingUnavailable:
        raise
    except Exception as exc:
        # This boundary includes credential-shape and Google auth transport failures;
        # neither should ever be reported to a customer as an invalid purchase.
        raise BillingUnavailable("Google Play authorization is temporarily unavailable.") from exc
    token = str(credentials.token or "").strip()
    if not token:
        raise BillingUnavailable("Google Play authorization returned no access token.")
    return token


def _parse(value: str) -> datetime | None:
    try:
        return (
            datetime.fromisoformat((value or "").replace("Z", "+00:00")).astimezone(UTC)
            if value
            else None
        )
    except ValueError:
        return None


def _max_expiry(payload: dict[str, Any], product_id: str) -> datetime | None:
    expiries = [
        _parse(str(item.get("expiryTime") or ""))
        for item in payload.get("lineItems") or []
        if item.get("productId") == product_id
    ]
    valid = [expiry for expiry in expiries if expiry]
    return max(valid) if valid else None


def verify_subscription(purchase_token: str, product_id: str = "") -> PlayEntitlement:
    purchase_token = purchase_token.strip()
    configured_product = configured_product_id()
    requested_product = product_id.strip()
    package_name = os.getenv("GOOGLE_PLAY_PACKAGE_NAME", "").strip()
    if not configured_product:
        raise RuntimeError("Google Play subscription product ID is not configured.")
    if requested_product and requested_product != configured_product:
        raise ValueError("Purchase product does not match the configured Killgate subscription.")
    product_id = configured_product
    if not purchase_token or not package_name:
        raise ValueError("Missing purchase token or package name.")

    access_token = _google_access_token()
    encoded_token = quote(purchase_token, safe="")
    encoded_package = quote(package_name, safe="")
    try:
        response = httpx.get(
            f"https://androidpublisher.googleapis.com/androidpublisher/v3/applications/{encoded_package}/purchases/subscriptionsv2/tokens/{encoded_token}",
            headers={"Authorization": f"Bearer {access_token}", "Accept": "application/json"},
            timeout=20,
        )
    except httpx.HTTPError as exc:
        raise BillingUnavailable("Google Play verification could not be reached.") from exc
    if response.status_code in {400, 404}:
        raise ValueError("Google Play could not verify this subscription purchase.")
    if response.status_code != 200:
        raise BillingUnavailable(
            f"Google Play verification returned HTTP {response.status_code}."
        )
    try:
        payload = response.json()
    except ValueError as exc:
        raise BillingUnavailable("Google Play verification returned invalid data.") from exc
    if not isinstance(payload, dict):
        raise BillingUnavailable("Google Play verification returned invalid data.")
    products = {str(item.get("productId") or "") for item in payload.get("lineItems") or []}
    if product_id not in products:
        raise ValueError("The purchase token does not contain the configured Killgate subscription product.")

    state = str(payload.get("subscriptionState") or "SUBSCRIPTION_STATE_UNSPECIFIED")
    acknowledgement = str(
        payload.get("acknowledgementState") or "ACKNOWLEDGEMENT_STATE_UNSPECIFIED"
    )
    expiry = _max_expiry(payload, product_id)
    active = state in ACTIVE_STATES and bool(expiry and expiry > datetime.now(UTC))

    linked_token = str(payload.get("linkedPurchaseToken") or "").strip()
    out_of_app = payload.get("outOfAppPurchaseContext")
    expired_token = (
        str(out_of_app.get("expiredPurchaseToken") or "").strip()
        if isinstance(out_of_app, dict) else ""
    )
    predecessor_hashes = tuple(
        dict.fromkeys(
            hash_purchase_token(token)
            for token in (linked_token, expired_token)
            if token
        )
    )

    return PlayEntitlement(
        product_id=product_id,
        active=active,
        subscription_state=state,
        expires_at=expiry,
        acknowledgement_state=acknowledgement,
        purchase_token_hash=hash_purchase_token(purchase_token),
        raw=payload,
        linked_purchase_token_hash=(hash_purchase_token(linked_token) if linked_token else ""),
        predecessor_token_hashes=predecessor_hashes,
    )


def verify_one_time_product(purchase_token: str, product_id: str) -> PlayEntitlement:
    """Verify a consumable/one-time Play product. Does not treat it as a subscription."""
    purchase_token = purchase_token.strip()
    product_id = product_id.strip()
    package_name = os.getenv("GOOGLE_PLAY_PACKAGE_NAME", "").strip()
    if not purchase_token or not package_name or not product_id:
        raise ValueError("Missing purchase token, package name, or product ID.")
    access_token = _google_access_token()
    encoded_token = quote(purchase_token, safe="")
    encoded_package = quote(package_name, safe="")
    encoded_product = quote(product_id, safe="")
    try:
        response = httpx.get(
            f"https://androidpublisher.googleapis.com/androidpublisher/v3/applications/{encoded_package}/purchases/products/{encoded_product}/tokens/{encoded_token}",
            headers={"Authorization": f"Bearer {access_token}", "Accept": "application/json"},
            timeout=20,
        )
    except httpx.HTTPError as exc:
        raise BillingUnavailable("Google Play verification could not be reached.") from exc
    if response.status_code in {400, 404}:
        raise ValueError("Google Play could not verify this one-time purchase.")
    if response.status_code != 200:
        raise BillingUnavailable(f"Google Play verification returned HTTP {response.status_code}.")
    try:
        payload = response.json()
    except ValueError as exc:
        raise BillingUnavailable("Google Play verification returned invalid data.") from exc
    if not isinstance(payload, dict):
        raise BillingUnavailable("Google Play verification returned invalid data.")
    purchase_state = payload.get("purchaseState")
    purchased = purchase_state in {0, "0", "PURCHASED"}
    return PlayEntitlement(
        product_id=product_id,
        active=purchased,
        subscription_state="ONE_TIME_PURCHASED" if purchased else "ONE_TIME_INVALID",
        expires_at=None,
        acknowledgement_state=str(payload.get("acknowledgementState") or ""),
        purchase_token_hash=hash_purchase_token(purchase_token),
        raw=payload,
    )


def consume_one_time_product(purchase_token: str, entitlement: PlayEntitlement) -> bool:
    """Consume a verified consumable after Killgate has durably granted it.

    Server-side consumption both fulfills Play acknowledgement requirements for
    consumables and makes the SKU repurchasable. A duplicate/previously consumed
    token is treated as already processed rather than granting anything again.
    """
    if not entitlement.active:
        return False
    purchase_token = purchase_token.strip()
    product_id = entitlement.product_id.strip()
    package_name = os.getenv("GOOGLE_PLAY_PACKAGE_NAME", "").strip()
    if not purchase_token or not product_id or not package_name:
        raise ValueError("Missing purchase token, package name, or product ID.")
    encoded_token = quote(purchase_token, safe="")
    encoded_package = quote(package_name, safe="")
    encoded_product = quote(product_id, safe="")
    access_token = _google_access_token()
    try:
        response = httpx.post(
            f"https://androidpublisher.googleapis.com/androidpublisher/v3/applications/{encoded_package}/purchases/products/{encoded_product}/tokens/{encoded_token}:consume",
            headers={"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"},
            json={},
            timeout=20,
        )
    except httpx.HTTPError as exc:
        raise BillingUnavailable("One-time purchase was granted but Play consumption could not be reached.") from exc
    if response.status_code in (200, 204):
        return True
    if response.status_code in (400, 404, 409):
        # The durable Killgate ledger is the duplicate-grant authority. A retry can
        # legitimately encounter a token Play already considers consumed.
        return False
    raise BillingUnavailable("One-time purchase was granted but Google Play consumption failed.")


def acknowledge_subscription(purchase_token: str, entitlement: PlayEntitlement) -> bool:
    """Acknowledge an active Play purchase after its entitlement is durably granted."""
    if (
        not entitlement.active
        or entitlement.acknowledgement_state != "ACKNOWLEDGEMENT_STATE_PENDING"
    ):
        return False

    purchase_token = purchase_token.strip()
    package_name = os.getenv("GOOGLE_PLAY_PACKAGE_NAME", "").strip()
    if not purchase_token or not package_name:
        raise ValueError("Missing purchase token or package name.")
    if entitlement.product_id != configured_product_id():
        raise ValueError("Purchase product does not match the configured Killgate subscription.")

    encoded_token = quote(purchase_token, safe="")
    encoded_package = quote(package_name, safe="")
    encoded_product = quote(entitlement.product_id, safe="")
    access_token = _google_access_token()
    try:
        response = httpx.post(
            f"https://androidpublisher.googleapis.com/androidpublisher/v3/applications/{encoded_package}/purchases/subscriptions/{encoded_product}/tokens/{encoded_token}:acknowledge",
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json",
            },
            json={},
            timeout=20,
        )
    except httpx.HTTPError as exc:
        raise BillingUnavailable("Google Play acknowledgement could not be reached.") from exc
    if response.status_code not in (200, 204):
        raise BillingUnavailable("Subscription was granted but Google Play acknowledgement failed.")
    entitlement.acknowledgement_state = "ACKNOWLEDGEMENT_STATE_ACKNOWLEDGED"
    return True


def _supabase_admin() -> tuple[str, str]:
    url = os.getenv("SUPABASE_URL", "").rstrip("/")
    key = os.getenv("SUPABASE_SECRET_KEY", "").strip()
    if not url or not key:
        raise RuntimeError("Billing lifecycle handling requires server-only SUPABASE_SECRET_KEY.")
    return url, key


def persist_entitlement(user_id: str, entitlement: PlayEntitlement) -> bool:
    """Atomically persist token ownership and update current entitlement only if it is not stale."""
    url, key = _supabase_admin()
    verified_at = datetime.now(UTC).isoformat()
    try:
        response = httpx.post(
            f"{url}/rest/v1/rpc/killgate_persist_play_entitlement",
            headers={
                "apikey": key,
                "Content-Type": "application/json",
            },
            json={
                "p_user_id": user_id,
                "p_product_id": entitlement.product_id,
                "p_purchase_token_hash": entitlement.purchase_token_hash,
                "p_active": entitlement.active,
                "p_subscription_state": entitlement.subscription_state,
                "p_expires_at": entitlement.expires_at.isoformat() if entitlement.expires_at else None,
                "p_verified_at": verified_at,
                "p_linked_purchase_token_hash": entitlement.linked_purchase_token_hash or None,
            },
            timeout=20,
        )
    except httpx.HTTPError as exc:
        raise BillingUnavailable("Subscription entitlement storage could not be reached.") from exc
    if response.status_code != 200:
        raise BillingUnavailable("The verified subscription could not be persisted atomically.")
    try:
        updated_current = response.json()
    except ValueError as exc:
        raise BillingUnavailable("Subscription entitlement storage returned invalid data.") from exc
    if not isinstance(updated_current, bool):
        raise BillingUnavailable("Subscription entitlement storage returned invalid data.")
    return updated_current


def get_entitlement(user_id: str, access_token: str) -> dict[str, Any] | None:
    """Read the caller's entitlement, distinguishing absence from a provider outage."""
    if not billing_enabled():
        return None
    url = os.getenv("SUPABASE_URL", "").rstrip("/")
    key = os.getenv("SUPABASE_PUBLISHABLE_KEY", "").strip()
    if not url or not key or not access_token:
        if os.getenv("AUTH_MODE", "local").strip().lower() != "supabase":
            return None
        raise BillingUnavailable("Billing entitlement storage is not configured or authenticated.")
    try:
        response = httpx.get(
            f"{url}/rest/v1/subscription_entitlements",
            headers={"apikey": key, "Authorization": f"Bearer {access_token}"},
            params={
                "select": "product_id,active,subscription_state,expires_at,last_verified_at",
                "user_id": f"eq.{user_id}",
                "limit": "1",
            },
            timeout=15,
        )
    except httpx.HTTPError as exc:
        raise BillingUnavailable("Billing entitlement storage could not be reached.") from exc
    if response.status_code != 200:
        raise BillingUnavailable("Billing entitlement storage returned an operational error.")
    try:
        rows = response.json()
    except (ValueError, TypeError) as exc:
        raise BillingUnavailable("Billing entitlement storage returned invalid data.") from exc
    if not isinstance(rows, list):
        raise BillingUnavailable("Billing entitlement storage returned invalid data.")
    return rows[0] if rows else None


def entitlement_is_current(row: dict[str, Any] | None) -> bool:
    """Return whether a stored entitlement matches the SKU, is unexpired, and is fresh."""
    expected_product = configured_product_id()
    if not expected_product or not row:
        return False
    expiry = _parse(str(row.get("expires_at") or ""))
    verified_at = _parse(str(row.get("last_verified_at") or ""))
    try:
        max_age_hours = int(os.getenv("ENTITLEMENT_MAX_AGE_HOURS", "24"))
    except ValueError:
        return False
    now = datetime.now(UTC)
    return bool(
        row.get("product_id") == expected_product
        and row.get("active")
        and expiry
        and expiry > now
        and verified_at
        and 1 <= max_age_hours <= 168
        and verified_at > now - timedelta(hours=max_age_hours)
        and verified_at <= now + timedelta(minutes=5)
    )


def user_has_active_entitlement(user_id: str, access_token: str) -> bool:
    if not billing_enforced():
        # Local development may exercise research before Play is wired. A
        # production typo must never turn that convenience into a paywall bypass.
        return os.getenv("APP_ENV", "development").strip().lower() != "production"
    if not configured_product_id():
        return False
    return entitlement_is_current(get_entitlement(user_id, access_token))


def verify_pubsub_push_authorization(authorization_header: str) -> dict[str, Any]:
    """Validate the Google-signed OIDC token on an authenticated Pub/Sub push."""
    audience = os.getenv("GOOGLE_PLAY_RTDN_AUDIENCE", "").strip()
    expected_email = os.getenv("GOOGLE_PLAY_RTDN_SERVICE_ACCOUNT_EMAIL", "").strip().lower()
    if not audience or not expected_email:
        raise RuntimeError("Google Play RTDN push authentication is not configured.")
    if not authorization_header.lower().startswith("bearer "):
        raise ValueError("Missing Pub/Sub bearer token.")

    token = authorization_header.split(None, 1)[1].strip()
    if not token:
        raise ValueError("Missing Pub/Sub bearer token.")

    from google.auth.transport.requests import Request as GoogleRequest
    from google.oauth2 import id_token

    claims = id_token.verify_oauth2_token(token, GoogleRequest(), audience=audience)
    issuer = str(claims.get("iss") or "")
    email = str(claims.get("email") or "").lower()
    email_verified = claims.get("email_verified")
    if issuer not in {"accounts.google.com", "https://accounts.google.com"}:
        raise ValueError("Unexpected Pub/Sub token issuer.")
    if email != expected_email or email_verified not in {True, "true"}:
        raise ValueError("Pub/Sub push identity does not match the configured service account.")
    return claims


def decode_rtdn_envelope(envelope: dict[str, Any]) -> RTDNMessage:
    """Decode a wrapped Cloud Pub/Sub RTDN message. Payload unwrapping must remain disabled."""
    message = envelope.get("message")
    if not isinstance(message, dict):
        raise TypeError("RTDN body is missing the Pub/Sub message envelope.")
    message_id = str(message.get("messageId") or "").strip()
    encoded = str(message.get("data") or "").strip()
    if not message_id or not encoded:
        raise ValueError("RTDN body is missing messageId or data.")

    try:
        decoded = base64.b64decode(encoded, validate=True)
        payload = json.loads(decoded.decode("utf-8"))
    except (ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("RTDN data is not valid base64-encoded JSON.") from exc
    if not isinstance(payload, dict):
        raise TypeError("RTDN data must decode to a JSON object.")

    package_name = str(payload.get("packageName") or "").strip()
    try:
        event_time_millis = int(payload.get("eventTimeMillis")) if payload.get("eventTimeMillis") else None
    except (TypeError, ValueError):
        event_time_millis = None

    kind = "other"
    notification_type: int | None = None
    purchase_token = ""

    subscription = payload.get("subscriptionNotification")
    voided = payload.get("voidedPurchaseNotification")
    if isinstance(subscription, dict):
        kind = "subscription"
        purchase_token = str(subscription.get("purchaseToken") or "").strip()
        try:
            notification_type = int(subscription.get("notificationType"))
        except (TypeError, ValueError):
            notification_type = None
    elif isinstance(voided, dict):
        try:
            voided_product_type = int(voided.get("productType") or 0)
        except (TypeError, ValueError):
            voided_product_type = 0
        if voided_product_type == 1:
            kind = "voided_subscription"
            purchase_token = str(voided.get("purchaseToken") or "").strip()
        else:
            kind = "voided_purchase"
    elif isinstance(payload.get("testNotification"), dict):
        kind = "test"
    elif isinstance(payload.get("pendingRefundReviewNotification"), dict):
        kind = "pending_refund_review"
    elif isinstance(payload.get("oneTimeProductNotification"), dict):
        kind = "one_time_product"

    return RTDNMessage(
        message_id=message_id[:512],
        package_name=package_name[:300],
        event_time_millis=event_time_millis,
        notification_kind=kind,
        notification_type=notification_type,
        purchase_token=purchase_token[:10000],
    )


def _strict_rows(response: httpx.Response, *, context: str) -> list[dict[str, Any]]:
    try:
        payload = response.json()
    except ValueError as exc:
        raise BillingUnavailable(f"{context} returned invalid JSON.") from exc
    if not isinstance(payload, list) or any(not isinstance(row, dict) for row in payload):
        raise BillingUnavailable(f"{context} returned an invalid row payload.")
    return payload


def find_entitlement_owner_by_token_hash(token_hash: str) -> str | None:
    """Resolve an already-hashed historical or current Play purchase token to its owner."""
    if not re.fullmatch(r"[0-9a-f]{64}", token_hash or ""):
        return None
    url, key = _supabase_admin()
    try:
        response = httpx.get(
            f"{url}/rest/v1/play_purchase_token_owners",
            headers={"apikey": key},
            params={
                "select": "user_id",
                "purchase_token_hash": f"eq.{token_hash}",
                "limit": "1",
            },
            timeout=15,
        )
    except httpx.HTTPError as exc:
        raise BillingUnavailable("Killgate could not resolve the RTDN purchase token owner.") from exc
    if response.status_code != 200:
        raise BillingUnavailable("Killgate could not resolve the RTDN purchase token owner.")
    rows = _strict_rows(response, context="RTDN token-owner lookup")
    if rows:
        user_id = str(rows[0].get("user_id") or "").strip()
        if not user_id:
            raise BillingUnavailable("RTDN token-owner lookup returned a row without a user id.")
        return user_id

    try:
        response = httpx.get(
            f"{url}/rest/v1/subscription_entitlements",
            headers={"apikey": key},
            params={
                "select": "user_id",
                "purchase_token_hash": f"eq.{token_hash}",
                "limit": "1",
            },
            timeout=15,
        )
    except httpx.HTTPError as exc:
        raise BillingUnavailable("Killgate could not resolve the RTDN purchase token owner.") from exc
    if response.status_code != 200:
        raise BillingUnavailable("Killgate could not resolve the RTDN purchase token owner.")
    rows = _strict_rows(response, context="RTDN entitlement-owner fallback")
    if not rows:
        return None
    user_id = str(rows[0].get("user_id") or "").strip()
    if not user_id:
        raise BillingUnavailable("RTDN entitlement-owner fallback returned a row without a user id.")
    return user_id


def find_entitlement_owner_by_token(purchase_token: str) -> str | None:
    """Map any previously verified raw Play token to its Killgate owner without storing it raw."""
    return find_entitlement_owner_by_token_hash(hash_purchase_token(purchase_token))


def rtdn_event_processed(message_id: str) -> bool:
    url, key = _supabase_admin()
    try:
        response = httpx.get(
            f"{url}/rest/v1/play_rtdn_events",
            headers={"apikey": key},
            params={"select": "message_id", "message_id": f"eq.{message_id}", "limit": "1"},
            timeout=10,
        )
    except httpx.HTTPError as exc:
        raise BillingUnavailable("Killgate could not check RTDN idempotency state.") from exc
    if response.status_code != 200:
        raise BillingUnavailable("Killgate could not check RTDN idempotency state.")
    rows = _strict_rows(response, context="RTDN idempotency lookup")
    if len(rows) > 1:
        raise BillingUnavailable("RTDN idempotency lookup returned ambiguous data.")
    if rows and str(rows[0].get("message_id") or "") != message_id:
        raise BillingUnavailable("RTDN idempotency lookup returned a mismatched message id.")
    return len(rows) == 1


def record_rtdn_event(message: RTDNMessage) -> None:
    url, key = _supabase_admin()
    payload = {
        "message_id": message.message_id,
        "package_name": message.package_name,
        "event_time_millis": message.event_time_millis,
        "notification_kind": message.notification_kind,
        "notification_type": message.notification_type,
        "purchase_token_hash": message.purchase_token_hash or None,
    }
    try:
        response = httpx.post(
            f"{url}/rest/v1/play_rtdn_events?on_conflict=message_id",
            headers={
                "apikey": key,
                "Content-Type": "application/json",
                "Prefer": "resolution=ignore-duplicates,return=minimal",
            },
            json=payload,
            timeout=10,
        )
    except httpx.HTTPError as exc:
        raise BillingUnavailable("Killgate could not record the processed RTDN message.") from exc
    if response.status_code not in (200, 201, 204):
        raise BillingUnavailable("Killgate could not record the processed RTDN message.")
