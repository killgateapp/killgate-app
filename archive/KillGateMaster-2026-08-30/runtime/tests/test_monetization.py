from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app import web
from app.models.state import SystemState
from app.services import catalog, state_store, wallet
from app.services.research_brief import build_research_brief


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTH_MODE", "local")
    monkeypatch.setenv("STATE_BACKEND", "local")
    monkeypatch.setenv("BILLING_ENFORCED", "0")
    monkeypatch.setattr(state_store, "DATA_DIR", tmp_path / "ventures")
    monkeypatch.setattr(wallet, "WALLET_DIR", tmp_path / "wallets")
    with TestClient(web.app) as test_client:
        yield test_client



def test_catalog_hero_order_puts_pass_first_and_pro_before_topup():
    order = catalog.hero_cta_order()
    assert order[0] == "GOOGLE_PLAY_VENTURE_PASS_PRODUCT_ID"
    assert order[1] == "GOOGLE_PLAY_EVIDENCE_RUN_PRODUCT_ID"
    assert order[2] == "GOOGLE_PLAY_FOUNDER_PRO_PRODUCT_ID"
    assert order[3] == "GOOGLE_PLAY_FOUNDER_TOPUP_PRODUCT_ID"


def test_venture_pass_grants_three_unbound_credits(tmp_path, monkeypatch):
    monkeypatch.setattr(wallet, "WALLET_DIR", tmp_path)
    store = wallet.load_wallet("user-1")
    product = next(item for item in catalog.PRODUCTS if item.kind == "venture_pass")
    wallet.grant_product(store, product, product_id="kg_pass")
    store = wallet.load_wallet("user-1")
    assert len(store.passes) == 1
    assert store.passes[0].credits_remaining == 3
    assert store.passes[0].family_id == ""


def test_bound_pass_debits_before_wallet(tmp_path, monkeypatch):
    monkeypatch.setattr(wallet, "WALLET_DIR", tmp_path)
    store = wallet.load_wallet("user-1")
    product = next(item for item in catalog.PRODUCTS if item.kind == "venture_pass")
    wallet.grant_product(store, product, product_id="kg_pass")
    store = wallet.load_wallet("user-1")
    assert wallet.bind_pass(store, store.passes[0].pass_id, "V-FAMILY")
    store = wallet.load_wallet("user-1")
    store.wallet_credits = 4
    wallet.save_wallet(store)
    result = wallet.consume_research_credit(store, "V-FAMILY")
    assert result["source"] == "venture_pass"
    store = wallet.load_wallet("user-1")
    assert store.passes[0].credits_remaining == 2
    assert store.wallet_credits == 4



def test_undelivered_venture_pass_debit_is_refunded_once(tmp_path, monkeypatch):
    monkeypatch.setattr(wallet, "WALLET_DIR", tmp_path)
    store = wallet.load_wallet("user-refund-pass")
    product = next(item for item in catalog.PRODUCTS if item.kind == "venture_pass")
    wallet.grant_product(store, product, product_id="kg_pass", family_id="V-REFUND")
    store = wallet.load_wallet("user-refund-pass")
    debit = wallet.consume_research_credit(store, "V-REFUND")
    assert debit["ok"] is True
    assert debit.get("debit_id")
    assert wallet.load_wallet("user-refund-pass").passes[0].credits_remaining == 2

    restored = wallet.refund_research_credit(store, debit)
    assert restored["duplicate"] is False
    assert wallet.load_wallet("user-refund-pass").passes[0].credits_remaining == 3

    duplicate = wallet.refund_research_credit(store, debit)
    assert duplicate["duplicate"] is True
    assert wallet.load_wallet("user-refund-pass").passes[0].credits_remaining == 3


def test_undelivered_wallet_credit_is_refunded(tmp_path, monkeypatch):
    monkeypatch.setattr(wallet, "WALLET_DIR", tmp_path)
    store = wallet.load_wallet("user-refund-wallet")
    store.wallet_credits = 1
    wallet.save_wallet(store)
    debit = wallet.consume_research_credit(store, "V-WALLET")
    assert debit["source"] == "wallet"
    assert wallet.load_wallet("user-refund-wallet").wallet_credits == 0
    wallet.refund_research_credit(store, debit)
    assert wallet.load_wallet("user-refund-wallet").wallet_credits == 1

def test_brief_does_not_include_live_findings():
    state = SystemState(hypothesis="Independent shops miss calls and will pay $99/month for an AI receptionist.")
    brief = build_research_brief(state)
    blob = " ".join(str(value) for value in brief.values())
    assert brief["preview"] is True
    assert brief["sources_retrieved"] is False
    assert "GO" in brief["public_verdicts_impossible"]
    assert "http://" not in blob
    assert "https://" not in blob


def test_new_idea_lands_on_unpaid_brief(client):
    create = client.post("/new", data={"idea": "Shops miss calls and need a booked receptionist offer."}, follow_redirects=False)
    assert create.status_code == 303
    assert create.headers["location"].endswith("/brief")
    page = client.get(create.headers["location"])
    assert page.status_code == 200
    assert "FREE TEST-PLAN PREVIEW" in page.text
    assert "No sources have been retrieved" in page.text
    assert "Venture Pass" in page.text
    assert "Only real buyers can prove demand" in page.text


def test_pivot_inherits_pass_family(client):
    parent = SystemState(hypothesis="Independent roofers need a faster quoting workflow")
    parent.metrics["last_research"] = "RESEARCH_PIVOT"
    parent.metrics["pass_family_id"] = "V-ROOT"
    from app.services.validation_contract import ensure_validation_contract
    ensure_validation_contract(parent)
    state_store.save_state("KG-PARENT-FAMILY", parent)
    response = client.post(
        "/v/KG-PARENT-FAMILY/pivot",
        data={"idea": "Independent roofers need an SMS intake assistant that qualifies storm-damage leads before a quote."},
        follow_redirects=False,
    )
    child_id = response.headers["location"].split("/")[-1]
    child = state_store.load_state(child_id)
    assert child.metrics["pass_family_id"] == "V-ROOT"


def test_pivot_preserves_previous_deep_research_run_lineage(client):
    parent = SystemState(hypothesis="Independent roofers need a faster quoting workflow")
    parent.metrics["last_research"] = "RESEARCH_PIVOT"
    parent.metrics["research_run_id"] = "run-parent-123"
    parent.metrics["pass_family_id"] = "V-ROOT"
    from app.services.validation_contract import ensure_validation_contract
    ensure_validation_contract(parent)
    state_store.save_state("KG-PARENT-RUN", parent)
    response = client.post(
        "/v/KG-PARENT-RUN/pivot",
        data={"idea": "Independent roofers need an SMS intake assistant for storm-damage leads."},
        follow_redirects=False,
    )
    child_id = response.headers["location"].split("/")[-1]
    child = state_store.load_state(child_id)
    assert child.metrics["deep_research_previous_run_id"] == "run-parent-123"



def test_provider_failure_restores_paid_research_credit(client, monkeypatch):
    state = SystemState(hypothesis="Independent shops need a stricter paid validation workflow.")
    state.metrics["pass_family_id"] = "V-REFUND-INTEGRATION"
    state_store.save_state("KG-REFUND-INTEGRATION", state)

    product = next(item for item in catalog.PRODUCTS if item.kind == "venture_pass")
    store = wallet.load_wallet("local-user")
    wallet.grant_product(
        store,
        product,
        product_id="killgate_venture_pass",
        family_id="V-REFUND-INTEGRATION",
    )
    assert wallet.load_wallet("local-user").passes[0].credits_remaining == 3

    monkeypatch.setenv("BILLING_ENFORCED", "1")
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setattr(
        web,
        "run_research_pass",
        lambda *_: (_ for _ in ()).throw(web.ResearchUnavailable("provider down")),
    )

    response = client.post("/v/KG-REFUND-INTEGRATION/run", follow_redirects=False)

    assert response.status_code == 503
    assert "allowance was restored" in response.text
    assert wallet.load_wallet("local-user").passes[0].credits_remaining == 3


def test_extra_evidence_run_is_family_bound(tmp_path, monkeypatch):
    monkeypatch.setattr(wallet, "WALLET_DIR", tmp_path)
    store = wallet.load_wallet("user-evidence")
    product = next(item for item in catalog.PRODUCTS if item.kind == "evidence_run")
    with pytest.raises(ValueError, match="idea family"):
        wallet.grant_product(store, product, product_id="kg_evidence")
    wallet.grant_product(store, product, product_id="kg_evidence", family_id="V-SAME")
    store = wallet.load_wallet("user-evidence")
    assert len(store.passes) == 1
    assert store.passes[0].family_id == "V-SAME"
    assert store.passes[0].credits_remaining == 1
    assert wallet.family_credits(store, "V-OTHER") == 0


def test_founder_topup_requires_active_pro(tmp_path, monkeypatch):
    monkeypatch.setattr(wallet, "WALLET_DIR", tmp_path)
    store = wallet.load_wallet("user-topup")
    product = next(item for item in catalog.PRODUCTS if item.kind == "founder_topup")
    with pytest.raises(ValueError, match="Founder Pro"):
        wallet.grant_product(store, product, product_id="kg_topup")
    wallet.grant_product(store, product, product_id="kg_topup", active_subscription=True)
    assert wallet.load_wallet("user-topup").wallet_credits == 3


def test_founder_pro_refills_once_per_billing_period(tmp_path, monkeypatch):
    monkeypatch.setattr(wallet, "WALLET_DIR", tmp_path)
    store = wallet.load_wallet("user-pro")
    product = next(item for item in catalog.PRODUCTS if item.kind == "subscription")
    expiry1 = datetime.now(UTC) + timedelta(days=30)
    wallet.grant_product(
        store, product, product_id="kg_pro", purchase_hash="a" * 64,
        subscription_period_id="period-1", subscription_expires_at=expiry1, active_subscription=True,
    )
    store = wallet.load_wallet("user-pro")
    assert store.subscription_credits == 9
    store.subscription_credits = 4
    wallet.save_wallet(store)
    duplicate = wallet.grant_product(
        store, product, product_id="kg_pro", purchase_hash="a" * 64,
        subscription_period_id="period-1", subscription_expires_at=expiry1, active_subscription=True,
    )
    assert duplicate["duplicate"] is True
    assert wallet.load_wallet("user-pro").subscription_credits == 4
    expiry2 = datetime.now(UTC) + timedelta(days=60)
    wallet.grant_product(
        wallet.load_wallet("user-pro"), product, product_id="kg_pro", purchase_hash="a" * 64,
        subscription_period_id="period-2", subscription_expires_at=expiry2, active_subscription=True,
    )
    assert wallet.load_wallet("user-pro").subscription_credits == 9


def test_beta_access_is_free_but_expires_after_fourteen_days(tmp_path, monkeypatch):
    monkeypatch.setattr(wallet, "WALLET_DIR", tmp_path)
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("BILLING_ENFORCED", "1")
    monkeypatch.setenv("KILLGATE_BETA_ENABLED", "1")
    monkeypatch.setenv("KILLGATE_BETA_USER_IDS", "beta-user")
    monkeypatch.setenv(
        "KILLGATE_BETA_START_AT",
        (datetime.now(UTC) - timedelta(days=1)).isoformat(),
    )

    access = wallet.research_access("beta-user", "V-BETA")
    assert access["ok"] is True
    assert access["beta"] is True
    assert access["beta_max_runs"] == 9
    assert access["beta_duration_days"] == 14
    assert wallet.research_access("other-user", "V-BETA")["ok"] is False

    monkeypatch.setenv(
        "KILLGATE_BETA_START_AT",
        (datetime.now(UTC) - timedelta(days=15)).isoformat(),
    )
    assert wallet.research_access("beta-user", "V-BETA")["ok"] is False
