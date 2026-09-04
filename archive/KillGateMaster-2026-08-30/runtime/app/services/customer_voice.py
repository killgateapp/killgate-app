"""Deduplication and independence grouping for observed customer voice."""

from __future__ import annotations

import hashlib
import re
from urllib.parse import urlparse

from app.models.customer_voice import VoiceObservation


def _normalized_text(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().lower()


def _domain(url: str) -> str:
    return (urlparse(url).hostname or "").lower().removeprefix("www.")


def deduplicate_voice_observations(observations: list[VoiceObservation]) -> list[VoiceObservation]:
    """Collapse repeated quote text while retaining the first provenance record."""
    unique: list[VoiceObservation] = []
    seen: set[str] = set()
    for observation in observations:
        normalized = _normalized_text(observation.text)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        observation.content_sha256 = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
        if not observation.independence_group:
            observation.independence_group = ":".join(
                part for part in (_domain(observation.source_url), observation.author_key.strip().lower()) if part
            ) or observation.source_id
        unique.append(observation)
    return unique


def group_voice_independence(observations: list[VoiceObservation]) -> dict[str, int]:
    """Count distinct source/author groups, not merely URLs or quote count."""
    return {
        group: sum(1 for observation in observations if observation.independence_group == group)
        for group in sorted({observation.independence_group for observation in observations if observation.independence_group})
    }
