"""
Core state models that mirror the Killgate operating specification.
These are the runtime source of truth.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


def utc_now() -> datetime:
    """Return an aware UTC timestamp for persisted runtime state."""
    return datetime.now(UTC)


class Phase(str, Enum):
    VALIDATION = "validation"
    BUILD = "build"
    DISTRIBUTE = "distribute"
    SCALE = "scale"
    KILL = "kill"


class ValidationDecision(str, Enum):
    GO = "go"
    CONTINUE_VALIDATION = "continue_validation"
    KILL = "kill"
    PIVOT = "pivot"


class EvidenceLevel(int, Enum):
    SYNTHETIC = 0
    MARKET_FACT = 1
    OBSERVED = 2
    DIRECT = 3
    COMMITMENT = 4
    PAYMENT = 5


class TaskStatus(str, Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    REVIEW = "review"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    BLOCKED = "blocked"


class AgentRole(str, Enum):
    SUPERVISOR = "supervisor"
    VALIDATION = "validation"
    BUILDER = "builder"
    DISTRIBUTION = "distribution"
    RISK_FINANCE = "risk_finance"
    EVALUATOR = "evaluator"


class Task(BaseModel):
    task_id: str
    created_by: AgentRole
    assigned_to: AgentRole
    objective: str
    status: TaskStatus = TaskStatus.PENDING
    inputs: dict[str, Any] = Field(default_factory=dict)
    deliverable: str | None = None
    acceptance_criteria: list[str] = Field(default_factory=list)
    dependencies: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class EvidenceItem(BaseModel):
    evidence_id: str
    evidence_level: EvidenceLevel
    source_type: str
    raw_quote_or_fact: str
    source_title: str = ""
    source_url: str = ""
    source_relevance: str = ""
    theme: str = ""
    reliability: str = "medium"
    supports_or_challenges: str = ""
    linked_hypothesis_claim: str = ""
    accessed_at: datetime = Field(default_factory=utc_now)
    # Derived evidence remains in the audit ledger when its originating buyer
    # record is corrected. Newer states also retain the exact record linkage.
    origin_record_ids: list[str] = Field(default_factory=list)
    voided_at: datetime | None = None
    void_reason: str = ""
    linkage_review_required: bool = False
    linkage_review_reason: str = ""


class ValidationContract(BaseModel):
    """System-generated rules frozen before research starts."""
    contract_version: str = "1.5"
    status: str = "locked"
    source: str = "system"
    hypothesis_fingerprint: str
    created_at: datetime = Field(default_factory=utc_now)
    locked_at: datetime = Field(default_factory=utc_now)
    critical_assumptions: list[str] = Field(default_factory=list)
    evidence_that_counts: list[str] = Field(default_factory=list)
    evidence_that_does_not_count: list[str] = Field(default_factory=list)
    research_rules: dict[str, Any] = Field(default_factory=dict)
    human_rules: dict[str, Any] = Field(default_factory=dict)
    decision_rules: dict[str, list[str]] = Field(default_factory=dict)
    notes: list[str] = Field(default_factory=list)


class DirectValidationRecord(BaseModel):
    """One real-buyer conversation / economic-check record."""
    record_id: str
    evidence_id: str = ""
    buyer_identifier: str = ""
    buyer_role: str
    qualification_basis: str = ""
    recent_real_example: str
    current_workaround: str
    pain_strength: str = "unknown"  # none | weak | moderate | strong | unknown
    pilot_price_tested: str = ""
    price_response: str = ""
    price_positive: bool = False
    payment_status: str = "not_asked"  # not_asked | declined | committed | paid
    payment_amount: float | None = None
    payment_reference: str = ""
    objection_or_no_reason: str = ""
    exact_quote: str = ""
    source_of_lead: str = ""
    created_at: datetime = Field(default_factory=utc_now)
    # Corrections are soft-voids: preserve the original record for audit/export,
    # but exclude it from all gate math after an explicit reason is recorded.
    voided_at: datetime | None = None
    void_reason: str = ""


class DecisionRecord(BaseModel):
    """Immutable-style audit snapshot for an accepted human decision."""
    decision_id: str
    decision: ValidationDecision
    actor: str = "human"
    gate_recommendation: ValidationDecision
    gate_snapshot: dict[str, Any] = Field(default_factory=dict)
    rationale: str = ""
    created_at: datetime = Field(default_factory=utc_now)


class SystemState(BaseModel):
    """Runtime single source of truth."""
    # Persistence revision. Supabase uses this for optimistic concurrency so two
    # tabs/devices cannot silently overwrite newer venture evidence.
    storage_revision: int = 0
    evidence_linkage_version: int = 0
    current_day: int = 1
    phase: Phase = Phase.VALIDATION
    hypothesis: str = ""
    icp: str = ""
    core_feature: str = ""
    pricing: dict[str, Any] = Field(default_factory=dict)
    metrics: dict[str, Any] = Field(default_factory=dict)
    active_blockers: list[str] = Field(default_factory=list)
    open_human_approvals: list[str] = Field(default_factory=list)
    recent_failures: list[str] = Field(default_factory=list)
    research_pass: bool = False
    validation_decision: ValidationDecision | None = None
    validation_contract: ValidationContract | None = None
    last_updated: datetime = Field(default_factory=utc_now)

    # Runtime collections
    tasks: list[Task] = Field(default_factory=list)
    evidence: list[EvidenceItem] = Field(default_factory=list)
    human_action_queue: list[dict[str, Any]] = Field(default_factory=list)
    direct_validation_records: list[DirectValidationRecord] = Field(default_factory=list)
    decision_log: list[DecisionRecord] = Field(default_factory=list)

    def summary(self) -> str:
        decision = self.validation_decision.value if self.validation_decision else "pending"
        return (
            f"Day {self.current_day} | Phase: {self.phase.value} | "
            f"Research Pass: {self.research_pass} | "
            f"Decision: {decision} | "
            f"Direct checks: {len(self.direct_validation_records)} | "
            f"Open tasks: {len([t for t in self.tasks if t.status in (TaskStatus.PENDING, TaskStatus.IN_PROGRESS)])}"
        )
