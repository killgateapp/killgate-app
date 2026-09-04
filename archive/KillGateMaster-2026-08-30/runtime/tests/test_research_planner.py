from __future__ import annotations

import pytest

from app.services.deep_research import initialize_research_run
from app.services.research_planner import build_research_plan, decompose_claims


def test_decompose_claims_creates_load_bearing_evidence_units():
    claims = decompose_claims(
        "Restaurants experience staffing gaps. Managers use spreadsheets as a workaround. "
        "The product will reduce missed shifts and customers will pay $149/month."
    )
    assert len(claims) == 4
    assert [claim.claim_id for claim in claims] == ["c1", "c2", "c3", "c4"]
    assert any(claim.claim_type == "value" and claim.load_bearing for claim in claims)
    assert any(claim.claim_type == "willingness_to_pay" for claim in claims)


def test_build_plan_preserves_locked_hypothesis_fingerprint():
    hypothesis = "Restaurants experience staffing gaps and managers use spreadsheets."
    run = initialize_research_run(
        venture_id="v", venture_family_id="f", validation_contract="c", hypothesis=hypothesis
    )
    plan = build_research_plan(run, hypothesis=hypothesis, buyer="restaurant manager")
    assert plan.run_id == run.run_id
    assert plan.buyer == "restaurant manager"
    assert len(plan.initial_queries) == 6
    assert "customer_voice" in plan.required_evidence_categories
    assert run.plan is plan


def test_build_plan_rejects_changed_hypothesis():
    run = initialize_research_run(venture_id="v", venture_family_id="f", validation_contract="c", hypothesis="locked")
    with pytest.raises(ValueError, match="locked run fingerprint"):
        build_research_plan(run, hypothesis="changed")
