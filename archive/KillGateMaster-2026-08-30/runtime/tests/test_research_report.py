from __future__ import annotations

from app.models.deep_research import ResearchRunStatus
from app.models.market_research import CompetitorType
from app.services.deep_research import initialize_research_run
from app.services.market_research import normalize_pricing, resolve_competitor
from app.services.research_report import build_deep_research_report, build_rerun_delta


def test_report_preserves_gaps_and_downgrades_unsupported_pass():
    run = initialize_research_run(venture_id="v", venture_family_id="f", validation_contract="c", hypothesis="h")
    run.status = ResearchRunStatus.COMPLETED
    run.result = {"recommendation": "RESEARCH_PASS", "plain_summary": "Summary", "confidence": 0.8}
    report = build_deep_research_report(
        run,
        evidence_matrix={"c1": {"gap": False}, "c2": {"gap": True, "challenging_source_ids": ["s2"]}},
        stopping_reason="evidence_saturated",
    )
    assert report.verdict.value == "INSUFFICIENT_EVIDENCE"
    assert report.unknowns == ["c2"]
    assert report.contradictions == ["c2"]
    assert report.stopping_reason == "evidence_saturated"


def test_rerun_delta_distinguishes_new_evidence_from_same_contract_reroll():
    previous = initialize_research_run(venture_id="v", venture_family_id="f", validation_contract="c", hypothesis="h")
    current = initialize_research_run(venture_id="v", venture_family_id="f", validation_contract="c", hypothesis="h")
    previous.result = {"recommendation": "RESEARCH_PIVOT"}
    current.result = {"recommendation": "RESEARCH_PASS"}
    delta = build_rerun_delta(current, previous)
    assert delta["material_evidence_changed"] is False
    assert delta["verdict_changed"] is True
    assert delta["hypothesis_changed"] is False


def test_report_exports_structured_competitor_and_observed_pricing_only():
    run = initialize_research_run(venture_id="v", venture_family_id="f", validation_contract="c", hypothesis="h")
    run.status = ResearchRunStatus.COMPLETED
    run.result = {"recommendation": "RESEARCH_PIVOT"}
    observed = normalize_pricing("$99 per month", source_id="source-1")
    assert observed is not None
    competitor = resolve_competitor("Example Tool", competitor_type=CompetitorType.DIRECT, source_ids=["source-1"])
    competitor.pricing = [observed]
    run.competitors = [competitor]
    run.pricing_observations = [observed]
    report = build_deep_research_report(run, evidence_matrix={})
    assert report.competitor_ids == ["example-tool"]
    assert report.pricing_observations[0]["amount"] == 99.0
