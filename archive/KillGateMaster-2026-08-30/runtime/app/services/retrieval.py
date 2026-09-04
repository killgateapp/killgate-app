"""Bounded, provenance-preserving HTTP retrieval for Deep Research sources."""

from __future__ import annotations

import hashlib
import ipaddress
import re
import socket
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from html.parser import HTMLParser
from typing import ClassVar
from urllib.parse import urljoin, urlparse

import httpx

from app.models.deep_research import (
    ResearchSourceKind,
    ResearchSourceRecord,
    ResearchSourceState,
)
from app.services.live_search import _canonical_url


class SourceRetrievalError(RuntimeError):
    """Raised when a source cannot be fetched within the retrieval policy."""


@dataclass(frozen=True)
class RetrievalPolicy:
    timeout_seconds: float = 10.0
    max_bytes: int = 500_000
    max_text_chars: int = 80_000
    max_redirects: int = 3
    allowed_ports: frozenset[int] = frozenset({80, 443})


@dataclass(frozen=True)
class RetrievedSource:
    url: str
    title: str
    text: str
    content_sha256: str
    accessed_at: datetime
    status_code: int
    content_type: str

    def provenance(self, *, source_kind: ResearchSourceKind = ResearchSourceKind.OTHER) -> ResearchSourceRecord:
        return ResearchSourceRecord(
            source_id=self.content_sha256[:16],
            url=self.url,
            title=self.title,
            source_kind=source_kind,
            source_state=ResearchSourceState.RETRIEVED,
            accessed_at=self.accessed_at,
            content_sha256=self.content_sha256,
        )


@dataclass
class SourceCache:
    """Small process-local cache; durable run state remains the source of truth."""

    ttl_seconds: float = 3600.0
    _items: dict[str, tuple[float, RetrievedSource]] = field(default_factory=dict)

    def get(self, url: str) -> RetrievedSource | None:
        item = self._items.get(url)
        if item is None:
            return None
        expires_at, source = item
        if time.monotonic() >= expires_at:
            self._items.pop(url, None)
            return None
        return source

    def put(self, source: RetrievedSource) -> None:
        self._items[source.url] = (time.monotonic() + self.ttl_seconds, source)


class _TextExtractor(HTMLParser):
    _ignored: ClassVar[frozenset[str]] = frozenset({"script", "style", "noscript", "svg", "template"})

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._depth = 0
        self._title = ""
        self._in_title = False
        self._chunks: list[str] = []

    @property
    def title(self) -> str:
        return re.sub(r"\s+", " ", self._title).strip()[:200]

    @property
    def text(self) -> str:
        return re.sub(r"\s+", " ", " ".join(self._chunks)).strip()

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        lowered = tag.lower()
        if lowered in self._ignored:
            self._depth += 1
        elif lowered == "title":
            self._in_title = True

    def handle_endtag(self, tag: str) -> None:
        lowered = tag.lower()
        if lowered in self._ignored and self._depth:
            self._depth -= 1
        elif lowered == "title":
            self._in_title = False

    def handle_data(self, data: str) -> None:
        if self._depth:
            return
        if self._in_title:
            self._title += f" {data}"
        elif data.strip():
            self._chunks.append(data)


def _validated_target(raw_url: str, policy: RetrievalPolicy) -> str:
    url = _canonical_url(raw_url)
    parsed = urlparse(url)
    if not url or parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise SourceRetrievalError("source URL must be an HTTP(S) URL")
    if parsed.username or parsed.password:
        raise SourceRetrievalError("source URL credentials are not allowed")
    try:
        port = parsed.port
    except ValueError as exc:
        raise SourceRetrievalError("source URL port is invalid") from exc
    effective_port = port or (443 if parsed.scheme == "https" else 80)
    if effective_port not in policy.allowed_ports:
        raise SourceRetrievalError("source URL port is not allowed")
    hostname = parsed.hostname.rstrip(".").lower()
    if hostname == "localhost" or hostname.endswith(".localhost"):
        raise SourceRetrievalError("local source targets are not allowed")
    try:
        addresses = {
            ipaddress.ip_address(info[4][0])
            for info in socket.getaddrinfo(hostname, effective_port, type=socket.SOCK_STREAM)
        }
    except (OSError, ValueError) as exc:
        raise SourceRetrievalError("source host could not be resolved") from exc
    if not addresses or any(
        address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_multicast
        or address.is_reserved
        or address.is_unspecified
        for address in addresses
    ):
        raise SourceRetrievalError("source host resolves to a non-public address")
    return url


def _extract(content: bytes, content_type: str, max_chars: int) -> tuple[str, str]:
    try:
        decoded = content.decode("utf-8", errors="replace")
    except Exception as exc:
        raise SourceRetrievalError("source content could not be decoded") from exc
    if "html" in content_type:
        parser = _TextExtractor()
        parser.feed(decoded)
        return parser.title, parser.text[:max_chars]
    return "", re.sub(r"\s+", " ", decoded).strip()[:max_chars]


def retrieve_source(
    raw_url: str,
    *,
    policy: RetrievalPolicy | None = None,
    cache: SourceCache | None = None,
) -> RetrievedSource:
    """Fetch one public source with redirect, size, and content bounds."""
    active_policy = policy or RetrievalPolicy()
    url = _validated_target(raw_url, active_policy)
    if cache is not None:
        cached = cache.get(url)
        if cached is not None:
            return cached
    current = url
    response: httpx.Response | None = None
    for _ in range(active_policy.max_redirects + 1):
        _validated_target(current, active_policy)
        try:
            response = httpx.get(
                current,
                headers={"User-Agent": "KillgateResearch/1.0"},
                follow_redirects=False,
                timeout=active_policy.timeout_seconds,
            )
        except httpx.HTTPError as exc:
            raise SourceRetrievalError("source provider could not be reached") from exc
        if response.status_code not in {301, 302, 303, 307, 308}:
            break
        location = response.headers.get("location", "")
        if not location:
            raise SourceRetrievalError("source returned an invalid redirect")
        current = urljoin(current, location)
    else:
        raise SourceRetrievalError("source redirect limit exceeded")
    if response is None or not 200 <= response.status_code < 300:
        status = response.status_code if response is not None else 0
        raise SourceRetrievalError(f"source returned HTTP {status}")
    content_type = response.headers.get("content-type", "").lower()
    if not any(kind in content_type for kind in ("text/html", "text/plain", "application/json")):
        raise SourceRetrievalError("source content type is not extractable text")
    declared_length = response.headers.get("content-length")
    if declared_length:
        try:
            exceeds_limit = int(declared_length) > active_policy.max_bytes
        except ValueError as exc:
            raise SourceRetrievalError("source content length is invalid") from exc
        if exceeds_limit:
            raise SourceRetrievalError("source exceeds the retrieval size limit")
    content = response.content
    if len(content) > active_policy.max_bytes:
        raise SourceRetrievalError("source exceeds the retrieval size limit")
    title, text = _extract(content, content_type, active_policy.max_text_chars)
    if not text:
        raise SourceRetrievalError("source contains no extractable text")
    source = RetrievedSource(
        url=_canonical_url(current),
        title=title,
        text=text,
        content_sha256=hashlib.sha256(content).hexdigest(),
        accessed_at=datetime.now(UTC),
        status_code=response.status_code,
        content_type=content_type.split(";", 1)[0],
    )
    if cache is not None:
        cache.put(source)
    return source
