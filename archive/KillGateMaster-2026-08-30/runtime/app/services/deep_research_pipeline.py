"""Feature-flagged bridge from Killgate's legacy research pass to Deep Research state."""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from urllib.parse import urlparse

from app.models.deep_research import (
    ResearchClaim,
    ResearchRun,
    ResearchRunStatus,
    ResearchSourceRecord,
    ResearchSourceState,
)
from app.models.evidence_graph import EvidenceLink, EvidenceRelation
from app.models.research_report import DeepResearchReport
from app.models.state import SystemState
from app.services.deep_research import (
    DeepResearchStoreUnavailable,
    initialize_research_run,
    load_research_run,
    persist_research_checkpoint,
    persist_research_run,
    record_evidence_set_fingerprint,
    transition_run,
)
from app.services.evidence_graph import build_evidence_matrix
from app.services.research import (
    ResearchResult,
    enforce_deep_observed_evidence_gate,
    run_research_pass,
    synthesize_research_result,
)
from app.services.research_planner import build_research_plan
from app.services.research_provider import (
    HttpSourceRetriever,
    LegacySearchProvider,
    TextEvidenceExtractor,
)
from app.services.research_report import build_deep_research_report
from app.services.retrieval import SourceRetrievalError
from app.services.validation_contract import ensure_validation_contract


class DeepResearchPipelineUnavailable(RuntimeError):
    """Raised when the feature-flagged durable pipeline cannot complete safely."""


@dataclass(frozen=True)
class DeepResearchPipelineResult:
    run: ResearchRun
    legacy_result: ResearchResult
    report: DeepResearchReport


# Keep test/integration overrides of the legacy provider seam working while
# the production path uses the explicit discovery -> synthesis split below.
_ORIGINAL_RUN_RESEARCH_PASS = run_research_pass


def _provider_override_active() -> bool:
    return run_research_pass is not _ORIGINAL_RUN_RESEARCH_PASS


def deep_research_enabled() -> bool:
    return os.getenv("DEEP_RESEARCH_ENABLED", "0").strip() == "1"


def _source_id(url: str) -> str:
    return hashlib.sha256(url.encode("utf-8")).hexdigest()[:16]


def _source_family(url: str) -> str:
    return (urlparse(url).hostname or "").lower().removeprefix("www.")


def _claim_for_evidence(item_claim: str, claims: list[ResearchClaim]) -> str:
    words = {word.lower() for word in item_claim.split() if len(word) > 3}
    if not words:
        return claims[0].claim_id if claims else ""
    ranked = sorted(
        ((len(words & {word.lower() for word in claim.text.split() if len(word) > 3}), claim.claim_id) for claim in claims),
        reverse=True,
    )
    return ranked[0][1] if ranked and ranked[0][0] else (claims[0].claim_id if claims else "")


def _persist(run: ResearchRun, user_id: str) -> None:
    value = persist_research_checkpoint(run, user_id=user_id)
    if value.get("ok") is False:
        raise DeepResearchPipelineUnavailable(f"Deep Research checkpoint rejected: {value.get('error', 'unknown error')}")


def _record_provider_usage(run: ResearchRun, result: ResearchResult) -> None:
    """Fold legacy provider telemetry into the durable bounded ledger.

    The legacy engine owns the actual provider call. This adapter records the
    observable call and token counts so the durable report cannot claim zero
    cost merely because the provider implementation predates Deep Research.
    Search is counted as one bounded operation for the legacy pass; hosted
    tool-level details remain provider telemetry rather than an invented count.
    """
    if result.used_llm and result.llm_model:
        try:
            run.cost.record_model_call(
                result.llm_model,
                input_tokens=result.llm_input_tokens,
                output_tokens=result.llm_output_tokens,
                reasoning_tokens=result.llm_reasoning_tokens,
                config=run.budget,
            )
        except ValueError as exc:
            raise DeepResearchPipelineUnavailable("Deep Research model budget was exceeded.") from exc


def _record_discovery(run: ResearchRun, hits) -> None:
    """Persist discovery metadata without promoting snippets to evidence."""
    run.discovery_sources = [
        ResearchSourceRecord(
            source_id=_source_id(hit.url),
            url=hit.url,
            title=hit.title,
            source_family=_source_family(hit.url),
            relevance=hit.relevance,
            source_state=ResearchSourceState.DISCOVERY,
            notes=[hit.relevance_reason] if hit.relevance_reason else [],
        )
        for hit in hits
        if hit.url
    ]


def _retrieve_and_qualify(run: ResearchRun, hits) -> None:
    """Move only safely retrieved public pages into the evidence set.

    Retrieval failures remain non-evidence.  They are deliberately not copied
    into ``run.sources`` and can never become disconfirming findings.
    """
    retriever = HttpSourceRetriever()
    extractor = TextEvidenceExtractor()
    seen_urls: set[str] = set()
    qualified: list[ResearchSourceRecord] = []
    for hit in hits:
        if hit.relevance != "direct" or not hit.url or hit.url in seen_urls:
            continue
        seen_urls.add(hit.url)
        try:
            run.cost.record_direct_page_fetch(config=run.budget)
        except ValueError:
            break
        try:
            extracted = extractor.extract(retriever.retrieve(hit.url))
        except (SourceRetrievalError, ValueError):
            continue
        source = extracted.source
        source.source_state = ResearchSourceState.QUALIFIED
        source.relevance = hit.relevance
        if hit.relevance_reason:
            source.notes.append(hit.relevance_reason)
        source.qualified_evidence_ids = [source.source_id]
        qualified.append(source)
    run.sources = qualified


def _discover_provider_hits(state: SystemState):
    if _provider_override_active():
        return []
    return LegacySearchProvider().search(state)


def _synthesize_provider_result(state: SystemState, hits) -> ResearchResult:
    if _provider_override_active():
        return run_research_pass(state)
    return synthesize_research_result(state, hits)


def run_deep_research_pipeline(
    state: SystemState,
    *,
    user_id: str,
    venture_id: str,
    venture_family_id: str,
    run_id: str,
    previous_run_id: str | None = None,
) -> DeepResearchPipelineResult:
    """Execute the existing research engine under durable Deep Research state.

    The current legacy engine remains the provider implementation. This bridge
    gives it a durable planner/checkpoint/report envelope while keeping wallet
    debit/refund and validation decisions in their existing web/service layers.
    """
    contract = ensure_validation_contract(state)
    previous_run = None
    if previous_run_id:
        # A rerun report is only meaningful when it can compare against the
        # authenticated parent snapshot. Fail closed instead of presenting a
        # fresh answer as unexplained progress.
        previous_run = load_research_run(run_id=previous_run_id, user_id=user_id)
        if previous_run is None:
            raise DeepResearchPipelineUnavailable("The previous research snapshot could not be loaded safely.")
    run = initialize_research_run(
        venture_id=venture_id,
        venture_family_id=venture_family_id,
        validation_contract=contract.model_dump(mode="json"),
        hypothesis=state.hypothesis,
        run_id=run_id,
        previous_run_id=previous_run_id,
    )
    try:
        persist_research_run(run, user_id=user_id)
        transition_run(run, ResearchRunStatus.PLANNING)
        build_research_plan(run, hypothesis=state.hypothesis)
        _persist(run, user_id)
        transition_run(run, ResearchRunStatus.RETRIEVING)
        _persist(run, user_id)
        try:
            run.cost.record_search_call(config=run.budget)
        except ValueError as exc:
            raise DeepResearchPipelineUnavailable("Deep Research search budget was exceeded.") from exc
        provider_hits = _discover_provider_hits(state)
        _record_discovery(run, provider_hits)
        transition_run(run, ResearchRunStatus.EXTRACTING)
        _retrieve_and_qualify(run, provider_hits)
        evidence_payload = [
            {
                "source_id": source.source_id,
                "url": source.url,
                "relevance": source.relevance,
            }
            for source in run.sources
        ]
        record_evidence_set_fingerprint(run, evidence_payload)
        _persist(run, user_id)

        transition_run(run, ResearchRunStatus.SYNTHESIZING)
        legacy_result = _synthesize_provider_result(state, provider_hits)
        if legacy_result.recommendation == "RESEARCH_PASS" and not run.sources:
            legacy_result.recommendation = "RESEARCH_PIVOT"
            legacy_result.confidence = min(legacy_result.confidence, 0.50)
            note = "Deep Research PASS blocked: no public source completed safe retrieval and qualification."
            legacy_result.evaluator_notes = f"{legacy_result.evaluator_notes} | {note}".strip(" |")
            legacy_result.plain_language = f"{legacy_result.plain_language}\n\n{note}".strip()
        enforce_deep_observed_evidence_gate(legacy_result, rules=contract.research_rules)
        _record_provider_usage(run, legacy_result)
        run.models_used = [
            model
            for model in (
                run.plan.planner_model if run.plan else "",
                legacy_result.llm_model,
            )
            if model
        ]
        # Provider-returned URLs do not become evidence merely because they
        # appear in a response.  Only the independently retrieved/qualified
        # set above is allowed into the durable evidence graph.
        qualified_source_ids_by_url = {source.url: source.source_id for source in run.sources}
        evidence_payload = [
            {"source_id": source.source_id, "url": source.url, "relevance": source.relevance}
            for source in run.sources
        ]
        record_evidence_set_fingerprint(run, evidence_payload)
        links = []
        for item in legacy_result.evidence_items:
            source_id = qualified_source_ids_by_url.get(item.url)
            if not source_id or not run.plan:
                continue
            claim_id = _claim_for_evidence(item.claim, run.plan.claims)
            if not claim_id:
                continue
            relation = (
                EvidenceRelation.CHALLENGES
                if item.supports_or_challenges.lower() in {"challenges", "challenging", "contradicts"}
                else EvidenceRelation.SUPPORTS
            )
            links.append(
                EvidenceLink(
                    claim_id=claim_id,
                    source_id=source_id,
                    relation=relation,
                    source_family=_source_family(item.url),
                    direct=item.relevance == "direct",
                )
            )
        if legacy_result.recommendation == "RESEARCH_PASS" and not links:
            legacy_result.recommendation = "RESEARCH_PIVOT"
            legacy_result.confidence = min(legacy_result.confidence, 0.50)
            note = "Deep Research PASS blocked: no material conclusion cited a qualified source."
            legacy_result.evaluator_notes = f"{legacy_result.evaluator_notes} | {note}".strip(" |")
            legacy_result.plain_language = f"{legacy_result.plain_language}\n\n{note}".strip()
        matrix = build_evidence_matrix(run.plan.claims if run.plan else [], links)
        run.result = {
            "recommendation": legacy_result.recommendation,
            "plain_summary": legacy_result.plain_language or legacy_result.summary,
            "confidence": legacy_result.confidence,
            "supporting_evidence": legacy_result.supporting_evidence,
            "disconfirming_evidence": legacy_result.disconfirming_evidence,
            "observed_user_evidence_count": legacy_result.observed_user_evidence_count,
            "independent_observed_voice_count": legacy_result.independent_observed_voice_count,
            "observed_community_count": legacy_result.observed_community_count,
        }
        report = build_deep_research_report(run, evidence_matrix=matrix, previous_run=previous_run)
        run.report = report.model_dump(mode="json")
        _persist(run, user_id)
        transition_run(run, ResearchRunStatus.EVALUATING)
        _persist(run, user_id)
        transition_run(run, ResearchRunStatus.COMPLETED)
        _persist(run, user_id)
        return DeepResearchPipelineResult(run=run, legacy_result=legacy_result, report=report)
    except (DeepResearchStoreUnavailable, DeepResearchPipelineUnavailable):
        raise
    except Exception as exc:
        try:
            if run.status not in {ResearchRunStatus.FAILED, ResearchRunStatus.CANCELLED, ResearchRunStatus.COMPLETED}:
                transition_run(run, ResearchRunStatus.FAILED, reason=str(exc))
                _persist(run, user_id)
        except (DeepResearchStoreUnavailable, DeepResearchPipelineUnavailable, ValueError, RuntimeError, TypeError):
            # Preserve the original provider failure; the web route will
            # reconcile the existing quota/debit reservation separately.
            return _raise_pipeline_failure(exc)
        raise DeepResearchPipelineUnavailable("Deep Research pipeline could not complete safely.") from exc


def _raise_pipeline_failure(exc: Exception) -> None:
    """Type-checking helper for the best-effort failure branch."""
    raise DeepResearchPipelineUnavailable("Deep Research pipeline could not complete safely.") from exc
