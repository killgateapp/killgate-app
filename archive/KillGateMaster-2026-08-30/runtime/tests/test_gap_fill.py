from __future__ import annotations

import pytest

from app.models.deep_research import ResearchBudgetConfig
from app.services.deep_research import initialize_research_run
from app.services.gap_fill import GapFillController, build_gap_fill_queries
from app.services.research_planner import build_research_plan


def test_gap_fill_stops_after_diminishing_returns():
    controller = GapFillController(ResearchBudgetConfig(), saturation_rounds=2)
    controller.reserve_search()
    first = controller.evaluate_round(unresolved_claim_ids=["c1"], new_source_ids=["s1"], elapsed_seconds=1)
    second = controller.evaluate_round(unresolved_claim_ids=["c1"], new_source_ids=[], elapsed_seconds=2)
    third = controller.evaluate_round(unresolved_claim_ids=["c1"], new_source_ids=[], elapsed_seconds=3)
    assert first.stop is False
    assert second.stop is False
    assert third == third.__class__(True, "evidence_saturated", ("c1",))


def test_gap_fill_honors_soft_cost_before_more_searches():
    budget = ResearchBudgetConfig(soft_cost_limit_usd=0.01, hard_cost_limit_usd=0.10)
    controller = GapFillController(budget)
    controller.reserve_search()
    decision = controller.evaluate_round(unresolved_claim_ids=["c1"], new_source_ids=["s1"], elapsed_seconds=1)
    assert decision.stop is True
    assert decision.reason == "soft_cost_limit"
    with pytest.raises(ValueError, match="hard cost limit"):
        for _ in range(11):
            controller.reserve_search()


def test_gap_fill_queries_are_claim_specific_and_bounded():
    hypothesis = "Restaurants experience staffing gaps. Managers use spreadsheets as a workaround."
    run = initialize_research_run(venture_id="v", venture_family_id="f", validation_contract="c", hypothesis=hypothesis)
    plan = build_research_plan(run, hypothesis=hypothesis)
    queries = build_gap_fill_queries(plan, ["c1", "unknown", "c2"], limit=1)
    assert len(queries) == 1
    assert "independent evidence counterexample" in queries[0]
