"""Deterministic hard-gate evaluation for direct customer evidence.

The LLM may summarize evidence, but it does not decide whether Boolean GO gates
are satisfied. This module enforces the locked Validation Contract in code.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

from app.models.state import DirectValidationRecord, SystemState, ValidationDecision
from app.services.validation_contract import (
    contract_matches_hypothesis,
    ensure_validation_contract,
)


@dataclass
class GateEvaluation:
    recommendation: ValidationDecision
    blockers: list[str] = field(default_factory=list)
    passed: list[str] = field(default_factory=list)
    conversations: int = 0
    strong_pain_count: int = 0
    strong_pain_ratio: float = 0.0
    price_positive_count: int = 0
    unverified_price_positive_count: int = 0
    paid_pilot_count: int = 0
    unverified_paid_count: int = 0
    reassessment_ceiling_reached: bool = False
    contradictions_reviewed: bool = False
    contract_matches: bool = True


def _is_paid(record: DirectValidationRecord) -> bool:
    return (
        record.payment_status == "paid"
        and record.payment_amount is not None
        and record.payment_amount > 0
        and _has_meaningful_payment_reference(record.payment_reference)
    )


def _has_concrete_nonzero_price(value: str) -> bool:
    """Recognize an actual price, not an arbitrary number such as "2 week trial"."""
    text = re.sub(r"\s+", " ", (value or "").strip().lower().replace(",", ""))
    if not text:
        return False

    number = r"(\d+(?:\.\d{1,2})?)"
    patterns = (
        rf"(?:[$€£¥]\s*){number}",
        rf"{number}\s*(?:usd|eur|gbp|cad|aud|dollars?|euros?|pounds?|bucks?)\b",
        rf"{number}\s*(?:/\s*|per\s+)(?:day|week|month|mo|year|yr)s?\b",
        rf"{number}\s*(?:daily|weekly|monthly|annually|yearly)\b",
    )
    for pattern in patterns:
        for match in re.finditer(pattern, text, flags=re.IGNORECASE):
            try:
                # Every pattern has exactly one capturing group: the numeric price.
                if float(match.group(1)) > 0:
                    return True
            except (ValueError, IndexError):
                continue

    # The field itself is explicitly a price field, so a bare numeric entry like
    # "99" or "99.00" is unambiguous. Mixed prose needs price syntax above.
    if re.fullmatch(r"\s*\d+(?:\.\d{1,2})?\s*", text):
        try:
            return float(text) > 0
        except ValueError:
            return False
    return False


def _has_meaningful_payment_reference(value: str) -> bool:
    reference = re.sub(r"\s+", " ", (value or "").strip())
    if len(reference) < 5:
        return False
    return reference.casefold() not in {
        "cash",
        "paid",
        "yes",
        "none",
        "n/a",
        "na",
        "receipt",
        "payment",
        "done",
    }


def _is_price_positive(record: DirectValidationRecord) -> bool:
    """A positive price signal only counts when a concrete non-zero price was tested."""
    return bool(
        record.price_positive
        and _has_concrete_nonzero_price(record.pilot_price_tested)
        and record.price_response.strip()
    )


def buyer_identity_key(value: str) -> str:
    """Normalize a user-entered buyer label so trivial casing/spacing cannot create fake uniqueness."""
    normalized = unicodedata.normalize("NFKC", value or "")
    return re.sub(r"\s+", " ", normalized.strip()).casefold()


def _is_qualified(record: DirectValidationRecord) -> bool:
    """Level-3 direct evidence must contain the contract's minimum real-world context."""
    return all(
        bool(value.strip())
        for value in (
            record.buyer_identifier,
            record.buyer_role,
            record.qualification_basis,
            record.recent_real_example,
            record.current_workaround,
        )
    )


def _qualified_groups(records: list[DirectValidationRecord]) -> dict[str, list[DirectValidationRecord]]:
    """Group immutable conversation/follow-up records by normalized buyer identity."""
    groups: dict[str, list[DirectValidationRecord]] = {}
    for record in records:
        if record.voided_at is not None or not _is_qualified(record):
            continue
        identifier = buyer_identity_key(record.buyer_identifier)
        if not identifier:
            continue
        groups.setdefault(identifier, []).append(record)
    return groups


def evaluate_validation_gate(state: SystemState) -> GateEvaluation:
    contract = ensure_validation_contract(state)
    human = contract.human_rules
    records = state.direct_validation_records
    qualified_groups = _qualified_groups(records)
    # Pain/price language is evaluated from the latest qualified interaction with each buyer.
    # Actual payments are durable economic evidence and may have arrived in an earlier/later follow-up.
    latest_records = [group[-1] for group in qualified_groups.values()]
    contract_matches = contract_matches_hypothesis(state)

    conversations = len(qualified_groups)
    strong_pain = sum(1 for record in latest_records if record.pain_strength == "strong")
    ratio = (strong_pain / conversations) if conversations else 0.0
    price_positive = sum(1 for record in latest_records if _is_price_positive(record))
    unverified_price_positive = sum(
        1 for record in latest_records if record.price_positive and not _is_price_positive(record)
    )
    paid = sum(1 for group in qualified_groups.values() if any(_is_paid(record) for record in group))
    unverified_paid = sum(
        1
        for group in qualified_groups.values()
        if not any(_is_paid(record) for record in group)
        and any(record.payment_status == "paid" for record in group)
    )
    qualified_history = [record for group in qualified_groups.values() for record in group]
    contradictions_reviewed = bool(qualified_history) and all(
        bool(record.objection_or_no_reason.strip()) for record in qualified_history
    )

    min_conversations = int(human["min_direct_conversations"])
    min_pain_ratio = float(human["min_strong_pain_ratio"])
    min_price_positive = int(human["min_price_positive_count"])
    min_paid = int(human["min_actual_paid_pilots"])
    max_before_reassessment = max(
        min_conversations, int(human.get("max_before_reassessment", 20))
    )
    reassessment_ceiling_reached = conversations >= max_before_reassessment

    passed: list[str] = []
    blockers: list[str] = []

    if contract_matches:
        passed.append("Locked Validation Contract matches the active hypothesis.")
    else:
        blockers.append("The hypothesis changed after the Validation Contract was locked; create a new pivot hypothesis and lock a new contract before proceeding.")

    if state.research_pass:
        passed.append("Research Qualification Gate passed.")
    else:
        blockers.append("Research Qualification Gate has not passed.")

    if conversations >= min_conversations:
        passed.append(f"{conversations} direct conversations recorded (minimum {min_conversations}).")
    else:
        blockers.append(f"Need {min_conversations - conversations} more qualified direct conversation(s).")
    if reassessment_ceiling_reached and paid < min_paid:
        blockers.append(
            f"Reassessment ceiling reached at {conversations} qualified buyers without clearing the {min_paid}-payment gate; do not keep interviewing the same hypothesis indefinitely."
        )

    if conversations and ratio >= min_pain_ratio:
        passed.append(f"Strong-pain rate is {ratio:.0%} (minimum {min_pain_ratio:.0%}).")
    else:
        blockers.append(f"Strong-pain rate is {ratio:.0%}; minimum is {min_pain_ratio:.0%}.")

    if price_positive >= min_price_positive or paid >= min_paid:
        passed.append(
            f"Price signal cleared ({price_positive} price-positive; {paid} paid pilot(s))."
        )
    else:
        blockers.append(
            f"Need {min_price_positive} price-positive buyers unless {min_paid} actual paid pilots are reached; currently {price_positive}/{paid}."
        )
    if unverified_price_positive:
        blockers.append(
            f"{unverified_price_positive} price-positive record(s) are not counted because a concrete pilot price and price reaction are both required."
        )

    if paid >= min_paid:
        passed.append(f"Payment gate passed with {paid} actual paid pilot(s).")
    else:
        blockers.append(f"Need {min_paid - paid} more actual paid pilot(s) or verifiable paid deposit(s).")
    if unverified_paid:
        blockers.append(f"{unverified_paid} record(s) marked paid are not counted because amount and payment evidence/reference are both required.")

    if contradictions_reviewed:
        passed.append("Every direct record includes an objection/no-priority field for contradiction review.")
    else:
        blockers.append("Record the objection, no-priority reason, or 'none stated' for every direct conversation.")

    all_go_gates = (
        contract_matches
        and state.research_pass
        and conversations >= min_conversations
        and ratio >= min_pain_ratio
        and (price_positive >= min_price_positive or paid >= min_paid)
        and paid >= min_paid
        and contradictions_reviewed
    )

    if all_go_gates:
        recommendation = ValidationDecision.GO
    elif not contract_matches or conversations < min_conversations or not state.research_pass:
        recommendation = ValidationDecision.CONTINUE_VALIDATION
    elif ratio < min_pain_ratio and paid >= min_paid:
        # Actual payment is stronger evidence than interview language. A low pain ratio
        # alongside real payments means the current ICP/problem framing is inconsistent,
        # not that the opportunity is proven dead.
        recommendation = ValidationDecision.PIVOT
    elif ratio < min_pain_ratio:
        recommendation = ValidationDecision.KILL
    elif reassessment_ceiling_reached and paid < min_paid:
        # Enough buyers have been tested. Continuing the unchanged hypothesis would
        # violate the locked reassessment ceiling; change the offer/ICP/price instead.
        recommendation = ValidationDecision.PIVOT
    elif price_positive < min_price_positive and paid < min_paid:
        # Problem signal exists but the tested commercial offer is weak.
        recommendation = ValidationDecision.PIVOT
    else:
        recommendation = ValidationDecision.CONTINUE_VALIDATION

    return GateEvaluation(
        recommendation=recommendation,
        blockers=blockers,
        passed=passed,
        conversations=conversations,
        strong_pain_count=strong_pain,
        strong_pain_ratio=ratio,
        price_positive_count=price_positive,
        unverified_price_positive_count=unverified_price_positive,
        paid_pilot_count=paid,
        unverified_paid_count=unverified_paid,
        reassessment_ceiling_reached=reassessment_ceiling_reached,
        contradictions_reviewed=contradictions_reviewed,
        contract_matches=contract_matches,
    )


def go_is_allowed(state: SystemState) -> bool:
    return evaluate_validation_gate(state).recommendation == ValidationDecision.GO
