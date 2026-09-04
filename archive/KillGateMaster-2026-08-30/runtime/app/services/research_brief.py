"""Unpaid research brief: the instrument, not the readings.

Generated only from the locked contract / hypothesis. Never performs live
search and never invents sources, scores, or verdicts.
"""
from __future__ import annotations

from typing import Any

from app.models.state import SystemState
from app.services.validation_contract import (
    _extract_stated_price,
    ensure_validation_contract,
)

QUERY_FAMILIES = (
    "Buyer pain and current workaround language",
    "Paid alternatives and public list prices",
    "Failed, abandoned, or regretted solutions",
    "Channel, switching-cost, and constraint evidence",
    "Disconfirming language: would not pay, already built, does not work",
)


def build_research_brief(state: SystemState) -> dict[str, Any]:
    ensure_validation_contract(state)
    contract = state.validation_contract
    price = _extract_stated_price(state.hypothesis)
    hypothesis = (state.hypothesis or "").strip()
    mechanisms = _provisional_mechanisms(hypothesis)
    return {
        "preview": True,
        "sources_retrieved": False,
        "hypothesis": hypothesis,
        "stated_price": price,
        "fingerprint": contract.hypothesis_fingerprint if contract else "",
        "critical_assumptions": list(contract.critical_assumptions) if contract else [],
        "evidence_that_counts": list(contract.evidence_that_counts) if contract else [],
        "evidence_that_does_not_count": list(contract.evidence_that_does_not_count) if contract else [],
        "research_rules": dict(contract.research_rules) if contract else {},
        "human_rules": dict(contract.human_rules) if contract else {},
        "query_families": list(QUERY_FAMILIES),
        "provisional_mechanisms": mechanisms,
        "public_verdicts_possible": [
            "RESEARCH_PASS — talk to buyers; never permission to build",
            "RESEARCH_FAIL — packet cannot clear the public gate",
            "RESEARCH_PIVOT — signal exists but the locked commercial sentence is wrong",
            "FEASIBILITY_REQUIRED — WTP depends on an unproven capability",
        ],
        "public_verdicts_impossible": [
            "GO",
            "A 0–100 success percentage that means safe to build",
            "A ten-page or 150-page memo used as permission",
        ],
        "human_gate": {
            "min_direct_conversations": (contract.human_rules or {}).get("min_direct_conversations", 8) if contract else 8,
            "min_strong_pain_ratio": (contract.human_rules or {}).get("min_strong_pain_ratio", 0.30) if contract else 0.30,
            "min_price_positive_count": (contract.human_rules or {}).get("min_price_positive_count", 4) if contract else 4,
            "min_actual_paid_pilots": (contract.human_rules or {}).get("min_actual_paid_pilots", 2) if contract else 2,
        },
    }


def _provisional_mechanisms(hypothesis: str) -> list[str]:
    text = hypothesis.strip()
    if not text:
        return ["Buyer exists", "Problem is costly enough to act", "Offer beats the current workaround", "Price can clear CAC"]
    return [
        "A narrow buyer experiences this problem in real work or life",
        "The current workaround is expensive, risky, or hated enough to switch",
        "The offer is better than that workaround on a dimension the buyer values",
        "Someone can authorize the stated or implied price",
    ]
