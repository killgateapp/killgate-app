import base64
import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app import web
from app.models.state import SystemState
from app.services import google_play, state_store, wallet
from app.services.validation_contract import ensure_validation_contract


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTH_MODE", "local")
    monkeypatch.setenv("STATE_BACKEND", "local")
    monkeypatch.setenv("BILLING_ENFORCED", "0")
    monkeypatch.delenv("GOOGLE_PLAY_PACKAGE_NAME", raising=False)
    monkeypatch.delenv("GOOGLE_PLAY_SUBSCRIPTION_PRODUCT_ID", raising=False)
    monkeypatch.delenv("GOOGLE_PLAY_RTDN_AUDIENCE", raising=False)
    monkeypatch.delenv("GOOGLE_PLAY_RTDN_SERVICE_ACCOUNT_EMAIL", raising=False)
    monkeypatch.setattr(state_store, "DATA_DIR", tmp_path / "ventures")
    monkeypatch.setattr(wallet, "WALLET_DIR", tmp_path / "wallets")
    with TestClient(web.app) as test_client:
        yield test_client


def test_account_privacy_export_and_delete_surfaces_exist(client):
    assert client.get("/account").status_code == 200
    assert "Your private Killgate workspace" in client.get("/account").text
    assert client.get("/privacy").status_code == 200
    assert "does not sell your personal data" in client.get("/privacy").text
    deletion = client.get("/delete-account")
    assert deletion.status_code == 200
    assert "Deleting Killgate does not cancel a Google Play subscription" in deletion.text
    assert "https://play.google.com/store/account/subscriptions" in deletion.text
    assert 'href="/support"' in deletion.text


def test_account_export_preserves_user_data_without_private_analysis_rules(client):
    state = SystemState(hypothesis="A scheduling tool for independent mobile groomers")
    ensure_validation_contract(state)
    state.metrics.update(
        {
            "last_research_plain": "Public evidence suggests this is worth buyer testing.",
            "evaluator_notes": "private evaluator explanation",
            "last_mechanism_scoreboard": [{"mechanism": "private method"}],
            "llm_model": "private-provider-detail",
        }
    )
    state_store.save_state("KG-EXPORT", state)

    response = client.get("/account/export")
    payload = response.json()
    serialized = json.dumps(payload)

    assert response.status_code == 200
    assert payload["export_version"] == "1.1"
    assert payload["ventures"][0]["state"]["hypothesis"] == state.hypothesis
    assert "last_research_plain" in payload["ventures"][0]["state"]["metrics"]
    for private_key in (
        "hypothesis_fingerprint",
        "research_rules",
        "decision_rules",
        "evaluator_notes",
        "last_mechanism_scoreboard",
        "llm_model",
    ):
        assert private_key not in serialized


def test_account_links_to_specific_google_play_subscription_management(client, monkeypatch):
    monkeypatch.setenv("GOOGLE_PLAY_PACKAGE_NAME", "com.killgate.app")
    monkeypatch.setenv("GOOGLE_PLAY_SUBSCRIPTION_PRODUCT_ID", "killgate_monthly")
    account = client.get("/account")
    assert account.status_code == 200
    assert (
        "https://play.google.com/store/account/subscriptions?"
        "sku=killgate_monthly&amp;package=com.killgate.app"
    ) in account.text


def test_billing_enforcement_blocks_expensive_research(client, monkeypatch):
    state = SystemState(hypothesis="A sufficiently detailed idea for mobile mechanics")
    state_store.save_state("KG-BILL", state)
    monkeypatch.setenv("BILLING_ENFORCED", "1")
    monkeypatch.setenv("APP_ENV", "production")
    response = client.post("/v/KG-BILL/run", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/v/KG-BILL/brief?billing=required"


def test_allowlisted_test_admin_can_access_research_without_wallet_credits(client, monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("BILLING_ENFORCED", "1")
    monkeypatch.setenv("KILLGATE_TEST_ADMIN_ENABLED", "1")
    monkeypatch.setenv("KILLGATE_TEST_ADMIN_USER_IDS", "local-user")

    access = wallet.research_access("local-user", "family-1")

    assert access["ok"] is True
    assert access["test_admin"] is True
    assert access["bound_credits"] == 0
    assert access["loose_credits"] == 0


def test_test_admin_run_skips_wallet_debit_but_keeps_research_path(client, monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("BILLING_ENFORCED", "1")
    monkeypatch.setenv("KILLGATE_TEST_ADMIN_ENABLED", "1")
    monkeypatch.setenv("KILLGATE_TEST_ADMIN_USER_IDS", "local-user")
    state = SystemState(hypothesis="Independent mechanics need a reliable missed-call intake assistant")
    state_store.save_state("KG-ADMIN", state)
    debit_calls = []
    research_calls = []
    monkeypatch.setattr(web, "consume_research_credit", lambda *args: debit_calls.append(args))
    monkeypatch.setattr(web.limiter, "allow", lambda *args, **kwargs: True)
    monkeypatch.setattr(web.limiter, "reserve_research", lambda *args, **kwargs: object())
    monkeypatch.setattr(web, "run_research_pass", lambda value: (research_calls.append(value) or SimpleNamespace(
        recommendation="RESEARCH_PASS",
        plain_language="Public evidence cleared the research gate.",
        disconfirming_evidence=[],
        supporting_evidence=["Signal"],
        decision_rule_triggers=[],
        confidence=0.6,
        used_web_search=True,
        evaluator_notes="",
        rejected_by_evaluator=False,
        search_hit_count=3,
        direct_source_count=3,
        indirect_source_count=0,
        irrelevant_source_count=0,
        independent_domain_count=3,
        evidence_coverage={},
        llm_model="gpt-test",
        llm_input_tokens=100,
        llm_cached_input_tokens=0,
        llm_output_tokens=20,
        llm_reasoning_tokens=0,
        llm_total_tokens=120,
        evidence_items=[],
    )))

    response = client.post("/v/KG-ADMIN/run", follow_redirects=False)

    assert response.status_code == 303
    assert debit_calls == []
    assert len(research_calls) == 1


def test_beta_run_skips_wallet_debit_but_keeps_research_path(client, monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("BILLING_ENFORCED", "1")
    monkeypatch.setenv("KILLGATE_BETA_ENABLED", "1")
    monkeypatch.setenv("KILLGATE_BETA_USER_IDS", "local-user")
    monkeypatch.setenv("KILLGATE_BETA_START_AT", (datetime.now(UTC) - timedelta(days=1)).isoformat())
    state = SystemState(hypothesis="Independent mechanics need a reliable missed-call intake assistant")
    state_store.save_state("KG-BETA", state)
    debit_calls = []
    research_calls = []
    monkeypatch.setattr(web, "consume_research_credit", lambda *args: debit_calls.append(args))
    monkeypatch.setattr(web.limiter, "allow", lambda *args, **kwargs: True)
    monkeypatch.setattr(web.limiter, "reserve_research", lambda *args, **kwargs: object())
    monkeypatch.setattr(web, "run_research_pass", lambda value: (research_calls.append(value) or SimpleNamespace(
        recommendation="RESEARCH_PASS",
        plain_language="Public evidence cleared the research gate.",
        disconfirming_evidence=[],
        supporting_evidence=["Signal"],
        decision_rule_triggers=[],
        confidence=0.6,
        used_web_search=True,
        evaluator_notes="",
        rejected_by_evaluator=False,
        search_hit_count=3,
        direct_source_count=3,
        indirect_source_count=0,
        irrelevant_source_count=0,
        independent_domain_count=3,
        evidence_coverage={},
        llm_model="gpt-test",
        llm_input_tokens=100,
        llm_cached_input_tokens=0,
        llm_output_tokens=20,
        llm_reasoning_tokens=0,
        llm_total_tokens=120,
        evidence_items=[],
    )))

    response = client.post("/v/KG-BETA/run", follow_redirects=False)

    assert response.status_code == 303
    assert debit_calls == []
    assert len(research_calls) == 1


def test_billing_verify_route_never_trusts_client_status(client, monkeypatch):
    monkeypatch.setenv("GOOGLE_PLAY_SUBSCRIPTION_PRODUCT_ID", "killgate_monthly")
    expires = datetime.now(UTC) + timedelta(days=30)
    entitlement = google_play.PlayEntitlement(
        product_id="killgate_monthly",
        active=True,
        subscription_state="SUBSCRIPTION_STATE_ACTIVE",
        expires_at=expires,
        acknowledgement_state="ACKNOWLEDGEMENT_STATE_ACKNOWLEDGED",
        purchase_token_hash="hash-only",
        raw={},
    )
    seen = {}
    monkeypatch.setattr(web, "verify_subscription", lambda token, product: (seen.update(token=token, product=product) or entitlement))
    monkeypatch.setattr(web, "persist_entitlement", lambda user_id, ent: (seen.update(user_id=user_id, persisted=ent) or True))
    response = client.post("/billing/google-play/verify", json={"purchase_token": "opaque-play-token", "product_id": "killgate_monthly", "active": True})
    assert response.status_code == 200
    assert response.json()["active"] is True
    assert seen["token"] == "opaque-play-token"
    assert seen["persisted"] is entitlement



def test_one_time_purchase_grants_before_play_consumption(client, monkeypatch):
    entitlement = google_play.PlayEntitlement(
        product_id="killgate_venture_pass",
        active=True,
        subscription_state="ONE_TIME_PURCHASED",
        expires_at=None,
        acknowledgement_state="1",
        purchase_token_hash="c" * 64,
        raw={"purchaseState": 0, "consumptionState": 0},
    )
    calls = []
    monkeypatch.setattr(web, "verify_one_time_product", lambda *_: entitlement)
    monkeypatch.setattr(
        web,
        "grant_product",
        lambda *args, **kwargs: (calls.append("grant") or {"ok": True}),
    )
    monkeypatch.setattr(
        web,
        "consume_one_time_product",
        lambda *args, **kwargs: (calls.append("consume") or True),
    )

    response = client.post(
        "/billing/google-play/verify",
        json={"purchase_token": "opaque-pass-token", "product_id": "killgate_venture_pass"},
    )

    assert response.status_code == 200
    assert calls == ["grant", "consume"]


def test_billing_route_persists_entitlement_before_acknowledgement(client, monkeypatch):
    monkeypatch.setenv("GOOGLE_PLAY_SUBSCRIPTION_PRODUCT_ID", "killgate_monthly")
    entitlement = google_play.PlayEntitlement(
        product_id="killgate_monthly",
        active=True,
        subscription_state="SUBSCRIPTION_STATE_ACTIVE",
        expires_at=datetime.now(UTC) + timedelta(days=30),
        acknowledgement_state="ACKNOWLEDGEMENT_STATE_PENDING",
        purchase_token_hash="hash-only",
        raw={},
    )
    calls = []
    monkeypatch.setattr(web, "verify_subscription", lambda *_: entitlement)
    monkeypatch.setattr(web, "persist_entitlement", lambda *_: (calls.append("persist") or True))
    monkeypatch.setattr(web, "acknowledge_subscription", lambda *_: calls.append("ack"))

    response = client.post(
        "/billing/google-play/verify",
        json={"purchase_token": "opaque-play-token", "product_id": "killgate_monthly"},
    )

    assert response.status_code == 200
    assert calls == ["persist", "ack"]


def test_google_play_grants_before_acknowledging(monkeypatch):
    monkeypatch.setenv("GOOGLE_PLAY_PACKAGE_NAME", "com.example.killgate")
    monkeypatch.setenv("GOOGLE_PLAY_SUBSCRIPTION_PRODUCT_ID", "killgate_monthly")
    monkeypatch.setattr(google_play, "_google_access_token", lambda: "oauth")
    expiry = (datetime.now(UTC) + timedelta(days=31)).isoformat().replace("+00:00", "Z")

    class Response:
        def __init__(self, status, payload=None): self.status_code=status; self._payload=payload or {}
        def json(self): return self._payload

    payload = {
        "subscriptionState": "SUBSCRIPTION_STATE_ACTIVE",
        "acknowledgementState": "ACKNOWLEDGEMENT_STATE_PENDING",
        "lineItems": [{"productId": "killgate_monthly", "expiryTime": expiry}],
    }
    calls = {"ack": 0}
    monkeypatch.setattr(google_play.httpx, "get", lambda *a, **k: Response(200, payload))
    def post(*a, **k): calls["ack"] += 1; return Response(200)
    monkeypatch.setattr(google_play.httpx, "post", post)

    result = google_play.verify_subscription("secret-purchase-token")
    assert result.active is True
    assert result.acknowledgement_state == "ACKNOWLEDGEMENT_STATE_PENDING"
    assert result.purchase_token_hash != "secret-purchase-token"
    assert len(result.purchase_token_hash) == 64
    assert calls["ack"] == 0

    assert google_play.acknowledge_subscription("secret-purchase-token", result) is True
    assert result.acknowledgement_state == "ACKNOWLEDGEMENT_STATE_ACKNOWLEDGED"
    assert calls["ack"] == 1


def test_play_billing_client_uses_digital_goods_and_backend_verification(client):
    js = client.get("/static/app.js").text
    assert "getDigitalGoodsService" in js
    assert "https://play.google.com/billing" in js
    assert "/billing/google-play/verify" in js
    assert "purchaseToken" in js



def _rtdn_envelope(*, message_id="msg-1", package="com.killgate.app", token="play-token", notification_type=2):
    developer_notification = {
        "version": "1.0",
        "packageName": package,
        "eventTimeMillis": "1787560000000",
        "subscriptionNotification": {
            "version": "1.0",
            "notificationType": notification_type,
            "purchaseToken": token,
        },
    }
    encoded = base64.b64encode(json.dumps(developer_notification).encode()).decode()
    return {"message": {"messageId": message_id, "data": encoded}, "subscription": "projects/x/subscriptions/y"}


def test_rtdn_subscription_reverifies_persists_and_deduplicates(client, monkeypatch):
    monkeypatch.setenv("GOOGLE_PLAY_PACKAGE_NAME", "com.killgate.app")
    monkeypatch.setenv("GOOGLE_PLAY_SUBSCRIPTION_PRODUCT_ID", "killgate_monthly")
    monkeypatch.setattr(web, "verify_pubsub_push_authorization", lambda header: {"email": "rtdn@example.test"})
    monkeypatch.setattr(web, "rtdn_event_processed", lambda message_id: False)
    monkeypatch.setattr(web, "find_entitlement_owner_by_token", lambda token: "user-123")
    expires = datetime.now(UTC) + timedelta(days=30)
    entitlement = google_play.PlayEntitlement(
        product_id="killgate_monthly",
        active=True,
        subscription_state="SUBSCRIPTION_STATE_ACTIVE",
        expires_at=expires,
        acknowledgement_state="ACKNOWLEDGEMENT_STATE_ACKNOWLEDGED",
        purchase_token_hash=google_play.hash_purchase_token("play-token"),
        raw={},
    )
    seen = {}
    monkeypatch.setattr(web, "verify_subscription", lambda token: (seen.update(token=token) or entitlement))
    monkeypatch.setattr(web, "persist_entitlement", lambda user_id, ent: (seen.update(user_id=user_id, entitlement=ent) or True))
    monkeypatch.setattr(web, "record_rtdn_event", lambda message: seen.update(message=message))

    response = client.post(
        "/billing/google-play/rtdn",
        headers={"Authorization": "Bearer signed-by-google"},
        json=_rtdn_envelope(),
    )
    assert response.status_code == 204
    assert seen["token"] == "play-token"
    assert seen["user_id"] == "user-123"
    assert seen["entitlement"] is entitlement
    assert seen["message"].message_id == "msg-1"
    assert seen["message"].purchase_token_hash == google_play.hash_purchase_token("play-token")


def test_rtdn_duplicate_message_skips_google_play_api(client, monkeypatch):
    monkeypatch.setenv("GOOGLE_PLAY_PACKAGE_NAME", "com.killgate.app")
    monkeypatch.setattr(web, "verify_pubsub_push_authorization", lambda header: {})
    monkeypatch.setattr(web, "rtdn_event_processed", lambda message_id: True)
    monkeypatch.setattr(web, "verify_subscription", lambda token: (_ for _ in ()).throw(AssertionError("must not reverify duplicate")))

    response = client.post(
        "/billing/google-play/rtdn",
        headers={"Authorization": "Bearer signed-by-google"},
        json=_rtdn_envelope(message_id="duplicate"),
    )
    assert response.status_code == 204


def test_rtdn_unknown_purchase_requests_retry_instead_of_losing_event(client, monkeypatch):
    monkeypatch.setenv("GOOGLE_PLAY_PACKAGE_NAME", "com.killgate.app")
    monkeypatch.setattr(web, "verify_pubsub_push_authorization", lambda header: {})
    monkeypatch.setattr(web, "rtdn_event_processed", lambda message_id: False)
    monkeypatch.setattr(web, "find_entitlement_owner_by_token", lambda token: None)
    seen = {"recorded": False}
    monkeypatch.setattr(web, "record_rtdn_event", lambda message: seen.update(recorded=True))

    response = client.post(
        "/billing/google-play/rtdn",
        headers={"Authorization": "Bearer signed-by-google"},
        json=_rtdn_envelope(message_id="race"),
    )
    assert response.status_code == 503
    assert seen["recorded"] is False


def test_rtdn_rejects_wrong_package_before_entitlement_change(client, monkeypatch):
    monkeypatch.setenv("GOOGLE_PLAY_PACKAGE_NAME", "com.killgate.app")
    monkeypatch.setattr(web, "verify_pubsub_push_authorization", lambda header: {})
    response = client.post(
        "/billing/google-play/rtdn",
        headers={"Authorization": "Bearer signed-by-google"},
        json=_rtdn_envelope(package="com.other.app"),
    )
    assert response.status_code == 400


def test_rtdn_decoder_does_not_require_or_store_raw_envelope_after_parsing():
    message = google_play.decode_rtdn_envelope(_rtdn_envelope(token="do-not-store-raw"))
    assert message.notification_kind == "subscription"
    assert message.purchase_token == "do-not-store-raw"
    assert message.purchase_token_hash == google_play.hash_purchase_token("do-not-store-raw")


def test_configured_product_id_has_no_invented_default(monkeypatch):
    monkeypatch.delenv("GOOGLE_PLAY_SUBSCRIPTION_PRODUCT_ID", raising=False)
    assert google_play.configured_product_id() == ""


def test_billing_verify_fails_cleanly_when_distributed_limiter_is_unavailable(client, monkeypatch):
    from app.services.rate_limit import RateLimitUnavailable

    monkeypatch.setattr(web.limiter, "allow", lambda *args, **kwargs: (_ for _ in ()).throw(RateLimitUnavailable()))
    response = client.post(
        "/billing/google-play/verify",
        json={"purchase_token": "opaque-token", "product_id": "configured-product"},
    )
    assert response.status_code == 503
    assert response.json() == {"ok": False, "error": "Billing verification is temporarily unavailable."}


def test_billing_verify_does_not_expose_runtime_error_details(client, monkeypatch):
    monkeypatch.setattr(web.limiter, "allow", lambda *args, **kwargs: True)
    monkeypatch.setattr(web, "verify_subscription", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("SUPER_SECRET_BACKEND_DETAIL")))
    response = client.post(
        "/billing/google-play/verify",
        json={"purchase_token": "opaque-token", "product_id": "configured-product"},
    )
    assert response.status_code == 503
    assert response.json() == {"ok": False, "error": "Billing verification is temporarily unavailable."}
    assert "SUPER_SECRET_BACKEND_DETAIL" not in response.text


def test_billing_verify_rejects_client_supplied_other_product(client, monkeypatch):
    monkeypatch.setenv("GOOGLE_PLAY_SUBSCRIPTION_PRODUCT_ID", "killgate_monthly")
    monkeypatch.setattr(web.limiter, "allow", lambda *args, **kwargs: True)
    seen = {"verify_called": False, "persist_called": False}
    monkeypatch.setattr(
        web,
        "verify_subscription",
        lambda *args, **kwargs: (seen.update(verify_called=True) or None),
    )
    monkeypatch.setattr(
        web,
        "persist_entitlement",
        lambda *args, **kwargs: seen.update(persist_called=True),
    )

    response = client.post(
        "/billing/google-play/verify",
        json={"purchase_token": "valid-token-for-other-sku", "product_id": "other_product"},
    )

    assert response.status_code == 400
    assert response.json()["error"] == "Purchase product is not in the Killgate catalog."
    assert seen == {"verify_called": False, "persist_called": False}


def test_verify_subscription_rejects_nonconfigured_product_before_google_call(monkeypatch):
    monkeypatch.setenv("GOOGLE_PLAY_PACKAGE_NAME", "com.example.killgate")
    monkeypatch.setenv("GOOGLE_PLAY_SUBSCRIPTION_PRODUCT_ID", "killgate_monthly")
    monkeypatch.setattr(
        google_play,
        "_google_access_token",
        lambda: (_ for _ in ()).throw(AssertionError("Google API must not be called for the wrong SKU")),
    )

    with pytest.raises(ValueError, match="does not match"):
        google_play.verify_subscription("opaque-token", "other_product")


def test_active_entitlement_must_match_configured_product(monkeypatch):
    monkeypatch.setenv("BILLING_ENFORCED", "1")
    monkeypatch.setenv("GOOGLE_PLAY_SUBSCRIPTION_PRODUCT_ID", "killgate_monthly")
    future = (datetime.now(UTC) + timedelta(days=30)).isoformat()
    monkeypatch.setattr(
        google_play,
        "get_entitlement",
        lambda *args, **kwargs: {
            "product_id": "other_product",
            "active": True,
            "expires_at": future,
        },
    )

    assert google_play.user_has_active_entitlement("user-1", "access-token") is False


def test_active_entitlement_fails_closed_when_product_not_configured(monkeypatch):
    monkeypatch.setenv("BILLING_ENFORCED", "1")
    monkeypatch.delenv("GOOGLE_PLAY_SUBSCRIPTION_PRODUCT_ID", raising=False)
    monkeypatch.setattr(
        google_play,
        "get_entitlement",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("No entitlement lookup needed")),
    )

    assert google_play.user_has_active_entitlement("user-1", "access-token") is False


def test_production_billing_bypass_fails_closed(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("BILLING_ENFORCED", "0")

    assert google_play.user_has_active_entitlement("user-1", "access-token") is False


def test_stored_entitlement_requires_recent_provider_verification(monkeypatch):
    monkeypatch.setenv("GOOGLE_PLAY_SUBSCRIPTION_PRODUCT_ID", "killgate_monthly")
    monkeypatch.setenv("ENTITLEMENT_MAX_AGE_HOURS", "24")
    now = datetime.now(UTC)
    row = {
        "product_id": "killgate_monthly",
        "active": True,
        "expires_at": (now + timedelta(days=20)).isoformat(),
        "last_verified_at": (now - timedelta(hours=25)).isoformat(),
    }

    assert google_play.entitlement_is_current(row) is False
    row["last_verified_at"] = (now - timedelta(hours=1)).isoformat()
    assert google_play.entitlement_is_current(row) is True


def test_persist_entitlement_is_one_atomic_rpc(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://project.supabase.test")
    monkeypatch.setenv("SUPABASE_SECRET_KEY", "server-secret")
    entitlement = google_play.PlayEntitlement(
        product_id="killgate_monthly",
        active=True,
        subscription_state="SUBSCRIPTION_STATE_ACTIVE",
        expires_at=datetime.now(UTC) + timedelta(days=30),
        acknowledgement_state="ACKNOWLEDGEMENT_STATE_ACKNOWLEDGED",
        purchase_token_hash="a" * 64,
        raw={},
    )
    seen = {}

    class Response:
        status_code = 200
        def json(self): return True

    def post(url, **kwargs):
        seen["url"] = url
        seen["kwargs"] = kwargs
        return Response()

    monkeypatch.setattr(google_play.httpx, "post", post)
    google_play.persist_entitlement("user-123", entitlement)

    assert seen["url"].endswith("/rest/v1/rpc/killgate_persist_play_entitlement")
    assert seen["kwargs"]["json"]["p_user_id"] == "user-123"
    assert seen["kwargs"]["json"]["p_purchase_token_hash"] == "a" * 64
    assert seen["kwargs"]["json"]["p_active"] is True


def test_persist_entitlement_fails_if_atomic_rpc_rejects(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://project.supabase.test")
    monkeypatch.setenv("SUPABASE_SECRET_KEY", "server-secret")
    entitlement = google_play.PlayEntitlement(
        product_id="killgate_monthly",
        active=True,
        subscription_state="SUBSCRIPTION_STATE_ACTIVE",
        expires_at=datetime.now(UTC) + timedelta(days=30),
        acknowledgement_state="ACKNOWLEDGEMENT_STATE_ACKNOWLEDGED",
        purchase_token_hash="b" * 64,
        raw={},
    )

    class Response:
        status_code = 409

    monkeypatch.setattr(google_play.httpx, "post", lambda *args, **kwargs: Response())
    with pytest.raises(RuntimeError, match="atomically"):
        google_play.persist_entitlement("user-123", entitlement)


def test_get_entitlement_distinguishes_outage_from_no_subscription(monkeypatch):
    monkeypatch.setenv("GOOGLE_PLAY_PACKAGE_NAME", "com.killgate.app")
    monkeypatch.setenv("GOOGLE_PLAY_SUBSCRIPTION_PRODUCT_ID", "killgate_monthly")
    monkeypatch.setenv("SUPABASE_URL", "https://project.supabase.test")
    monkeypatch.setenv("SUPABASE_PUBLISHABLE_KEY", "publishable")

    class Response:
        status_code = 503
        def json(self): return {"message": "temporary"}

    monkeypatch.setattr(google_play.httpx, "get", lambda *args, **kwargs: Response())
    with pytest.raises(google_play.BillingUnavailable):
        google_play.get_entitlement("user-123", "access-token")


def test_one_time_pass_path_is_not_coupled_to_subscription_entitlement_outage(client, monkeypatch):
    monkeypatch.setattr(
        google_play,
        "user_has_active_entitlement",
        lambda *args, **kwargs: (_ for _ in ()).throw(google_play.BillingUnavailable("temporary")),
    )
    response = client.post("/v/DOES-NOT-MATTER/run", follow_redirects=False)
    # The run route no longer checks subscription entitlement before checking the
    # wallet, so a Venture Pass user cannot be blocked by a Pro-status outage.
    assert response.status_code == 303


def test_find_entitlement_owner_uses_token_history_before_current_row(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://project.supabase.test")
    monkeypatch.setenv("SUPABASE_SECRET_KEY", "server-secret")

    class Response:
        status_code = 200
        def __init__(self, payload): self._payload = payload
        def json(self): return self._payload

    seen = []
    def get(url, **kwargs):
        seen.append(url)
        if "play_purchase_token_owners" in url:
            return Response([{"user_id": "history-owner"}])
        raise AssertionError("current entitlement fallback should not be queried")

    monkeypatch.setattr(google_play.httpx, "get", get)

    assert google_play.find_entitlement_owner_by_token("old-play-token") == "history-owner"
    assert len(seen) == 1


def test_session_cookie_age_invalid_config_falls_back_safely(monkeypatch):
    from fastapi.responses import Response as FastAPIResponse

    from app.services import auth

    monkeypatch.setenv("AUTH_MODE", "local")
    monkeypatch.setenv("SESSION_COOKIE_MAX_AGE", "not-an-integer")
    response = FastAPIResponse()
    session = auth.SessionResolution(
        user=auth.AuthUser("user-1", "user@example.test", "access"),
        access_token="access",
        refresh_token="refresh",
    )

    auth.set_session_cookies(response, session)

    headers = response.headers.getlist("set-cookie")
    assert len(headers) == 2
    assert all("Max-Age=2592000" in header for header in headers)


def test_verify_subscription_extracts_replacement_lineage(monkeypatch):
    monkeypatch.setenv("GOOGLE_PLAY_PACKAGE_NAME", "com.example.killgate")
    monkeypatch.setenv("GOOGLE_PLAY_SUBSCRIPTION_PRODUCT_ID", "killgate_monthly")
    monkeypatch.setattr(google_play, "_google_access_token", lambda: "oauth")
    expiry = (datetime.now(UTC) + timedelta(days=31)).isoformat().replace("+00:00", "Z")
    payload = {
        "subscriptionState": "SUBSCRIPTION_STATE_ACTIVE",
        "acknowledgementState": "ACKNOWLEDGEMENT_STATE_ACKNOWLEDGED",
        "linkedPurchaseToken": "old-upgrade-token",
        "outOfAppPurchaseContext": {"expiredPurchaseToken": "older-expired-token"},
        "lineItems": [{"productId": "killgate_monthly", "expiryTime": expiry}],
    }

    class Response:
        status_code = 200
        def json(self): return payload

    monkeypatch.setattr(google_play.httpx, "get", lambda *a, **k: Response())
    result = google_play.verify_subscription("new-token")
    assert result.linked_purchase_token_hash == google_play.hash_purchase_token("old-upgrade-token")
    assert result.predecessor_token_hashes == (
        google_play.hash_purchase_token("old-upgrade-token"),
        google_play.hash_purchase_token("older-expired-token"),
    )


def test_google_play_provider_503_is_not_reported_as_bad_purchase(monkeypatch):
    monkeypatch.setenv("GOOGLE_PLAY_PACKAGE_NAME", "com.example.killgate")
    monkeypatch.setenv("GOOGLE_PLAY_SUBSCRIPTION_PRODUCT_ID", "killgate_monthly")
    monkeypatch.setattr(google_play, "_google_access_token", lambda: "oauth")

    class Response:
        status_code = 503
        def json(self): return {}

    monkeypatch.setattr(google_play.httpx, "get", lambda *a, **k: Response())
    with pytest.raises(google_play.BillingUnavailable):
        google_play.verify_subscription("token")


def test_rtdn_new_replacement_token_can_resolve_owner_from_predecessor(client, monkeypatch):
    monkeypatch.setenv("GOOGLE_PLAY_PACKAGE_NAME", "com.killgate.app")
    monkeypatch.setenv("GOOGLE_PLAY_SUBSCRIPTION_PRODUCT_ID", "killgate_monthly")
    monkeypatch.setattr(web, "verify_pubsub_push_authorization", lambda header: {})
    monkeypatch.setattr(web, "rtdn_event_processed", lambda message_id: False)
    new_token = "replacement-token"
    old_hash = google_play.hash_purchase_token("old-token")
    entitlement = google_play.PlayEntitlement(
        product_id="killgate_monthly",
        active=True,
        subscription_state="SUBSCRIPTION_STATE_ACTIVE",
        expires_at=datetime.now(UTC) + timedelta(days=30),
        acknowledgement_state="ACKNOWLEDGEMENT_STATE_ACKNOWLEDGED",
        purchase_token_hash=google_play.hash_purchase_token(new_token),
        raw={},
        linked_purchase_token_hash=old_hash,
        predecessor_token_hashes=(old_hash,),
    )
    monkeypatch.setattr(web, "verify_subscription", lambda token: entitlement)
    monkeypatch.setattr(web, "find_entitlement_owner_by_token", lambda token: None)
    monkeypatch.setattr(
        web,
        "find_entitlement_owner_by_token_hash",
        lambda token_hash: "user-123" if token_hash == old_hash else None,
    )
    seen = {}
    monkeypatch.setattr(web, "persist_entitlement", lambda user_id, ent: seen.update(user_id=user_id, ent=ent))
    monkeypatch.setattr(web, "record_rtdn_event", lambda message: seen.update(recorded=True))

    response = client.post(
        "/billing/google-play/rtdn",
        headers={"Authorization": "Bearer google"},
        json=_rtdn_envelope(token=new_token, notification_type=4),
    )
    assert response.status_code == 204
    assert seen["user_id"] == "user-123"
    assert seen["ent"] is entitlement
    assert seen["recorded"] is True


@pytest.mark.parametrize(
    "state,days,expected",
    [
        ("SUBSCRIPTION_STATE_ACTIVE", 10, True),
        ("SUBSCRIPTION_STATE_IN_GRACE_PERIOD", 2, True),
        ("SUBSCRIPTION_STATE_CANCELED", 3, True),
        ("SUBSCRIPTION_STATE_CANCELED", -1, False),
        ("SUBSCRIPTION_STATE_ON_HOLD", 10, False),
        ("SUBSCRIPTION_STATE_EXPIRED", 10, False),
        ("SUBSCRIPTION_STATE_PAUSED", 10, False),
    ],
)
def test_google_play_entitlement_states_are_fail_closed(monkeypatch, state, days, expected):
    monkeypatch.setenv("GOOGLE_PLAY_PACKAGE_NAME", "com.example.killgate")
    monkeypatch.setenv("GOOGLE_PLAY_SUBSCRIPTION_PRODUCT_ID", "killgate_monthly")
    monkeypatch.setattr(google_play, "_google_access_token", lambda: "oauth")
    expiry = (datetime.now(UTC) + timedelta(days=days)).isoformat().replace("+00:00", "Z")
    payload = {
        "subscriptionState": state,
        "acknowledgementState": "ACKNOWLEDGEMENT_STATE_ACKNOWLEDGED",
        "lineItems": [{"productId": "killgate_monthly", "expiryTime": expiry}],
    }

    class Response:
        status_code = 200
        def json(self): return payload

    monkeypatch.setattr(google_play.httpx, "get", lambda *a, **k: Response())
    result = google_play.verify_subscription("token")
    assert result.active is expected


def test_rtdn_idempotency_malformed_200_payload_fails_closed(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://project.supabase.test")
    monkeypatch.setenv("SUPABASE_SECRET_KEY", "server-secret")

    class Response:
        status_code = 200
        def json(self):
            return {"message_id": "looks-truthy-but-is-not-a-row-list"}

    monkeypatch.setattr(google_play.httpx, "get", lambda *args, **kwargs: Response())
    with pytest.raises(google_play.BillingUnavailable, match="invalid row payload"):
        google_play.rtdn_event_processed("msg-123")


def test_rtdn_idempotency_requires_exact_message_id(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://project.supabase.test")
    monkeypatch.setenv("SUPABASE_SECRET_KEY", "server-secret")

    class Response:
        status_code = 200
        def json(self):
            return [{"message_id": "different-message"}]

    monkeypatch.setattr(google_play.httpx, "get", lambda *args, **kwargs: Response())
    with pytest.raises(google_play.BillingUnavailable, match="mismatched"):
        google_play.rtdn_event_processed("msg-123")


def test_rtdn_idempotency_transport_failure_requests_retry(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://project.supabase.test")
    monkeypatch.setenv("SUPABASE_SECRET_KEY", "server-secret")
    monkeypatch.setattr(
        google_play.httpx,
        "get",
        lambda *args, **kwargs: (_ for _ in ()).throw(google_play.httpx.ConnectError("down")),
    )
    with pytest.raises(google_play.BillingUnavailable):
        google_play.rtdn_event_processed("msg-123")


def test_token_owner_lookup_rejects_row_without_user_id(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://project.supabase.test")
    monkeypatch.setenv("SUPABASE_SECRET_KEY", "server-secret")

    class Response:
        status_code = 200
        def json(self):
            return [{}]

    monkeypatch.setattr(google_play.httpx, "get", lambda *args, **kwargs: Response())
    with pytest.raises(google_play.BillingUnavailable, match="without a user id"):
        google_play.find_entitlement_owner_by_token("known-token")


def test_malformed_service_account_config_is_operational_not_bad_purchase(monkeypatch):
    monkeypatch.setenv("GOOGLE_PLAY_SERVICE_ACCOUNT_JSON", "{not-json")
    monkeypatch.delenv("GOOGLE_PLAY_SERVICE_ACCOUNT_FILE", raising=False)
    with pytest.raises(google_play.BillingUnavailable, match="credential"):
        google_play._credentials_info()
