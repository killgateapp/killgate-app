"""System-generated, locked validation contract for each Killgate venture.

The founder does not define the basic kill/pass rules. Killgate creates the
rules before research begins and persists them with the venture so the bar
cannot silently move after evidence arrives.
"""

from __future__ import annotations

import hashlib
import re
from typing import Any

from app.models.state import SystemState, ValidationContract

CONTRACT_VERSION = "1.5"


def hypothesis_fingerprint(hypothesis: str) -> str:
    normalized = re.sub(r"\s+", " ", hypothesis.strip().lower())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:16]


def _extract_stated_price(hypothesis: str) -> str:
    match = re.search(
        r"\$\s*\d+(?:\.\d{1,2})?(?:\s*(?:-|–|to)\s*\$?\s*\d+(?:\.\d{1,2})?)?"
        r"(?:\s*(?:(?:per|/)\s*(?:month|mo|year|yr)|monthly|annually))?",
        hypothesis,
        re.IGNORECASE,
    )
    return re.sub(r"\s+", " ", match.group(0)).strip() if match else "Not stated"


def build_validation_contract(state: SystemState) -> ValidationContract:
    """Create the default locked decision contract before evidence is collected."""
    price = _extract_stated_price(state.hypothesis)

    critical_assumptions: list[str] = [
        "A narrow, identifiable buyer experiences the stated problem in real life.",
        "The problem is frequent, costly, risky, frustrating, or urgent enough to change behavior.",
        "The buyer already uses a workaround, alternative, budget, or other resource to address the job.",
        "The proposed offer is meaningfully better than the buyer's current alternative on a dimension they value.",
        "A reachable buyer can authorize or influence a purchase.",
        "The economics can support the proposed price and a realistic acquisition path.",
    ]
    if price != "Not stated":
        critical_assumptions.append(f"Qualified buyers will accept a real paid pilot around the stated price ({price}).")
    else:
        critical_assumptions.append("A concrete pilot price can be stated before direct buyer validation begins.")

    return ValidationContract(
        contract_version=CONTRACT_VERSION,
        status="locked",
        source="system",
        hypothesis_fingerprint=hypothesis_fingerprint(state.hypothesis),
        critical_assumptions=critical_assumptions,
        evidence_that_counts=[
            "Level 1: verified market facts such as competitor pricing, regulations, and documented market constraints.",
            "Level 2: observed real-user behavior or language from public sources, deduplicated and provenance-linked.",
            "Level 3: direct conversations with qualified buyers, including recent real examples and actual workarounds.",
            "Level 4: concrete commitments that cost the buyer something meaningful in time, access, reputation, or process.",
            "Level 5: completed payment or verifiable paid-pilot deposit.",
        ],
        evidence_that_does_not_count=[
            "AI personas, simulations, generated survey answers, or model speculation.",
            "The founder's own claims about demand, market size, urgency, or willingness to pay.",
            "Likes, compliments, waitlist clicks, or generic 'sounds useful' reactions by themselves.",
            "Hypothetical 'I would pay' statements without a real offer and an observable commitment.",
            "Duplicate, syndicated, context-free, or topically irrelevant sources.",
        ],
        research_rules={
            "min_directly_relevant_public_sources": 3,
            "min_independent_domains": 2,
            "require_problem_evidence": True,
            "require_current_behavior_or_alternative_evidence": True,
            "require_budget_or_spend_proxy_for_pass": True,
            "require_disconfirming_search": True,
            "min_source_backed_supporting_claims": 2,
            "min_disconfirming_or_constraint_findings": 2,
            # Deep Research's public-observation scorecard is stronger than
            # the low-cost relevance pre-gate and is enforced only by the
            # feature-flagged deep pipeline.
            "min_observed_user_evidence_items": 30,
            "min_independent_observed_voices": 15,
            "min_observed_communities": 3,
            "require_mechanism_scoreboard": True,
            "require_feasibility_gate_for_load_bearing_capability": True,
            "research_pass_meaning": "Worth direct buyer validation; never permission to build.",
        },
        human_rules={
            "min_direct_conversations": 8,
            "default_target_conversations": "8–12",
            "max_before_reassessment": 20,
            "min_strong_pain_ratio": 0.30,
            "min_price_positive_count": 4,
            "min_actual_paid_pilots": 2,
            "require_unique_qualified_buyers": True,
            "require_payment_evidence_reference": True,
            "require_recent_real_examples": True,
            "require_objections_or_no_priority_feedback_recorded": True,
        },
        decision_rules={
            "FEASIBILITY_REQUIRED": [
                "Public evidence supports a real problem, alternatives, and spend signal, but willingness-to-pay depends on an unproven load-bearing technical capability.",
                "Ordinary buyer-price interviews stay blocked until a pre-registered capability test passes.",
                "The capability test must lock decision-time inputs, later ground truth, metrics, baselines, and pass/fail thresholds before it is run.",
            ],
            "GO": [
                "Research Qualification Gate passed.",
                "At least 8 unique qualified direct-buyer conversations are recorded; duplicate buyers cannot inflate the count.",
                "At least 30% show strong repeated pain backed by a recent real example.",
                "At least 4 qualified buyers are price-positive unless 2 actual paid pilots already exist.",
                "At least 2 actual paid pilots or verifiable paid deposits exist, each with a received amount and payment evidence/reference.",
                "Contradictory, negative, and no-priority evidence has been recorded and weighed.",
            ],
            "CONTINUE_VALIDATION": [
                "The underlying problem/offer still has credible signal, but one or more required gates remain genuinely unresolved.",
                "The next experiment is specific, evidence-seeking, and does not silently lower a locked threshold.",
            ],
            "PIVOT": [
                "Problem evidence is credible but the tested customer, offer, workflow, positioning, channel, or price is contradicted.",
                "A pivot creates a new hypothesis and therefore a new locked validation contract before new evidence is gathered.",
            ],
            "KILL": [
                "Direct evidence shows the target buyer does not experience meaningful recurring pain or does not prioritize the job.",
                "Adequate alternatives solve the job well enough that the proposed product lacks a defensible improvement.",
                "After sufficient qualified testing, willingness to commit/pay remains below the locked threshold without a credible narrower hypothesis.",
                "A fatal legal, platform, trust, technical, or economic constraint makes the opportunity commercially unattractive.",
            ],
        },
        notes=[
            "Killgate v1.5: mechanisms must be split and classified as core/supporting plus KEEP/TEST/REMOVE_DEFER/CONTRADICTED before a research verdict is accepted.",
            "A commodity supporting or downstream-bundled mechanism does not force a commercial pivot when removing it leaves the locked willingness-to-pay sentence unchanged.",
            "An unproven load-bearing capability is not automatically contradicted; it triggers FEASIBILITY_REQUIRED before ordinary willingness-to-pay interviews.",
            "Absence of web evidence is not automatically evidence that demand is absent; insufficient research can block progression without proving KILL.",
            "The contract is generated before research and may not be weakened after evidence arrives.",
            "Starting a materially different hypothesis requires a new contract rather than editing this one in place.",
        ],
    )


def ensure_validation_contract(state: SystemState) -> ValidationContract:
    """Backfill older saved ventures without changing an existing locked contract."""
    if state.validation_contract is None:
        state.validation_contract = build_validation_contract(state)
    return state.validation_contract


def contract_matches_hypothesis(state: SystemState) -> bool:
    """A locked contract may not be silently reused for a materially changed hypothesis."""
    contract = ensure_validation_contract(state)
    return contract.hypothesis_fingerprint == hypothesis_fingerprint(state.hypothesis)


def contract_summary(contract: ValidationContract) -> dict[str, Any]:
    """Compact, render-friendly summary."""
    return {
        "status": contract.status,
        "version": contract.contract_version,
        "critical_assumptions": contract.critical_assumptions,
        "research_rules": contract.research_rules,
        "human_rules": contract.human_rules,
        "decision_rules": contract.decision_rules,
    }
