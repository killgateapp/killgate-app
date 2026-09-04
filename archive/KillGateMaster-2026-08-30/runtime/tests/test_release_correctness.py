"""Regression coverage for the release review's correctness and concurrency cases."""
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Event
from types import SimpleNamespace

import httpx
import pytest
from fastapi.testclient import TestClient

from app import web
from app.models.deep_research import ResearchSnapshot
from app.models.research_report import DeepResearchReport, ResearchVerdict
from app.models.state import (
    DirectValidationRecord,
    EvidenceItem,
    EvidenceLevel,
    Phase,
    SystemState,
    ValidationDecision,
)
from app.services import (
    audit_trail,
    google_play,
    packet,
    rate_limit,
    state_store,
    wallet,
)
from app.services.research import ResearchResult
from app.services.slots import archive_state, slot_status
from app.services.validation_contract import ensure_validation_contract


@pytest.fixture
def client(tmp_path, monkeypatch):
    for key, value in {"AUTH_MODE": "local", "STATE_BACKEND": "local", "WALLET_BACKEND": "local",
                       "APP_ENV": "production", "BILLING_ENFORCED": "1", "KILLGATE_TEST_ADMIN_ENABLED": "0",
                       "GOOGLE_PLAY_FOUNDER_PRO_PRODUCT_ID": "killgate_founder_pro"}.items():
        monkeypatch.setenv(key, value)
    monkeypatch.delenv("KILLGATE_BETA_USER_IDS", raising=False)
    monkeypatch.setattr(state_store, "DATA_DIR", tmp_path / "ventures")
    monkeypatch.setattr(wallet, "WALLET_DIR", tmp_path / "wallets")
    monkeypatch.setattr(web, "limiter", rate_limit.SlidingWindowLimiter())
    with TestClient(web.app) as instance:
        yield instance


def seed_research():
    state = SystemState(hypothesis="Independent plumbers will pay for automatic lost-estimate follow-up.")
    ensure_validation_contract(state)
    state_store.save_state("V-RESEARCH", state)
    store = wallet.load_wallet("local-user")
    store.wallet_credits = 3
    wallet.save_wallet(store)
    return state


def result():
    return ResearchResult(summary="Result", recommendation="RESEARCH_PIVOT", plain_language="Try a narrower buyer.")


def entitlement():
    return google_play.PlayEntitlement(
        product_id="killgate_founder_pro", active=True,
        subscription_state="SUBSCRIPTION_STATE_ACTIVE", expires_at=datetime.now(UTC) + timedelta(days=30),
        acknowledgement_state="ACKNOWLEDGEMENT_STATE_PENDING", purchase_token_hash="a" * 64, raw={},
    )


@pytest.mark.parametrize("updated_current", [False, None])
def test_stale_subscription_route_neither_grants_nor_acknowledges(client, monkeypatch, updated_current):
    monkeypatch.setattr(web, "verify_subscription", lambda *_: entitlement())
    monkeypatch.setattr(web, "persist_entitlement", lambda *_: updated_current)
    monkeypatch.setattr(web, "grant_product", lambda *a, **kw: pytest.fail("stale refill"))
    monkeypatch.setattr(web, "acknowledge_subscription", lambda *_: pytest.fail("stale acknowledgement"))
    response = client.post("/billing/google-play/verify", json={"purchase_token": "opaque", "product_id": entitlement().product_id})
    assert response.status_code == 200
    assert response.json() == {"ok": True, "status": "stale_purchase_ignored", "updated_current": False}
    assert "active" not in response.json()


@pytest.mark.parametrize("accepted,grant_result", [(False, None), (True, {"ok": False, "error": "stale_purchase_ignored"})])
def test_stale_rtdn_is_audited_without_grant_or_acknowledgement(client, monkeypatch, accepted, grant_result):
    monkeypatch.setenv("GOOGLE_PLAY_PACKAGE_NAME", "com.killgate.app")
    message = SimpleNamespace(message_id="stale-message", package_name="com.killgate.app",
                              notification_kind="subscription", purchase_token="opaque")
    monkeypatch.setattr(web, "verify_pubsub_push_authorization", lambda *_: {})
    monkeypatch.setattr(web, "decode_rtdn_envelope", lambda *_: message)
    monkeypatch.setattr(web, "rtdn_event_processed", lambda *_: False)
    monkeypatch.setattr(web, "verify_subscription", lambda *_: entitlement())
    monkeypatch.setattr(web, "find_entitlement_owner_by_token", lambda *_: "local-user")
    monkeypatch.setattr(web, "persist_entitlement", lambda *_: accepted)
    grants, recorded = [], []
    monkeypatch.setattr(web, "grant_product", lambda *a, **kw: (grants.append(True) or grant_result))
    monkeypatch.setattr(web, "acknowledge_subscription", lambda *_: pytest.fail("stale acknowledgement"))
    monkeypatch.setattr(web, "record_rtdn_event", lambda msg: recorded.append(msg))
    response = client.post("/billing/google-play/rtdn", json={})
    assert response.status_code == 204
    assert grants == ([True] if accepted else [])
    assert recorded == [message]


def test_current_subscription_grant_precedes_acknowledgement(client, monkeypatch):
    monkeypatch.setattr(web, "verify_subscription", lambda *_: entitlement())
    calls = []
    monkeypatch.setattr(web, "persist_entitlement", lambda *_: (calls.append("persist") or True))
    monkeypatch.setattr(web, "grant_product", lambda *a, **kw: (calls.append("grant") or {"ok": True}))
    monkeypatch.setattr(web, "acknowledge_subscription", lambda *_: calls.append("acknowledge"))
    response = client.post("/billing/google-play/verify", json={"purchase_token": "opaque", "product_id": entitlement().product_id})
    assert response.status_code == 200
    assert response.json()["active"] is True
    assert calls == ["persist", "grant", "acknowledge"]


def test_attempt_rejection_never_reserves_or_debits(client, monkeypatch):
    seed_research()
    monkeypatch.setattr(web.limiter, "allow", lambda *_: False)
    monkeypatch.setattr(web.limiter, "reserve_research", lambda *a, **kw: pytest.fail("quota leak"))
    monkeypatch.setattr(web, "consume_research_credit", lambda *a, **kw: pytest.fail("unexpected debit"))
    response = client.post("/v/V-RESEARCH/run")
    assert response.status_code == 429
    assert "research_run_id" not in state_store.load_state("V-RESEARCH").metrics


def test_deep_research_feature_flag_routes_through_durable_pipeline(client, monkeypatch):
    seed_research()
    called = []
    report = DeepResearchReport(run_id="run", verdict=ResearchVerdict.PIVOT, summary="durable")
    monkeypatch.setattr(web, "deep_research_enabled", lambda: True)

    def pipeline(state, **kwargs):
        called.append(kwargs)
        return SimpleNamespace(
            legacy_result=result(),
            report=report,
            run=SimpleNamespace(storage_revision=7),
        )

    monkeypatch.setattr(web, "run_deep_research_pipeline", pipeline)
    response = client.post("/v/V-RESEARCH/run", follow_redirects=False)
    assert response.status_code == 303
    assert called[0]["run_id"] == state_store.load_state("V-RESEARCH").metrics["research_run_id"]
    saved = state_store.load_state("V-RESEARCH")
    assert saved.metrics["deep_research_storage_revision"] == 7
    assert saved.metrics["deep_research_report"]["verdict"] == "RESEARCH_PIVOT"


def test_deep_research_report_export_is_auth_scoped(client):
    seed_research()
    state = state_store.load_state("V-RESEARCH")
    state.metrics["deep_research_report"] = {"run_id": "run-1", "verdict": "RESEARCH_PIVOT"}
    state_store.save_state("V-RESEARCH", state)
    response = client.get("/v/V-RESEARCH/deep-research.json")
    assert response.status_code == 200
    assert response.json()["run_id"] == "run-1"
    assert "deep-research" in response.headers["content-disposition"]


def test_deep_research_status_is_owner_scoped_and_never_returns_internal_checkpoint(client, monkeypatch):
    seed_research()
    state = state_store.load_state("V-RESEARCH")
    state.metrics.update(research_run_id="run-status", research_run_status="retrieving")
    state_store.save_state("V-RESEARCH", state)
    monkeypatch.setattr(web, "load_research_run", lambda **kwargs: None)
    response = client.get("/v/V-RESEARCH/deep-research-status.json")
    assert response.status_code == 200
    assert response.json() == {
        "run_id": "run-status",
        "status": "retrieving",
        "terminal": False,
        "report_available": False,
        "failure": None,
    }
    assert client.get("/v/not-owned/deep-research-status.json").status_code == 404


def test_deep_research_export_prefers_immutable_snapshot_when_available(client, monkeypatch):
    seed_research()
    state = state_store.load_state("V-RESEARCH")
    state.metrics["deep_research_report"] = {"run_id": "run-1", "verdict": "RESEARCH_PIVOT"}
    state_store.save_state("V-RESEARCH", state)
    snapshot = ResearchSnapshot(
        research_run_id="run-1",
        venture_id="V-RESEARCH",
        venture_family_id="family-1",
        validation_contract_fingerprint="a" * 64,
        hypothesis_fingerprint="b" * 64,
        report={"run_id": "run-1", "verdict": "RESEARCH_FAIL", "summary": "immutable"},
    )
    monkeypatch.setattr(web, "load_research_snapshot", lambda **kwargs: snapshot)
    response = client.get("/v/V-RESEARCH/deep-research.json")
    assert response.status_code == 200
    assert response.json()["report"]["summary"] == "immutable"
    assert response.json()["research_run_id"] == "run-1"


def test_lost_debit_response_is_refunded_by_run_id_before_retry(client, monkeypatch):
    seed_research()
    seen = []
    def committed_then_timeout(store, family, research_run_id):
        seen.append(research_run_id)
        wallet.consume_research_credit(store, family, research_run_id)
        raise wallet.WalletStoreUnavailable("response lost after commit")
    monkeypatch.setattr(web, "consume_research_credit", committed_then_timeout)
    monkeypatch.setattr(web, "run_research_pass", lambda *_: pytest.fail("provider must not start"))
    response = client.post("/v/V-RESEARCH/run")
    assert response.status_code == 503
    assert "allowance was restored" in response.text
    saved = state_store.load_state("V-RESEARCH")
    assert saved.metrics["research_run_id"] == seen[0]
    assert saved.metrics["research_run_status"] == "failed"
    assert wallet.load_wallet("local-user").wallet_credits == 3
    assert not web.limiter._events["research-hourly:local-user"]
    assert not web.limiter._events["research-rolling:local-user"]
    assert wallet.consume_research_credit(wallet.load_wallet("local-user"), "V-RESEARCH", seen[0])["error"] == "research_run_cancelled"
    monkeypatch.setattr(web, "consume_research_credit", wallet.consume_research_credit)
    monkeypatch.setattr(web, "run_research_pass", lambda *_: result())
    assert client.post("/v/V-RESEARCH/run", follow_redirects=False).status_code == 303
    assert wallet.load_wallet("local-user").wallet_credits == 2
    assert state_store.load_state("V-RESEARCH").metrics["research_run_id"] != seen[0]


def test_lost_quota_response_is_cancelled_without_charge(client, monkeypatch):
    seed_research()
    reserve = web.limiter.reserve_research
    def timeout(user_id, **kwargs):
        reserve(user_id, **kwargs)
        raise rate_limit.RateLimitUnavailable("lost response")
    monkeypatch.setattr(web.limiter, "reserve_research", timeout)
    response = client.post("/v/V-RESEARCH/run")
    assert response.status_code == 503
    assert wallet.load_wallet("local-user").wallet_credits == 3
    assert not web.limiter._events["research-hourly:local-user"]
    assert state_store.load_state("V-RESEARCH").metrics["research_run_status"] == "failed"


def test_failed_reconciliation_blocks_fresh_charges_and_recovers_same_run(client, monkeypatch):
    seed_research()
    monkeypatch.setattr(web, "run_research_pass", lambda *_: (_ for _ in ()).throw(web.ResearchUnavailable("down")))
    monkeypatch.setattr(web, "cancel_research_credit", lambda *_: (_ for _ in ()).throw(wallet.WalletStoreUnavailable("down")))
    first = client.post("/v/V-RESEARCH/run")
    assert first.status_code == 503
    saved = state_store.load_state("V-RESEARCH")
    assert saved.metrics["research_run_status"] == "reconciliation"
    assert wallet.load_wallet("local-user").wallet_credits == 2
    monkeypatch.setattr(web, "consume_research_credit", lambda *a, **kw: pytest.fail("must reconcile before a new debit"))
    assert client.post("/v/V-RESEARCH/run").status_code == 503
    assert state_store.load_state("V-RESEARCH").metrics["research_run_id"] == saved.metrics["research_run_id"]
    monkeypatch.setattr(web, "cancel_research_credit", wallet.cancel_research_credit)
    assert "allowance was restored" in client.post("/v/V-RESEARCH/run").text
    assert wallet.load_wallet("local-user").wallet_credits == 3


def test_lost_result_save_response_does_not_refund_delivered_research(client, monkeypatch):
    seed_research()
    monkeypatch.setattr(web, "run_research_pass", lambda *_: result())
    def save_then_timeout(venture_id, updated, **kwargs):
        state_store.save_state(venture_id, updated, **kwargs)
        if updated.metrics.get("last_research"):
            raise state_store.StateStoreUnavailable("lost save acknowledgement")
    monkeypatch.setattr(web, "save_state", save_then_timeout)
    response = client.post("/v/V-RESEARCH/run", follow_redirects=False)
    assert response.status_code == 303
    assert state_store.load_state("V-RESEARCH").metrics["research_run_status"] == "delivered"
    assert wallet.load_wallet("local-user").wallet_credits == 2
    assert len(web.limiter._events["research-hourly:local-user"]) == 1


def test_reconciliation_fences_a_delayed_result_save_before_refunding(client, monkeypatch):
    seed_research()
    delayed = []
    def provider(state):
        delayed.append(state.model_copy(deep=True))
        raise web.ResearchUnavailable("provider stopped")
    monkeypatch.setattr(web, "run_research_pass", provider)
    def refund_after_delayed_save(store, run_id):
        late = delayed[0]
        late.metrics["last_research"] = "RESEARCH_PASS"
        late.metrics["research_run_status"] = "delivered"
        with pytest.raises(state_store.StateConflictError):
            state_store.save_state("V-RESEARCH", late)
        return wallet.cancel_research_credit(store, run_id)
    monkeypatch.setattr(web, "cancel_research_credit", refund_after_delayed_save)
    assert client.post("/v/V-RESEARCH/run").status_code == 503
    assert wallet.load_wallet("local-user").wallet_credits == 3
    assert "last_research" not in state_store.load_state("V-RESEARCH").metrics


def test_simultaneous_research_posts_only_invoke_provider_once(client, monkeypatch):
    seed_research()
    entered, finish = Event(), Event()
    def provider(_):
        entered.set()
        assert finish.wait(5)
        return result()
    monkeypatch.setattr(web, "run_research_pass", provider)
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(client.post, "/v/V-RESEARCH/run", follow_redirects=False)
        assert entered.wait(5)
        try:
            second = client.post("/v/V-RESEARCH/run", follow_redirects=False)
            assert second.status_code == 409
            assert wallet.load_wallet("local-user").wallet_credits == 2
        finally:
            finish.set()
        assert first.result().status_code == 303
    assert len(web.limiter._events["research-hourly:local-user"]) == 1


@pytest.mark.parametrize("prior", ["RESEARCH_PIVOT", "RESEARCH_FAIL"])
def test_final_kill_wins_in_packet_page_artwork_and_filename(client, prior):
    state = seed_research()
    state.metrics["last_research"] = prior
    state.validation_decision = ValidationDecision.KILL
    state.phase = Phase.KILL
    state_store.save_state("V-RESEARCH", state)
    assert packet.public_gate_label(state) == "KILL"
    payload = client.get("/v/V-RESEARCH/packet.json")
    assert payload.json()["gate"]["storedDecision"] == "kill"
    assert payload.json()["gate"]["displayRecommendation"] == "KILL"
    assert "kill" in payload.headers["content-disposition"].lower()
    response = client.get("/v/V-RESEARCH")
    assert '/static/brand/gate-kill.jpg' in response.text
    assert '<strong>Kill</strong>' in response.text


@pytest.mark.parametrize("unarchive", [False, True])
def test_concurrent_routes_cannot_admit_four_live_roots(client, unarchive):
    for i in range(4 if unarchive else 2):
        state = SystemState(hypothesis=f"Local contractor workflow idea number {i}")
        ensure_validation_contract(state)
        if i > 1:
            archive_state(state)
        state_store.save_state(f"V-SLOT-{i}", state)
    def attempt(i):
        if unarchive:
            return client.post(f"/v/V-SLOT-{i}/unarchive", follow_redirects=False)
        return client.post("/new", data={"idea": f"A new scheduling offer for local shops number {i}"}, follow_redirects=False)
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(attempt, [2, 3]))
    assert sorted(response.status_code for response in responses) == [303, 409]
    assert slot_status(state_store.list_states())["used"] == 3


def buyer(i=1):
    return DirectValidationRecord(record_id=f"R-{i}", buyer_identifier=f"Buyer {i}", buyer_role="Owner",
                                  recent_real_example="Missed estimate last week", current_workaround="Spreadsheet",
                                  exact_quote="We forgot to follow up.")


def legacy_item(record, identity="E-LEGACY"):
    return EvidenceItem(evidence_id=identity, evidence_level=EvidenceLevel.DIRECT,
                        source_type="qualified_buyer_conversation", source_title=record.buyer_identifier,
                        raw_quote_or_fact=record.exact_quote)


def test_legacy_direct_link_is_backfilled_and_voided(client):
    record = buyer()
    state = SystemState(hypothesis="A contractor workflow", direct_validation_records=[record], evidence=[legacy_item(record)])
    state_store.save_state("V-LEGACY", state)
    response = client.post("/v/V-LEGACY/record/R-1/void", data={"reason": "This entry described the wrong buyer."}, follow_redirects=False)
    assert response.status_code == 303
    saved = state_store.load_state("V-LEGACY")
    assert saved.evidence_linkage_version == 1
    assert saved.direct_validation_records[0].evidence_id == "E-LEGACY"
    assert saved.evidence[0].origin_record_ids == ["R-1"]
    assert saved.evidence[0].voided_at == saved.direct_validation_records[0].voided_at
    assert not packet.build_evidence_packet("V-LEGACY", saved)["evidence"]["items"]


def test_ambiguous_legacy_direct_items_are_quarantined_and_manually_correctable(client):
    first = buyer()
    second = first.model_copy(update={"record_id": "R-2"})
    state = SystemState(hypothesis="A contractor workflow", direct_validation_records=[first, second], evidence=[legacy_item(first)])
    state_store.save_state("V-LEGACY", state)
    saved = state_store.load_state("V-LEGACY")
    assert saved.evidence[0].origin_record_ids == []
    payload = packet.build_evidence_packet("V-LEGACY", saved)["evidence"]
    assert payload["items"] == []
    assert len(payload["requiresReview"]) == 1
    assert '/v/V-LEGACY/evidence/E-LEGACY/void' in client.get("/v/V-LEGACY/history").text
    response = client.post("/v/V-LEGACY/evidence/E-LEGACY/void", data={"reason": "Duplicate legacy quote; retain the buyer record."}, follow_redirects=False)
    assert response.status_code == 303
    assert state_store.load_state("V-LEGACY").evidence[0].voided_at is not None


def test_legacy_shared_payment_keeps_other_active_origin():
    first = buyer().model_copy(update={"payment_status": "paid", "payment_amount": 99, "payment_reference": "receipt-123"})
    second = first.model_copy(update={"record_id": "R-2"})
    evidence = EvidenceItem(evidence_id="E-PAY", evidence_level=EvidenceLevel.PAYMENT, source_type="paid_pilot",
                            source_title=first.buyer_identifier, raw_quote_or_fact=audit_trail._payment_fact(first))
    state = SystemState(direct_validation_records=[first, second], evidence=[evidence])
    audit_trail.void_direct_evidence(state, first.record_id, "Duplicate follow-up, keep the original receipt.")
    assert evidence.origin_record_ids == ["R-1", "R-2"]
    assert evidence.voided_at is None
    audit_trail.void_direct_evidence(state, second.record_id, "The original receipt was entered incorrectly.")
    assert evidence.voided_at is not None


def test_legacy_mixed_timestamp_formats_require_review_instead_of_crashing():
    record = buyer()
    evidence = legacy_item(record)
    record.created_at = record.created_at.replace(tzinfo=None)
    state = SystemState(direct_validation_records=[record], evidence=[evidence])
    audit_trail.backfill_evidence_linkage(state)
    assert evidence.linkage_review_required is True
    assert evidence.origin_record_ids == []


def test_already_voided_legacy_record_does_not_reappear_as_active_evidence():
    record = buyer()
    evidence = legacy_item(record)
    record.voided_at = datetime.now(UTC)
    record.void_reason = "Buyer evidence was previously corrected."
    state = SystemState(direct_validation_records=[record], evidence=[evidence])
    audit_trail.backfill_evidence_linkage(state)
    assert evidence.voided_at is not None
    assert evidence.origin_record_ids == [record.record_id]
    assert packet.build_evidence_packet("V-LEGACY", state)["evidence"]["items"] == []


def test_oldest_buyer_correction_is_reachable_through_history_pages(client):
    state = SystemState(hypothesis="Local plumbers need a follow-up service", direct_validation_records=[buyer(i) for i in range(41)])
    ensure_validation_contract(state)
    state_store.save_state("V-HISTORY", state)
    assert 'href="/v/V-HISTORY/history"' in client.get("/v/V-HISTORY").text
    assert '?history_page=2' in client.get("/v/V-HISTORY/history").text
    assert '?history_page=3' in client.get("/v/V-HISTORY/history?history_page=2").text
    oldest = client.get("/v/V-HISTORY/history?history_page=3")
    assert '/v/V-HISTORY/record/R-0/void' in oldest.text
    assert client.post("/v/V-HISTORY/record/R-0/void", data={"reason": "Wrong buyer recorded in the oldest entry."}, follow_redirects=False).status_code == 303
    assert state_store.load_state("V-HISTORY").direct_validation_records[0].voided_at is not None


def test_home_uses_two_bulk_reads_and_pages_archives(client, monkeypatch):
    calls = []
    active = SystemState(hypothesis="Active venture")
    ensure_validation_contract(active)
    archives = [(f"V-ARCHIVE-{i}", archive_state(SystemState(hypothesis=f"Archived idea {i}"))) for i in range(21)]
    def bulk(**kwargs):
        calls.append(kwargs)
        return archives if kwargs["archived"] else [("V-ACTIVE", active)]
    monkeypatch.setattr(web, "list_states", bulk)
    monkeypatch.setattr(web, "load_state", lambda *a, **kw: pytest.fail("N+1 state read"))
    response = client.get("/")
    assert response.status_code == 200
    assert len(calls) == 2
    assert calls[1]["limit"] == 21
    assert 'Active validations: 1/3' in response.text
    assert 'archive_page=2' in response.text
    assert 'V-ARCHIVE-20' not in response.text


def test_wallet_rpc_replays_same_run_id_after_transport_failure(client, monkeypatch):
    monkeypatch.setenv("WALLET_BACKEND", "supabase")
    monkeypatch.setenv("SUPABASE_URL", "https://project.example")
    monkeypatch.setenv("SUPABASE_SECRET_KEY", "test-only")
    run_id = str(uuid.uuid4())
    requests = []
    def post(url, **kwargs):
        requests.append(kwargs["json"])
        assert url.endswith('/killgate_wallet_debit_once')
        if len(requests) == 1:
            raise httpx.ReadTimeout("lost response")
        return httpx.Response(200, json={"ok": True, "debit_id": 42, "source": "wallet", "duplicate": True})
    monkeypatch.setattr(wallet.httpx, "post", post)
    with pytest.raises(wallet.WalletStoreUnavailable):
        wallet.consume_research_credit(wallet.Wallet("user-1"), "V-ONE", run_id)
    assert wallet.consume_research_credit(wallet.Wallet("user-1"), "V-ONE", run_id)["debit_id"] == 42
    assert requests[0] == requests[1]
    assert requests[0]["p_research_run_id"] == run_id


def test_bulk_state_rows_use_database_revisions(client, monkeypatch):
    monkeypatch.setenv("STATE_BACKEND", "supabase")
    monkeypatch.setenv("SUPABASE_URL", "https://project.example")
    monkeypatch.setenv("SUPABASE_PUBLISHABLE_KEY", "test-publishable")
    calls = []
    def get(url, **kwargs):
        calls.append(kwargs)
        return httpx.Response(200, json=[{"id": "V-ONE", "revision": 7, "state": SystemState().model_dump(mode="json")}])
    monkeypatch.setattr(state_store.httpx, "get", get)
    rows = state_store.list_states(owner_id="user", access_token="test-session", archived=True, limit=21, offset=20)
    assert rows[0][1].storage_revision == 7
    assert len(calls) == 1
    assert calls[0]["params"]["select"] == "id,state,revision"
    assert calls[0]["params"]["offset"] == "20"


def test_bulk_loader_honors_a_smaller_postgrest_row_cap(client, monkeypatch):
    monkeypatch.setenv("STATE_BACKEND", "supabase")
    monkeypatch.setenv("SUPABASE_URL", "https://project.example")
    monkeypatch.setenv("SUPABASE_PUBLISHABLE_KEY", "test-publishable")
    def get(url, **kwargs):
        offset = int(kwargs["params"]["offset"])
        assert kwargs["headers"]["Prefer"] == "count=exact"
        return httpx.Response(200, json=[{"id": f"V-{offset}", "revision": 1, "state": {}}],
                              headers={"Content-Range": f"{offset}-{offset}/2"})
    monkeypatch.setattr(state_store.httpx, "get", get)
    assert len(state_store.list_states(owner_id="user", access_token="test-session")) == 2
