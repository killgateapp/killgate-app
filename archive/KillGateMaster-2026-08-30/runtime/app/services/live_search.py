"""
Live web search for Killgate research.

Search is deliberately split into two jobs:
1. Build concept-level queries from the buyer/problem description.
2. Classify every returned result before it is allowed into scoring.

The second step is a hard safety boundary. A result that merely matches an
isolated word (for example, a dictionary page for "want") is not evidence.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field, replace
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse


class LiveSearchUnavailable(RuntimeError):
    """Raised when the live-search provider cannot be queried reliably."""


@dataclass(frozen=True)
class QuerySpec:
    theme: str
    text: str


@dataclass
class SearchHit:
    title: str
    url: str
    snippet: str
    query: str
    query_theme: str = "general"
    relevance: str = "unclassified"  # direct | indirect | irrelevant
    relevance_reason: str = ""
    matched_terms: list[str] = field(default_factory=list)


_STOPWORDS = {
    "a", "about", "acquire", "acquisition", "after", "all", "also", "an",
    "and", "any", "app", "application", "are", "as", "at", "be", "been",
    "before", "build", "building", "business", "by", "called", "can", "card",
    "customer", "customers", "day", "describe", "do", "does", "for", "from",
    "get", "gets", "had", "has", "have", "help", "how", "i", "idea", "if",
    "in", "into", "is", "it", "its", "long", "market", "mobile", "month",
    "months", "my", "none", "not", "nothing", "of", "on", "one", "or", "our", "own",
    "people", "per", "plan", "product", "service", "should", "simple", "social",
    "report", "reports", "show", "showing", "software", "some", "start", "that", "the", "their", "them", "then", "there",
    "these", "they", "this", "through", "to", "tool", "tools", "update", "users",
    "using", "validated", "validation", "want", "website", "what", "when", "where",
    "which", "who", "why", "will", "with", "would", "year", "you", "your",
}

_NON_CONCEPT_SENTENCE_MARKERS = (
    "acquire customers", "acquisition", "advertising", "assumption", "customers would come",
    "costs $", "growth would come", "it costs", "none of", "nothing has been validated", "price is", "priced at", "users pay",
    "would acquire", "would be reached", "would come from",
)

_BLOCKED_EVIDENCE_DOMAINS = (
    "dictionary.cambridge.org",
    "dictionary.com",
    "merriam-webster.com",
    "thesaurus.com",
    "vocabulary.com",
    "wiktionary.org",
    "wikipedia.org",
)

_GENERIC_TITLE_PATTERNS = (
    "definition & meaning",
    "definition and meaning",
    "english meaning",
    "synonyms and antonyms",
    "synonyms: ",
    "instagram photos and videos",
)


_MULTI_LABEL_PUBLIC_SUFFIXES = {
    "co.uk", "org.uk", "ac.uk", "gov.uk",
    "com.au", "net.au", "org.au",
    "co.nz", "org.nz",
    "co.jp", "ne.jp",
    "co.in", "firm.in", "net.in", "org.in",
    "com.br", "com.mx", "com.sg", "com.tr",
    "co.za", "com.cn", "com.hk", "com.tw", "co.kr",
}

_TRACKING_QUERY_KEYS = {
    "fbclid", "gclid", "mc_cid", "mc_eid", "ref", "source", "utm_campaign",
    "utm_content", "utm_medium", "utm_source", "utm_term",
}


def _stem(token: str) -> str:
    """Small dependency-free normalizer used only for conservative matching."""
    word = token.lower().strip("-_'")
    if len(word) > 5 and word.endswith("ies"):
        return word[:-3] + "y"
    for suffix in ("ing", "ers", "ed", "es", "s"):
        if len(word) > len(suffix) + 3 and word.endswith(suffix):
            return word[: -len(suffix)]
    return word


def _concept_terms(hypothesis: str, limit: int = 12) -> list[str]:
    """Extract buyer/problem terms without pricing, promotion, or founder claims."""
    original = hypothesis.strip()
    brand_match = re.search(
        r"\bbuild\s+(?:(?:an?|the)\s+)?(?:called\s+)?([A-Za-z][A-Za-z0-9_-]{2,})",
        original,
    )
    brand = brand_match.group(1).lower() if brand_match else ""

    sentences = re.split(r"(?<=[.!?])\s+|\n+", original)
    concept_sentences = [
        sentence
        for sentence in sentences
        if sentence.strip()
        and not any(marker in sentence.lower() for marker in _NON_CONCEPT_SENTENCE_MARKERS)
    ]
    text = " ".join(concept_sentences[:3]) or original
    text = re.sub(
        r"^\s*i\s+(?:want|plan|would\s+like)\s+to\s+build\s+",
        "",
        text,
        flags=re.IGNORECASE,
    )

    terms: list[str] = []
    seen_stems = set()
    for token in re.findall(r"[A-Za-z][A-Za-z0-9'-]{2,}", text):
        lower = token.lower().strip("-'")
        root = _stem(lower)
        if lower == brand or lower in _STOPWORDS or root in _STOPWORDS:
            continue
        if root in seen_stems:
            continue
        seen_stems.add(root)
        terms.append(lower)
        if len(terms) >= limit:
            break
    return terms


def _make_query_specs(hypothesis: str) -> list[QuerySpec]:
    terms = _concept_terms(hypothesis)
    context = " ".join(terms[:10]).strip()
    if not context:
        context = "customer problem workflow"

    return [
        QuerySpec("pain", f"{context} problem complaint frustrating difficult delay"),
        QuerySpec("workaround", f"{context} workaround currently use manual process"),
        QuerySpec("alternatives", f"{context} alternative competitor platform pricing reviews"),
        QuerySpec("budget", f"{context} price cost fee subscription paid budget"),
        QuerySpec("negative", f"{context} not worth cancelled failed abandoned don't need"),
        QuerySpec("user_voice", f"{context} site:reddit.com"),
    ]


def _make_queries(hypothesis: str) -> list[str]:
    """Compatibility helper used by tests and integrations."""
    return [spec.text for spec in _make_query_specs(hypothesis)]


def _canonical_url(raw_url: str) -> str:
    try:
        parsed = urlparse(raw_url.strip())
    except ValueError:
        return ""
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.netloc:
        return ""
    # Credentials in evidence URLs are never useful and can create misleading links.
    if parsed.username is not None or parsed.password is not None:
        return ""
    host = (parsed.hostname or "").strip(".").lower()
    if not host or any(char.isspace() for char in host):
        return ""
    try:
        port = parsed.port
    except ValueError:
        return ""
    netloc = host if port is None else f"{host}:{port}"
    clean_query = urlencode(
        [(key, value) for key, value in parse_qsl(parsed.query) if key.lower() not in _TRACKING_QUERY_KEYS]
    )
    return urlunparse(
        (parsed.scheme.lower(), netloc, parsed.path.rstrip("/") or "/", "", clean_query, "")
    )


def source_domain(url: str) -> str:
    """Return a conservative registrable-domain approximation for source independence."""
    try:
        parsed = urlparse(url)
    except ValueError:
        return ""
    if parsed.scheme.lower() not in {"http", "https"}:
        return ""
    host = (parsed.hostname or "").strip(".").lower().removeprefix("www.")
    if not host:
        return ""
    # Keep IP literals intact.
    if re.fullmatch(r"\d{1,3}(?:\.\d{1,3}){3}", host) or ":" in host:
        return host
    labels = [label for label in host.split(".") if label]
    if len(labels) <= 2:
        return host
    last_two = ".".join(labels[-2:])
    if last_two in _MULTI_LABEL_PUBLIC_SUFFIXES and len(labels) >= 3:
        return ".".join(labels[-3:])
    return last_two


def _automatic_rejection_reason(hit: SearchHit) -> str:
    domain = source_domain(hit.url)
    title = hit.title.lower().strip()
    if not domain:
        return "Missing or invalid source URL."
    if any(domain == blocked or domain.endswith(f".{blocked}") for blocked in _BLOCKED_EVIDENCE_DOMAINS):
        return "Reference/definition source does not validate customer demand."
    if any(pattern in title for pattern in _GENERIC_TITLE_PATTERNS):
        return "Generic definition or social landing page."
    if len(re.findall(r"[A-Za-z0-9]+", title)) <= 1:
        return "Title is too generic to establish relevance."
    return ""


def classify_search_hits(hypothesis: str, hits: list[SearchHit]) -> list[SearchHit]:
    """Classify results before any source or claim is allowed to influence a verdict."""
    concept_terms = _concept_terms(hypothesis)
    concept_roots = {_stem(term): term for term in concept_terms}
    classified: list[SearchHit] = []

    for hit in hits:
        rejection = _automatic_rejection_reason(hit)
        text_tokens = re.findall(r"[A-Za-z][A-Za-z0-9'-]{2,}", f"{hit.title} {hit.snippet}".lower())
        text_roots = {_stem(token) for token in text_tokens}
        matched = [original for root, original in concept_roots.items() if root in text_roots]

        if rejection:
            relevance = "irrelevant"
            reason = rejection
        elif len(matched) >= 2:
            relevance = "direct"
            reason = f"Matches the submitted buyer/problem context: {', '.join(matched[:5])}."
        elif len(matched) == 1:
            relevance = "indirect"
            reason = f"Matches only one concept term ({matched[0]}); cannot prove a material claim."
        else:
            relevance = "irrelevant"
            reason = "No meaningful buyer/problem overlap with the submitted hypothesis."

        classified.append(
            replace(
                hit,
                relevance=relevance,
                relevance_reason=reason,
                matched_terms=matched,
            )
        )

    return classified


def live_search(hypothesis: str, max_results_per_query: int = 5) -> list[SearchHit]:
    """Run concept-level web searches and distinguish no evidence from provider failure."""
    DDGS = None
    try:
        from ddgs import DDGS as _DDGS

        DDGS = _DDGS
    except ImportError:
        try:
            from duckduckgo_search import DDGS as _DDGS

            DDGS = _DDGS
        except ImportError as exc:
            raise LiveSearchUnavailable("No live-search provider library is installed.") from exc

    hits: list[SearchHit] = []
    seen = set()
    attempts = 0
    failures = 0

    try:
        with DDGS() as ddgs:
            for spec in _make_query_specs(hypothesis):
                attempts += 1
                try:
                    results = list(ddgs.text(spec.text, max_results=max_results_per_query))
                except Exception:  # noqa: BLE001 - third-party provider errors are intentionally isolated per query
                    failures += 1
                    continue
                for result in results:
                    raw_url = (result.get("href") or result.get("link") or result.get("url") or "").strip()
                    url = _canonical_url(raw_url)
                    if not url or url in seen:
                        continue
                    seen.add(url)
                    hits.append(
                        SearchHit(
                            title=(result.get("title") or "")[:200],
                            url=url,
                            snippet=(result.get("body") or result.get("snippet") or "")[:500],
                            query=spec.text,
                            query_theme=spec.theme,
                        )
                    )
                if len(hits) >= 30:
                    break
    except Exception as exc:
        raise LiveSearchUnavailable("The live-search provider could not be reached.") from exc

    if attempts and failures == attempts:
        raise LiveSearchUnavailable("Every live-search query failed.")
    return classify_search_hits(hypothesis, hits[:30])


def format_hits_for_prompt(hits: list[SearchHit]) -> str:
    """Format only pre-classified evidence; callers should omit irrelevant hits."""
    if not hits:
        return "No directly relevant live search results were retrieved."
    lines = []
    for index, hit in enumerate(hits, 1):
        lines.append(
            f"[DIRECT {index}] Theme: {hit.query_theme}\n"
            f"Title: {hit.title}\n"
            f"URL: {hit.url}\n"
            f"Snippet: {hit.snippet}\n"
            f"Relevance: {hit.relevance_reason}\n"
        )
    return "\n".join(lines)
