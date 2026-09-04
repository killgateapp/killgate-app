from urllib.parse import unquote

import pytest
from fastapi.testclient import TestClient

from app import web
from app.models.state import (
    DirectValidationRecord,
    Phase,
    SystemState,
    ValidationDecision,
)
from app.services import state_store
from app.services.live_search import SearchHit, classify_search_hits
from app.services.research import _heuristic_with_hits
from app.services.validation_contract import (
    ensure_validation_contract,
    hypothesis_fingerprint,
)
from app.services.validation_gate import evaluate_validation_gate, go_is_allowed

IDEA = (
    "QuoteRevive follows up on unclosed estimates for independent plumbers and HVAC companies "
    "and charges $99 per month."
)


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(state_store, "DATA_DIR", tmp_path / "ventures")
    with TestClient(web.app) as test_client:
        yield test_client


def _record(i: int, *, pain="strong", positive=True, paid=False, amount=0.0):
    return DirectValidationRecord(
        record_id=f"C-{i}",
        buyer_identifier=f"buyer-{i}",
        buyer_role="Owner",
        qualification_basis="Owns the service business and decides software purchases",
        recent_real_example=f"Lost quote follow-up last week #{i}",
        current_workaround="Manual spreadsheet and callbacks",
        pain_strength=pain,
        pilot_price_tested="$99/month",
        price_response="Price is acceptable" if positive else "Not at that price",
        price_positive=positive,
        payment_status="paid" if paid else "declined",
        payment_amount=amount if paid else None,
        payment_reference=f"receipt-{i}" if paid and amount > 0 else "",
        objection_or_no_reason="none stated" if positive else "low priority",
        exact_quote="I lose track of estimates.",
    )


def _go_ready_state() -> SystemState:
    state = SystemState(hypothesis=IDEA, research_pass=True)
    ensure_validation_contract(state)
    state.direct_validation_records = [
        _record(1, paid=True, amount=99),
        _record(2, paid=True, amount=99),
        _record(3),
        _record(4),
        _record(5, pain="moderate"),
        _record(6, pain="moderate"),
        _record(7, pain="weak", positive=False),
        _record(8, pain="weak", positive=False),
    ]
    return state


def test_new_venture_gets_system_locked_contract_before_research(client):
    create = client.post("/new", data={"idea": IDEA}, follow_redirects=False)
    assert create.status_code == 303
    location = unquote(create.headers["location"]).rstrip("/")
    assert location.endswith("/brief")
    venture_id = location.split("/")[-2]
    state = state_store.load_state(venture_id)

    assert state is not None
    assert state.research_pass is False
    assert state.validation_contract is not None
    assert state.validation_contract.status == "locked"
    assert state.validation_contract.source == "system"
    assert state.validation_contract.hypothesis_fingerprint

    page = client.get(create.headers["location"])
    assert "FREE TEST-PLAN PREVIEW" in page.text
    assert "Your idea is now locked for this validation" in page.text
    assert "pre-commit" not in page.text.lower()
    assert 'name="pre_commit' not in page.text.lower()
    assert "Fingerprint" not in page.text
    assert "Query families" not in page.text
    assert "Provisional mechanisms" not in page.text


def test_contract_is_not_silently_rebuilt_after_hypothesis_changes():
    state = SystemState(hypothesis=IDEA)
    original = ensure_validation_contract(state)
    original_fingerprint = original.hypothesis_fingerprint

    state.hypothesis = "A materially different SaaS for dental offices"
    same_object = ensure_validation_contract(state)
    gate = evaluate_validation_gate(state)

    assert same_object.hypothesis_fingerprint == original_fingerprint
    assert gate.contract_matches is False
    assert gate.recommendation == ValidationDecision.CONTINUE_VALIDATION
    assert go_is_allowed(state) is False
    assert any("hypothesis changed" in blocker.lower() for blocker in gate.blockers)


def test_research_thresholds_are_read_from_locked_contract():
    hits = classify_search_hits(
        IDEA,
        [
            SearchHit(title="Plumbers lose quotes", url="https://a.example/pain", snippet="Plumbers report lost jobs and frustrating missed follow-up problems.", query="q", query_theme="pain"),
            SearchHit(title="Manual callbacks", url="https://b.example/alt", snippet="HVAC owners currently use manual callbacks and spreadsheet workarounds.", query="q", query_theme="alternatives"),
            SearchHit(title="Follow-up pricing", url="https://c.example/price", snippet="Contractors pay $99 per month for a follow-up service.", query="q", query_theme="budget"),
        ],
    )
    state = SystemState(hypothesis=IDEA)
    contract = ensure_validation_contract(state)
    contract.research_rules["min_directly_relevant_public_sources"] = 4

    result = _heuristic_with_hits(state, hits)

    assert result.recommendation == "RESEARCH_FAIL"
    assert any("at least 4" in item.lower() for item in result.decision_rule_triggers)


def test_hard_gate_blocks_go_until_all_evidence_thresholds_pass():
    state = SystemState(hypothesis=IDEA, research_pass=True)
    ensure_validation_contract(state)
    state.direct_validation_records = [_record(i) for i in range(1, 9)]

    gate = evaluate_validation_gate(state)
    assert gate.recommendation == ValidationDecision.CONTINUE_VALIDATION
    assert gate.paid_pilot_count == 0
    assert go_is_allowed(state) is False

    state.direct_validation_records[0] = _record(1, paid=True, amount=99)
    state.direct_validation_records[1] = _record(2, paid=True, amount=99)
    gate = evaluate_validation_gate(state)

    assert gate.recommendation == ValidationDecision.GO
    assert gate.paid_pilot_count == 2
    assert go_is_allowed(state) is True


def test_paid_label_without_money_received_does_not_clear_payment_gate():
    state = _go_ready_state()
    state.direct_validation_records[0].payment_amount = 0
    state.direct_validation_records[0].payment_reference = ""
    state.direct_validation_records[1].payment_amount = 0
    state.direct_validation_records[1].payment_reference = ""

    gate = evaluate_validation_gate(state)

    assert gate.paid_pilot_count == 0
    assert gate.recommendation != ValidationDecision.GO


def test_low_interview_pain_with_real_payments_pivots_instead_of_killing():
    state = SystemState(hypothesis=IDEA, research_pass=True)
    ensure_validation_contract(state)
    state.direct_validation_records = [
        _record(1, pain="strong", paid=True, amount=99),
        _record(2, pain="strong", paid=True, amount=99),
        *[_record(i, pain="weak", positive=False) for i in range(3, 9)],
    ]

    gate = evaluate_validation_gate(state)

    assert gate.strong_pain_ratio < 0.30
    assert gate.paid_pilot_count == 2
    assert gate.recommendation == ValidationDecision.PIVOT


def test_web_manual_go_is_rejected_when_locked_gates_fail(client):
    state = SystemState(hypothesis=IDEA, research_pass=True)
    ensure_validation_contract(state)
    state_store.save_state("KG-TEST", state)

    response = client.post("/v/KG-TEST/approve", data={"decision": "GO"}, follow_redirects=False)
    assert response.status_code == 303
    saved = state_store.load_state("KG-TEST")

    assert saved.validation_decision is None
    assert saved.phase == Phase.VALIDATION
    assert "GO blocked" in saved.metrics["approval_error"]


def test_web_evidence_backed_go_can_advance_to_build(client):
    state = _go_ready_state()
    state_store.save_state("KG-GO", state)

    response = client.post("/v/KG-GO/approve", data={"decision": "GO"}, follow_redirects=False)
    assert response.status_code == 303
    saved = state_store.load_state("KG-GO")

    assert saved.validation_decision == ValidationDecision.GO
    assert saved.phase == Phase.BUILD
    assert len(saved.decision_log) == 1
    assert saved.decision_log[0].gate_recommendation == ValidationDecision.GO


def test_duplicate_buyer_cannot_inflate_conversation_count():
    state = SystemState(hypothesis=IDEA, research_pass=True)
    ensure_validation_contract(state)
    state.direct_validation_records = [_record(i) for i in range(1, 8)]
    duplicate = _record(99)
    duplicate.buyer_identifier = "BUYER-1"
    state.direct_validation_records.append(duplicate)

    gate = evaluate_validation_gate(state)

    assert len(state.direct_validation_records) == 8
    assert gate.conversations == 7
    assert gate.recommendation == ValidationDecision.CONTINUE_VALIDATION


def test_paid_status_requires_payment_reference_to_count():
    state = _go_ready_state()
    state.direct_validation_records[0].payment_reference = ""
    state.direct_validation_records[1].payment_reference = ""

    gate = evaluate_validation_gate(state)

    assert gate.paid_pilot_count == 0
    assert gate.unverified_paid_count == 2
    assert go_is_allowed(state) is False


def test_record_endpoint_persists_direct_and_payment_evidence(client):
    state = SystemState(hypothesis=IDEA, research_pass=True)
    ensure_validation_contract(state)
    state_store.save_state("KG-RECORD", state)

    response = client.post(
        "/v/KG-RECORD/record",
        data={
            "buyer_identifier": "Acme HVAC owner",
            "buyer_role": "Owner",
            "qualification_basis": "Owns the HVAC company and approves software purchases",
            "source_of_lead": "Trade group",
            "recent_real_example": "Three quotes went cold last month",
            "current_workaround": "Manual callbacks",
            "pain_strength": "strong",
            "pilot_price_tested": "$99/month",
            "price_response": "Yes at that price",
            "price_positive": "true",
            "payment_status": "paid",
            "payment_amount": "99",
            "payment_reference": "INV-1001",
            "objection_or_no_reason": "none stated",
            "exact_quote": "I forget to follow up when we get slammed.",
        },
        follow_redirects=False,
    )
    assert response.status_code == 303
    saved = state_store.load_state("KG-RECORD")
    assert len(saved.direct_validation_records) == 1
    assert len(saved.evidence) == 2
    assert sorted(int(item.evidence_level) for item in saved.evidence) == [3, 5]

    duplicate = client.post(
        "/v/KG-RECORD/record",
        data={
            "buyer_identifier": "ACME HVAC OWNER",
            "buyer_role": "Owner",
            "qualification_basis": "Same buyer",
            "recent_real_example": "Same example",
            "current_workaround": "Same workaround",
            "pain_strength": "strong",
            "price_response": "Same",
            "price_positive": "true",
            "payment_status": "declined",
            "payment_amount": "",
            "payment_reference": "",
            "objection_or_no_reason": "none stated",
            "exact_quote": "Same buyer again",
        },
        follow_redirects=False,
    )
    assert duplicate.status_code == 303
    saved = state_store.load_state("KG-RECORD")
    assert len(saved.direct_validation_records) == 2
    gate = evaluate_validation_gate(saved)
    assert gate.conversations == 1
    assert "Follow-up saved" in saved.metrics["last_evidence_note"]


def test_evidence_correction_preserves_history_and_removes_gate_credit(client):
    state = SystemState(hypothesis=IDEA, research_pass=True)
    ensure_validation_contract(state)
    state_store.save_state("KG-CORRECT", state)
    create = client.post(
        "/v/KG-CORRECT/record",
        data={
            "buyer_identifier": "Acme HVAC owner",
            "buyer_role": "Owner",
            "qualification_basis": "Owns the company and controls this software budget",
            "source_of_lead": "Trade group",
            "recent_real_example": "Three quotes went cold last month",
            "current_workaround": "Manual callbacks",
            "pain_strength": "strong",
            "pilot_price_tested": "$99/month",
            "price_response": "Yes at that price",
            "price_positive": "true",
            "payment_status": "paid",
            "payment_amount": "99",
            "payment_reference": "INV-1001",
            "objection_or_no_reason": "none stated",
            "exact_quote": "I forget to follow up when we get slammed.",
        },
        follow_redirects=False,
    )
    assert create.status_code == 303
    before = state_store.load_state("KG-CORRECT")
    record = before.direct_validation_records[0]
    assert evaluate_validation_gate(before).paid_pilot_count == 1

    corrected = client.post(
        f"/v/KG-CORRECT/record/{record.record_id}/void",
        data={"reason": "The invoice belonged to a different customer."},
        follow_redirects=False,
    )

    assert corrected.status_code == 303
    saved = state_store.load_state("KG-CORRECT")
    assert len(saved.direct_validation_records) == 1
    assert saved.direct_validation_records[0].voided_at is not None
    assert saved.direct_validation_records[0].void_reason == "The invoice belonged to a different customer."
    assert saved.direct_validation_records[0].payment_reference == "INV-1001"
    assert len(saved.evidence) == 2
    assert all(item.voided_at is not None for item in saved.evidence)
    assert all(item.void_reason for item in saved.evidence)
    gate = evaluate_validation_gate(saved)
    assert gate.conversations == 0
    assert gate.paid_pilot_count == 0

    page = client.get("/v/KG-CORRECT")
    assert "Corrected" in page.text
    assert "The invoice belonged to a different customer." in page.text


def test_evidence_correction_requires_a_reason_and_cannot_be_repeated(client):
    state = SystemState(hypothesis=IDEA, research_pass=True)
    ensure_validation_contract(state)
    record = _record(1)
    state.direct_validation_records = [record]
    state_store.save_state("KG-CORRECTION-GUARD", state)

    short = client.post(
        f"/v/KG-CORRECTION-GUARD/record/{record.record_id}/void",
        data={"reason": "mistake"},
    )
    assert short.status_code == 409
    assert state_store.load_state("KG-CORRECTION-GUARD").direct_validation_records[0].voided_at is None

    first = client.post(
        f"/v/KG-CORRECTION-GUARD/record/{record.record_id}/void",
        data={"reason": "This was recorded against the wrong buyer."},
        follow_redirects=False,
    )
    assert first.status_code == 303
    repeated = client.post(
        f"/v/KG-CORRECTION-GUARD/record/{record.record_id}/void",
        data={"reason": "Trying to change the correction a second time."},
    )
    assert repeated.status_code == 409


def test_correction_withdraws_go_when_locked_gate_no_longer_passes(client):
    state = _go_ready_state()
    state_store.save_state("KG-GO-CORRECTION", state)
    approved = client.post(
        "/v/KG-GO-CORRECTION/approve",
        data={"decision": "GO"},
        follow_redirects=False,
    )
    assert approved.status_code == 303
    approved_state = state_store.load_state("KG-GO-CORRECTION")
    paid_record = approved_state.direct_validation_records[0]

    corrected = client.post(
        f"/v/KG-GO-CORRECTION/record/{paid_record.record_id}/void",
        data={"reason": "The reported payment was never actually received."},
        follow_redirects=False,
    )

    assert corrected.status_code == 303
    saved = state_store.load_state("KG-GO-CORRECTION")
    assert saved.validation_decision is None
    assert saved.phase == Phase.VALIDATION
    assert len(saved.decision_log) == 1
    assert saved.decision_log[0].decision == ValidationDecision.GO
    assert "prior GO was withdrawn" in saved.metrics["approval_error"]
    assert go_is_allowed(saved) is False


def test_followup_payment_counts_without_inflating_unique_buyer_count():
    state = SystemState(hypothesis=IDEA, research_pass=True)
    ensure_validation_contract(state)
    first = _record(1, paid=False, amount=0)
    first.payment_status = "committed"
    followup = _record(99, paid=True, amount=99)
    followup.buyer_identifier = "  BUYER-1  "
    state.direct_validation_records = [first, followup]

    gate = evaluate_validation_gate(state)

    assert gate.conversations == 1
    assert gate.paid_pilot_count == 1


def test_buyer_identity_normalizes_case_unicode_and_internal_whitespace():
    state = SystemState(hypothesis=IDEA, research_pass=True)
    ensure_validation_contract(state)
    first = _record(1)
    first.buyer_identifier = "Acme   HVAC Owner"
    second = _record(2)
    second.buyer_identifier = "ＡＣＭＥ HVAC OWNER"  # full-width characters normalize with NFKC
    state.direct_validation_records = [first, second]

    assert evaluate_validation_gate(state).conversations == 1


def test_price_positive_requires_concrete_tested_price():
    state = _go_ready_state()
    for record in state.direct_validation_records[:4]:
        record.payment_status = "declined"
        record.payment_amount = None
        record.payment_reference = ""
        record.price_positive = True
        record.pilot_price_tested = ""
    # remove paid-pilot bypass as well
    state.direct_validation_records[0].payment_status = "declined"
    state.direct_validation_records[1].payment_status = "declined"

    gate = evaluate_validation_gate(state)

    assert gate.price_positive_count < 4
    assert gate.unverified_price_positive_count >= 4
    assert gate.recommendation != ValidationDecision.GO
    assert any("concrete pilot price" in blocker for blocker in gate.blockers)


def test_incomplete_direct_record_does_not_count_as_qualified_conversation():
    state = SystemState(hypothesis=IDEA, research_pass=True)
    ensure_validation_contract(state)
    record = _record(1)
    record.current_workaround = ""
    state.direct_validation_records = [record]

    gate = evaluate_validation_gate(state)

    assert gate.conversations == 0
    assert gate.recommendation == ValidationDecision.CONTINUE_VALIDATION


def test_record_endpoint_rejects_whitespace_only_required_evidence(client):
    state = SystemState(hypothesis=IDEA, research_pass=True)
    ensure_validation_contract(state)
    state_store.save_state("KG-BLANK", state)

    response = client.post(
        "/v/KG-BLANK/record",
        data={
            "buyer_identifier": "Buyer A",
            "buyer_role": "Owner",
            "qualification_basis": "Owner can buy",
            "recent_real_example": "   ",
            "current_workaround": "Spreadsheet",
            "pain_strength": "strong",
            "pilot_price_tested": "$99",
            "price_response": "Yes",
            "price_positive": "true",
            "payment_status": "declined",
            "payment_amount": "",
            "payment_reference": "",
            "objection_or_no_reason": "none stated",
            "exact_quote": "Need this",
        },
        follow_redirects=False,
    )

    assert response.status_code == 400
    saved = state_store.load_state("KG-BLANK")
    assert saved.direct_validation_records == []


def test_research_noop_after_pass_does_not_consume_quota(client, monkeypatch):
    state = SystemState(hypothesis=IDEA, research_pass=True)
    ensure_validation_contract(state)
    state_store.save_state("KG-PASSED", state)
    monkeypatch.setattr(
        web.limiter,
        "allow_research",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("quota must not be consumed")),
    )

    response = client.post("/v/KG-PASSED/run", follow_redirects=False)

    assert response.status_code == 303


def test_final_decision_cannot_be_rewritten(client):
    state = _go_ready_state()
    state_store.save_state("KG-FINAL", state)
    first = client.post("/v/KG-FINAL/approve", data={"decision": "GO"}, follow_redirects=False)
    assert first.status_code == 303

    rewrite = client.post("/v/KG-FINAL/approve", data={"decision": "KILL"}, follow_redirects=False)
    assert rewrite.status_code == 409
    saved = state_store.load_state("KG-FINAL")
    assert saved.validation_decision == ValidationDecision.GO
    assert saved.phase == Phase.BUILD
    assert len(saved.decision_log) == 1


def test_nonfinal_gate_recommendations_cannot_be_accepted_as_final_decisions(client):
    state = SystemState(hypothesis=IDEA, research_pass=True)
    ensure_validation_contract(state)
    state_store.save_state("KG-NONFINAL", state)

    response = client.post(
        "/v/KG-NONFINAL/approve",
        data={"decision": "PIVOT"},
        follow_redirects=False,
    )

    assert response.status_code == 400
    saved = state_store.load_state("KG-NONFINAL")
    assert saved.validation_decision is None
    assert saved.decision_log == []


def test_multiple_paid_followups_from_same_buyer_count_as_one_paid_buyer():
    state = SystemState(hypothesis=IDEA, research_pass=True)
    ensure_validation_contract(state)
    first = _record(1, paid=True, amount=99)
    second = _record(2, paid=True, amount=199)
    second.buyer_identifier = "BUYER-1"
    state.direct_validation_records = [first, second]

    gate = evaluate_validation_gate(state)

    assert gate.conversations == 1
    assert gate.paid_pilot_count == 1


def test_locked_reassessment_ceiling_prevents_endless_continue_without_payment():
    state = SystemState(hypothesis=IDEA, research_pass=True)
    contract = ensure_validation_contract(state)
    max_checks = int(contract.human_rules["max_before_reassessment"])
    state.direct_validation_records = [
        _record(i, pain="strong", positive=True, paid=False)
        for i in range(1, max_checks + 1)
    ]

    gate = evaluate_validation_gate(state)

    assert gate.conversations == max_checks
    assert gate.price_positive_count >= int(contract.human_rules["min_price_positive_count"])
    assert gate.paid_pilot_count == 0
    assert gate.reassessment_ceiling_reached is True
    assert gate.recommendation == ValidationDecision.PIVOT
    assert any("do not keep interviewing" in blocker for blocker in gate.blockers)


def test_free_or_nonnumeric_offer_never_counts_as_price_positive():
    state = SystemState(hypothesis=IDEA, research_pass=True)
    ensure_validation_contract(state)
    records = [_record(i, positive=True) for i in range(1, 9)]
    for record in records:
        record.pilot_price_tested = "free pilot"
    state.direct_validation_records = records

    gate = evaluate_validation_gate(state)

    assert gate.price_positive_count == 0
    assert gate.unverified_price_positive_count == 8


def test_completed_negative_research_cannot_be_rerolled(client, monkeypatch):
    state = SystemState(hypothesis="Independent roofers need a faster quoting workflow")
    state.metrics["last_research"] = "RESEARCH_FAIL"
    state.metrics["last_research_plain"] = "The locked public-research gate did not clear."
    state_store.save_state("KG-NO-REROLL", state)

    monkeypatch.setattr(
        web.limiter,
        "reserve_research",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("quota must not be touched")),
    )
    monkeypatch.setattr(
        web,
        "run_research_pass",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("research must not rerun")),
    )

    response = client.post("/v/KG-NO-REROLL/run", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/v/KG-NO-REROLL"


def test_negative_research_can_start_materially_different_pivot_with_fresh_contract(client):
    parent = SystemState(hypothesis="Independent roofers need a faster quoting workflow")
    ensure_validation_contract(parent)
    parent.metrics["last_research"] = "RESEARCH_PIVOT"
    parent.metrics["last_research_plain"] = "The offer needs a different workflow."
    state_store.save_state("KG-PARENT", parent)

    response = client.post(
        "/v/KG-PARENT/pivot",
        data={"idea": "Independent roofers need an SMS intake assistant that qualifies storm-damage leads before a quote."},
        follow_redirects=False,
    )
    assert response.status_code == 303
    child_id = response.headers["location"].split("/")[-1]
    child = state_store.load_state(child_id)
    assert child is not None
    assert child.metrics["pivot_parent_venture_id"] == "KG-PARENT"
    assert child.validation_contract is not None
    assert child.validation_contract.hypothesis_fingerprint == hypothesis_fingerprint(child.hypothesis)
    assert child.validation_contract.hypothesis_fingerprint != parent.validation_contract.hypothesis_fingerprint
    assert child.research_pass is False
    assert child.direct_validation_records == []


def test_pivot_rejects_same_normalized_hypothesis(client):
    parent = SystemState(hypothesis="Independent roofers need a faster quoting workflow")
    ensure_validation_contract(parent)
    parent.metrics["last_research"] = "RESEARCH_PIVOT"
    state_store.save_state("KG-SAME-PIVOT", parent)

    response = client.post(
        "/v/KG-SAME-PIVOT/pivot",
        data={"idea": "  INDEPENDENT   ROOFERS need a faster quoting workflow  "},
        follow_redirects=False,
    )
    assert response.status_code == 400
    assert "materially change" in response.text


def test_duration_number_does_not_masquerade_as_price():
    state = SystemState(hypothesis=IDEA, research_pass=True)
    ensure_validation_contract(state)
    records = [_record(i, positive=True) for i in range(1, 9)]
    for record in records:
        record.pilot_price_tested = "2 week trial"
        record.price_response = "Sounds fine"
    state.direct_validation_records = records
    gate = evaluate_validation_gate(state)
    assert gate.price_positive_count == 0
    assert gate.unverified_price_positive_count == 8


def test_real_price_formats_still_count():
    prices = ["$99", "99", "99/month", "99 per month", "99 USD", "99 monthly"]
    for index, price in enumerate(prices, 1):
        record = _record(index, positive=True)
        record.pilot_price_tested = price
        record.price_response = "yes"
        state = SystemState(hypothesis=IDEA, research_pass=True, direct_validation_records=[record])
        gate = evaluate_validation_gate(state)
        assert gate.price_positive_count == 1, price


def test_placeholder_payment_reference_never_counts_as_level_five():
    state = SystemState(hypothesis=IDEA, research_pass=True)
    ensure_validation_contract(state)
    records = [_record(i, paid=True, amount=99.0) for i in range(1, 9)]
    records[0].payment_reference = "cash"
    records[1].payment_reference = "paid"
    state.direct_validation_records = records
    gate = evaluate_validation_gate(state)
    assert gate.paid_pilot_count == 6
    assert gate.unverified_paid_count == 2


def test_research_reservation_is_released_if_stale_state_prevents_persist(client, monkeypatch):
    from types import SimpleNamespace

    from app.services.rate_limit import ResearchReservation

    state = SystemState(hypothesis="Independent mechanics need a reliable missed-call intake assistant")
    ensure_validation_contract(state)
    state_store.save_state("KG-RACE", state)

    reservation = ResearchReservation("local:test", local_timestamp=123.0)
    released = []
    monkeypatch.setattr(web.limiter, "allow", lambda *args, **kwargs: True)
    monkeypatch.setattr(web.limiter, "reserve_research", lambda *args, **kwargs: reservation)
    monkeypatch.setattr(web.limiter, "release_research_run", lambda user_id, run_id: released.append((user_id, run_id)))
    monkeypatch.setattr(
        web,
        "run_research_pass",
        lambda _state: SimpleNamespace(
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
        ),
    )
    def conflict_on_result(venture_id, updated, **kwargs):
        if updated.metrics.get("last_research"):
            raise state_store.StateConflictError("stale")
        return state_store.save_state(venture_id, updated, **kwargs)

    monkeypatch.setattr(web, "save_state", conflict_on_result)

    response = client.post("/v/KG-RACE/run", follow_redirects=False)

    assert response.status_code == 503
    assert len(released) == 1
    assert released[0][1] == state_store.load_state("KG-RACE").metrics["research_run_id"]


def test_feasibility_gate_blocks_buyer_stage_until_pass_is_recorded(client):
    state = SystemState(hypothesis="Collision shops pay $249/month for pre-teardown supplement prediction.")
    ensure_validation_contract(state)
    state.metrics["last_research"] = "FEASIBILITY_REQUIRED"
    state.metrics["last_research_plain"] = "Pain and spend are real enough to continue, but the load-bearing prediction capability is unproven."
    state.metrics["feasibility_status"] = "pending"
    state.metrics["last_feasibility_test"] = {
        "capability": "Pre-teardown omission prediction",
        "why_load_bearing": "The value proposition collapses if the signal is absent.",
        "decision_time_inputs": ["initial estimate", "photos"],
        "later_ground_truth": "post-teardown supplement",
        "metrics": ["capture rate", "false-positive rate"],
        "baselines": ["human estimator"],
        "pass_thresholds": ["capture >= 50%"],
        "fail_thresholds": ["capture < 30%"],
    }
    state_store.save_state("KG-FEAS", state)

    before = client.get("/v/KG-FEAS")
    assert before.status_code == 200
    assert "CRITICAL CAPABILITY TEST" in before.text
    assert "BUYER PROOF" not in before.text

    response = client.post(
        "/v/KG-FEAS/feasibility",
        data={
            "result": "PASS",
            "evidence_reference": "retrospective-run-001",
            "notes": "Locked thresholds cleared on the held-out repair set.",
        },
        follow_redirects=False,
    )
    assert response.status_code == 303
    saved = state_store.load_state("KG-FEAS")
    assert saved is not None
    assert saved.research_pass is True
    assert saved.metrics["feasibility_status"] == "passed"
    assert saved.metrics["feasibility_evidence_reference"] == "retrospective-run-001"

    after = client.get("/v/KG-FEAS")
    assert after.status_code == 200
    assert "BUYER PROOF" in after.text


def test_workspace_explains_research_result_without_internal_analysis_details(client):
    state = SystemState(hypothesis="Mobile groomers need a better last-minute booking workflow")
    ensure_validation_contract(state)
    state.metrics.update(
        {
            "last_research": "RESEARCH_PASS",
            "last_research_plain": "Public evidence supports moving to direct buyer testing.",
            "last_supporting": ["Independent groomers describe costly schedule gaps."],
            "last_disconfirming": ["Some operators already use general scheduling tools."],
            "last_decision_rules": ["private exact trigger"],
            "last_confidence": 0.8123,
            "evaluator_notes": "private evaluator explanation",
            "last_mechanism_scoreboard": [{"mechanism": "private method"}],
            "search_hit_count": 12,
            "direct_source_count": 5,
            "independent_domain_count": 3,
        }
    )
    state_store.save_state("KG-PLAIN", state)

    page = client.get("/v/KG-PLAIN")

    assert page.status_code == 200
    assert "Public evidence supports buyer testing" in page.text
    assert "Sources used in this result" not in page.text
    assert "Why Killgate reached this result" in page.text
    for private_text in (
        "RESEARCH_PASS",
        "private exact trigger",
        "81%",
        "private evaluator explanation",
        "Mechanism scoreboard",
        "private method",
    ):
        assert private_text not in page.text
