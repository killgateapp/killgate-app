"""Durable-domain models for Killgate's bounded Deep Research pipeline.

The contracts remain provider-neutral: they can be used by the bounded
planner/executor without allowing the model to set budgets, bypass gates, or
perform untracked side effects.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models.market_research import CompetitorProfile, PricingObservation


def utc_now() -> datetime:
    return datetime.now(UTC)


class ResearchRunStatus(str, Enum):
    QUEUED = "queued"
    PLANNING = "planning"
    RETRIEVING = "retrieving"
    EXTRACTING = "extracting"
    SYNTHESIZING = "synthesizing"
    EVALUATING = "evaluating"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ResearchSourceKind(str, Enum):
    CUSTOMER_VOICE = "customer_voice"
    PRICING = "pricing"
    COMPETITOR = "competitor"
    ALTERNATIVE = "alternative"
    MARKET_FACT = "market_fact"
    REGULATORY = "regulatory"
    TECHNICAL = "technical"
    OTHER = "other"


class ResearchSourceState(str, Enum):
    """Lifecycle state for a public source.

    Discovery is intentionally not evidence.  A source may affect a verdict
    only after it has been retrieved, extracted, verified, and qualified by
    the application-owned pipeline.
    """

    DISCOVERY = "discovery"
    RETRIEVED = "retrieved"
    EXTRACTED = "extracted"
    VERIFIED = "verified"
    QUALIFIED = "qualified"
    INACCESSIBLE = "inaccessible"


class CommercialInterest(str, Enum):
    """The source publisher's relationship to the claim being evaluated."""

    VENDOR_CONTROLLED = "vendor_controlled"
    COMMERCIALLY_INTERESTED = "commercially_interested"
    INDEPENDENT = "independent"
    USER_GENERATED = "user_generated"
    GOVERNMENTAL_REGULATORY = "governmental_regulatory"
    UNKNOWN = "unknown"


class ResearchSourceRecord(BaseModel):
    """A provenance-preserving source reference and its extracted metadata."""

    source_id: str
    url: str
    title: str = ""
    source_kind: ResearchSourceKind = ResearchSourceKind.OTHER
    source_state: ResearchSourceState = ResearchSourceState.DISCOVERY
    commercial_interest: CommercialInterest = CommercialInterest.UNKNOWN
    source_family: str = ""
    publisher: str = ""
    accessed_at: datetime = Field(default_factory=utc_now)
    content_sha256: str = ""
    relevance: str = "direct"
    observed_voice: bool = False
    vendor_claim: bool = False
    inaccessible: bool = False
    qualified_evidence_ids: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class ResearchClaim(BaseModel):
    """One falsifiable claim in the claim-to-evidence graph."""

    claim_id: str
    text: str
    claim_type: str = "commercial"
    importance: str = "material"
    load_bearing: bool = False
    required_evidence_categories: list[str] = Field(default_factory=list)
    supporting_evidence_ids: list[str] = Field(default_factory=list)
    challenging_evidence_ids: list[str] = Field(default_factory=list)
    status: str = "unresolved"
    corroborated: bool = False


class ResearchPlan(BaseModel):
    """Bounded planner output; the application owns limits and execution."""

    run_id: str
    primary_hypothesis: str
    buyer: str = ""
    job_to_be_done: str = ""
    price_hypothesis: str = ""
    claims: list[ResearchClaim] = Field(default_factory=list)
    required_evidence_categories: list[str] = Field(default_factory=list)
    initial_queries: list[str] = Field(default_factory=list)
    contradiction_targets: list[str] = Field(default_factory=list)
    technical_questions: list[str] = Field(default_factory=list)
    anticipated_source_types: list[str] = Field(default_factory=list)
    planner_model: str = ""
    created_at: datetime = Field(default_factory=utc_now)


class ResearchBudgetConfig(BaseModel):
    """Owner-controlled ceilings for one run.

    These are limits, not promises that a run will spend the full amount.
    """

    model_config = ConfigDict(extra="forbid")

    config_version: str = "1"
    max_model_calls: int = Field(default=12, ge=1, le=100)
    max_search_calls: int = Field(default=24, ge=1, le=200)
    max_direct_page_fetches: int = Field(default=18, ge=0, le=200)
    max_competitor_profiles: int = Field(default=12, ge=0, le=100)
    max_elapsed_seconds: int = Field(default=900, ge=30, le=86_400)
    soft_cost_limit_usd: float = Field(default=0.60, ge=0.0, le=100.0)
    hard_cost_limit_usd: float = Field(default=1.25, ge=0.01, le=100.0)
    web_search_cost_per_call_usd: float = Field(default=0.01, ge=0.0, le=10.0)
    model_input_cost_per_million: dict[str, float] = Field(
        default_factory=lambda: {"gpt-5.6-luna": 0.20, "gpt-5.6-terra": 2.0, "gpt-5.6-sol": 4.0}
    )
    model_output_cost_per_million: dict[str, float] = Field(
        default_factory=lambda: {"gpt-5.6-luna": 1.20, "gpt-5.6-terra": 12.0, "gpt-5.6-sol": 20.0}
    )

    @model_validator(mode="after")
    def validate_cost_order(self) -> ResearchBudgetConfig:
        if self.hard_cost_limit_usd <= self.soft_cost_limit_usd:
            raise ValueError("hard_cost_limit_usd must be greater than soft_cost_limit_usd")
        return self


class CostLedger(BaseModel):
    """Deterministic usage ledger; callers must reserve before doing work."""

    model_calls: int = 0
    search_calls: int = 0
    direct_page_fetches: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    reasoning_tokens: int = 0
    estimated_cost_usd: float = 0.0
    soft_limit_reached: bool = False
    hard_limit_reached: bool = False
    blocked_operations: list[str] = Field(default_factory=list)

    def record_model_call(
        self,
        model: str,
        *,
        input_tokens: int = 0,
        output_tokens: int = 0,
        reasoning_tokens: int = 0,
        config: ResearchBudgetConfig,
    ) -> float:
        if self.model_calls >= config.max_model_calls:
            self.blocked_operations.append("model_call_limit")
            raise ValueError("maximum model calls exceeded")
        if min(input_tokens, output_tokens, reasoning_tokens) < 0:
            raise ValueError("token counts cannot be negative")
        input_rate = config.model_input_cost_per_million.get(model, 0.0)
        output_rate = config.model_output_cost_per_million.get(model, 0.0)
        cost = (input_tokens / 1_000_000) * input_rate + (output_tokens / 1_000_000) * output_rate
        projected = self.estimated_cost_usd + cost
        if projected > config.hard_cost_limit_usd + 1e-9:
            self.hard_limit_reached = True
            self.blocked_operations.append("hard_cost_limit")
            raise ValueError("model call would exceed hard cost limit")
        self.model_calls += 1
        self.input_tokens += input_tokens
        self.output_tokens += output_tokens
        self.reasoning_tokens += reasoning_tokens
        self.estimated_cost_usd = round(projected, 8)
        self.soft_limit_reached = self.estimated_cost_usd >= config.soft_cost_limit_usd
        return cost

    def record_search_call(self, *, config: ResearchBudgetConfig) -> float:
        if self.search_calls >= config.max_search_calls:
            self.blocked_operations.append("search_call_limit")
            raise ValueError("maximum search calls exceeded")
        cost = config.web_search_cost_per_call_usd
        projected = self.estimated_cost_usd + cost
        if projected > config.hard_cost_limit_usd + 1e-9:
            self.hard_limit_reached = True
            self.blocked_operations.append("hard_cost_limit")
            raise ValueError("search call would exceed hard cost limit")
        self.search_calls += 1
        self.estimated_cost_usd = round(projected, 8)
        self.soft_limit_reached = self.estimated_cost_usd >= config.soft_cost_limit_usd
        return cost

    def record_page_fetch(self, *, config: ResearchBudgetConfig) -> None:
        if self.direct_page_fetches >= config.max_direct_page_fetches:
            self.blocked_operations.append("direct_page_fetch_limit")
            raise ValueError("maximum direct page fetches exceeded")
        self.direct_page_fetches += 1


class ResearchRun(BaseModel):
    """Persistable run envelope shared by all later Deep Research phases."""

    run_id: str
    venture_id: str
    venture_family_id: str
    validation_contract_fingerprint: str
    hypothesis_fingerprint: str
    locked_hypothesis: str = ""
    locked_validation_contract: dict[str, Any] = Field(default_factory=dict)
    previous_run_id: str | None = None
    evidence_set_fingerprint: str = ""
    storage_revision: int = Field(default=0, ge=0)
    status: ResearchRunStatus = ResearchRunStatus.QUEUED
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
    research_config_version: str = "1"
    prompt_protocol_version: str = "1"
    models_used: list[str] = Field(default_factory=list)
    budget: ResearchBudgetConfig = Field(default_factory=ResearchBudgetConfig)
    cost: CostLedger = Field(default_factory=CostLedger)
    plan: ResearchPlan | None = None
    discovery_sources: list[ResearchSourceRecord] = Field(default_factory=list)
    sources: list[ResearchSourceRecord] = Field(default_factory=list)
    competitors: list[CompetitorProfile] = Field(default_factory=list)
    pricing_observations: list[PricingObservation] = Field(default_factory=list)
    result: dict[str, Any] = Field(default_factory=dict)
    report: dict[str, Any] = Field(default_factory=dict)
    failure_reason: str = ""


class ResearchSnapshot(BaseModel):
    """Immutable, exportable record of one completed research execution."""

    model_config = ConfigDict(extra="forbid")

    research_run_id: str
    venture_id: str
    venture_family_id: str
    validation_contract_fingerprint: str
    hypothesis_fingerprint: str
    previous_run_id: str | None = None
    evidence_set_fingerprint: str = ""
    research_date: datetime = Field(default_factory=utc_now)
    completed_at: datetime = Field(default_factory=utc_now)
    research_config_version: str = "1"
    prompt_protocol_version: str = "1"
    models_used: list[str] = Field(default_factory=list)
    budget: ResearchBudgetConfig = Field(default_factory=ResearchBudgetConfig)
    plan: ResearchPlan | None = None
    evidence: list[ResearchSourceRecord] = Field(default_factory=list)
    competitors: list[CompetitorProfile] = Field(default_factory=list)
    pricing_observations: list[PricingObservation] = Field(default_factory=list)
    result: dict[str, Any] = Field(default_factory=dict)
    cost: CostLedger = Field(default_factory=CostLedger)
    report: dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def from_run(cls, run: ResearchRun) -> ResearchSnapshot:
        if run.status is not ResearchRunStatus.COMPLETED:
            raise ValueError("only completed research runs can become snapshots")
        return cls(
            research_run_id=run.run_id,
            venture_id=run.venture_id,
            venture_family_id=run.venture_family_id,
            validation_contract_fingerprint=run.validation_contract_fingerprint,
            hypothesis_fingerprint=run.hypothesis_fingerprint,
            previous_run_id=run.previous_run_id,
            evidence_set_fingerprint=run.evidence_set_fingerprint,
            research_date=run.created_at,
            completed_at=run.updated_at,
            research_config_version=run.research_config_version,
            prompt_protocol_version=run.prompt_protocol_version,
            models_used=list(run.models_used),
            budget=run.budget,
            plan=run.plan,
            evidence=list(run.sources),
            competitors=list(run.competitors),
            pricing_observations=list(run.pricing_observations),
            result=dict(run.result),
            cost=run.cost,
            report=dict(run.report),
        )
