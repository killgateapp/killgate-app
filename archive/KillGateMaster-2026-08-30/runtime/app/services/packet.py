"""Attested evidence packet. A GO is a contract against this file."""
from __future__ import annotations

import re
from datetime import UTC, datetime

from app.models.state import SystemState
from app.services.validation_gate import evaluate_validation_gate


def slug_for_packet(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", (value or "").lower()).strip("-")[:48]
    return slug or "workspace"


def public_gate_label(state: SystemState) -> str:
    """Display label. Stored decision remains go / continue_validation / pivot / kill."""
    if state.validation_decision and state.validation_decision.value == "go":
        if str(state.metrics.get("sell_ready") or "").lower() in {"1", "true", "yes"}:
            return "GO_SELL"
        return "GO_BUILD"
    if state.validation_decision and state.validation_decision.value == "kill":
        return "KILL"
    if state.metrics.get("owner_stopped"):
        return "OWNER_STOPPED"
    if state.validation_decision:
        return state.validation_decision.value.upper()
    last = str(state.metrics.get("last_research") or "").upper()
    if last == "RESEARCH_PIVOT":
        return "PIVOT"
    if last == "RESEARCH_FAIL":
        return "CONTINUE"
    return "CONTINUE"


def build_evidence_packet(venture_id: str, state: SystemState) -> dict:
    from app.services.audit_trail import backfill_evidence_linkage

    backfill_evidence_linkage(state)
    gate = evaluate_validation_gate(state)
    contract = state.validation_contract
    validation_plan = None
    if contract:
        human = contract.human_rules
        validation_plan = {
            "status": contract.status,
            "lockedAt": contract.locked_at.isoformat(),
            "criticalAssumptions": list(contract.critical_assumptions),
            "evidencePolicy": {
                "accepted": list(contract.evidence_that_counts),
                "rejected": list(contract.evidence_that_does_not_count),
            },
            "buyerEvidenceRequirements": {
                "minimumQualifiedConversations": int(human.get("min_direct_conversations", 0)),
                "minimumStrongPainRatio": float(human.get("min_strong_pain_ratio", 0)),
                "minimumPricePositiveRecords": int(human.get("min_price_positive_count", 0)),
                "minimumPaidPilots": int(human.get("min_actual_paid_pilots", 0)),
            },
        }
    return {
        "packetVersion": "1.1",
        "product": "Killgate",
        "exportedAt": datetime.now(UTC).isoformat(),
        "ventureId": venture_id,
        "workspace": {
            "hypothesis": state.hypothesis,
            "phase": state.phase.value,
            "archivedAt": state.metrics.get("archived_at"),
            "passFamilyId": state.metrics.get("pass_family_id") or venture_id,
        },
        "gate": {
            "storedDecision": state.validation_decision.value if state.validation_decision else None,
            "displayRecommendation": public_gate_label(state),
            "blockers": gate.blockers,
            "passed": gate.passed,
            "conversations": gate.conversations,
            "strongPainRatio": gate.strong_pain_ratio,
            "pricePositiveCount": gate.price_positive_count,
            "paidPilotCount": gate.paid_pilot_count,
        },
        "validationPlan": validation_plan,
        "deepResearch": state.metrics.get("deep_research_report"),
        "evidence": {
            "buyers": [row.model_dump(mode="json") for row in state.direct_validation_records],
            "items": [
                item.model_dump(mode="json")
                for item in state.evidence
                if not item.voided_at and not item.linkage_review_required
            ],
            "requiresReview": [item.model_dump(mode="json") for item in state.evidence
                               if item.linkage_review_required and not item.voided_at],
        },
        "attestation": (
            "This packet is an attested snapshot of owner-entered evidence and "
            "a system-locked evidence standard. Killgate does not independently verify interviews, "
            "payments, or URLs."
        ),
    }
