"""Typed competitor and pricing evidence records."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


class CompetitorType(str, Enum):
    DIRECT = "direct"
    SUBSTITUTE = "substitute"
    INCUMBENT = "incumbent"
    MANUAL = "manual"
    STATUS_QUO = "status_quo"


class PricingObservation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_id: str
    currency: str = Field(min_length=3, max_length=3)
    amount: float = Field(ge=0)
    interval: str = "one_time"
    billing_note: str = ""
    normalized_monthly_amount: float | None = Field(default=None, ge=0)
    confidence: str = "observed"


class CompetitorProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    competitor_id: str
    canonical_name: str
    competitor_type: CompetitorType
    aliases: list[str] = Field(default_factory=list)
    buyer_segment: str = ""
    observed_capabilities: list[str] = Field(default_factory=list)
    source_ids: list[str] = Field(default_factory=list)
    pricing: list[PricingObservation] = Field(default_factory=list)
    evidence_notes: list[str] = Field(default_factory=list)
