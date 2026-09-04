"""Customer-voice evidence records with explicit independence metadata."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class VoiceObservation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    observation_id: str
    source_id: str
    source_url: str
    community: str = ""
    author_key: str = ""
    text: str = Field(min_length=1)
    theme: str = "general"
    sentiment: str = "mixed"
    independence_group: str = ""
    content_sha256: str = ""

