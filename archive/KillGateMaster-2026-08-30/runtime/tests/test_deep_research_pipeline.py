from __future__ import annotations

import pytest

from app.models.deep_research import ResearchRunStatus
from app.models.state import SystemState
from app.services.deep_research import initialize_research_run
from app.services.deep_research_pipeline import (
    DeepResearchPipelineUnavailable,
    run_deep_research_pipeline,
)
from app.services.research import ResearchResult


def test_pipeline_persists_plan_progress_and_report_without_changing_legacy_result(monkeypatch):
    checkpoints = []
    monkeypatch.setattr("app.services.deep_research_pipeline.persist_research_run", lambda run, user_id: {"ok": True})
    monkeypatch.setattr(
        "app.services.deep_research_pipeline.persist_research_checkpoint",
        lambda run, user_id: checkpoints.append(run.status) or {"ok": True, "run": {"revision": run.storage_revision + 1, "status": run.status.value}},
    )
    legacy = ResearchResult(summary="legacy", plain_language="legacy report", recommendation="RESEARCH_PIVOT")
    monkeypatch.setattr("app.services.deep_research_pipeline.run_research_pass", lambda state: legacy)
    state = SystemState(hypothesis="Restaurants experience staffing gaps.")

    result = run_deep_research_pipeline(
        state,
        user_id="user-1",
        venture_id="venture-1",
        venture_family_id="family-1",
        run_id="run-1",
    )
    assert result.legacy_result is legacy
    assert result.run.status.value == "completed"
    assert result.run.plan is not None
    assert result.report.run_id == "run-1"
    assert checkpoints[0].value == "planning"
    assert checkpoints[-1].value == "completed"


def test_pipeline_converts_provider_failure_to_safe_failure(monkeypatch):
    checkpoints = []
    monkeypatch.setattr("app.services.deep_research_pipeline.persist_research_run", lambda run, user_id: {"ok": True})
    monkeypatch.setattr(
        "app.services.deep_research_pipeline.persist_research_checkpoint",
        lambda run, user_id: checkpoints.append(run.status) or {"ok": True, "run": {"revision": run.storage_revision + 1, "status": run.status.value}},
    )
    monkeypatch.setattr(
        "app.services.deep_research_pipeline.run_research_pass",
        lambda state: (_ for _ in ()).throw(RuntimeError("provider timeout")),
    )
    state = SystemState(hypothesis="Restaurants experience staffing gaps.")

    with pytest.raises(DeepResearchPipelineUnavailable):
        run_deep_research_pipeline(
            state,
            user_id="user-1",
            venture_id="venture-1",
            venture_family_id="family-1",
            run_id="run-1",
        )
    assert checkpoints[-1].value == "failed"


def test_pipeline_requires_and_compares_authenticated_parent_snapshot(monkeypatch):
    checkpoints = []
    monkeypatch.setattr("app.services.deep_research_pipeline.persist_research_run", lambda run, user_id: {"ok": True})
    monkeypatch.setattr(
        "app.services.deep_research_pipeline.persist_research_checkpoint",
        lambda run, user_id: checkpoints.append(run.status) or {"ok": True, "run": {"revision": run.storage_revision + 1, "status": run.status.value}},
    )
    monkeypatch.setattr(
        "app.services.deep_research_pipeline.run_research_pass",
        lambda state: ResearchResult(summary="rerun", recommendation="RESEARCH_PIVOT"),
    )
    parent = initialize_research_run(
        venture_id="venture-1", venture_family_id="family-1", validation_contract="contract", hypothesis="Restaurants experience staffing gaps.", run_id="parent-run"
    )
    parent.status = ResearchRunStatus.COMPLETED
    parent.result = {"recommendation": "RESEARCH_PIVOT"}
    parent.evidence_set_fingerprint = "a" * 64
    monkeypatch.setattr("app.services.deep_research_pipeline.load_research_run", lambda run_id, user_id: parent)

    result = run_deep_research_pipeline(
        SystemState(hypothesis="Restaurants experience staffing gaps."),
        user_id="user-1", venture_id="venture-1", venture_family_id="family-1", run_id="child-run", previous_run_id="parent-run"
    )
    assert result.report.rerun_delta["previous_run_id"] == "parent-run"
    assert result.report.rerun_delta["previous_verdict"] == "RESEARCH_PIVOT"


def test_pipeline_records_legacy_provider_usage_in_durable_cost_ledger(monkeypatch):
    monkeypatch.setattr("app.services.deep_research_pipeline.persist_research_run", lambda run, user_id: {"ok": True})
    monkeypatch.setattr(
        "app.services.deep_research_pipeline.persist_research_checkpoint",
        lambda run, user_id: {"ok": True, "run": {"revision": run.storage_revision + 1, "status": run.status.value}},
    )
    monkeypatch.setattr(
        "app.services.deep_research_pipeline.run_research_pass",
        lambda state: ResearchResult(
            summary="telemetry",
            used_llm=True,
            used_web_search=True,
            llm_model="gpt-5.6-luna",
            llm_input_tokens=1_000,
            llm_output_tokens=500,
            llm_reasoning_tokens=100,
        ),
    )

    result = run_deep_research_pipeline(
        SystemState(hypothesis="Restaurants experience staffing gaps."),
        user_id="user-1", venture_id="venture-1", venture_family_id="family-1", run_id="run-telemetry"
    )
    assert result.run.cost.search_calls == 1
    assert result.run.cost.model_calls == 1
    assert result.run.cost.input_tokens == 1_000
    assert result.run.cost.output_tokens == 500
    assert result.run.cost.reasoning_tokens == 100


def test_pipeline_blocks_pass_when_no_qualified_public_source_exists(monkeypatch):
    monkeypatch.setattr("app.services.deep_research_pipeline.persist_research_run", lambda run, user_id: {"ok": True})
    monkeypatch.setattr(
        "app.services.deep_research_pipeline.persist_research_checkpoint",
        lambda run, user_id: {"ok": True, "run": {"revision": run.storage_revision + 1, "status": run.status.value}},
    )
    candidate = ResearchResult(summary="candidate", plain_language="candidate", recommendation="RESEARCH_PASS", confidence=0.9)
    monkeypatch.setattr("app.services.deep_research_pipeline.run_research_pass", lambda state: candidate)

    result = run_deep_research_pipeline(
        SystemState(hypothesis="Restaurants experience staffing gaps."),
        user_id="user-1", venture_id="venture-1", venture_family_id="family-1", run_id="run-no-source",
    )
    assert result.legacy_result.recommendation == "RESEARCH_PIVOT"
    assert "qualification" in result.legacy_result.evaluator_notes
