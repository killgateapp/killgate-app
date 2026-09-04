from __future__ import annotations

import pytest

from app.models.deep_research import (
    ResearchBudgetConfig,
    ResearchRunStatus,
    ResearchSnapshot,
)
from app.services.deep_research import (
    DeepResearchStoreUnavailable,
    ResearchChargeHooks,
    ResearchExecutionError,
    ResearchWorkerLease,
    claim_research_run,
    execute_research_run,
    initialize_research_run,
    load_research_run,
    load_research_snapshot,
    persist_research_checkpoint,
    persist_research_run,
    record_evidence_set_fingerprint,
    release_research_run_claim,
    transition_run,
)


class Response:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        return self._payload


def test_initialize_run_fingerprints_locked_inputs_without_side_effects():
    run = initialize_research_run(
        venture_id="v-1",
        venture_family_id="family-1",
        validation_contract={"status": "locked", "version": "1.5"},
        hypothesis="Independent restaurants need earlier staffing warnings.",
    )

    assert run.status is ResearchRunStatus.QUEUED
    assert len(run.run_id) == 36
    assert len(run.validation_contract_fingerprint) == 64
    assert len(run.hypothesis_fingerprint) == 64
    assert run.cost.model_calls == 0
    assert run.cost.search_calls == 0


def test_run_lifecycle_is_bounded_and_terminal():
    run = initialize_research_run(
        venture_id="v-1",
        venture_family_id="family-1",
        validation_contract="contract",
        hypothesis="hypothesis",
    )
    for status in (
        ResearchRunStatus.PLANNING,
        ResearchRunStatus.RETRIEVING,
        ResearchRunStatus.EXTRACTING,
        ResearchRunStatus.SYNTHESIZING,
        ResearchRunStatus.EVALUATING,
        ResearchRunStatus.COMPLETED,
    ):
        transition_run(run, status)
    with pytest.raises(ValueError, match="invalid research run transition"):
        transition_run(run, ResearchRunStatus.FAILED, reason="too late")


def test_completed_run_can_be_materialized_once_as_snapshot():
    run = initialize_research_run(
        venture_id="v-1", venture_family_id="family-1", validation_contract="contract", hypothesis="hypothesis"
    )
    run.status = ResearchRunStatus.COMPLETED
    run.result = {"recommendation": "RESEARCH_PIVOT"}
    run.report = {"run_id": run.run_id}
    snapshot = ResearchSnapshot.from_run(run)
    assert snapshot.research_run_id == run.run_id
    assert snapshot.venture_family_id == "family-1"
    assert snapshot.report == {"run_id": run.run_id}

    queued = initialize_research_run(
        venture_id="v-1", venture_family_id="family-1", validation_contract="contract", hypothesis="hypothesis"
    )
    with pytest.raises(ValueError, match="only completed"):
        ResearchSnapshot.from_run(queued)


def test_cost_ledger_enforces_call_and_hard_cost_limits():
    config = ResearchBudgetConfig(
        max_model_calls=1,
        max_search_calls=1,
        soft_cost_limit_usd=0.01,
        hard_cost_limit_usd=0.02,
        web_search_cost_per_call_usd=0.01,
    )
    run = initialize_research_run(
        venture_id="v-1", venture_family_id="family-1", validation_contract="c", hypothesis="h", budget=config
    )
    run.cost.record_search_call(config=config)
    assert run.cost.soft_limit_reached
    with pytest.raises(ValueError, match="hard cost limit"):
        run.cost.record_model_call("gpt-5.6-luna", input_tokens=1, output_tokens=20_000, config=config)
    assert run.cost.hard_limit_reached
    assert run.cost.model_calls == 0


def test_fingerprint_changes_when_evidence_changes():
    run = initialize_research_run(
        venture_id="v-1", venture_family_id="family-1", validation_contract="c", hypothesis="h"
    )
    first = record_evidence_set_fingerprint(run, [{"source": "a"}])
    second = record_evidence_set_fingerprint(run, [{"source": "b"}])
    assert first != second
    assert run.evidence_set_fingerprint == second


def test_budget_rejects_inverted_cost_limits():
    with pytest.raises(ValueError, match="hard_cost_limit_usd"):
        ResearchBudgetConfig(soft_cost_limit_usd=2, hard_cost_limit_usd=1)


def test_persisted_run_create_is_idempotent_and_updates_revision(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://project.supabase.co")
    monkeypatch.setenv("SUPABASE_SECRET_KEY", "server-secret-placeholder")
    calls = []

    def fake_post(url, *, headers, json, timeout):
        calls.append((url, json))
        return Response(200, {"ok": True, "duplicate": True, "run": {"revision": 0, "status": "queued"}})

    monkeypatch.setattr("app.services.deep_research.httpx.post", fake_post)
    run = initialize_research_run(venture_id="v", venture_family_id="f", validation_contract="c", hypothesis="h")
    result = persist_research_run(run, user_id="user-1")
    assert result["duplicate"] is True
    assert run.storage_revision == 0
    assert calls[0][0].endswith("/killgate_deep_research_run_create")
    assert calls[0][1]["p_checkpoint"]["sources"] == []


def test_checkpoint_revision_conflict_does_not_mutate_run(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://project.supabase.co")
    monkeypatch.setenv("SUPABASE_SECRET_KEY", "server-secret-placeholder")
    monkeypatch.setattr(
        "app.services.deep_research.httpx.post",
        lambda *args, **kwargs: Response(200, {"ok": False, "error": "revision_conflict", "revision": 4}),
    )
    run = initialize_research_run(venture_id="v", venture_family_id="f", validation_contract="c", hypothesis="h")
    result = persist_research_checkpoint(run, user_id="user-1")
    assert result["error"] == "revision_conflict"
    assert run.storage_revision == 0
    assert run.status is ResearchRunStatus.QUEUED


def test_persistence_requires_server_only_configuration(monkeypatch):
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.delenv("SUPABASE_SECRET_KEY", raising=False)
    run = initialize_research_run(venture_id="v", venture_family_id="f", validation_contract="c", hypothesis="h")
    with pytest.raises(DeepResearchStoreUnavailable):
        persist_research_run(run, user_id="user-1")


def test_load_research_run_reconstructs_checkpoint_and_filters_identity(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://project.supabase.co")
    monkeypatch.setenv("SUPABASE_SECRET_KEY", "server-secret-placeholder")
    calls = []

    def fake_get(url, *, headers, params, timeout):
        calls.append((url, headers, params))
        return Response(
            200,
            [
                {
                    "run_id": "run-1",
                    "venture_id": "venture-1",
                    "venture_family_id": "family-1",
                    "validation_contract_fingerprint": "a" * 64,
                    "hypothesis_fingerprint": "b" * 64,
                    "previous_run_id": None,
                    "evidence_set_fingerprint": "c" * 64,
                    "revision": 3,
                    "status": "retrieving",
                    "created_at": "2026-09-01T00:00:00Z",
                    "updated_at": "2026-09-01T00:01:00Z",
                    "checkpoint": {
                        "research_config_version": "2",
                        "prompt_protocol_version": "7",
                        "data": {"models_used": ["gpt-5.6-luna"], "budget": {"config_version": "1"}},
                    },
                    "cost_ledger": {"search_calls": 2},
                    "result": {"ok": True},
                    "report": {"summary": "checkpoint"},
                    "failure_reason": "",
                }
            ],
        )

    monkeypatch.setattr("app.services.deep_research.httpx.get", fake_get)
    run = load_research_run(run_id="run-1", user_id="user-1")
    assert run is not None
    assert run.storage_revision == 3
    assert run.status is ResearchRunStatus.RETRIEVING
    assert run.models_used == ["gpt-5.6-luna"]
    assert run.cost.search_calls == 2
    assert run.result == {"ok": True}
    assert calls[0][2]["user_id"] == "eq.user-1"


def test_load_research_snapshot_reconstructs_immutable_export(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://project.supabase.co")
    monkeypatch.setenv("SUPABASE_SECRET_KEY", "server-secret-placeholder")
    calls = []

    def fake_get(url, *, headers, params, timeout):
        calls.append(params)
        return Response(
            200,
            [{
                "research_run_id": "run-snapshot",
                "user_id": "user-1",
                "venture_id": "venture-1",
                "venture_family_id": "family-1",
                "validation_contract_fingerprint": "a" * 64,
                "hypothesis_fingerprint": "b" * 64,
                "previous_run_id": None,
                "evidence_set_fingerprint": "c" * 64,
                "research_date": "2026-09-01T00:00:00Z",
                "completed_at": "2026-09-01T00:05:00Z",
                "models_used": ["gpt-5.6-luna"],
                "budget_config": {"config_version": "1"},
                "evidence": [],
                "result": {"recommendation": "RESEARCH_PIVOT"},
                "cost_ledger": {"model_calls": 1},
                "report": {"run_id": "run-snapshot"},
            }],
        )

    monkeypatch.setattr("app.services.deep_research.httpx.get", fake_get)
    snapshot = load_research_snapshot(run_id="run-snapshot", user_id="user-1")
    assert snapshot is not None
    assert snapshot.research_run_id == "run-snapshot"
    assert snapshot.models_used == ["gpt-5.6-luna"]
    assert snapshot.cost.model_calls == 1
    assert calls[0]["user_id"] == "eq.user-1"


def test_executor_persists_bounded_progress_and_commits_once(monkeypatch):
    run = initialize_research_run(venture_id="v", venture_family_id="f", validation_contract="c", hypothesis="h")
    monkeypatch.setattr("app.services.deep_research.persist_research_run", lambda current, user_id: {"ok": True})
    progress = []
    events = []

    def checkpoint(current, owner):
        progress.append(current.status)
        return {"ok": True}

    stages = {
        status: (lambda current, status=status: events.append(status))
        for status in (
            ResearchRunStatus.PLANNING,
            ResearchRunStatus.RETRIEVING,
            ResearchRunStatus.EXTRACTING,
            ResearchRunStatus.SYNTHESIZING,
            ResearchRunStatus.EVALUATING,
        )
    }
    reserved = []
    committed = []
    result = execute_research_run(
        run,
        user_id="user-1",
        stages=stages,
        checkpoint=checkpoint,
        charge_hooks=ResearchChargeHooks(
            reserve=lambda current: reserved.append(current.run_id) or True,
            commit=lambda current: committed.append(current.run_id),
        ),
    )
    assert result.status is ResearchRunStatus.COMPLETED
    assert events == list(stages)
    assert progress[0] is ResearchRunStatus.PLANNING
    assert progress[-1] is ResearchRunStatus.COMPLETED
    assert len(reserved) == 1
    assert committed == [run.run_id]


def test_executor_refunds_and_marks_failed_when_a_stage_raises(monkeypatch):
    run = initialize_research_run(venture_id="v", venture_family_id="f", validation_contract="c", hypothesis="h")
    monkeypatch.setattr("app.services.deep_research.persist_research_run", lambda current, user_id: {"ok": True})
    checkpoints = []
    refunded = []

    def checkpoint(current, owner):
        checkpoints.append(current.status)
        return {"ok": True}

    def fail(current):
        raise ValueError("provider timeout")

    with pytest.raises(ResearchExecutionError, match="bounded research stage failed"):
        execute_research_run(
            run,
            user_id="user-1",
            stages={ResearchRunStatus.PLANNING: fail},
            checkpoint=checkpoint,
            charge_hooks=ResearchChargeHooks(refund=lambda current: refunded.append(current.status)),
        )
    assert run.status is ResearchRunStatus.FAILED
    assert "provider timeout" in run.failure_reason
    assert refunded == [ResearchRunStatus.FAILED]
    assert checkpoints[-1] is ResearchRunStatus.FAILED


def test_worker_claim_and_release_use_service_only_rpc_without_exposing_credentials(monkeypatch):
    calls = []

    def fake_rpc(name, payload):
        calls.append((name, payload))
        return {"ok": True, "run": {}}

    monkeypatch.setattr("app.services.deep_research._rpc", fake_rpc)
    lease = ResearchWorkerLease(run_id="run-1", user_id="user-1", token="lease-1", lease_seconds=300)
    assert claim_research_run(run_id="run-1", user_id="user-1", lease=lease) is lease
    assert calls[0][0] == "killgate_deep_research_run_claim"
    assert calls[0][1]["p_lease_token"] == "lease-1"

    monkeypatch.setattr("app.services.deep_research._rpc_bool", lambda name, payload: name.endswith("release"))
    assert release_research_run_claim(lease) is True
