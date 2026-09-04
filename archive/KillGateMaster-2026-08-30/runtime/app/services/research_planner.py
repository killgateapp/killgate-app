"""Application-owned claim decomposition and bounded query planning."""

from __future__ import annotations

import hashlib
import re
from datetime import UTC, datetime

from app.models.deep_research import ResearchClaim, ResearchPlan, ResearchRun
from app.services.model_routing import model_for_stage

_CLAIM_PATTERNS: tuple[tuple[str, str, str], ...] = (
    ("problem", "problem_existence", "Buyers experience the stated problem often enough to matter."),
    ("cost", "economic_impact", "The problem creates a material operational or financial cost."),
    ("manual", "current_behavior", "Buyers currently use a manual workflow or workaround."),
    ("competitor", "alternative", "Existing alternatives leave a material gap for the buyer."),
    ("pay", "willingness_to_pay", "The buyer has a budget or credible willingness to pay."),
    ("price", "willingness_to_pay", "The proposed price is plausible for the buyer and category."),
    ("reduce", "value", "The proposed mechanism can create measurable economic value."),
    ("save", "value", "The proposed mechanism can create measurable economic value."),
    ("predict", "capability", "The proposed mechanism can work accurately enough at decision time."),
    ("automate", "capability", "The proposed mechanism can work accurately enough at decision time."),
)


def _clean_sentences(hypothesis: str) -> list[str]:
    return [
        re.sub(r"\s+", " ", sentence).strip(" .")
        for sentence in re.split(r"(?<=[.!?])\s+|\n+", hypothesis.strip())
        if sentence.strip()
    ]


def decompose_claims(hypothesis: str, *, price_hypothesis: str = "") -> list[ResearchClaim]:
    """Split founder wording into falsifiable, independently supportable claims."""
    sentences = _clean_sentences(hypothesis)
    clauses: list[str] = []
    for sentence in sentences:
        parts = re.split(r"\s+and\s+(?=(?:the|customers?|buyers?|managers?|teams?)\b)", sentence, flags=re.IGNORECASE)
        clauses.extend(parts if len(parts) > 1 else [sentence])
    if not sentences:
        raise ValueError("hypothesis is required")
    claims: list[ResearchClaim] = []
    seen_types: set[str] = set()
    for sentence in clauses:
        lowered = sentence.lower()
        matched = next((item for item in _CLAIM_PATTERNS if item[0] in lowered), None)
        claim_type, text = (matched[1], sentence) if matched else ("commercial", sentence)
        if claim_type in seen_types and len(claims) >= 8:
            continue
        claims.append(
            ResearchClaim(
                claim_id=f"c{len(claims) + 1}",
                text=text,
                claim_type=claim_type,
                importance="material" if len(claims) < 8 else "context",
                load_bearing=claim_type in {"problem_existence", "willingness_to_pay", "capability", "value"},
                required_evidence_categories=[claim_type],
            )
        )
        seen_types.add(claim_type)
        if len(claims) >= 8:
            break
    if price_hypothesis.strip() and not any(claim.claim_type == "willingness_to_pay" for claim in claims):
        claims.append(
            ResearchClaim(
                claim_id=f"c{len(claims) + 1}",
                text=price_hypothesis.strip(),
                claim_type="willingness_to_pay",
                load_bearing=True,
                required_evidence_categories=["spend", "pricing"],
            )
        )
    return claims[:8]


def build_research_plan(
    run: ResearchRun,
    *,
    hypothesis: str,
    buyer: str = "",
    job_to_be_done: str = "",
    price_hypothesis: str = "",
) -> ResearchPlan:
    """Create a bounded plan without changing the locked run fingerprints."""
    normalized_hypothesis = hypothesis.strip()
    if not normalized_hypothesis:
        raise ValueError("hypothesis is required")
    if hashlib.sha256(normalized_hypothesis.encode("utf-8")).hexdigest() != run.hypothesis_fingerprint:
        raise ValueError("hypothesis does not match the locked run fingerprint")
    claims = decompose_claims(normalized_hypothesis, price_hypothesis=price_hypothesis)
    context = " ".join(claim.text for claim in claims[:3])
    plan = ResearchPlan(
        run_id=run.run_id,
        primary_hypothesis=context,
        buyer=buyer.strip(),
        job_to_be_done=job_to_be_done.strip(),
        price_hypothesis=price_hypothesis.strip(),
        claims=claims,
        required_evidence_categories=[
            "customer_voice", "current_behavior", "alternatives", "spend", "negative", "feasibility"
        ],
        initial_queries=[
            f"{context} customer problem complaint",
            f"{context} current workaround manual process",
            f"{context} alternatives competitor reviews pricing",
            f"{context} cost budget subscription fee",
            f"{context} failed cancelled not worth",
            f"{context} site:reddit.com",
        ],
        contradiction_targets=[
            "buyers do not experience the problem frequently",
            "buyers already have an adequate alternative",
            "the proposed price exceeds the available budget",
            "the proposed capability is infeasible at decision time",
        ],
        technical_questions=[claim.text for claim in claims if claim.claim_type == "capability"],
        anticipated_source_types=["customer_voice", "pricing_pages", "competitor_docs", "industry_reports"],
        # The current planner is deterministic and provider-neutral. Record
        # the application-owned model route reserved for a future provider
        # planner rather than letting a prompt choose it.
        planner_model=model_for_stage("planner"),
    )
    run.plan = plan
    run.updated_at = datetime.now(UTC)
    return plan
