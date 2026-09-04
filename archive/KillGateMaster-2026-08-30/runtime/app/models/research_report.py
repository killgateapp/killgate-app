"""Auditable Deep Research report and rerun-delta contracts."""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ResearchVerdict(str, Enum):
    PASS = "RESEARCH_PASS"
    FAIL = "RESEARCH_FAIL"
    PIVOT = "RESEARCH_PIVOT"
    FEASIBILITY_REQUIRED = "FEASIBILITY_REQUIRED"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"


class DeepResearchReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: str
    verdict: ResearchVerdict
    summary: str = ""
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    knowns: list[str] = Field(default_factory=list)
    unknowns: list[str] = Field(default_factory=list)
    contradictions: list[str] = Field(default_factory=list)
    evidence_matrix: dict[str, dict[str, Any]] = Field(default_factory=dict)
    source_ids: list[str] = Field(default_factory=list)
    qualified_source_ids: list[str] = Field(default_factory=list)
    discovery_source_count: int = Field(default=0, ge=0)
    competitor_ids: list[str] = Field(default_factory=list)
    pricing_observations: list[dict[str, Any]] = Field(default_factory=list)
    observed_user_evidence_count: int = Field(default=0, ge=0)
    independent_observed_voice_count: int = Field(default=0, ge=0)
    observed_community_count: int = Field(default=0, ge=0)
    stopping_reason: str = ""
    cost_ledger: dict[str, Any] = Field(default_factory=dict)
    models_used: list[str] = Field(default_factory=list)
    rerun_delta: dict[str, Any] = Field(default_factory=dict)
