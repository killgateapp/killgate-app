"""Provider-neutral seams for bounded Deep Research acquisition stages."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Protocol
from urllib.parse import urlparse

from app.models.deep_research import (
    CommercialInterest,
    ResearchSourceKind,
    ResearchSourceRecord,
    ResearchSourceState,
)
from app.models.state import SystemState
from app.services.live_search import SearchHit
from app.services.research import discover_research_hits
from app.services.retrieval import (
    RetrievalPolicy,
    RetrievedSource,
    SourceCache,
    retrieve_source,
)


class SearchProvider(Protocol):
    """Return classified discovery metadata; snippets are not evidence."""

    def search(self, state: SystemState) -> list[SearchHit]: ...


class SourceRetriever(Protocol):
    """Retrieve one public source under SSRF and content bounds."""

    def retrieve(self, url: str) -> RetrievedSource: ...


class EvidenceExtractor(Protocol):
    """Convert retrieved content into a bounded, provenance-linked record."""

    def extract(self, source: RetrievedSource) -> ExtractedEvidence: ...


@dataclass(frozen=True)
class ExtractedEvidence:
    source: ResearchSourceRecord
    text: str


@dataclass(frozen=True)
class LegacySearchProvider:
    """Adapter for the existing DuckDuckGo discovery implementation."""

    def search(self, state: SystemState) -> list[SearchHit]:
        return discover_research_hits(state)


@dataclass
class HttpSourceRetriever:
    policy: RetrievalPolicy = field(default_factory=RetrievalPolicy)
    cache: SourceCache | None = None

    def retrieve(self, url: str) -> RetrievedSource:
        return retrieve_source(url, policy=self.policy, cache=self.cache)


@dataclass(frozen=True)
class TextEvidenceExtractor:
    max_chars: int = 8_000

    def extract(self, source: RetrievedSource) -> ExtractedEvidence:
        if self.max_chars < 1:
            raise ValueError("max_chars must be positive")
        text = re.sub(r"\s+", " ", source.text).strip()[: self.max_chars]
        if not text:
            raise ValueError("retrieved source contains no extractable evidence")
        record = qualify_retrieved_source(source)
        record.source_state = ResearchSourceState.EXTRACTED
        return ExtractedEvidence(source=record, text=text)


_USER_GENERATED_HOST_MARKERS = (
    "reddit.", "news.ycombinator.", "github.", "stackoverflow.", "g2.",
    "capterra.", "play.google.", "apps.apple.", "discourse.", "community.",
    "forum.", "forums.",
)
_REGULATORY_HOST_MARKERS = (".gov", ".gov.", "europa.eu")


def qualify_retrieved_source(source: RetrievedSource) -> ResearchSourceRecord:
    """Create a conservative provenance record for retrieved public content.

    This function intentionally classifies publisher incentives, not truth.  A
    later evidence stage decides whether the source can support a particular
    claim.  Unknown publishers remain unknown rather than being promoted to
    independent evidence.
    """
    record = source.provenance(source_kind=ResearchSourceKind.OTHER)
    host = (urlparse(source.url).hostname or "").lower().removeprefix("www.")
    record.source_family = host
    if any(marker in host for marker in _REGULATORY_HOST_MARKERS):
        record.source_kind = ResearchSourceKind.REGULATORY
        record.commercial_interest = CommercialInterest.GOVERNMENTAL_REGULATORY
    elif any(marker in host for marker in _USER_GENERATED_HOST_MARKERS):
        record.source_kind = ResearchSourceKind.CUSTOMER_VOICE
        record.commercial_interest = CommercialInterest.USER_GENERATED
        record.observed_voice = True
    return record
