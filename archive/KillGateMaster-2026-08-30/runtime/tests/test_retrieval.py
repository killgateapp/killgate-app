from __future__ import annotations

import pytest

from app.services import retrieval
from app.services.retrieval import (
    RetrievalPolicy,
    SourceCache,
    SourceRetrievalError,
    retrieve_source,
)


class Response:
    def __init__(self, status_code, content=b"", headers=None):
        self.status_code = status_code
        self.content = content
        self.headers = headers or {}


def public_dns(hostname, port, *, type):
    return [(None, None, None, None, ("93.184.216.34", port))]


def test_retrieve_source_extracts_text_and_preserves_provenance(monkeypatch):
    monkeypatch.setattr(retrieval.socket, "getaddrinfo", public_dns)
    calls = []

    def fake_get(url, **kwargs):
        calls.append((url, kwargs))
        return Response(
            200,
            b"<html><head><title> Buyer Voice </title><script>ignore()</script></head><body>Useful complaint text.</body></html>",
            {"content-type": "text/html; charset=utf-8"},
        )

    monkeypatch.setattr(retrieval.httpx, "get", fake_get)
    cache = SourceCache()
    source = retrieve_source("https://Example.com/research?utm_source=test", cache=cache)
    assert source.url == "https://example.com/research"
    assert source.title == "Buyer Voice"
    assert source.text == "Useful complaint text."
    assert len(source.content_sha256) == 64
    assert source.provenance().content_sha256 == source.content_sha256
    retrieve_source(source.url, cache=cache)
    assert len(calls) == 1


def test_retrieve_source_rejects_private_and_nonstandard_targets(monkeypatch):
    with pytest.raises(SourceRetrievalError, match="local source"):
        retrieve_source("http://localhost/private")

    def private_dns(hostname, port, *, type):
        return [(None, None, None, None, ("127.0.0.1", port))]

    monkeypatch.setattr(retrieval.socket, "getaddrinfo", private_dns)
    with pytest.raises(SourceRetrievalError, match="non-public"):
        retrieve_source("https://example.com")
    with pytest.raises(SourceRetrievalError, match="port"):
        retrieve_source("https://example.com:8443")


def test_retrieve_source_validates_redirects_and_size(monkeypatch):
    def redirect_dns(hostname, port, *, type):
        address = "127.0.0.1" if hostname == "127.0.0.1" else "93.184.216.34"
        return [(None, None, None, None, (address, port))]

    monkeypatch.setattr(retrieval.socket, "getaddrinfo", redirect_dns)
    responses = iter(
        [
            Response(302, headers={"location": "http://127.0.0.1/private"}),
        ]
    )
    monkeypatch.setattr(retrieval.httpx, "get", lambda *args, **kwargs: next(responses))
    with pytest.raises(SourceRetrievalError, match="non-public"):
        retrieve_source("https://example.com")

    monkeypatch.setattr(
        retrieval.httpx,
        "get",
        lambda *args, **kwargs: Response(
            200,
            b"0123456789",
            {"content-type": "text/plain", "content-length": "10"},
        ),
    )
    with pytest.raises(SourceRetrievalError, match="size limit"):
        retrieve_source("https://example.com", policy=RetrievalPolicy(max_bytes=5))
