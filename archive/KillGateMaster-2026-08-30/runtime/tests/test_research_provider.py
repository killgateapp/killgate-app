from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.models.deep_research import CommercialInterest, ResearchSourceState
from app.services.research_provider import HttpSourceRetriever, TextEvidenceExtractor
from app.services.retrieval import RetrievalPolicy, RetrievedSource


def test_text_evidence_extractor_normalizes_and_preserves_content_provenance():
    source = RetrievedSource(
        url="https://example.com/report",
        title="Report",
        text="  Buyer   complaint\nwith   detail. ",
        content_sha256="a" * 64,
        accessed_at=datetime.now(UTC),
        status_code=200,
        content_type="text/html",
    )
    extracted = TextEvidenceExtractor(max_chars=100).extract(source)
    assert extracted.text == "Buyer complaint with detail."
    assert extracted.source.url == source.url
    assert extracted.source.content_sha256 == source.content_sha256
    assert extracted.source.source_state is ResearchSourceState.EXTRACTED


def test_text_evidence_extractor_marks_public_forum_content_as_user_generated():
    source = RetrievedSource(
        url="https://www.reddit.com/r/example/comments/1/",
        title="Discussion",
        text="A buyer explains a repeated workaround.",
        content_sha256="b" * 64,
        accessed_at=datetime.now(UTC),
        status_code=200,
        content_type="text/html",
    )
    extracted = TextEvidenceExtractor().extract(source)
    assert extracted.source.source_state is ResearchSourceState.EXTRACTED
    assert extracted.source.commercial_interest is CommercialInterest.USER_GENERATED
    assert extracted.source.observed_voice is True


def test_text_evidence_extractor_rejects_empty_or_unbounded_configuration():
    source = RetrievedSource(
        url="https://example.com/report",
        title="Report",
        text="useful",
        content_sha256="a" * 64,
        accessed_at=datetime.now(UTC),
        status_code=200,
        content_type="text/plain",
    )
    with pytest.raises(ValueError, match="max_chars"):
        TextEvidenceExtractor(max_chars=0).extract(source)


def test_http_source_retriever_delegates_policy_and_cache(monkeypatch):
    seen = {}
    expected = object()

    def fake_retrieve(url, *, policy, cache):
        seen.update(url=url, policy=policy, cache=cache)
        return expected

    monkeypatch.setattr("app.services.research_provider.retrieve_source", fake_retrieve)
    policy = RetrievalPolicy(max_bytes=123)
    retriever = HttpSourceRetriever(policy=policy)
    assert retriever.retrieve("https://example.com") is expected
    assert seen["url"] == "https://example.com"
    assert seen["policy"] is policy
