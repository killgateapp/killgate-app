from __future__ import annotations

from app.models.customer_voice import VoiceObservation
from app.services.customer_voice import (
    deduplicate_voice_observations,
    group_voice_independence,
)


def observation(text, source_id, author):
    return VoiceObservation(
        observation_id=source_id,
        source_id=source_id,
        source_url=f"https://community.example.com/{source_id}",
        author_key=author,
        text=text,
        theme="pain",
    )


def test_voice_deduplication_preserves_provenance_and_groups_independence():
    records = deduplicate_voice_observations(
        [
            observation("We keep missing shifts.", "s1", "alice"),
            observation(" we   keep missing shifts. ", "s2", "bob"),
            observation("Managers use a spreadsheet.", "s3", "alice"),
        ]
    )
    assert len(records) == 2
    assert all(len(record.content_sha256) == 64 for record in records)
    groups = group_voice_independence(records)
    assert groups["community.example.com:alice"] == 2
