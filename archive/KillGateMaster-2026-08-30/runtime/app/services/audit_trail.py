"""Persist evidence and decision provenance instead of keeping only summary metrics."""

from __future__ import annotations

import uuid

from app.models.state import (
    DecisionRecord,
    DirectValidationRecord,
    EvidenceItem,
    EvidenceLevel,
    SystemState,
    ValidationDecision,
    utc_now,
)
from app.services.research import ResearchResult
from app.services.validation_gate import (
    GateEvaluation,
    _has_meaningful_payment_reference,
    buyer_identity_key,
)


def append_research_evidence(state: SystemState, result: ResearchResult) -> None:
    existing = {(item.source_url, item.raw_quote_or_fact) for item in state.evidence if item.source_url}
    for item in result.evidence_items:
        key = (item.url, item.claim)
        if key in existing:
            continue
        state.evidence.append(
            EvidenceItem(
                evidence_id=f"E-{uuid.uuid4().hex[:10].upper()}",
                evidence_level=EvidenceLevel.MARKET_FACT,
                source_type="public_research",
                raw_quote_or_fact=item.claim[:4000],
                source_title=item.source[:500],
                source_url=item.url[:2000],
                source_relevance=item.relevance,
                theme=item.theme,
                reliability="medium",
                supports_or_challenges=item.supports_or_challenges,
                linked_hypothesis_claim=state.hypothesis[:1000],
            )
        )
        existing.add(key)


def _payment_fact(record: DirectValidationRecord) -> str:
    return (
        f"Paid pilot received: ${record.payment_amount:.2f}; "
        f"reference: {record.payment_reference[:500]}"
    )


def backfill_evidence_linkage(state: SystemState) -> None:
    """Versioned, conservative upgrade for saved states predating source links.

    A direct item needs an exact quote, normalized buyer, source/level match,
    chronological consistency, and a one-to-one match. Ambiguous duplicates
    are quarantined for explicit review, never paired by a guess.
    """
    if state.evidence_linkage_version >= 1:
        return
    records = state.direct_validation_records
    for item in state.evidence:
        if item.origin_record_ids:
            continue
        candidates = []
        direct = item.source_type == "qualified_buyer_conversation" and item.evidence_level == EvidenceLevel.DIRECT
        payment = item.source_type == "paid_pilot" and item.evidence_level == EvidenceLevel.PAYMENT
        if not direct and not payment:
            continue
        for record in records:
            if buyer_identity_key(item.source_title) != buyer_identity_key(record.buyer_identifier[:500]):
                continue
            if direct:
                matches = (item.raw_quote_or_fact == (record.exact_quote or record.recent_real_example)[:4000]
                           and bool(record.created_at.tzinfo) == bool(item.accessed_at.tzinfo)
                           and record.created_at <= item.accessed_at
                           and (not record.evidence_id or record.evidence_id == item.evidence_id))
            else:
                matches = (record.payment_status == "paid" and record.payment_amount is not None
                           and record.payment_amount > 0 and _has_meaningful_payment_reference(record.payment_reference)
                           and item.raw_quote_or_fact == _payment_fact(record))
            if matches:
                candidates.append(record)
        matching_items = [other for other in state.evidence
                          if other.source_type == item.source_type and other.evidence_level == item.evidence_level
                          and buyer_identity_key(other.source_title) == buyer_identity_key(item.source_title)
                          and other.raw_quote_or_fact == item.raw_quote_or_fact]
        if not candidates or len(matching_items) != 1 or (direct and len(candidates) != 1):
            item.linkage_review_required = True
            item.linkage_review_reason = "Legacy buyer evidence could not be linked unambiguously. Review the original record and quote."
            continue
        item.origin_record_ids = [record.record_id for record in candidates]
        if direct:
            candidates[0].evidence_id = item.evidence_id
        if all(record.voided_at is not None for record in candidates):
            # This derived item is being corrected now; preserve any existing
            # correction, and avoid inventing an ordering for mixed legacy zones.
            item.voided_at = item.voided_at or utc_now()
            item.void_reason = item.void_reason or "Legacy linkage upgrade: all supporting buyer records were already corrected."
    state.evidence_linkage_version = 1


def append_direct_evidence(state: SystemState, record: DirectValidationRecord) -> None:
    if not record.evidence_id:
        record.evidence_id = f"E-{uuid.uuid4().hex[:10].upper()}"
    state.evidence.append(
        EvidenceItem(
            evidence_id=record.evidence_id,
            evidence_level=EvidenceLevel.DIRECT,
            source_type="qualified_buyer_conversation",
            raw_quote_or_fact=(record.exact_quote or record.recent_real_example)[:4000],
            source_title=record.buyer_identifier[:500],
            source_relevance="direct_buyer",
            theme="human_reality_check",
            reliability="high",
            supports_or_challenges="mixed",
            linked_hypothesis_claim=state.hypothesis[:1000],
            origin_record_ids=[record.record_id],
        )
    )
    if (
        record.payment_status == "paid"
        and record.payment_amount is not None
        and record.payment_amount > 0
        and _has_meaningful_payment_reference(record.payment_reference)
    ):
        payment_fact = _payment_fact(record)
        # A follow-up can repeat a previously entered receipt. Preserve the audit history
        # without creating duplicate Level-5 evidence for the same payment.
        existing_payment = next((
            item
            for item in state.evidence
            if item.voided_at is None
            and int(item.evidence_level) == int(EvidenceLevel.PAYMENT)
            and buyer_identity_key(item.source_title) == buyer_identity_key(record.buyer_identifier[:500])
            and item.raw_quote_or_fact == payment_fact
        ), None)
        if existing_payment is not None:
            if record.record_id not in existing_payment.origin_record_ids:
                existing_payment.origin_record_ids.append(record.record_id)
        else:
            state.evidence.append(
                EvidenceItem(
                    evidence_id=f"E-{uuid.uuid4().hex[:10].upper()}",
                    evidence_level=EvidenceLevel.PAYMENT,
                    source_type="paid_pilot",
                    raw_quote_or_fact=payment_fact,
                    source_title=record.buyer_identifier[:500],
                    source_relevance="economic_commitment",
                    theme="payment",
                    reliability="high",
                    supports_or_challenges="supports",
                    linked_hypothesis_claim=state.hypothesis[:1000],
                    origin_record_ids=[record.record_id],
                )
            )


def void_direct_evidence(
    state: SystemState,
    record_id: str,
    reason: str,
) -> DirectValidationRecord:
    """Soft-void a mistaken buyer record and every derived audit item it solely supports."""
    backfill_evidence_linkage(state)
    matches = [record for record in state.direct_validation_records if record.record_id == record_id]
    if not matches:
        raise LookupError("Evidence record was not found.")
    if len(matches) != 1:
        raise RuntimeError("Evidence record identifiers are ambiguous.")

    record = matches[0]
    if record.voided_at is not None:
        raise ValueError("Evidence record was already corrected.")

    cleaned_reason = " ".join(reason.split())[:500]
    if len(cleaned_reason) < 10:
        raise ValueError("A correction reason of at least 10 characters is required.")

    corrected_at = utc_now()
    record.voided_at = corrected_at
    record.void_reason = cleaned_reason

    records_by_id = {item.record_id: item for item in state.direct_validation_records}
    for item in state.evidence:
        direct_match = bool(record.evidence_id and item.evidence_id == record.evidence_id)
        linked_match = record.record_id in item.origin_record_ids
        if not (direct_match or linked_match):
            continue

        # One payment ledger item may be supported by multiple follow-ups. It
        # remains active while at least one linked source record remains active.
        active_link_remains = any(
            linked_id != record.record_id
            and linked_id in records_by_id
            and records_by_id[linked_id].voided_at is None
            for linked_id in item.origin_record_ids
        )
        if active_link_remains and not direct_match:
            continue
        item.voided_at = corrected_at
        item.void_reason = cleaned_reason

    return record


def append_decision(
    state: SystemState,
    decision: ValidationDecision,
    gate: GateEvaluation,
    *,
    rationale: str = "",
) -> None:
    state.decision_log.append(
        DecisionRecord(
            decision_id=f"D-{uuid.uuid4().hex[:10].upper()}",
            decision=decision,
            actor="human",
            gate_recommendation=gate.recommendation,
            gate_snapshot={
                "contract_matches": gate.contract_matches,
                "conversations": gate.conversations,
                "strong_pain_ratio": gate.strong_pain_ratio,
                "price_positive_count": gate.price_positive_count,
                "paid_pilot_count": gate.paid_pilot_count,
                "unverified_paid_count": gate.unverified_paid_count,
                "reassessment_ceiling_reached": gate.reassessment_ceiling_reached,
                "contradictions_reviewed": gate.contradictions_reviewed,
                "passed": list(gate.passed),
                "blockers": list(gate.blockers),
            },
            rationale=rationale[:2000],
        )
    )
