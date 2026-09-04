from app.models.state import SystemState
from app.services import catalog, slots
from app.services.packet import build_evidence_packet, public_gate_label
from app.services.validation_contract import ensure_validation_contract


def test_catalog_defaults_are_the_play_console_ids(monkeypatch):
    for name in (
        "GOOGLE_PLAY_VENTURE_PASS_PRODUCT_ID",
        "GOOGLE_PLAY_EVIDENCE_RUN_PRODUCT_ID",
        "GOOGLE_PLAY_FOUNDER_PRO_PRODUCT_ID",
        "GOOGLE_PLAY_FOUNDER_TOPUP_PRODUCT_ID",
        "GOOGLE_PLAY_SUBSCRIPTION_PRODUCT_ID",
    ):
        monkeypatch.delenv(name, raising=False)
    ids = {row["kind"]: row["product_id"] for row in catalog.catalog_with_ids()}
    assert ids["venture_pass"] == "killgate_venture_pass"
    assert ids["evidence_run"] == "killgate_evidence_run"
    assert ids["subscription"] == "killgate_founder_pro"
    assert ids["founder_topup"] == "killgate_founder_topup"


def test_fourth_live_lock_is_blocked():
    rows = []
    for i in range(3):
        state = SystemState(hypothesis=f"Idea number {i} needs a real buyer and a price")
        ensure_validation_contract(state)
        rows.append((f"V-{i}", state))
    assert slots.slot_status(rows)["full"] is True
    assert slots.can_open_live_lock(rows) is False


def test_archive_frees_a_slot():
    rows = []
    for i in range(3):
        state = SystemState(hypothesis=f"Idea number {i} needs a real buyer and a price")
        ensure_validation_contract(state)
        rows.append((f"V-{i}", state))
    slots.archive_state(rows[0][1])
    assert slots.slot_status(rows)["used"] == 2
    assert slots.can_open_live_lock(rows) is True


def test_pivot_child_does_not_consume_a_slot():
    parent = SystemState(hypothesis="Parent idea for independent shops missing calls")
    ensure_validation_contract(parent)
    child = SystemState(hypothesis="Pivot to SMS intake for storm-damage roofers")
    ensure_validation_contract(child)
    child.metrics["pivot_parent_venture_id"] = "V-PARENT"
    rows = [("V-PARENT", parent), ("V-CHILD", child)]
    assert slots.slot_status(rows)["used"] == 1


def test_go_display_label_is_go_build():
    from app.models.state import ValidationDecision
    state = SystemState(hypothesis="Shops miss calls and will pay for a receptionist")
    state.validation_decision = ValidationDecision.GO
    assert public_gate_label(state) == "GO_BUILD"
    packet = build_evidence_packet("V-1", state)
    assert packet["gate"]["displayRecommendation"] == "GO_BUILD"
    assert "attestation" in packet


def test_customer_packet_keeps_evidence_requirements_without_internal_rules():
    state = SystemState(hypothesis="Shops miss calls and will pay for a receptionist")
    ensure_validation_contract(state)

    packet = build_evidence_packet("V-PRIVATE", state)
    serialized = str(packet)

    assert packet["packetVersion"] == "1.1"
    assert "validationPlan" in packet
    assert "buyerEvidenceRequirements" in packet["validationPlan"]
    assert packet["validationPlan"]["buyerEvidenceRequirements"]["minimumPricePositiveRecords"] == 4
    assert "evaluatorRecommendation" not in packet["gate"]
    assert "contract" not in packet
    for private_key in ("research_rules", "decision_rules", "hypothesis_fingerprint"):
        assert private_key not in serialized
