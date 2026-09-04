"""Deterministic report assembly; model synthesis remains a separate provider step."""

from __future__ import annotations

from typing import Any

from app.models.deep_research import ResearchRun
from app.models.research_report import DeepResearchReport, ResearchVerdict


def _verdict(value: Any, *, has_gaps: bool) -> ResearchVerdict:
    try:
        verdict = ResearchVerdict(str(value))
    except ValueError:
        return ResearchVerdict.INSUFFICIENT_EVIDENCE if has_gaps else ResearchVerdict.PIVOT
    if verdict is ResearchVerdict.PASS and has_gaps:
        return ResearchVerdict.INSUFFICIENT_EVIDENCE
    return verdict


def build_rerun_delta(current: ResearchRun, previous: ResearchRun | None) -> dict[str, Any]:
    """Explain changes without asserting that a new model answer is progress."""
    if previous is None:
        return {"previous_run_id": None, "material_evidence_changed": True, "verdict_changed": False}
    current_verdict = current.result.get("recommendation")
    previous_verdict = previous.result.get("recommendation")
    return {
        "previous_run_id": previous.run_id,
        "material_evidence_changed": current.evidence_set_fingerprint != previous.evidence_set_fingerprint,
        "contract_changed": current.validation_contract_fingerprint != previous.validation_contract_fingerprint,
        "hypothesis_changed": current.hypothesis_fingerprint != previous.hypothesis_fingerprint,
        "verdict_changed": current_verdict != previous_verdict,
        "current_verdict": current_verdict,
        "previous_verdict": previous_verdict,
    }


def build_deep_research_report(
    run: ResearchRun,
    *,
    evidence_matrix: dict[str, dict[str, Any]],
    stopping_reason: str = "",
    previous_run: ResearchRun | None = None,
) -> DeepResearchReport:
    """Assemble an exportable report while preserving unresolved gaps."""
    unknowns = [claim_id for claim_id, row in evidence_matrix.items() if row.get("gap")]
    knowns = [claim_id for claim_id, row in evidence_matrix.items() if not row.get("gap")]
    contradictions = [
        claim_id for claim_id, row in evidence_matrix.items()
        if row.get("challenging_source_ids")
    ]
    result = run.result
    return DeepResearchReport(
        run_id=run.run_id,
        verdict=_verdict(result.get("recommendation"), has_gaps=bool(unknowns)),
        summary=str(result.get("plain_summary") or result.get("summary") or ""),
        confidence=float(result.get("confidence") or 0.0),
        knowns=knowns,
        unknowns=unknowns,
        contradictions=contradictions,
        evidence_matrix=evidence_matrix,
        source_ids=[source.source_id for source in run.sources],
        qualified_source_ids=[source.source_id for source in run.sources if source.source_state.value == "qualified"],
        discovery_source_count=len(run.discovery_sources),
        competitor_ids=[competitor.competitor_id for competitor in run.competitors],
        pricing_observations=[pricing.model_dump(mode="json") for pricing in run.pricing_observations],
        observed_user_evidence_count=int(result.get("observed_user_evidence_count") or 0),
        independent_observed_voice_count=int(result.get("independent_observed_voice_count") or 0),
        observed_community_count=int(result.get("observed_community_count") or 0),
        stopping_reason=stopping_reason,
        cost_ledger=run.cost.model_dump(mode="json"),
        models_used=list(run.models_used),
        rerun_delta=build_rerun_delta(run, previous_run),
    )
