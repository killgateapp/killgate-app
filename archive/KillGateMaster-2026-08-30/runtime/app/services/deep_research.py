"""Bounded Deep Research lifecycle, accounting, and durable run storage."""

from __future__ import annotations

import hashlib
import json
import os
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import httpx

from app.models.deep_research import (
    ResearchBudgetConfig,
    ResearchRun,
    ResearchRunStatus,
    ResearchSnapshot,
)


class DeepResearchStoreUnavailable(RuntimeError):
    """Raised when durable Deep Research persistence is not safely available."""


class ResearchExecutionError(RuntimeError):
    """Raised when a bounded stage fails after a run has been reserved."""


@dataclass(frozen=True)
class ResearchWorkerLease:
    """Opaque ownership token for one bounded worker attempt."""

    run_id: str
    user_id: str
    token: str
    lease_seconds: int = 300


@dataclass(frozen=True)
class ResearchChargeHooks:
    """Idempotent entitlement callbacks supplied by the existing wallet layer.

    The executor does not import or replace wallet policy.  Production callers
    provide callbacks backed by the existing ``research_run_id`` debit and
    refund RPCs, so a retry cannot charge or refund the same run twice.
    """

    reserve: Callable[[ResearchRun], bool] | None = None
    refund: Callable[[ResearchRun], None] | None = None
    commit: Callable[[ResearchRun], None] | None = None


def _server_config() -> tuple[str, str]:
    url = os.getenv("SUPABASE_URL", "").strip().rstrip("/")
    secret = os.getenv("SUPABASE_SECRET_KEY", "").strip()
    if not url.startswith("https://") or not secret:
        raise DeepResearchStoreUnavailable("Production Deep Research storage is not configured.")
    return url, secret


def _rpc(name: str, payload: dict[str, Any]) -> dict[str, Any]:
    url, secret = _server_config()
    try:
        response = httpx.post(
            f"{url}/rest/v1/rpc/{name}",
            headers={"apikey": secret, "Content-Type": "application/json"},
            json=payload,
            timeout=15,
        )
    except httpx.HTTPError as exc:
        raise DeepResearchStoreUnavailable("Deep Research storage could not be reached.") from exc
    if not 200 <= response.status_code < 300:
        raise DeepResearchStoreUnavailable(f"Deep Research storage returned HTTP {response.status_code}.")
    try:
        value = response.json()
    except ValueError as exc:
        raise DeepResearchStoreUnavailable("Deep Research storage returned invalid data.") from exc
    if not isinstance(value, dict):
        raise DeepResearchStoreUnavailable("Deep Research storage returned an invalid result.")
    return value


def _rpc_bool(name: str, payload: dict[str, Any]) -> bool:
    """Call a server-only boolean RPC without weakening response validation."""
    url, secret = _server_config()
    try:
        response = httpx.post(
            f"{url}/rest/v1/rpc/{name}",
            headers={"apikey": secret, "Content-Type": "application/json"},
            json=payload,
            timeout=15,
        )
    except httpx.HTTPError as exc:
        raise DeepResearchStoreUnavailable("Deep Research storage could not be reached.") from exc
    if not 200 <= response.status_code < 300:
        raise DeepResearchStoreUnavailable(f"Deep Research storage returned HTTP {response.status_code}.")
    try:
        value = response.json()
    except ValueError as exc:
        raise DeepResearchStoreUnavailable("Deep Research storage returned invalid data.") from exc
    if not isinstance(value, bool):
        raise DeepResearchStoreUnavailable("Deep Research storage returned an invalid result.")
    return value


def _rest_get(path: str, *, params: dict[str, str]) -> list[dict[str, Any]]:
    """Read a run through the server-only PostgREST path.

    The table is intentionally not exposed to end-user roles.  Callers must
    use the service key, and this helper never includes that key in errors.
    """
    url, secret = _server_config()
    try:
        response = httpx.get(
            f"{url}/rest/v1/{path.lstrip('/')}",
            headers={"apikey": secret},
            params=params,
            timeout=15,
        )
    except httpx.HTTPError as exc:
        raise DeepResearchStoreUnavailable("Deep Research storage could not be reached.") from exc
    if not 200 <= response.status_code < 300:
        raise DeepResearchStoreUnavailable(f"Deep Research storage returned HTTP {response.status_code}.")
    try:
        value = response.json()
    except ValueError as exc:
        raise DeepResearchStoreUnavailable("Deep Research storage returned invalid data.") from exc
    if not isinstance(value, list) or any(not isinstance(row, dict) for row in value):
        raise DeepResearchStoreUnavailable("Deep Research storage returned an invalid result.")
    return value


def _checkpoint_payload(run: ResearchRun) -> dict[str, Any]:
    return {
        "research_config_version": run.research_config_version,
        "prompt_protocol_version": run.prompt_protocol_version,
        "locked_hypothesis": run.locked_hypothesis,
        "locked_validation_contract": run.locked_validation_contract,
        "models_used": run.models_used,
        "plan": run.plan.model_dump(mode="json") if run.plan else None,
        "discovery_sources": [source.model_dump(mode="json") for source in run.discovery_sources],
        "sources": [source.model_dump(mode="json") for source in run.sources],
        "competitors": [competitor.model_dump(mode="json") for competitor in run.competitors],
        "pricing_observations": [pricing.model_dump(mode="json") for pricing in run.pricing_observations],
        "evidence_set_fingerprint": run.evidence_set_fingerprint,
        "budget": run.budget.model_dump(mode="json"),
    }


def _apply_persisted_row(run: ResearchRun, value: dict[str, Any]) -> dict[str, Any]:
    row = value.get("run")
    if not isinstance(row, dict):
        raise DeepResearchStoreUnavailable("Deep Research storage returned no run row.")
    try:
        revision = int(row.get("revision"))
        status = ResearchRunStatus(str(row.get("status")))
    except (TypeError, ValueError) as exc:
        raise DeepResearchStoreUnavailable("Deep Research storage returned an invalid run row.") from exc
    if revision < 0:
        raise DeepResearchStoreUnavailable("Deep Research storage returned an invalid revision.")
    run.storage_revision = revision
    run.status = status
    run.updated_at = datetime.now(UTC)
    return value


def _fingerprint(value: Any) -> str:
    if isinstance(value, str):
        payload = value.strip().encode("utf-8")
    else:
        payload = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def initialize_research_run(
    *,
    venture_id: str,
    venture_family_id: str,
    validation_contract: str | dict[str, Any],
    hypothesis: str,
    run_id: str | None = None,
    previous_run_id: str | None = None,
    budget: ResearchBudgetConfig | None = None,
    prompt_protocol_version: str = "1",
) -> ResearchRun:
    """Create a queued run without browsing, model calls, or entitlement mutation."""
    if not venture_id.strip() or not venture_family_id.strip():
        raise ValueError("venture_id and venture_family_id are required")
    if not hypothesis.strip():
        raise ValueError("hypothesis is required")
    config = budget or ResearchBudgetConfig()
    return ResearchRun(
        run_id=run_id.strip() if run_id and run_id.strip() else str(uuid.uuid4()),
        venture_id=venture_id.strip(),
        venture_family_id=venture_family_id.strip(),
        validation_contract_fingerprint=_fingerprint(validation_contract),
        hypothesis_fingerprint=_fingerprint(hypothesis),
        locked_hypothesis=hypothesis.strip(),
        locked_validation_contract=(validation_contract if isinstance(validation_contract, dict) else {}),
        previous_run_id=previous_run_id,
        research_config_version=config.config_version,
        prompt_protocol_version=prompt_protocol_version,
        budget=config,
    )


_ALLOWED_TRANSITIONS: dict[ResearchRunStatus, set[ResearchRunStatus]] = {
    ResearchRunStatus.QUEUED: {ResearchRunStatus.PLANNING, ResearchRunStatus.CANCELLED},
    ResearchRunStatus.PLANNING: {ResearchRunStatus.RETRIEVING, ResearchRunStatus.FAILED, ResearchRunStatus.CANCELLED},
    ResearchRunStatus.RETRIEVING: {ResearchRunStatus.EXTRACTING, ResearchRunStatus.FAILED, ResearchRunStatus.CANCELLED},
    ResearchRunStatus.EXTRACTING: {ResearchRunStatus.SYNTHESIZING, ResearchRunStatus.FAILED, ResearchRunStatus.CANCELLED},
    ResearchRunStatus.SYNTHESIZING: {ResearchRunStatus.EVALUATING, ResearchRunStatus.FAILED, ResearchRunStatus.CANCELLED},
    ResearchRunStatus.EVALUATING: {ResearchRunStatus.COMPLETED, ResearchRunStatus.FAILED},
    ResearchRunStatus.COMPLETED: set(),
    ResearchRunStatus.FAILED: set(),
    ResearchRunStatus.CANCELLED: set(),
}


def transition_run(run: ResearchRun, next_status: ResearchRunStatus, *, reason: str = "") -> ResearchRun:
    """Apply only a legal lifecycle transition and refresh its timestamp."""
    if next_status not in _ALLOWED_TRANSITIONS[run.status]:
        raise ValueError(f"invalid research run transition: {run.status.value} -> {next_status.value}")
    run.status = next_status
    run.updated_at = datetime.now(UTC)
    if next_status == ResearchRunStatus.FAILED:
        run.failure_reason = reason.strip() or "research run failed"
    return run


def record_evidence_set_fingerprint(run: ResearchRun, evidence: Any) -> str:
    """Record the deterministic evidence fingerprint before synthesis/evaluation."""
    run.evidence_set_fingerprint = _fingerprint(evidence)
    run.updated_at = datetime.now(UTC)
    return run.evidence_set_fingerprint


def persist_research_run(run: ResearchRun, *, user_id: str) -> dict[str, Any]:
    """Create a durable run envelope; safe to retry with the same run ID."""
    if not user_id.strip():
        raise ValueError("user_id is required")
    value = _rpc(
        "killgate_deep_research_run_create",
        {
            "p_user_id": user_id.strip(),
            "p_run_id": run.run_id,
            "p_venture_id": run.venture_id,
            "p_venture_family_id": run.venture_family_id,
            "p_validation_contract_fingerprint": run.validation_contract_fingerprint,
            "p_hypothesis_fingerprint": run.hypothesis_fingerprint,
            "p_previous_run_id": run.previous_run_id,
            "p_research_config_version": run.research_config_version,
            "p_prompt_protocol_version": run.prompt_protocol_version,
            "p_checkpoint": _checkpoint_payload(run),
        },
    )
    return _apply_persisted_row(run, value)


def persist_research_checkpoint(run: ResearchRun, *, user_id: str) -> dict[str, Any]:
    """Persist one fenced checkpoint and advance the run revision exactly once."""
    if not user_id.strip():
        raise ValueError("user_id is required")
    value = _rpc(
        "killgate_deep_research_run_checkpoint",
        {
            "p_user_id": user_id.strip(),
            "p_run_id": run.run_id,
            "p_expected_revision": run.storage_revision,
            "p_status": run.status.value,
            "p_checkpoint": _checkpoint_payload(run),
            "p_cost_ledger": run.cost.model_dump(mode="json"),
            "p_result": run.result or None,
            "p_report": run.report or None,
            "p_failure_reason": run.failure_reason,
        },
    )
    if value.get("ok") is False:
        return value
    return _apply_persisted_row(run, value)


def claim_research_run(*, run_id: str, user_id: str, lease: ResearchWorkerLease | None = None) -> ResearchWorkerLease:
    """Claim a nonterminal run through the service-role-only lease RPC.

    The database is the concurrency authority.  A caller never treats a local
    dispatch acknowledgement as ownership, preventing duplicate Cloud Tasks or
    retry deliveries from performing charged provider work concurrently.
    """
    if not run_id.strip() or not user_id.strip():
        raise ValueError("run_id and user_id are required")
    active = lease or ResearchWorkerLease(run_id=run_id, user_id=user_id, token=str(uuid.uuid4()))
    if active.run_id != run_id or active.user_id != user_id:
        raise ValueError("worker lease identity does not match the requested run")
    value = _rpc(
        "killgate_deep_research_run_claim",
        {
            "p_user_id": user_id,
            "p_run_id": run_id,
            "p_lease_token": active.token,
            "p_lease_seconds": active.lease_seconds,
        },
    )
    if value.get("ok") is not True:
        raise DeepResearchStoreUnavailable(f"Deep Research worker claim was rejected: {value.get('error', 'unknown error')}")
    return active


def release_research_run_claim(lease: ResearchWorkerLease) -> bool:
    """Release a worker lease without changing the run lifecycle."""
    return _rpc_bool(
        "killgate_deep_research_run_release",
        {
            "p_user_id": lease.user_id,
            "p_run_id": lease.run_id,
            "p_lease_token": lease.token,
        },
    )


def load_research_run(*, run_id: str, user_id: str) -> ResearchRun | None:
    """Load one durable run for authenticated resume/reconciliation.

    Filtering by both run ID and authenticated user ID prevents a caller from
    turning this read into a cross-account lookup.  ``None`` means the row is
    not present; malformed rows fail closed as store-unavailable.
    """
    if not run_id.strip() or not user_id.strip():
        raise ValueError("run_id and user_id are required")
    rows = _rest_get(
        "deep_research_runs",
        params={"select": "*", "run_id": f"eq.{run_id.strip()}", "user_id": f"eq.{user_id.strip()}", "limit": "1"},
    )
    if not rows:
        return None
    row = rows[0]
    checkpoint = row.get("checkpoint")
    if not isinstance(checkpoint, dict):
        checkpoint = {}
    data = checkpoint.get("data")
    if not isinstance(data, dict):
        data = checkpoint
    plan_value = data.get("plan")
    try:
        run = ResearchRun(
            run_id=str(row["run_id"]),
            venture_id=str(row["venture_id"]),
            venture_family_id=str(row["venture_family_id"]),
            validation_contract_fingerprint=str(row["validation_contract_fingerprint"]),
            hypothesis_fingerprint=str(row["hypothesis_fingerprint"]),
            locked_hypothesis=str(data.get("locked_hypothesis") or ""),
            locked_validation_contract=(data.get("locked_validation_contract") if isinstance(data.get("locked_validation_contract"), dict) else {}),
            previous_run_id=row.get("previous_run_id"),
            evidence_set_fingerprint=str(row.get("evidence_set_fingerprint") or data.get("evidence_set_fingerprint") or ""),
            storage_revision=int(row.get("revision", 0)),
            status=ResearchRunStatus(str(row["status"])),
            created_at=row.get("created_at") or datetime.now(UTC),
            updated_at=row.get("updated_at") or datetime.now(UTC),
            research_config_version=str(checkpoint.get("research_config_version") or "1"),
            prompt_protocol_version=str(checkpoint.get("prompt_protocol_version") or "1"),
            models_used=list(data.get("models_used") or []),
            budget=ResearchBudgetConfig.model_validate(data.get("budget") or {}),
            cost=row.get("cost_ledger") or {},
            plan=plan_value if isinstance(plan_value, dict) else None,
            discovery_sources=list(data.get("discovery_sources") or []),
            sources=list(data.get("sources") or []),
            competitors=list(data.get("competitors") or []),
            pricing_observations=list(data.get("pricing_observations") or []),
            result=row.get("result") or {},
            report=row.get("report") or {},
            failure_reason=str(row.get("failure_reason") or ""),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise DeepResearchStoreUnavailable("Deep Research storage returned an invalid run row.") from exc
    return run


def load_research_snapshot(*, run_id: str, user_id: str) -> ResearchSnapshot | None:
    """Load an immutable completed snapshot for an authenticated owner."""
    if not run_id.strip() or not user_id.strip():
        raise ValueError("run_id and user_id are required")
    rows = _rest_get(
        "deep_research_snapshots",
        params={"select": "*", "research_run_id": f"eq.{run_id.strip()}", "user_id": f"eq.{user_id.strip()}", "limit": "1"},
    )
    if not rows:
        return None
    row = rows[0]
    try:
        return ResearchSnapshot(
            research_run_id=str(row["research_run_id"]),
            venture_id=str(row["venture_id"]),
            venture_family_id=str(row["venture_family_id"]),
            validation_contract_fingerprint=str(row["validation_contract_fingerprint"]),
            hypothesis_fingerprint=str(row["hypothesis_fingerprint"]),
            previous_run_id=row.get("previous_run_id"),
            evidence_set_fingerprint=str(row.get("evidence_set_fingerprint") or ""),
            research_date=row.get("research_date") or row.get("created_at") or datetime.now(UTC),
            completed_at=row.get("completed_at") or row.get("created_at") or datetime.now(UTC),
            research_config_version=str(row.get("research_config_version") or "1"),
            prompt_protocol_version=str(row.get("prompt_protocol_version") or "1"),
            models_used=list(row.get("models_used") or []),
            budget=ResearchBudgetConfig.model_validate(row.get("budget_config") or {}),
            plan=row.get("plan") if isinstance(row.get("plan"), dict) else None,
            evidence=list(row.get("evidence") or []),
            competitors=list(row.get("competitors") or []),
            pricing_observations=list(row.get("pricing_observations") or []),
            result=row.get("result") or {},
            cost=row.get("cost_ledger") or {},
            report=row.get("report") or {},
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise DeepResearchStoreUnavailable("Deep Research storage returned an invalid snapshot.") from exc


_EXECUTION_SEQUENCE = (
    ResearchRunStatus.PLANNING,
    ResearchRunStatus.RETRIEVING,
    ResearchRunStatus.EXTRACTING,
    ResearchRunStatus.SYNTHESIZING,
    ResearchRunStatus.EVALUATING,
)


def execute_research_run(
    run: ResearchRun,
    *,
    user_id: str,
    stages: Mapping[ResearchRunStatus, Callable[[ResearchRun], None]],
    charge_hooks: ResearchChargeHooks | None = None,
    checkpoint: Callable[[ResearchRun, str], dict[str, Any]] | None = None,
) -> ResearchRun:
    """Run bounded stages with durable progress and idempotent charge hooks.

    This is deliberately an orchestration seam, not an autonomous agent. The
    caller supplies each stage; the executor owns legal transitions,
    checkpoint ordering, terminal failure handling, and exactly-once callback
    intent. Re-invoking it after a worker interruption resumes from the
    persisted status/revision and callbacks must remain idempotent by run ID.
    """
    if not user_id.strip():
        raise ValueError("user_id is required")
    if run.status in {ResearchRunStatus.COMPLETED, ResearchRunStatus.FAILED, ResearchRunStatus.CANCELLED}:
        return run
    save_checkpoint = checkpoint or (lambda current, owner: persist_research_checkpoint(current, user_id=owner))

    def save(current: ResearchRun) -> None:
        value = save_checkpoint(current, user_id)
        if isinstance(value, dict) and value.get("ok") is False:
            raise ResearchExecutionError(f"checkpoint rejected: {value.get('error', 'unknown error')}")

    persist_research_run(run, user_id=user_id)
    hooks = charge_hooks or ResearchChargeHooks()
    if hooks.reserve is not None and not hooks.reserve(run):
        raise ResearchExecutionError("research entitlement could not be reserved")
    try:
        start_index = _EXECUTION_SEQUENCE.index(run.status) if run.status in _EXECUTION_SEQUENCE else -1
        for next_status in _EXECUTION_SEQUENCE[start_index + 1 :]:
            transition_run(run, next_status)
            save(run)
            stage = stages.get(next_status)
            if stage is None:
                raise ResearchExecutionError(f"missing bounded stage: {next_status.value}")
            stage(run)
            save(run)
        transition_run(run, ResearchRunStatus.COMPLETED)
        save(run)
        if hooks.commit is not None:
            hooks.commit(run)
        return run
    except Exception as exc:
        try:
            if run.status not in {ResearchRunStatus.FAILED, ResearchRunStatus.CANCELLED, ResearchRunStatus.COMPLETED}:
                transition_run(run, ResearchRunStatus.FAILED, reason=str(exc))
                save(run)
        finally:
            if hooks.refund is not None:
                hooks.refund(run)
        if isinstance(exc, ResearchExecutionError):
            raise
        raise ResearchExecutionError("bounded research stage failed") from exc
