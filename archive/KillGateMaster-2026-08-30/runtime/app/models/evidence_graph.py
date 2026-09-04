"""Claim-to-evidence graph records used by deterministic corroboration gates."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict


class EvidenceRelation(str, Enum):
    SUPPORTS = "supports"
    CHALLENGES = "challenges"


class EvidenceLink(BaseModel):
    model_config = ConfigDict(extra="forbid")

    claim_id: str
    source_id: str
    relation: EvidenceRelation
    source_family: str
    direct: bool = True

