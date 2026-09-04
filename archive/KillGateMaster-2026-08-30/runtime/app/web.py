"""Killgate Web UI – evidence-gated validation and installable PWA."""

from __future__ import annotations

import os
import re
import uuid
from datetime import UTC, datetime
from html import escape, unescape
from pathlib import Path
from urllib.parse import quote, unquote, urlsplit

from fastapi import FastAPI, Form, Query, Request
from fastapi.responses import (
    FileResponse,
    HTMLResponse,
    JSONResponse,
    RedirectResponse,
    Response,
)
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.models.state import (
    DirectValidationRecord,
    Phase,
    SystemState,
    ValidationDecision,
)
from app.observability import configure_observability
from app.services.audit_trail import (
    append_decision,
    append_direct_evidence,
    append_research_evidence,
    void_direct_evidence,
)
from app.services.auth import (
    AuthRateLimited,
    AuthUnavailable,
    SessionResolution,
    auth_mode,
    clear_session_cookies,
    request_account_deletion,
    resolve_request_session,
    set_session_cookies,
    sign_in,
    sign_out,
    sign_up,
)
from app.services.catalog import catalog_with_ids, find_product, hero_cta_order
from app.services.deep_research import (
    DeepResearchStoreUnavailable,
    load_research_run,
    load_research_snapshot,
)
from app.services.deep_research_pipeline import (
    DeepResearchPipelineUnavailable,
    deep_research_enabled,
    run_deep_research_pipeline,
)
from app.services.google_play import (
    BillingUnavailable,
    acknowledge_subscription,
    billing_enabled,
    configured_product_id,
    consume_one_time_product,
    decode_rtdn_envelope,
    entitlement_is_current,
    find_entitlement_owner_by_token,
    find_entitlement_owner_by_token_hash,
    get_entitlement,
    persist_entitlement,
    record_rtdn_event,
    rtdn_event_processed,
    verify_one_time_product,
    verify_pubsub_push_authorization,
    verify_subscription,
)
from app.services.packet import (
    build_evidence_packet,
    public_gate_label,
    slug_for_packet,
)
from app.services.rate_limit import Limit, RateLimitUnavailable, limiter
from app.services.readiness import readiness_report
from app.services.reality_check import generate_reality_check_plan
from app.services.research import ResearchUnavailable, run_research_pass
from app.services.research_brief import build_research_brief
from app.services.research_policy import research_safety_cap_30d
from app.services.slots import (
    SLOT_FULL_MESSAGE,
    archive_state,
    is_archived,
    slot_status,
    unarchive_state,
)
from app.services.state_store import (
    StateConflictError,
    StateStoreUnavailable,
    create_state_with_slot,
    delete_all_user_data,
    export_user_data,
    list_states,
    load_state,
    new_venture_id,
    save_state,
    save_unarchived_state_with_slot,
)
from app.services.validation_contract import (
    ensure_validation_contract,
    hypothesis_fingerprint,
)
from app.services.validation_gate import (
    buyer_identity_key,
    evaluate_validation_gate,
    go_is_allowed,
)
from app.services.wallet import (
    Wallet,
    WalletStoreUnavailable,
    bind_pass,
    cancel_research_credit,
    consume_research_credit,
    family_credits,
    grant_product,
    load_wallet,
    research_access,
    unbound_passes,
)

STATIC_DIR = Path(__file__).resolve().parent / "static"
configure_observability()
MAX_SHARED_IDEA_LENGTH = 8_000
MAX_REQUEST_BODY_BYTES = 1_048_576
SAMPLE_REPORTS = (
    (
        "Fire sprinkler contractor",
        "/static/sample-reports/fire-sprinkler-validation-report.pdf",
        "Local service validation with install-base, inspection-cycle, and buyer-risk checks.",
    ),
    (
        "AI Gmail assistant",
        "/static/sample-reports/ai-gmail-validation-report.pdf",
        "Inbox workflow validation with competitor pressure and switching-friction analysis.",
    ),
    (
        "Collision repair SaaS",
        "/static/sample-reports/collision-repair-saas-validation.pdf",
        "Vertical SaaS report covering shop operations, insurance drag, and adoption constraints.",
    ),
    (
        "Commercial cleaning",
        "/static/sample-reports/commercial-cleaning-saas-validation-report.pdf",
        "B2B service-market report with labor, churn, and route-density assumptions called out.",
    ),
    (
        "Contract renewal",
        "/static/sample-reports/contract-renewal-validation.pdf",
        "Renewal-risk workflow validation for account teams and owner-operated services.",
    ),
    (
        "Dental no-show",
        "/static/sample-reports/dental-no-show-validation.pdf",
        "Practice-operations validation around appointment leakage and measurable recovery.",
    ),
    (
        "Mood-to-dinner",
        "/static/sample-reports/mood-to-dinner-validation-report.pdf",
        "Consumer-app validation with habit, intent, and willingness-to-pay questions separated.",
    ),
    (
        "Restaurant scheduling",
        "/static/sample-reports/restaurant-scheduling-validation.pdf",
        "Labor scheduling report focused on manager pain, margin sensitivity, and alternatives.",
    ),
    (
        "Vehicle audio diagnostics",
        "/static/sample-reports/vehicle-audio-diagnostics-killgate-report.pdf",
        "Technical-service validation with diagnostic uncertainty and monetization constraints.",
    ),
)
SAMPLE_REACTIONS = (
    (
        "Example founder reaction",
        "It turned a vague maybe into a concrete list of evidence I had to get before building.",
    ),
    (
        "Example operator reaction",
        "The useful part is seeing which assumptions are still just guesses, even after research.",
    ),
    (
        "Example consultant reaction",
        "It gives me a report I can hand back before anyone asks engineering to chase a weak idea.",
    ),
)

app = FastAPI(
    title="Killgate",
    description="Evidence-based idea validation before you build",
    version="1.2.0",
)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.exception_handler(StateConflictError)
async def state_conflict_handler(request: Request, exc: StateConflictError):
    return HTMLResponse(
        "This idea changed in another tab or device. Refresh the idea, review the newest evidence, and submit again.",
        status_code=409,
    )


@app.exception_handler(StateStoreUnavailable)
async def state_store_unavailable_handler(request: Request, exc: StateStoreUnavailable):
    return HTMLResponse(
        "Killgate storage is temporarily unavailable. No venture change was confirmed; try again shortly.",
        status_code=503,
    )


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    """Keep browser navigation errors inside the product experience.

    JSON and static-resource callers keep their machine-readable framework
    errors. A person following an old link or a mistyped workspace path gets a
    clear recovery page instead of FastAPI's raw JSON error object.
    """
    machine_path = request.url.path.startswith(
        ("/api/", "/billing/google-play/", "/static/", "/.well-known/")
    )
    if machine_path:
        return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)

    if exc.status_code == 404:
        message = "The page or idea you requested is no longer available."
    elif exc.status_code == 405:
        message = "That action is not available on this page."
    else:
        message = str(exc.detail)

    user, action_href, action_label = _recovery_action(request)
    return _problem_response(
        status_code=exc.status_code,
        message=message,
        action_href=action_href,
        action_label=action_label,
        user=user,
    )


@app.get("/healthz")
def healthz():
    return {"status": "ok", "service": "killgate", "version": app.version}


@app.get("/readyz")
def readyz():
    report = readiness_report()
    # Do not publish names or status of deployment secrets from a health endpoint.
    payload = {"status": "ready" if report.runtime_ready else "not_ready"}
    return JSONResponse(payload, status_code=200 if report.runtime_ready else 503)


def _session(request: Request) -> SessionResolution:
    return getattr(request.state, "auth_session", SessionResolution(user=None))

def _safe_next(value: str) -> str:
    value = (value or "/").strip()[:2000]
    if (
        not value.startswith("/")
        or value.startswith("//")
        or "\\" in value
        or any(ord(char) < 32 for char in value)
    ):
        return "/"
    parsed = urlsplit(value)
    if parsed.scheme or parsed.netloc:
        return "/"
    return value


def _bounded_int_env(name: str, default: int, *, minimum: int = 1, maximum: int = 10000) -> int:
    try:
        value = int(os.getenv(name, str(default)).strip())
    except ValueError:
        value = default
    return max(minimum, min(value, maximum))


def _pre_auth_limit(env_name: str, default_requests: int, seconds: int) -> Limit:
    return Limit(_bounded_int_env(env_name, default_requests), seconds)


def _login_redirect(request: Request):
    path = request.url.path + (("?" + request.url.query) if request.url.query else "")
    return RedirectResponse(f"/login?next={quote(_safe_next(path))}", status_code=303)


def _recovery_action(request: Request):
    """Return a safe navigation target for an HTML recovery screen."""
    user = _session(request).user
    if user:
        return user, "/", "Back to your workspace"
    if request.url.path in {"/login", "/signup"}:
        label = "Back to sign in" if request.url.path == "/login" else "Back to account creation"
        return None, request.url.path, label
    if auth_mode() == "supabase":
        return None, "/login", "Go to sign in"
    return None, "/", "Return home"


@app.middleware("http")
async def reject_oversized_requests(request: Request, call_next):
    if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
        raw_length = request.headers.get("content-length", "").strip()
        if raw_length:
            try:
                content_length = int(raw_length)
            except ValueError:
                return HTMLResponse("Invalid Content-Length header.", status_code=400)
            if content_length < 0:
                return HTMLResponse("Invalid Content-Length header.", status_code=400)
            if content_length > MAX_REQUEST_BODY_BYTES:
                return HTMLResponse("Request body is too large.", status_code=413)
        # Content-Length can be omitted (for example with chunked transfer).
        # Count streaming chunks and stop as soon as the cap is crossed instead
        # of buffering an arbitrarily large body before checking its length.
        chunks: list[bytes] = []
        total = 0
        async for chunk in request.stream():
            total += len(chunk)
            if total > MAX_REQUEST_BODY_BYTES:
                return HTMLResponse("Request body is too large.", status_code=413)
            chunks.append(chunk)
        request._body = b"".join(chunks)
    return await call_next(request)


@app.middleware("http")
async def load_auth_session(request: Request, call_next):
    if request.url.path.startswith("/static/") or request.url.path in {"/manifest.webmanifest", "/service-worker.js"}:
        request.state.auth_session = SessionResolution(user=None)
        return await call_next(request)
    try:
        # The auth client is synchronous. Keep its provider I/O off the ASGI
        # event loop so forged cookies cannot serialize the whole worker.
        resolution = await run_in_threadpool(resolve_request_session, request)
    except AuthUnavailable:
        return HTMLResponse(
            "Sign-in service is temporarily unavailable. Your session was not cleared; try again shortly.",
            status_code=503,
        )
    request.state.auth_session = resolution
    if (
        request.method in {"POST", "PUT", "PATCH", "DELETE"}
        and auth_mode() == "supabase"
        and request.url.path not in {"/share", "/billing/google-play/rtdn"}
    ):
        # SameSite=Strict protects authenticated form posts, and this Origin check
        # also blocks login/session-swapping CSRF before a user session exists.
        origin = request.headers.get("origin", "").rstrip("/")
        configured_origin = os.getenv("PUBLIC_APP_ORIGIN", "").strip().rstrip("/")
        expected_origin = configured_origin or str(request.base_url).rstrip("/")
        if origin != expected_origin:
            return HTMLResponse("Cross-origin request rejected", status_code=403)
    response = await call_next(request)
    if resolution.refreshed:
        set_session_cookies(response, resolution)
    elif (
        auth_mode() == "supabase"
        and resolution.user is None
        and (request.cookies.get("kg_access") or request.cookies.get("kg_refresh"))
    ):
        # Invalid/expired credentials are not an outage. Clear them once so every
        # anonymous request does not repeatedly hammer the refresh endpoint.
        clear_session_cookies(response)
    return response


@app.middleware("http")
async def present_html_errors_as_recovery_pages(request: Request, call_next):
    """Turn safe, plain HTML error text into an actionable product screen.

    Routes deliberately return short, non-sensitive messages for failed form
    submissions. Keeping that text is important, but leaving it on a blank
    browser page strands people after a retry, quota, or conflict response.
    This middleware applies one accessible recovery treatment to those HTML
    errors without changing API JSON responses or route-level status codes.
    """
    response = await call_next(request)
    content_type = response.headers.get("content-type", "").lower()
    if (
        response.status_code < 400
        or not content_type.startswith("text/html")
        or response.headers.get("x-killgate-recovery-page") == "1"
    ):
        return response

    body = getattr(response, "body", None)
    if body is None:
        chunks: list[bytes] = []
        async for chunk in response.body_iterator:
            chunks.append(chunk.encode() if isinstance(chunk, str) else chunk)
        body = b"".join(chunks)

    message = unescape(body.decode("utf-8", errors="replace")).strip()
    if not message:
        message = "Killgate could not complete that request. Try again shortly."

    user, action_href, action_label = _recovery_action(request)

    return _problem_response(
        status_code=response.status_code,
        message=message,
        action_href=action_href,
        action_label=action_label,
        user=user,
    )


@app.middleware("http")
async def add_security_headers(request, call_next):
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    response.headers.setdefault(
        "Permissions-Policy",
        "camera=(), microphone=(), geolocation=(), usb=()",
    )
    response.headers.setdefault(
        "Content-Security-Policy",
        "default-src 'self'; base-uri 'self'; form-action 'self'; "
        "frame-ancestors 'none'; img-src 'self' data:; "
        "style-src 'self'; script-src 'self'; connect-src 'self'",
    )
    if not request.url.path.startswith("/static/"):
        content_type = response.headers.get("content-type", "").lower()
        if content_type.startswith("text/html") or "application/json" in content_type:
            # Venture/evidence/account pages can contain private customer research.
            # Browser/proxy caches must not retain them after logout/account deletion.
            response.headers.setdefault("Cache-Control", "no-store")
    return response


def page(title: str, body: str, *, page_class: str = "", user=None) -> str:
    safe_title = escape(title)
    safe_page_class = escape(page_class, quote=True)
    if user:
        account_controls = (
            '<nav class="account-nav" aria-label="Account">'
            f'<a class="account-link" href="/account">{escape(user.email or "Account")}</a>'
            '<form method="post" action="/logout">'
            '<button class="text-button" type="submit">Sign out</button>'
            '</form></nav>'
        )
    elif auth_mode() == "supabase":
        account_controls = '<nav class="account-nav" aria-label="Account"><a href="/login">Sign in</a></nav>'
    else:
        account_controls = ''
    return f"""<!doctype html>
<html lang="en-US">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
  <meta name="description" content="Test whether an idea deserves your time and money before you build it.">
  <meta name="theme-color" content="#050914">
  <meta name="color-scheme" content="dark">
  <meta name="mobile-web-app-capable" content="yes">
  <meta name="apple-mobile-web-app-capable" content="yes">
  <meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
  <meta name="apple-mobile-web-app-title" content="Killgate">
  <meta property="og:title" content="Killgate">
  <meta property="og:description" content="Test whether an idea deserves your time and money before you build it.">
  <meta property="og:image" content="/static/brand/killgate-play-store-feature.png">
  <meta name="twitter:card" content="summary_large_image">
  <link rel="manifest" href="/manifest.webmanifest">
  <link rel="icon" href="/static/icons/favicon.ico" sizes="any">
  <link rel="icon" href="/static/icons/favicon-32.png" sizes="32x32" type="image/png">
  <link rel="apple-touch-icon" href="/static/icons/apple-touch-180.png">
  <link rel="stylesheet" href="/static/app.css?v=play-store-visuals-5">
  <title>{safe_title}</title>
</head>
<body class="{safe_page_class}">
  <a class="skip-link" href="#main-content">Skip to main content</a>
  <header class="app-header">
    <a class="brand" href="/" aria-label="Killgate home">
      <img src="/static/icons/killgate-store-512.png" width="42" height="42" alt="">
      <span><strong>Killgate</strong><small>Idea Validation</small></span>
    </a>
    <div class="header-actions"><button class="install-button" type="button" data-install-app hidden>Install</button>{account_controls}</div>
  </header>
  <div class="connection-banner" data-connection-banner role="status" hidden>
    You are offline. Killgate can reopen, but analysis and saved ventures need a connection.
  </div>
  <main id="main-content" tabindex="-1">{body}</main>
  <footer>
    <span class="footer-tagline">Test ideas early. Build with evidence.</span>
    <nav class="footer-nav" aria-label="Footer"><a href="/how-it-works">How it works</a><a href="/privacy">Privacy</a><a href="/support">Support</a></nav>
    <span class="version">v1.2.0</span>
  </footer>
  <script src="/static/app.js" defer></script>
</body>
</html>"""


_PROBLEM_COPY = {
    400: ("CHECK THAT REQUEST", "We need a little more information."),
    401: ("SIGN IN REQUIRED", "Sign in to continue."),
    403: ("REQUEST BLOCKED", "That request cannot be completed here."),
    404: ("NOT FOUND", "We could not find that."),
    409: ("NEEDS A FRESH LOOK", "That action needs your attention."),
    413: ("REQUEST TOO LARGE", "That request is larger than Killgate can accept."),
    429: ("TAKE A SHORT PAUSE", "Please wait before trying again."),
    503: ("TEMPORARILY UNAVAILABLE", "Killgate is temporarily unavailable."),
}


def _problem_response(
    *,
    status_code: int,
    message: str,
    action_href: str,
    action_label: str,
    user=None,
) -> HTMLResponse:
    """Render a safe, accessible recovery page for an expected HTML error."""
    eyebrow, heading = _PROBLEM_COPY.get(
        status_code,
        ("REQUEST NOT COMPLETED", "Killgate could not complete that request."),
    )
    safe_message = str(message).strip()[:1_000] or "Try again shortly."
    body = f"""
    <section class="hero compact problem-hero" aria-labelledby="problem-title">
      <span class="eyebrow">{escape(eyebrow)}</span>
      <h1 id="problem-title">{escape(heading)}</h1>
      <p class="callout caution" role="alert">{escape(safe_message)}</p>
      <div class="problem-actions">
        <a class="button-link" href="{escape(_safe_next(action_href), quote=True)}">{escape(action_label)}</a>
      </div>
    </section>
    """
    return HTMLResponse(
        page(f"{heading} · Killgate", body, page_class="problem-page", user=user),
        status_code=status_code,
        headers={"Cache-Control": "no-store", "X-Killgate-Recovery-Page": "1"},
    )


def _protocol_idea(protocol: str) -> str:
    if not protocol:
        return ""
    decoded = unquote(protocol).strip()
    prefix = "web+killgate:"
    if decoded.lower().startswith(prefix):
        decoded = decoded[len(prefix) :]
    return decoded[:MAX_SHARED_IDEA_LENGTH]


def _shared_idea(title: str, text: str, url: str) -> str:
    pieces = [value.strip() for value in (title, text) if value.strip()]
    clean_url = url.strip()
    if clean_url and all(clean_url not in piece for piece in pieces):
        pieces.append(clean_url)
    return "\n\n".join(pieces)[:MAX_SHARED_IDEA_LENGTH]


def _list(items) -> str:
    return "<ul>" + "".join(f"<li>{escape(str(item))}</li>" for item in items) + "</ul>"


def _password_field(field_id: str, autocomplete: str) -> str:
    safe_id = escape(field_id, quote=True)
    safe_autocomplete = escape(autocomplete, quote=True)
    return f"""
    <div class="password-field">
      <input id="{safe_id}" name="password" type="password" autocomplete="{safe_autocomplete}" minlength="8" data-password-input required>
      <button class="password-toggle" type="button" data-password-toggle aria-controls="{safe_id}" aria-label="Show password" aria-pressed="false">
        <svg aria-hidden="true" viewBox="0 0 24 24" width="20" height="20" focusable="false">
          <path d="M2.5 12s3.5-6 9.5-6 9.5 6 9.5 6-3.5 6-9.5 6-9.5-6-9.5-6Z"></path>
          <circle cx="12" cy="12" r="3"></circle>
        </svg>
      </button>
    </div>
    """


def _render_sample_reports(section_id: str, *, limit: int = 4) -> str:
    heading_id = f"{section_id}-title"
    cards = []
    for title, href, detail in SAMPLE_REPORTS[:limit]:
        cards.append(
            f"""
            <a class="report-card" href="{escape(href, quote=True)}" target="_blank" rel="noopener">
              <span>PDF sample</span>
              <strong>{escape(title)}</strong>
              <p>{escape(detail)}</p>
            </a>
            """
        )
    return f"""
    <section class="sample-reports" id="{escape(section_id, quote=True)}" aria-labelledby="{escape(heading_id, quote=True)}">
      <div class="section-kicker">
        <span class="eyebrow">SAMPLE REPORT PREVIEW</span>
        <h2 id="{escape(heading_id, quote=True)}">See what a finished validation report looks like.</h2>
      </div>
      <div class="report-grid">{"".join(cards)}</div>
    </section>
    """


def _render_sample_reactions(section_id: str) -> str:
    heading_id = f"{section_id}-title"
    cards = []
    for label, quote_text in SAMPLE_REACTIONS:
        cards.append(
            f"""
            <figure class="reaction-card">
              <blockquote>{escape(quote_text)}</blockquote>
              <figcaption>{escape(label)}</figcaption>
            </figure>
            """
        )
    return f"""
    <section class="sample-reactions" id="{escape(section_id, quote=True)}" aria-labelledby="{escape(heading_id, quote=True)}">
      <div class="section-kicker">
        <span class="eyebrow">SAMPLE REACTIONS</span>
        <h2 id="{escape(heading_id, quote=True)}">Illustrative reactions to the kind of clarity Killgate provides.</h2>
      </div>
      <div class="reaction-grid">{"".join(cards)}</div>
    </section>
    """


def _render_product_explainer(section_id: str) -> str:
    safe_section_id = escape(section_id, quote=True)
    heading_id = f"{section_id}-title"
    return f"""
    <section class="product-explainer" id="{safe_section_id}" aria-labelledby="{escape(heading_id, quote=True)}">
      <div class="section-kicker">
        <span class="eyebrow">HOW KILLGATE WORKS</span>
        <h2 id="{escape(heading_id, quote=True)}">Turn one idea into an evidence-based decision.</h2>
        <p>Killgate is for founders and operators who want to learn whether an idea is worth more time and money before they build it.</p>
      </div>
      <div class="journey-grid">
        <article class="journey-card"><span>01</span><h3>Describe the idea</h3><p>Name the buyer, the problem, and what you would sell. Plain English is enough.</p></article>
        <article class="journey-card"><span>02</span><h3>See the test plan</h3><p>Killgate turns the idea into a locked question and shows what evidence must be collected before you spend on research.</p></article>
        <article class="journey-card"><span>03</span><h3>Check public reality</h3><p>If you choose live research, you receive a plain-language report with relevant public evidence, cautions, and source links.</p></article>
        <article class="journey-card"><span>04</span><h3>Prove it with buyers</h3><p>Use the interview guide, record real conversations and commitments, then decide whether to build, keep testing, change direction, or stop.</p></article>
      </div>
      <p class="scope-note"><strong>What Killgate does not do:</strong> it does not guarantee success, invent customer opinions, or treat web research as proof that people will buy.</p>
    </section>
    """


def _render_contract(state: SystemState) -> str:
    contract = ensure_validation_contract(state)
    human = contract.human_rules
    return f"""
    <section class="panel contract-panel">
      <div class="contract-titleline">
        <div>
          <span class="eyebrow">VALIDATION CONTRACT</span>
          <h2>The evidence standard was locked before results arrived.</h2>
        </div>
        <span class="lock-badge">LOCKED</span>
      </div>
      <p class="muted">This keeps a promising result from lowering the bar and a disappointing result from quietly changing the question.</p>
      <div class="contract-thresholds">
        <div><span>Public evidence</span><strong>Enough relevant, independent sources to justify buyer testing</strong></div>
        <div><span>Buyer conversations</span><strong>At least {int(human['min_direct_conversations'])} qualified buyers</strong></div>
        <div><span>Problem strength</span><strong>At least {float(human['min_strong_pain_ratio']):.0%} report strong recent pain</strong></div>
        <div><span>Payment proof</span><strong>At least {int(human['min_actual_paid_pilots'])} verified paid pilots</strong></div>
      </div>
      <details>
        <summary>What the locked plan protects</summary>
        <h3>Evidence Killgate accepts</h3>{_list(contract.evidence_that_counts)}
        <h3>Evidence Killgate rejects</h3>{_list(contract.evidence_that_does_not_count)}
        <h3>Possible decisions</h3>
        <ul>
          <li><strong>Go Build:</strong> the required public and buyer evidence has cleared the standard.</li>
          <li><strong>Continue:</strong> the idea may still be worth testing, but important proof is missing.</li>
          <li><strong>Pivot:</strong> a real problem may exist, but the buyer, offer, price, or approach should change.</li>
          <li><strong>Stop:</strong> strong negative evidence says more investment is not justified.</li>
        </ul>
      </details>
    </section>
    """


def _render_gate_progress(state: SystemState) -> str:
    gate = evaluate_validation_gate(state)
    rec = {
        ValidationDecision.GO: "GO BUILD",
        ValidationDecision.KILL: "STOP",
        ValidationDecision.PIVOT: "PIVOT",
        ValidationDecision.CONTINUE_VALIDATION: "CONTINUE TESTING",
    }[gate.recommendation]
    rec_class = {
        ValidationDecision.GO: "verdict-pass",
        ValidationDecision.KILL: "verdict-kill",
        ValidationDecision.PIVOT: "verdict-caution",
        ValidationDecision.CONTINUE_VALIDATION: "verdict-caution",
    }[gate.recommendation]
    blockers = _list(gate.blockers) if gate.blockers else "<p class=\"muted\">No blockers remain.</p>"
    passed = _list(gate.passed) if gate.passed else "<p class=\"muted\">No requirement has been completed yet.</p>"
    return f"""
    <div class="gate-progress">
      <div class="gate-header"><strong>Current recommendation</strong><span class="{rec_class}">{escape(rec)}</span></div>
      <div class="gate-metrics">
        <div><span>Conversations</span><strong>{gate.conversations}</strong></div>
        <div><span>Strong pain</span><strong>{gate.strong_pain_ratio:.0%}</strong></div>
        <div><span>Price-positive</span><strong>{gate.price_positive_count}</strong></div>
        <div><span>Paid pilots</span><strong>{gate.paid_pilot_count}</strong></div>
        <div><span>Evidence items</span><strong>{len(state.evidence)}</strong></div>
      </div>
      <details><summary>What the evidence already supports</summary>{passed}</details>
      <details open><summary>What still needs evidence</summary>{blockers}</details>
    </div>
    """


def _render_direct_records(state: SystemState, venture_id: str, *, records=None) -> str:
    if not state.direct_validation_records:
        return '<p class="muted small">No direct buyer records yet.</p>'
    rows = []
    for record in (records if records is not None else reversed(state.direct_validation_records[-8:])):
        amount = f"${record.payment_amount:.2f}" if record.payment_amount else "—"
        if record.voided_at is not None:
            status = (
                '<span class="correction-status">Corrected</span>'
                f'<span class="correction-reason">{escape(record.void_reason)}</span>'
            )
        else:
            form_id = f"void-{re.sub(r'[^A-Za-z0-9_-]', '-', record.record_id)}"
            status = (
                f'<form class="void-form" method="post" data-confirm-void action="/v/{quote(venture_id)}/record/{quote(record.record_id)}/void">'
                f'<label for="{escape(form_id, quote=True)}">Correction reason</label>'
                f'<input id="{escape(form_id, quote=True)}" name="reason" minlength="10" maxlength="500" '
                'placeholder="What was entered incorrectly?" required>'
                '<button class="danger" type="submit">Void mistaken entry</button>'
                '</form>'
            )
        rows.append(
            "<tr>"
            f"<td>{escape(record.buyer_identifier or record.buyer_role)}</td>"
            f"<td>{escape(record.pain_strength.title())}</td>"
            f"<td>{'Yes' if record.price_positive else 'No'}</td>"
            f"<td>{escape(record.payment_status.title())}</td>"
            f"<td>{escape(amount)}</td>"
            f"<td>{status}</td>"
            "</tr>"
        )
    return (
        '<div class="table-wrap"><table><thead><tr><th>Buyer</th><th>Pain</th><th>Price +</th><th>Payment</th><th>Amount</th><th>Correction</th></tr></thead>'
        '<tbody>' + "".join(rows) + "</tbody></table></div>"
    )


def _render_audit_trail(state: SystemState, venture_id: str) -> str:
    friendly_decisions = {
        ValidationDecision.GO: "Go Build",
        ValidationDecision.KILL: "Stop",
        ValidationDecision.PIVOT: "Pivot",
        ValidationDecision.CONTINUE_VALIDATION: "Continue testing",
    }
    decisions = []
    for item in reversed(state.decision_log[-5:]):
        decisions.append(
            "<tr>"
            f"<td>{escape(friendly_decisions[item.decision])}</td>"
            f"<td>{escape(friendly_decisions[item.gate_recommendation])}</td>"
            f"<td>{escape(item.created_at.isoformat(timespec='seconds'))}</td>"
            "</tr>"
        )
    decision_html = (
        '<div class="table-wrap"><table><thead><tr><th>Recorded decision</th><th>Recommendation at the time</th><th>Recorded</th></tr></thead><tbody>'
        + "".join(decisions) + "</tbody></table></div>"
        if decisions else '<p class="muted small">No accepted final decisions yet.</p>'
    )
    active_evidence = [item for item in state.evidence if item.voided_at is None and not item.linkage_review_required]
    needs_review = sum(item.linkage_review_required and item.voided_at is None for item in state.evidence)
    review_note = f'<p class="callout caution">{needs_review} older evidence item(s) need linkage review and are excluded from active evidence.</p>' if needs_review else ""
    level5 = sum(1 for item in active_evidence if int(item.evidence_level) == 5)
    corrected = sum(1 for record in state.direct_validation_records if record.voided_at is not None)
    correction_note = (
        f" {corrected} mistaken buyer record(s) are preserved as corrected and excluded from the current recommendation."
        if corrected else ""
    )
    post_decision_records = (
        '<h3>Direct evidence history</h3>' + _render_direct_records(state, venture_id)
        if state.direct_validation_records and state.validation_decision is not None else ""
    )
    return f"""
    <section class="panel">
      <span class="eyebrow">AUDIT TRAIL</span>
      <h2>Evidence and decisions are preserved.</h2>
      <p class="muted">{len(state.evidence)} evidence item(s) are preserved; {len(active_evidence)} remain active, including {level5} verified payment item(s). Public research, buyer conversations, and payments remain distinguishable.{escape(correction_note)}</p>
      {review_note}<p><a href="/v/{quote(venture_id)}/history">Complete evidence history and corrections</a></p>
      {decision_html}{post_decision_records}
    </section>
    """


@app.get("/.well-known/assetlinks.json", include_in_schema=False)
def digital_asset_links():
    package_name = os.getenv("GOOGLE_PLAY_PACKAGE_NAME", "").strip()
    raw_fingerprint = os.getenv("PLAY_APP_SIGNING_SHA256", "").strip()
    compact = re.sub(r"[:\s-]", "", raw_fingerprint)
    if not re.fullmatch(r"[0-9A-Fa-f]{64}", compact) or not re.fullmatch(
        r"[A-Za-z][A-Za-z0-9_]*(?:\.[A-Za-z][A-Za-z0-9_]*)+", package_name
    ):
        return JSONResponse({"error": "Digital Asset Links is not configured."}, status_code=503)
    fingerprint = ":".join(compact.upper()[i : i + 2] for i in range(0, 64, 2))
    return JSONResponse(
        [{
            "relation": ["delegate_permission/common.handle_all_urls"],
            "target": {
                "namespace": "android_app",
                "package_name": package_name,
                "sha256_cert_fingerprints": [fingerprint],
            },
        }],
        headers={"Cache-Control": "public, max-age=300"},
    )


@app.get("/manifest.webmanifest", include_in_schema=False)
def manifest():
    return FileResponse(
        STATIC_DIR / "manifest.webmanifest",
        media_type="application/manifest+json",
        headers={"Cache-Control": "public, max-age=3600"},
    )


@app.get("/service-worker.js", include_in_schema=False)
def service_worker():
    return FileResponse(
        STATIC_DIR / "service-worker.js",
        media_type="application/javascript",
        headers={"Cache-Control": "no-cache", "Service-Worker-Allowed": "/"},
    )


@app.get("/offline", response_class=HTMLResponse, include_in_schema=False)
def offline():
    body = """
    <section class="hero compact">
      <img class="offline-art" src="/static/brand/offline-room.jpg" alt="" width="420" height="220">
      <span class="eyebrow">OFFLINE MODE</span>
      <h1>Killgate is still here.</h1>
      <p>Your connection is not. Reconnect before running research or saving a new decision.</p>
      <a class="button-link" href="/">Try again</a>
    </section>
    """
    return page("Offline · Killgate", body, page_class="offline-page")


@app.get("/how-it-works", response_class=HTMLResponse)
def how_it_works(request: Request):
    user = _session(request).user
    action_href = "/#new-idea" if user else "/signup"
    action_label = "Start an idea" if user else "Create a private workspace"
    body = f"""
    <section class="hero compact explainer-hero">
      <span class="eyebrow">KILLGATE IN PLAIN ENGLISH</span>
      <h1>Decide what an idea has earned before you build it.</h1>
      <p>Killgate organizes public evidence and real buyer proof around one clear business idea, then helps you choose the next responsible action.</p>
      <a class="button-link" href="{action_href}">{action_label}</a>
    </section>
    {_render_product_explainer("product-journey")}
    <section class="panel">
      <span class="eyebrow">WHAT YOU RECEIVE</span>
      <h2>A decision trail you can inspect.</h2>
      <ul>
        <li>A locked validation plan before research begins.</li>
        <li>An optional public-research report with supporting evidence, caution signals, and source links.</li>
        <li>A practical guide for conversations that only real buyers can answer.</li>
        <li>A private record of evidence, corrections, commitments, and decisions.</li>
        <li>A clear recommendation: build, keep testing, change direction, or stop.</li>
      </ul>
      <p class="callout">Killgate shows the evidence and reasons you need to understand a result. Its private analysis instructions, source-screening methods, and service safeguards stay on the server.</p>
    </section>
    """
    return page("How Killgate works", body, page_class="explainer-page", user=user)


@app.get("/", response_class=HTMLResponse)
def home(request: Request, idea: str = "", protocol: str = "", archive_page: int = Query(1, ge=1, le=100000)):
    session = _session(request)
    if not session.user:
        return _login_redirect(request)
    user = session.user
    active_states = list_states(owner_id=user.user_id, access_token=user.access_token, archived=False)
    archive_states = list_states(
        owner_id=user.user_id, access_token=user.access_token,
        archived=True, limit=21, offset=(archive_page - 1) * 20,
    )
    items = ""
    for vid, state in active_states + archive_states[:20]:
        ensure_validation_contract(state)

        if state.phase == Phase.KILL:
            badge = '<span class="status status-kill">Stopped</span>'
        elif state.validation_decision == ValidationDecision.GO:
            badge = f'<span class="status status-pass">{escape(public_gate_label(state)).replace("_", " ")}</span>'
        elif state.research_pass:
            badge = '<span class="status status-pass">Public research complete</span>'
        else:
            badge = '<span class="status status-checking">Validation active</span>'

        hypothesis = escape(state.hypothesis)
        preview = hypothesis[:135] + ("…" if len(hypothesis) > 135 else "")
        safe_vid = escape(vid)
        archive_bit = '<span class="muted small">Archived</span>' if is_archived(state) else f'<span class="muted small">Active validation · Day {state.current_day}</span>'
        items += f"""
        <article class="venture-card">
          <div class="venture-topline"><a href="/v/{quote(vid)}"><strong>{safe_vid}</strong></a>{badge}</div>
          <p>{preview}</p>{archive_bit}
        </article>"""

    if not items:
        items = '<div class="empty-state"><strong>No ideas here yet.</strong><span>Your first validation will appear here.</span></div>'

    if archive_page > 1 or len(archive_states) > 20:
        links = []
        if archive_page > 1:
            links.append(f'<a href="/?archive_page={archive_page - 1}#ideas">Newer archived ideas</a>')
        if len(archive_states) > 20:
            links.append(f'<a href="/?archive_page={archive_page + 1}#ideas">Older archived ideas</a>')
        items += '<nav aria-label="Archived ideas">' + ' · '.join(links) + '</nav>'
    slots = slot_status(active_states)
    slot_note = f'<p class="muted small">Active validations: {slots["used"]}/{slots["max"]}. Archive an active idea to open a spot. Related revisions stay together and do not use another spot.</p>'
    prefill = (_protocol_idea(protocol) or idea.strip())[:MAX_SHARED_IDEA_LENGTH]
    intake_note = '<p class="intake-note" role="status">Shared idea loaded. Review it, then start the test.</p>' if prefill else ""

    body = f"""
    <section class="hero">
      <span class="eyebrow">KILLGATE</span>
      <h1>Ideas are easy.<br><span class="brand-accent">Evidence is rare.</span></h1>
      <p>Killgate tests your idea against real-world reality.</p>
      {slot_note}
    </section>
    <div class="promo-gate-art" aria-hidden="true"></div>
    <section class="panel intake-panel" id="new-idea" aria-labelledby="new-idea-title">
      <div class="section-heading"><span class="step-number">01</span><div><h2 id="new-idea-title">What's your idea?</h2><p>Describe your business idea and we'll turn it into a testable hypothesis.</p></div></div>
      {intake_note}
      <form method="post" action="/new">
        <label for="idea">Describe your business idea and we'll turn it into a testable hypothesis.</label>
        <textarea id="idea" name="idea" rows="5" minlength="10" maxlength="8000" aria-describedby="idea-help idea-count idea-file-status idea-preflight-privacy" placeholder="Example: Independent auto shops miss calls while technicians are busy. I want to sell them an AI receptionist that answers, qualifies the job, and books an appointment." required>{escape(prefill)}</textarea>
        <section class="idea-preflight" id="idea-preflight" data-idea-preflight aria-labelledby="idea-preflight-title" tabindex="-1" hidden>
          <div class="idea-preflight-heading"><span class="eyebrow">IDEA PREFLIGHT</span><h3 id="idea-preflight-title">Make the test specific before you lock it.</h3></div>
          <p class="idea-preflight-summary" data-idea-preflight-summary role="status" aria-live="polite"></p>
          <ul class="preflight-checks" aria-label="Testable-idea ingredients">
            <li data-idea-preflight-check="buyer"><span class="preflight-marker" aria-hidden="true" data-idea-preflight-marker>○</span><div><strong>Named buyer</strong><p data-idea-preflight-detail>Who specifically has the problem?</p></div></li>
            <li data-idea-preflight-check="problem"><span class="preflight-marker" aria-hidden="true" data-idea-preflight-marker>○</span><div><strong>Costly or repeated problem</strong><p data-idea-preflight-detail>What is going wrong in their real work or life?</p></div></li>
            <li data-idea-preflight-check="offer"><span class="preflight-marker" aria-hidden="true" data-idea-preflight-marker>○</span><div><strong>Offer or change</strong><p data-idea-preflight-detail>What would you sell or change for that buyer?</p></div></li>
            <li data-idea-preflight-check="economics"><span class="preflight-marker" aria-hidden="true" data-idea-preflight-marker>○</span><div><strong>Economics or outcome</strong><p data-idea-preflight-detail>What price, cost, time, or measurable result matters?</p></div></li>
          </ul>
          <p class="preflight-next" data-idea-preflight-next></p>
          <p class="muted small" id="idea-preflight-privacy">This is a writing check, not a demand score. It runs only in this browser: no research is retrieved, nothing is saved, and your validation plan does not change until you continue.</p>
        </section>
        <div class="form-footer"><div class="idea-meta"><span id="idea-help" class="muted small">Minimum 10 characters</span><span id="idea-count" class="muted small" data-idea-count>0 / 8,000 characters</span><span id="idea-file-status" class="muted small" data-file-status role="status" aria-live="polite"></span></div><div class="idea-actions"><button class="secondary-button" type="button" data-idea-preflight-trigger aria-controls="idea-preflight" aria-expanded="false">Check the idea first</button><button type="submit" data-idea-submit>Start Validation <span aria-hidden="true">→</span></button></div></div>
      </form>
    </section>
    {_render_product_explainer("home-product-journey")}
    {_render_sample_reactions("idea-reactions")}
    {_render_sample_reports("idea-sample-reports", limit=4)}
    <section id="ideas" aria-labelledby="ideas-title">
      <div class="section-heading list-heading"><span class="step-number">02</span><div><h2 id="ideas-title">Your ideas</h2><p>Reopen an idea to review its validation plan, evidence, next action, or decision.</p></div></div>
      <div class="venture-grid">{items}</div>
    </section>
    """
    return page("Killgate · Validate Before You Build", body, page_class="home-page", user=user)


@app.post("/share", include_in_schema=False)
def receive_share(title: str = Form(""), text: str = Form(""), url: str = Form("")):
    idea = _shared_idea(title, text, url)
    target = f"/?idea={quote(idea)}#new-idea" if idea else "/#new-idea"
    return RedirectResponse(target, status_code=303)


@app.post("/new")
def new_idea(request: Request, idea: str = Form(...)):
    session = _session(request)
    if not session.user:
        return _login_redirect(request)
    user = session.user
    try:
        new_idea_allowed = limiter.allow(f"new:{user.user_id}", Limit(20, 3600))
    except RateLimitUnavailable:
        return HTMLResponse("Idea creation is temporarily unavailable. Try again shortly.", status_code=503)
    if not new_idea_allowed:
        return HTMLResponse("Too many new-idea requests. Try again later.", status_code=429)
    idea = idea.strip()[:MAX_SHARED_IDEA_LENGTH]
    if len(idea) < 10:
        return RedirectResponse("/#new-idea", status_code=303)
    venture_id = new_venture_id()
    state = SystemState(current_day=1, phase=Phase.VALIDATION, hypothesis=idea)
    ensure_validation_contract(state)  # lock the rules before any evidence exists
    state.metrics["pass_family_id"] = venture_id
    if not create_state_with_slot(venture_id, state, owner_id=user.user_id, access_token=user.access_token):
        return HTMLResponse(SLOT_FULL_MESSAGE, status_code=409)
    return RedirectResponse(f"/v/{venture_id}/brief", status_code=303)



def _owned_states(user) -> list[tuple[str, SystemState]]:
    return list_states(owner_id=user.user_id, access_token=user.access_token)

def _family_id(state: SystemState, venture_id: str) -> str:
    return str(state.metrics.get("pass_family_id") or venture_id).strip() or venture_id


def _render_offer_cards(
    next_path: str = "/account",
    *,
    family_id: str = "",
    active_subscription: bool = False,
) -> str:
    cards = []
    by_env = {item["sku_env"]: item for item in catalog_with_ids()}
    for sku_env in hero_cta_order():
        item = by_env.get(sku_env)
        if not item:
            continue
        if item.get("requires_family") and not family_id:
            continue
        if item.get("requires_active_subscription") and not active_subscription:
            continue
        product_id = item["product_id"]
        price_note = "Play localized price"
        if item["kind"] == "subscription":
            price_note = "Monthly · Play localized price"
        family_attr = f' data-family-id="{escape(family_id, quote=True)}"' if family_id else ""
        button = ""
        dev_local = (
            os.getenv("BILLING_ENFORCED", "0").strip() != "1"
            and os.getenv("APP_ENV", "development").strip().lower() != "production"
            and not billing_enabled()
        )
        if dev_local:
            button = (
                f'<form method="post" action="/billing/local-grant">'
                f'<input type="hidden" name="kind" value="{escape(item["kind"], quote=True)}">'
                f'<input type="hidden" name="family_id" value="{escape(family_id, quote=True)}">'
                f'<input type="hidden" name="next" value="{escape(next_path, quote=True)}">'
                f'<button type="submit">Grant local {escape(item["title"])} (dev only)</button></form>'
            )
        elif product_id:
            button = (
                f'<div class="billing-panel" data-play-billing data-product-id="{escape(product_id, quote=True)}" '
                f'data-product-kind="{escape(item["kind"], quote=True)}"{family_attr}>'
                f'<p class="billing-price" data-billing-price></p>'
                f'<button type="button" data-play-subscribe>Buy with Google Play</button>'
                f'<p class="muted small" data-billing-detail></p></div>'
            )
        cards.append(
            f'<article class="panel offer-card" data-offer-kind="{escape(item["kind"], quote=True)}">'
            f'<span class="eyebrow">{escape(item["kind"].replace("_", " ").upper())}</span>'
            f'<h3>{escape(item["title"])}</h3>'
            f'<p class="price-label">{escape(price_note)}</p>'
            f'<p>{escape(item["blurb"])}</p>{button}</article>'
        )
    return '<div class="offer-grid">' + "".join(cards) + "</div>"


@app.get("/v/{venture_id}/brief", response_class=HTMLResponse)
def research_brief_page(request: Request, venture_id: str, billing: str = ""):
    session = _session(request)
    if not session.user:
        return _login_redirect(request)
    user = session.user
    state = load_state(venture_id, owner_id=user.user_id, access_token=user.access_token)
    if not state:
        return HTMLResponse("Idea not found", status_code=404)
    if state.validation_contract is None:
        ensure_validation_contract(state)
        state.metrics.setdefault("pass_family_id", venture_id)
        save_state(venture_id, state, owner_id=user.user_id, access_token=user.access_token)
    brief = build_research_brief(state)
    family = _family_id(state, venture_id)
    try:
        wallet = load_wallet(user.user_id)
        access = research_access(user.user_id, family)
    except WalletStoreUnavailable:
        return HTMLResponse("Paid research status is temporarily unavailable. Try again shortly.", status_code=503)
    try:
        active_pro = entitlement_is_current(get_entitlement(user.user_id, user.access_token))
    except BillingUnavailable:
        active_pro = False
    assumptions = "".join(f"<li>{escape(item)}</li>" for item in brief["critical_assumptions"])
    human = brief["human_gate"]
    billing_note = ""
    if billing == "required":
        billing_note = '<p class="callout caution">Live research is paid. This page is the work order. No sources have been retrieved.</p>'
    elif access.get("beta"):
        billing_note = '<p class="callout">Beta access is active: up to 9 free live research runs during the 14-day beta window.</p>'
    bind_html = ""
    open_passes = unbound_passes(wallet)
    if open_passes and family_credits(wallet, family) < 1:
        options = "".join(
            f'<option value="{escape(item.pass_id, quote=True)}">{escape(item.pass_id)} · {item.credits_remaining} runs left</option>'
            for item in open_passes
        )
        bind_html = (
            f'<form method="post" action="/v/{quote(venture_id)}/bind-pass">'
            f'<label for="pass_id">Attach a Venture Pass to this idea family</label>'
            f'<select id="pass_id" name="pass_id" required><option value="">Choose a pass</option>{options}</select>'
            f'<button type="submit">Attach pass</button></form>'
        )
    run_html = ""
    if access.get("ok") and not state.metrics.get("last_research"):
        run_html = (
            f'<form method="post" action="/v/{quote(venture_id)}/run">'
            f'<button type="submit">Run live public research</button></form>'
        )
    elif state.metrics.get("last_research"):
        run_html = f'<p><a class="button-link" href="/v/{quote(venture_id)}">Open the research result</a></p>'
    credit_line = (
        f'<p class="muted">Credits on this idea family: {family_credits(wallet, family)}. '
        f'Unbound wallet/subscription credits: {wallet.wallet_credits + wallet.subscription_credits}.</p>'
    )
    body = f"""
    <nav class="back-nav"><a href="/#ideas">← All ideas</a> · <a href="/v/{quote(venture_id)}">Workspace</a></nav>
    <section class="hero compact">
      <img class="brief-art" src="/static/brand/brief-document.jpg" alt="" width="420" height="220">
      <span class="eyebrow">FREE TEST-PLAN PREVIEW</span>
      <h1>Know what will be tested before you buy research.</h1>
      <p>This page explains the question, evidence, and next steps. No sources have been retrieved and no research credit has been used.</p>
    </section>
    {billing_note}
    <section class="panel">
      <span class="eyebrow">THE QUESTION</span>
      <h2>Your idea is now locked for this validation.</h2>
      <p class="research-copy">{escape(brief["hypothesis"])}</p>
      <p class="muted small">Price in your draft: {escape(str(brief["stated_price"]))}</p>
      <h3>What must be true for the idea to work</h3><ul>{assumptions}</ul>
      <p class="muted small">A materially different buyer, problem, offer, or price should start a new validation instead of rewriting this one after results arrive.</p>
    </section>
    <section class="panel">
      <span class="eyebrow">WHAT LIVE RESEARCH DELIVERS</span>
      <h2>A public-evidence report you can inspect.</h2>
      <p>A Venture Pass covers one validation cycle for this idea and legitimate changes that grow from it. It buys research, evidence, and a clear public-evidence result—not a promise that the idea will succeed.</p>
      <ul>
        <li>Evidence that the stated problem appears in the real world.</li>
        <li>Current workarounds, alternatives, prices, and practical constraints.</li>
        <li>Reasons the idea may be weaker or riskier than it first appears.</li>
        <li>Source links and a plain-language explanation of what the public evidence supports.</li>
      </ul>
      <p class="muted small">You see the evidence and reasons needed to understand the result. Killgate's private research instructions and screening process remain on the server.</p>
    </section>
    <section class="panel">
      <span class="eyebrow">WHAT HAPPENS AFTER THE REPORT</span>
      <h2>Only real buyers can prove demand.</h2>
      <p>Public research can show whether an idea deserves buyer testing, needs a change, lacks enough evidence, or depends on a capability that must be tested first. It cannot prove that customers will pay.</p>
      <p class="callout">A Go Build decision still needs at least {int(human["min_direct_conversations"])} unique qualified buyers, {float(human["min_strong_pain_ratio"]):.0%} strong recent pain, {int(human["min_price_positive_count"])} price-positive records, and {int(human["min_actual_paid_pilots"])} verified paid pilots.</p>
      <p>Killgate provides the interview guide and records the evidence. You provide the real conversations, commitments, and payment proof.</p>
    </section>
    <section class="panel">
      <span class="eyebrow">START LIVE RESEARCH</span>
      <h2>Choose research access only when the test plan looks right.</h2>
      {credit_line}{bind_html}{run_html}
      {_render_offer_cards(f"/v/{venture_id}/brief", family_id=family, active_subscription=active_pro)}
      <p class="muted small">Most founders only need a Venture Pass. Extra Evidence Runs stay with this idea. Founder Pro is optional and intended for people validating ideas regularly.</p>
    </section>
    """
    return page(f"Brief · {venture_id} · Killgate", body, page_class="brief-page", user=user)



@app.post("/v/{venture_id}/archive")
def archive_venture(request: Request, venture_id: str):
    session = _session(request)
    if not session.user:
        return _login_redirect(request)
    user = session.user
    state = load_state(venture_id, owner_id=user.user_id, access_token=user.access_token)
    if not state:
        return HTMLResponse("Idea not found", status_code=404)
    archive_state(state)
    save_state(venture_id, state, owner_id=user.user_id, access_token=user.access_token)
    return RedirectResponse("/#ideas", status_code=303)


@app.post("/v/{venture_id}/unarchive")
def unarchive_venture(request: Request, venture_id: str):
    session = _session(request)
    if not session.user:
        return _login_redirect(request)
    user = session.user
    state = load_state(venture_id, owner_id=user.user_id, access_token=user.access_token)
    if not state:
        return HTMLResponse("Idea not found", status_code=404)
    if not is_archived(state):
        return RedirectResponse(f"/v/{quote(venture_id)}", status_code=303)
    unarchive_state(state)
    if not save_unarchived_state_with_slot(venture_id, state, owner_id=user.user_id, access_token=user.access_token):
        return HTMLResponse(SLOT_FULL_MESSAGE, status_code=409)
    return RedirectResponse(f"/v/{quote(venture_id)}", status_code=303)


@app.get("/v/{venture_id}/packet.json")
def download_packet(request: Request, venture_id: str):
    session = _session(request)
    if not session.user:
        return _login_redirect(request)
    user = session.user
    state = load_state(venture_id, owner_id=user.user_id, access_token=user.access_token)
    if not state:
        return HTMLResponse("Idea not found", status_code=404)
    packet = build_evidence_packet(venture_id, state)
    filename = f"killgate-{slug_for_packet(public_gate_label(state))}-{slug_for_packet(state.hypothesis)}.json"
    return JSONResponse(packet, headers={"Content-Disposition": f'attachment; filename="{filename}"'})


@app.get("/v/{venture_id}/deep-research.json")
def download_deep_research_report(request: Request, venture_id: str):
    """Download the immutable snapshot, with rollout-safe state fallback."""
    session = _session(request)
    if not session.user:
        return _login_redirect(request)
    state = load_state(venture_id, owner_id=session.user.user_id, access_token=session.user.access_token)
    if not state:
        return JSONResponse({"error": "not_found"}, status_code=404)
    report = state.metrics.get("deep_research_report")
    if not isinstance(report, dict):
        return JSONResponse({"error": "deep_research_not_available"}, status_code=404)
    snapshot = None
    snapshot_run_id = str(report.get("run_id") or "").strip()
    if snapshot_run_id:
        try:
            snapshot = load_research_snapshot(run_id=snapshot_run_id, user_id=session.user.user_id)
        except DeepResearchStoreUnavailable:
            # Older deployments may not have the additive snapshot table yet;
            # preserve the already authenticated venture-state export during
            # the migration rollout rather than failing the customer export.
            snapshot = None
    export_payload = snapshot.model_dump(mode="json") if snapshot is not None else report
    filename = f"killgate-deep-research-{slug_for_packet(state.hypothesis)}.json"
    return JSONResponse(export_payload, headers={"Content-Disposition": f'attachment; filename="{filename}"'})


@app.get("/v/{venture_id}/deep-research-status.json")
def deep_research_status(request: Request, venture_id: str):
    """Return owner-safe lifecycle state without exposing research internals."""
    session = _session(request)
    if not session.user:
        return _login_redirect(request)
    state = load_state(venture_id, owner_id=session.user.user_id, access_token=session.user.access_token)
    if not state:
        return JSONResponse({"error": "not_found"}, status_code=404)
    run_id = str(state.metrics.get("research_run_id") or "").strip()
    if not run_id:
        return JSONResponse({"error": "deep_research_not_available"}, status_code=404)
    fallback_status = str(state.metrics.get("research_run_status") or "pending")
    status = fallback_status
    report_available = isinstance(state.metrics.get("deep_research_report"), dict)
    terminal_failure = ""
    try:
        run = load_research_run(run_id=run_id, user_id=session.user.user_id)
    except DeepResearchStoreUnavailable:
        run = None
    if run is not None:
        status = run.status.value
        report_available = report_available or bool(run.report)
        if run.status.value in {"failed", "cancelled"}:
            terminal_failure = "research_unavailable"
    terminal = status in {"completed", "failed", "cancelled", "delivered"}
    return JSONResponse(
        {
            "run_id": run_id,
            "status": status,
            "terminal": terminal,
            "report_available": report_available,
            "failure": terminal_failure or None,
        }
    )

@app.post("/v/{venture_id}/bind-pass")
def bind_pass_route(request: Request, venture_id: str, pass_id: str = Form(...)):
    session = _session(request)
    if not session.user:
        return _login_redirect(request)
    user = session.user
    state = load_state(venture_id, owner_id=user.user_id, access_token=user.access_token)
    if not state:
        return HTMLResponse("Idea not found", status_code=404)
    family = _family_id(state, venture_id)
    wallet = load_wallet(user.user_id)
    bind_pass(wallet, pass_id.strip(), family)
    return RedirectResponse(f"/v/{quote(venture_id)}/brief", status_code=303)


@app.get("/v/{venture_id}", response_class=HTMLResponse)
def venture(request: Request, venture_id: str):
    session = _session(request)
    if not session.user:
        return _login_redirect(request)
    user = session.user
    state = load_state(venture_id, owner_id=user.user_id, access_token=user.access_token)
    if not state:
        return HTMLResponse("Idea not found", status_code=404)
    if state.validation_contract is None:
        ensure_validation_contract(state)
        save_state(venture_id, state, owner_id=user.user_id, access_token=user.access_token)

    decision = public_gate_label(state) if (state.validation_decision or state.metrics.get("last_research")) else "Pending"
    last_research = state.metrics.get("last_research_plain", "")
    last_rec = state.metrics.get("last_research", "")
    last_dis = state.metrics.get("last_disconfirming", []) or []
    last_sup = state.metrics.get("last_supporting", []) or []
    hit_count = state.metrics.get("search_hit_count", 0)
    direct_count = state.metrics.get("direct_source_count", 0)
    domain_count = state.metrics.get("independent_domain_count", 0)
    sample_urls = state.metrics.get("sample_urls", []) or []
    rejected = state.metrics.get("rejected_by_evaluator", False)
    approval_error = state.metrics.get("approval_error", "")
    evidence_note = state.metrics.get("last_evidence_note", "")
    feasibility_test = state.metrics.get("last_feasibility_test") or {}
    feasibility_status = str(state.metrics.get("feasibility_status") or "pending").lower()
    feasibility_evidence = str(state.metrics.get("feasibility_evidence_reference") or "")
    feasibility_notes = str(state.metrics.get("feasibility_notes") or "")

    contract_html = _render_contract(state)

    research_html = ""
    if last_research:
        rec_upper = str(last_rec).upper()
        recommendation_class = "verdict-pass" if "PASS" in rec_upper else "verdict-caution"
        if "FAIL" in rec_upper:
            recommendation_class = "verdict-caution"
        recommendation_title = {
            "RESEARCH_PASS": "Public evidence supports buyer testing",
            "RESEARCH_FAIL": "More public evidence is needed",
            "RESEARCH_PIVOT": "Change the idea before more testing",
            "FEASIBILITY_REQUIRED": "Test a critical capability first",
        }.get(rec_upper, "Public evidence review complete")
        source_summary = (
            f"Killgate reviewed {hit_count} public results and retained {direct_count} relevant sources "
            f"across {domain_count} independent sites. The links below show what supports this result. "
            "Public information is useful background, but it is not proof that customers will buy."
        )
        supporting_html = "<h3>Supporting signals</h3>" + _list(last_sup) if last_sup else ""
        disconfirming_html = "<h3>Reasons for caution</h3>" + _list(last_dis) if last_dis else ""
        public_reasons = {
            "RESEARCH_PASS": [
                "The retained sources directly address the buyer and problem in this idea.",
                "The public evidence is strong enough to justify testing the offer with real buyers.",
            ],
            "RESEARCH_FAIL": [
                "The available public evidence is not strong or relevant enough to justify buyer testing yet.",
                "More evidence or a clearer idea is needed before moving forward.",
            ],
            "RESEARCH_PIVOT": [
                "The evidence points to changing the buyer, problem, offer, price, or approach before more testing.",
            ],
            "FEASIBILITY_REQUIRED": [
                "The offer depends on a critical capability that must be proven before price testing is meaningful.",
            ],
        }.get(rec_upper, ["The result reflects the relevant public evidence currently available."])
        rules_html = "<h3>Why Killgate reached this result</h3>" + _list(public_reasons)
        urls_html = ""
        if sample_urls:
            urls_html = "<h3>Sources used in this result</h3><ul>" + "".join(
                f'<li><a href="{escape(str(url), quote=True)}" target="_blank" rel="noopener">{escape(str(url))}</a></li>'
                for url in sample_urls[:5]
            ) + "</ul>"
        rejected_html = (
            '<p class="verdict-caution">A weak positive signal did not meet the evidence standard, '
            "so Killgate kept the result cautious.</p>"
            if rejected
            else ""
        )
        insufficiency_note = ""
        if "FAIL" in rec_upper:
            insufficiency_note = (
                '<p class="callout caution">The public evidence is not strong enough to move forward yet. '
                "That does not prove demand is absent.</p>"
            )
        if rec_upper == "FEASIBILITY_REQUIRED":
            insufficiency_note = (
                '<p class="callout caution"><strong>Capability test required:</strong> prove the critical '
                "capability this offer depends on before asking buyers to pay.</p>"
            )

        feasibility_html = ""
        if rec_upper == "FEASIBILITY_REQUIRED" and feasibility_test:
            def _fi_list(key: str) -> str:
                values = feasibility_test.get(key, []) or []
                return _list([str(v) for v in values]) if values else '<p class="muted">Not supplied.</p>'
            status_copy = {
                "passed": '<p class="callout"><strong>Capability test passed.</strong> Buyer testing is now available for this unchanged idea.</p>',
                "failed": '<p class="callout caution"><strong>Capability test failed.</strong> Change the approach or stop this idea before buyer-price testing.</p>',
            }.get(feasibility_status, '<p class="callout caution"><strong>Capability test pending.</strong> Prove this critical capability before testing willingness to pay.</p>')
            form_html = ""
            if feasibility_status == "pending":
                form_html = (
                    f'<form class="evidence-form" method="post" action="/v/{quote(venture_id)}/feasibility">'
                    '<label for="feasibility_result">Did the capability meet the test standard?</label>'
                    '<select id="feasibility_result" name="result" required><option value="">Choose</option><option value="PASS">PASS</option><option value="FAIL">FAIL</option></select>'
                    '<label for="feasibility_evidence_reference">Evidence/reference</label>'
                    '<input id="feasibility_evidence_reference" name="evidence_reference" maxlength="1000" placeholder="Dataset/run/report/reference that lets you verify the test" required>'
                    '<label for="feasibility_notes">What happened</label>'
                    '<textarea id="feasibility_notes" name="notes" rows="3" maxlength="3000" required></textarea>'
                    '<button type="submit">Record capability test result</button></form>'
                )
            evidence_copy = f'<p class="muted small">Recorded evidence: {escape(feasibility_evidence)}</p>' if feasibility_evidence else ""
            notes_copy = f'<p>{escape(feasibility_notes)}</p>' if feasibility_notes else ""
            feasibility_html = (
                '<section class="panel feasibility-panel"><span class="eyebrow">CRITICAL CAPABILITY TEST</span>'
                f'<h2>{escape(str(feasibility_test.get("capability", "Critical capability test")))}</h2>'
                f'<p>{escape(str(feasibility_test.get("why_load_bearing", "")))}</p>{status_copy}{evidence_copy}{notes_copy}'
                f'<h3>What the test may use</h3>{_fi_list("decision_time_inputs")}'
                f'<h3>What later confirms the result</h3><p>{escape(str(feasibility_test.get("later_ground_truth", "")))}</p>'
                f'<h3>What to measure</h3>{_fi_list("metrics")}<h3>What to compare it with</h3>{_fi_list("baselines")}'
                f'<h3>What counts as a pass</h3>{_fi_list("pass_thresholds")}<h3>What counts as a failure</h3>{_fi_list("fail_thresholds")}'
                f'{form_html}</section>'
            )
        research_html = f"""
        <section class="panel research-result">
          <span class="eyebrow">PUBLIC EVIDENCE RESULT</span><h2 class="{recommendation_class}">{escape(recommendation_title)}</h2>
          <p class="muted">{escape(source_summary)}</p>{insufficiency_note}{rejected_html}
          <div class="research-copy">{escape(str(last_research))}</div>{supporting_html}{disconfirming_html}{rules_html}{urls_html}
        </section>{feasibility_html}"""

    reality_html = ""
    if state.research_pass and state.validation_decision is None:
        plan = generate_reality_check_plan(state)
        questions = ""
        for index, question in enumerate(plan.questions, 1):
            questions += f'<div class="question"><span>{index:02d}</span><div><strong>{escape(str(question.get("question", "")))}</strong><p>{escape(str(question.get("why", "")))}</p></div></div>'
        reality_html = f"""
        <section class="panel reality-panel">
          <span class="eyebrow">BUYER PROOF</span><h2>Now test what only real customers can prove.</h2>
          <p>{escape(plan.intro)}</p><div class="question-list">{questions}</div><p class="callout">{escape(plan.plain_instructions)}</p>
          {_render_gate_progress(state)}
          {f'<p class="callout">{escape(str(evidence_note))}</p>' if evidence_note else ''}
          <h3>Record a qualified buyer conversation or follow-up</h3><p class="muted small">For a follow-up with the same buyer, reuse the same buyer/company label. Follow-ups update the evidence without increasing the unique-buyer count.</p>
          <form class="evidence-form" method="post" action="/v/{quote(venture_id)}/record">
            <div class="form-grid">
              <div><label for="buyer_identifier">Buyer/company label</label><input id="buyer_identifier" name="buyer_identifier" maxlength="160" placeholder="ABC Plumbing owner #1" required></div>
              <div><label for="buyer_role">Buyer role</label><input id="buyer_role" name="buyer_role" maxlength="160" required></div>
              <div><label for="source_of_lead">Where you found them</label><input id="source_of_lead" name="source_of_lead" maxlength="160"></div>
            </div>
            <label for="qualification_basis">Why this person is a qualified buyer / purchase influencer</label><textarea id="qualification_basis" name="qualification_basis" rows="2" required></textarea>
            <label for="recent_real_example">Recent real example of the problem</label><textarea id="recent_real_example" name="recent_real_example" rows="3" required></textarea>
            <label for="current_workaround">What they actually do today</label><textarea id="current_workaround" name="current_workaround" rows="3" required></textarea>
            <div class="form-grid">
              <div><label for="pain_strength">Pain strength</label><select id="pain_strength" name="pain_strength" required><option value="">Choose</option><option value="none">None</option><option value="weak">Weak</option><option value="moderate">Moderate</option><option value="strong">Strong</option></select></div>
              <div><label for="pilot_price_tested">Pilot price actually offered</label><input id="pilot_price_tested" name="pilot_price_tested" maxlength="80" placeholder="$99"></div>
            </div>
            <label for="price_response">Exact reaction to the price/offer</label><textarea id="price_response" name="price_response" rows="3" required></textarea>
            <div class="form-grid">
              <div><label for="price_positive">Price-positive?</label><select id="price_positive" name="price_positive" required><option value="false">No / unclear</option><option value="true">Yes</option></select></div>
              <div><label for="payment_status">Payment status</label><select id="payment_status" name="payment_status" required><option value="not_asked">Not asked</option><option value="declined">Declined</option><option value="committed">Committed, not paid</option><option value="paid">Paid</option></select></div>
              <div><label for="payment_amount">Amount actually received</label><input id="payment_amount" name="payment_amount" type="number" min="0" step="0.01" inputmode="decimal"></div>
            </div>
            <label for="payment_reference">Payment evidence/reference (required for a paid pilot to count)</label><input id="payment_reference" name="payment_reference" maxlength="500" placeholder="Receipt/invoice/reference ID only — no card or bank details">
            <label for="objection_or_no_reason">Objection / why not now / or type “none stated”</label><textarea id="objection_or_no_reason" name="objection_or_no_reason" rows="2" required></textarea>
            <label for="exact_quote">Most important exact customer quote</label><textarea id="exact_quote" name="exact_quote" rows="2" required></textarea>
            <button type="submit">Save buyer evidence and update the decision</button>
          </form>
          <h3>Recent direct records</h3><p class="muted small">Mistakes are corrected by voiding the original entry with a reason, then recording a new entry. The original remains in the audit trail.</p>{_render_direct_records(state, venture_id)}
        </section>"""

    gate = evaluate_validation_gate(state)
    approval_message = f'<p class="callout caution">{escape(str(approval_error))}</p>' if approval_error else ""
    if state.phase != Phase.KILL and state.validation_decision != ValidationDecision.GO:
        research_completed = bool(state.research_pass or state.metrics.get("last_research"))
        run_button = "" if research_completed else f'<form method="post" action="/v/{quote(venture_id)}/run"><button type="submit">Run live public research <span aria-hidden="true">→</span></button></form>'
        go_button = ""
        if gate.recommendation == ValidationDecision.GO:
            go_button = f'<form method="post" action="/v/{quote(venture_id)}/approve"><input type="hidden" name="decision" value="GO"><button type="submit">Record Go Build decision</button></form>'
        research_recommendation = str(state.metrics.get("last_research") or "").upper()
        pivot_available = (
            research_recommendation in {"RESEARCH_FAIL", "RESEARCH_PIVOT", "FEASIBILITY_REQUIRED"}
            or gate.recommendation in {ValidationDecision.PIVOT, ValidationDecision.KILL}
        )
        pivot_form = ""
        if pivot_available:
            pivot_form = (
                f'<form class="pivot-form" method="post" action="/v/{quote(venture_id)}/pivot">'
                '<label for="pivot_idea">New version of this idea</label>'
                '<textarea id="pivot_idea" name="idea" rows="4" maxlength="8000" '
                'placeholder="Change the buyer, problem, offer, workflow, positioning, channel, or price in a meaningful way." required></textarea>'
                '<button type="submit">Start a new validation for this change</button>'
                '</form>'
            )
        actions = (
            f'{approval_message}<section class="action-stack" aria-label="Idea actions">'
            f'{run_button}{go_button}{pivot_form}'
            f'<form method="post" action="/v/{quote(venture_id)}/approve">'
            '<input type="hidden" name="decision" value="KILL">'
            '<button type="submit" class="danger">Stop this idea</button></form></section>'
        )
    elif state.phase == Phase.KILL:
        actions = '<div class="killed-notice"><strong>Idea stopped.</strong><span>Killgate will not advance this idea unless you create a new version.</span></div>'
    else:
        actions = '<div class="go-notice"><strong>Go Build recorded.</strong><span>The required evidence passed and you explicitly approved the decision.</span></div>'

    pivot_parent = str(state.metrics.get("pivot_parent_venture_id") or "").strip()
    lineage_html = (
        f'<p class="callout">This new version was created from <a href="/v/{quote(pivot_parent)}">{escape(pivot_parent)}</a>. It has its own validation plan and evidence history.</p>'
        if pivot_parent else ""
    )

    label = public_gate_label(state)
    if label == "GO_BUILD" or label == "GO_SELL":
        verdict_src = "/static/brand/gate-go.jpg"
    elif label == "KILL":
        verdict_src = "/static/brand/gate-kill.jpg"
    elif label == "PIVOT":
        verdict_src = "/static/brand/gate-pivot.jpg"
    else:
        verdict_src = "/static/brand/hero-atmosphere.jpg"
    verdict_img = f'<img class="verdict-art" src="{verdict_src}" alt="" width="420" height="220">'
    body = f"""
    <nav class="back-nav"><a href="/#ideas">← All ideas</a> · <a href="/v/{quote(venture_id)}/brief">Test plan</a> · <a href="/v/{quote(venture_id)}/packet.json">Download validation record</a></nav>
    {lineage_html}
    <section class="venture-hero">{verdict_img}<span class="eyebrow">VENTURE {escape(venture_id)}</span><h1>{escape(state.hypothesis)}</h1>
      <div class="metrics"><div><span>Stage</span><strong>{escape(state.phase.value.title())}</strong></div><div><span>Decision</span><strong>{escape(decision.replace('_', ' ').title())}</strong></div><div><span>Day</span><strong>{state.current_day}</strong></div></div>
    </section>
    {contract_html}{research_html}{reality_html}{_render_audit_trail(state, venture_id)}{actions}
    """
    if is_archived(state):
        archive_forms = f'<form method="post" action="/v/{quote(venture_id)}/unarchive"><button type="submit">Unarchive this idea</button></form>'
    else:
        archive_forms = f'<form method="post" action="/v/{quote(venture_id)}/archive"><button type="submit">Archive and free a live slot</button></form>'
    body = body.replace("</nav>", "</nav>\n    " + archive_forms, 1)
    return page(f"{venture_id} · Killgate", body, page_class="venture-page", user=user)



def _reconcile_research(user, venture_id: str, run_id: str, paid: bool) -> str:
    """Confirm delivery before refunding an ambiguous save/debit outcome.

    Both cancellation RPCs are idempotent and also fence delayed requests.
    A durable pending/reconciliation marker prevents a fresh charge on retry.
    """
    try:
        current = load_state(venture_id, owner_id=user.user_id, access_token=user.access_token)
    except StateStoreUnavailable:
        return "pending"
    if not current or current.metrics.get("research_run_id") != run_id:
        return "pending"
    if current.metrics.get("last_research"):
        return "delivered"
    # Fence any still-in-flight result PATCH before refunding. A read alone
    # cannot prove that a timed-out write will not commit a moment later.
    current.metrics["research_run_status"] = "reconciliation"
    try:
        save_state(venture_id, current, owner_id=user.user_id, access_token=user.access_token)
    except (StateStoreUnavailable, StateConflictError):
        return "pending"
    restored = True
    if paid:
        try:
            cancel_research_credit(Wallet(user_id=user.user_id), run_id)
        except WalletStoreUnavailable:
            restored = False
    try:
        limiter.release_research_run(user.user_id, run_id)
    except RateLimitUnavailable:
        restored = False
    current.metrics["research_run_status"] = "failed" if restored else "reconciliation"
    try:
        save_state(venture_id, current, owner_id=user.user_id, access_token=user.access_token)
    except (StateStoreUnavailable, StateConflictError):
        return "pending"
    return "restored" if restored else "pending"


def _research_failure(user, venture_id: str, run_id: str, paid: bool):
    outcome = _reconcile_research(user, venture_id, run_id, paid)
    if outcome == "delivered":
        return RedirectResponse(f"/v/{quote(venture_id)}", status_code=303)
    if outcome == "restored":
        return HTMLResponse(
            "Research is temporarily unavailable. Your included research allowance was restored; try again shortly.",
            status_code=503,
        )
    return HTMLResponse(
        "Research could not be completed or reconciled yet. No new research charge will be started for this idea. "
        f"Contact support with research reference {escape(run_id)}; do not make another purchase to retry.",
        status_code=503,
    )


@app.get("/v/{venture_id}/history", response_class=HTMLResponse)
def evidence_history(request: Request, venture_id: str, history_page: int = Query(1, ge=1, le=100000)):
    session = _session(request)
    if not session.user:
        return _login_redirect(request)
    user = session.user
    state = load_state(venture_id, owner_id=user.user_id, access_token=user.access_token)
    if not state:
        return HTMLResponse("Idea not found", status_code=404)
    records = list(reversed(state.direct_validation_records))
    offset = (history_page - 1) * 20
    table = _render_direct_records(state, venture_id, records=records[offset:offset + 20])
    links = []
    if history_page > 1:
        links.append(f'<a href="?history_page={history_page - 1}">Newer buyer records</a>')
    if len(records) > offset + 20:
        links.append(f'<a href="?history_page={history_page + 1}">Older buyer records</a>')
    review = []
    for item in state.evidence:
        if not item.linkage_review_required or item.voided_at:
            continue
        review.append(
            f'<article><h3>{escape(item.source_title)}</h3><p>{escape(item.raw_quote_or_fact)}</p>'
            f'<p>{escape(item.linkage_review_reason)}</p>'
            f'<form method="post" action="/v/{quote(venture_id)}/evidence/{quote(item.evidence_id)}/void">'
            '<label>Reason for excluding this ambiguous legacy item'
            '<input name="reason" minlength="10" maxlength="500" required></label>'
            '<button class="danger" type="submit">Void legacy item with a reason</button></form></article>'
        )
    body = (
        f'<nav><a href="/v/{quote(venture_id)}">Back to idea</a></nav>'
        '<section class="panel"><h1>Evidence history and corrections</h1>'
        '<p>All buyer records remain reachable here, including corrected entries and evidence behind a final decision.</p>'
        + table + '<nav aria-label="Buyer record pages">' + ' · '.join(links) + '</nav></section>'
        + ('<section class="panel"><h2>Legacy evidence requiring review</h2><p>These items are excluded from active evidence. '
           'Review their original quotes, void an incorrect or ambiguous item with a reason, and record any verified replacement through buyer evidence.</p>'
           + ''.join(review) + '</section>' if review else '')
    )
    return page("Evidence history · Killgate", body, user=user)


@app.post("/v/{venture_id}/evidence/{evidence_id}/void")
def void_legacy_item(request: Request, venture_id: str, evidence_id: str, reason: str = Form(...)):
    session = _session(request)
    if not session.user:
        return _login_redirect(request)
    user = session.user
    try:
        allowed = limiter.allow(f"evidence-correction:{user.user_id}", Limit(30, 3600))
    except RateLimitUnavailable:
        return HTMLResponse("Evidence correction is temporarily unavailable.", status_code=503)
    if not allowed:
        return HTMLResponse("Evidence-correction rate limit reached.", status_code=429)
    state = load_state(venture_id, owner_id=user.user_id, access_token=user.access_token)
    if not state:
        return HTMLResponse("Idea not found", status_code=404)
    matches = [item for item in state.evidence if item.evidence_id == evidence_id]
    cleaned = ' '.join(reason.split())[:500]
    if len(matches) != 1 or not matches[0].linkage_review_required or matches[0].voided_at or len(cleaned) < 10:
        return HTMLResponse("Only an uncorrected legacy-review item can be voided, with a reason of at least 10 characters.", status_code=409)
    matches[0].voided_at = datetime.now(UTC)
    matches[0].void_reason = cleaned
    state.last_updated = datetime.now(UTC)
    save_state(venture_id, state, owner_id=user.user_id, access_token=user.access_token)
    return RedirectResponse(f"/v/{quote(venture_id)}/history", status_code=303)


@app.post("/v/{venture_id}/run")
def run_step(request: Request, venture_id: str):
    session = _session(request)
    if not session.user:
        return _login_redirect(request)
    user = session.user
    state = load_state(venture_id, owner_id=user.user_id, access_token=user.access_token)
    if not state or state.phase == Phase.KILL:
        return RedirectResponse(f"/v/{quote(venture_id)}", status_code=303)
    family = _family_id(state, venture_id)
    # A completed research gate is immutable for this hypothesis. Re-running the
    # same unchanged idea until search/model variance turns green would defeat Killgate.
    if state.research_pass or state.metrics.get("last_research"):
        return RedirectResponse(f"/v/{quote(venture_id)}", status_code=303)
    previous_run = str(
        state.metrics.get("deep_research_previous_run_id")
        or state.metrics.get("research_run_id")
        or ""
    )
    if previous_run and state.metrics.get("research_run_status") == "reconciliation":
        return _research_failure(user, venture_id, previous_run, bool(state.metrics.get("research_run_paid")))
    if previous_run and state.metrics.get("research_run_status") == "pending":
        return HTMLResponse(
            "This research run is already in progress or awaiting reconciliation. No additional credit was used. "
            f"If it does not finish, contact support with research reference {escape(previous_run)}.", status_code=409,
        )
    access = research_access(user.user_id, family)
    if not access.get("ok"):
        return RedirectResponse(f"/v/{quote(venture_id)}/brief?billing=required", status_code=303)

    try:
        if access.get("beta"):
            rolling_limit = int(access["beta_max_runs"])
            rolling_window_seconds = int(access["beta_duration_days"]) * 24 * 3600
        else:
            rolling_limit = research_safety_cap_30d()
            rolling_window_seconds = 30 * 24 * 3600
        attempt_allowed = limiter.allow(f"research-attempt:{user.user_id}", Limit(20, 3600))
    except RateLimitUnavailable:
        return HTMLResponse("Research is temporarily unavailable. Try again shortly.", status_code=503)
    if not attempt_allowed:
        return HTMLResponse("Too many research attempts. Try again later.", status_code=429)

    run_id = str(uuid.uuid4())
    paid = not any(access.get(key) for key in ("dev_bypass", "test_admin", "beta"))
    ensure_validation_contract(state)
    state.metrics.update(research_run_id=run_id, research_run_status="pending", research_run_paid=paid)
    # CAS claims this hypothesis before quota/debit/provider work. Competing
    # requests cannot charge twice or both run the provider against one revision.
    save_state(venture_id, state, owner_id=user.user_id, access_token=user.access_token)
    try:
        reservation = limiter.reserve_research(
            user.user_id,
            hourly_requests=int(os.getenv("RESEARCH_RUNS_PER_HOUR", "8")),
            rolling_30d_requests=rolling_limit,
            rolling_window_seconds=rolling_window_seconds,
            research_run_id=run_id,
        )
    except RateLimitUnavailable:
        return _research_failure(user, venture_id, run_id, paid)
    if reservation is None:
        if _reconcile_research(user, venture_id, run_id, paid) != "restored":
            return _research_failure(user, venture_id, run_id, paid)
        hourly = int(os.getenv("RESEARCH_RUNS_PER_HOUR", "8"))
        rolling = rolling_limit
        if access.get("beta"):
            limit_message = f"The beta allowance is {rolling} free runs during the 14-day beta window."
        else:
            limit_message = f"The API safety ceiling is {rolling} successful runs per rolling 30 days."
        return HTMLResponse(
            f"Research safety limit reached. {limit_message} The hourly limit is {hourly}; paid entitlements are tracked separately.",
            status_code=429,
        )

    debit = None
    if not state.research_pass:
        if paid:
            try:
                debit = consume_research_credit(access["wallet"], family, research_run_id=run_id)
            except WalletStoreUnavailable:
                return _research_failure(user, venture_id, run_id, paid)
            if not debit.get("ok"):
                if _reconcile_research(user, venture_id, run_id, paid) != "restored":
                    return _research_failure(user, venture_id, run_id, paid)
                return RedirectResponse(f"/v/{quote(venture_id)}/brief?billing=required", status_code=303)
        try:
            if deep_research_enabled():
                pipeline = run_deep_research_pipeline(
                    state,
                    user_id=user.user_id,
                    venture_id=venture_id,
                    venture_family_id=family,
                    run_id=run_id,
                    previous_run_id=previous_run or None,
                )
                result = pipeline.legacy_result
                state.metrics["deep_research_report"] = pipeline.report.model_dump(mode="json")
                state.metrics["deep_research_storage_revision"] = pipeline.run.storage_revision
            else:
                result = run_research_pass(state)
        except (ResearchUnavailable, DeepResearchPipelineUnavailable, DeepResearchStoreUnavailable):
            return _research_failure(user, venture_id, run_id, paid)
        except Exception:
            # A programming/provider exception also means no research result was delivered.
            # Restore the paid entitlement before surfacing the unexpected failure.
            _reconcile_research(user, venture_id, run_id, paid)
            raise
        state.metrics["last_research"] = result.recommendation
        state.metrics["research_run_status"] = "delivered"
        state.metrics["last_research_plain"] = result.plain_language
        state.metrics["last_disconfirming"] = result.disconfirming_evidence
        state.metrics["last_supporting"] = result.supporting_evidence
        state.metrics["last_decision_rules"] = result.decision_rule_triggers
        state.metrics.pop("last_kill_criteria", None)
        state.metrics["last_confidence"] = result.confidence
        state.metrics["used_web_search"] = result.used_web_search
        state.metrics["evaluator_notes"] = result.evaluator_notes
        state.metrics["rejected_by_evaluator"] = result.rejected_by_evaluator
        state.metrics["search_hit_count"] = result.search_hit_count
        state.metrics["direct_source_count"] = result.direct_source_count
        state.metrics["indirect_source_count"] = result.indirect_source_count
        state.metrics["irrelevant_source_count"] = result.irrelevant_source_count
        state.metrics["independent_domain_count"] = result.independent_domain_count
        state.metrics["evidence_coverage"] = result.evidence_coverage
        state.metrics["last_mechanism_scoreboard"] = getattr(result, "mechanism_scoreboard", [])
        state.metrics["last_feasibility_test"] = getattr(result, "feasibility_test", None) or {}
        if result.recommendation == "FEASIBILITY_REQUIRED":
            state.metrics["feasibility_status"] = "pending"
            state.metrics.pop("feasibility_evidence_reference", None)
            state.metrics.pop("feasibility_notes", None)
        state.metrics["llm_model"] = result.llm_model
        state.metrics["llm_input_tokens"] = result.llm_input_tokens
        state.metrics["llm_cached_input_tokens"] = result.llm_cached_input_tokens
        state.metrics["llm_output_tokens"] = result.llm_output_tokens
        state.metrics["llm_reasoning_tokens"] = result.llm_reasoning_tokens
        state.metrics["llm_total_tokens"] = result.llm_total_tokens
        state.metrics["sample_urls"] = [item.url for item in result.evidence_items if item.url][:5]
        if debit:
            state.metrics["last_credit_source"] = debit.get("source")
        append_research_evidence(state, result)
        state.metrics.pop("approval_error", None)
        if result.recommendation == "RESEARCH_PASS":
            state.research_pass = True
        state.current_day += 1
        state.last_updated = datetime.now(UTC)
        try:
            save_state(venture_id, state, owner_id=user.user_id, access_token=user.access_token)
        except (StateConflictError, StateStoreUnavailable):
            # A lost save response might still have delivered the result. Read
            # the canonical state before deciding whether to refund anything.
            return _research_failure(user, venture_id, run_id, paid)
    return RedirectResponse(f"/v/{quote(venture_id)}", status_code=303)


@app.post("/v/{venture_id}/feasibility")
def record_feasibility_result(
    venture_id: str,
    request: Request,
    result: str = Form(...),
    evidence_reference: str = Form(...),
    notes: str = Form(...),
):
    session = _session(request)
    if not session.user:
        return _login_redirect(request)
    user = session.user
    state = load_state(venture_id, owner_id=user.user_id, access_token=user.access_token)
    if not state or state.validation_decision is not None:
        return RedirectResponse(f"/v/{quote(venture_id)}", status_code=303)
    if str(state.metrics.get("last_research") or "").upper() != "FEASIBILITY_REQUIRED":
        return RedirectResponse(f"/v/{quote(venture_id)}", status_code=303)
    if str(state.metrics.get("feasibility_status") or "pending").lower() != "pending":
        return RedirectResponse(f"/v/{quote(venture_id)}", status_code=303)

    normalized = result.strip().upper()
    reference = evidence_reference.strip()[:1000]
    detail = notes.strip()[:3000]
    if normalized not in {"PASS", "FAIL"} or len(reference) < 3 or len(detail) < 3:
        state.metrics["approval_error"] = "A feasibility result requires PASS or FAIL plus a meaningful evidence reference and notes."
        save_state(venture_id, state, owner_id=user.user_id, access_token=user.access_token)
        return RedirectResponse(f"/v/{quote(venture_id)}", status_code=303)

    state.metrics["feasibility_status"] = "passed" if normalized == "PASS" else "failed"
    state.metrics["feasibility_evidence_reference"] = reference
    state.metrics["feasibility_notes"] = detail
    state.metrics.pop("approval_error", None)
    if normalized == "PASS":
        state.research_pass = True
    else:
        state.research_pass = False
        if "Load-bearing capability test failed." not in state.active_blockers:
            state.active_blockers.append("Load-bearing capability test failed.")
    state.current_day += 1
    state.last_updated = datetime.now(UTC)
    save_state(venture_id, state, owner_id=user.user_id, access_token=user.access_token)
    return RedirectResponse(f"/v/{quote(venture_id)}", status_code=303)


@app.post("/v/{venture_id}/record")
def record_direct_evidence(
    venture_id: str,
    request: Request,
    buyer_identifier: str = Form(...),
    buyer_role: str = Form(...),
    qualification_basis: str = Form(...),
    recent_real_example: str = Form(...),
    current_workaround: str = Form(...),
    pain_strength: str = Form(...),
    pilot_price_tested: str = Form(""),
    price_response: str = Form(...),
    price_positive: str = Form("false"),
    payment_status: str = Form("not_asked"),
    payment_amount: str = Form(""),
    payment_reference: str = Form(""),
    objection_or_no_reason: str = Form(...),
    exact_quote: str = Form(...),
    source_of_lead: str = Form(""),
):
    session = _session(request)
    if not session.user:
        return _login_redirect(request)
    user = session.user
    try:
        evidence_allowed = limiter.allow(f"evidence:{user.user_id}", Limit(60, 3600))
    except RateLimitUnavailable:
        return HTMLResponse("Evidence entry is temporarily unavailable. Try again shortly.", status_code=503)
    if not evidence_allowed:
        return HTMLResponse("Evidence-entry rate limit reached. Try again later.", status_code=429)
    state = load_state(venture_id, owner_id=user.user_id, access_token=user.access_token)
    if not state or not state.research_pass or state.validation_decision is not None:
        return RedirectResponse(f"/v/{quote(venture_id)}", status_code=303)

    allowed_pain = {"none", "weak", "moderate", "strong"}
    allowed_payment = {"not_asked", "declined", "committed", "paid"}
    clean_pain = pain_strength if pain_strength in allowed_pain else "unknown"
    clean_payment = payment_status if payment_status in allowed_payment else "not_asked"
    amount = None
    try:
        if payment_amount.strip():
            parsed = float(payment_amount)
            amount = parsed if 0 < parsed <= 1_000_000 else None
    except ValueError:
        amount = None

    clean_identifier = re.sub(r"\s+", " ", buyer_identifier.strip())[:160]
    clean_role = buyer_role.strip()[:160]
    clean_qualification = qualification_basis.strip()[:2000]
    clean_recent_example = recent_real_example.strip()[:4000]
    clean_workaround = current_workaround.strip()[:4000]
    clean_price_response = price_response.strip()[:4000]
    clean_objection = objection_or_no_reason.strip()[:2000]
    clean_quote = exact_quote.strip()[:2000]
    required_values = {
        "buyer/company label": clean_identifier,
        "buyer role": clean_role,
        "qualification basis": clean_qualification,
        "recent real example": clean_recent_example,
        "current workaround": clean_workaround,
        "price/offer reaction": clean_price_response,
        "objection/no-priority response": clean_objection,
        "customer quote": clean_quote,
    }
    missing = [name for name, value in required_values.items() if not value]
    if missing:
        return HTMLResponse(
            "Evidence was not saved because these required fields were blank: " + ", ".join(missing),
            status_code=400,
        )

    # Reusing a normalized buyer label is an immutable follow-up, not a new unique buyer.
    # The gate groups these records so repeated conversations can never inflate buyer counts.
    is_follow_up = buyer_identity_key(clean_identifier) in {
        buyer_identity_key(record.buyer_identifier) for record in state.direct_validation_records
    }

    record = DirectValidationRecord(
        record_id=f"C-{uuid.uuid4().hex[:10].upper()}",
        buyer_identifier=clean_identifier,
        buyer_role=clean_role,
        qualification_basis=clean_qualification,
        source_of_lead=source_of_lead.strip()[:160],
        recent_real_example=clean_recent_example,
        current_workaround=clean_workaround,
        pain_strength=clean_pain,
        pilot_price_tested=pilot_price_tested.strip()[:80],
        price_response=clean_price_response,
        price_positive=price_positive.lower() == "true",
        payment_status=clean_payment,
        payment_amount=amount,
        payment_reference=payment_reference.strip()[:500],
        objection_or_no_reason=clean_objection,
        exact_quote=clean_quote,
    )
    state.direct_validation_records.append(record)
    append_direct_evidence(state, record)
    state.metrics.pop("approval_error", None)
    if is_follow_up:
        state.metrics["last_evidence_note"] = (
            f"Follow-up saved for {clean_identifier}. Unique-buyer count was not increased."
        )
    else:
        state.metrics["last_evidence_note"] = f"New qualified-buyer record saved for {clean_identifier}."
    gate = evaluate_validation_gate(state)
    state.metrics["hard_gate_recommendation"] = gate.recommendation.value
    state.metrics["hard_gate_blockers"] = gate.blockers
    state.metrics["hard_gate_paid_pilots"] = gate.paid_pilot_count
    state.last_updated = datetime.now(UTC)
    save_state(venture_id, state, owner_id=user.user_id, access_token=user.access_token)
    return RedirectResponse(f"/v/{quote(venture_id)}", status_code=303)


@app.post("/v/{venture_id}/record/{record_id}/void")
def void_evidence_record(
    venture_id: str,
    record_id: str,
    request: Request,
    reason: str = Form(...),
):
    session = _session(request)
    if not session.user:
        return _login_redirect(request)
    user = session.user
    try:
        correction_allowed = limiter.allow(f"evidence-correction:{user.user_id}", Limit(30, 3600))
    except RateLimitUnavailable:
        return HTMLResponse("Evidence correction is temporarily unavailable. Try again shortly.", status_code=503)
    if not correction_allowed:
        return HTMLResponse("Evidence-correction rate limit reached. Try again later.", status_code=429)

    state = load_state(venture_id, owner_id=user.user_id, access_token=user.access_token)
    if not state:
        return HTMLResponse("Idea not found", status_code=404)

    try:
        record = void_direct_evidence(state, record_id[:160], reason)
    except LookupError:
        return HTMLResponse("Evidence record not found", status_code=404)
    except ValueError as exc:
        return HTMLResponse(str(exc), status_code=409)
    except RuntimeError:
        return HTMLResponse("Evidence correction could not be applied safely.", status_code=409)

    gate = evaluate_validation_gate(state)
    state.metrics["hard_gate_recommendation"] = gate.recommendation.value
    state.metrics["hard_gate_blockers"] = gate.blockers
    state.metrics["hard_gate_paid_pilots"] = gate.paid_pilot_count
    state.metrics["last_evidence_note"] = (
        f"Corrected {record.record_id}; the original entry remains in the audit trail and no longer counts."
    )
    if state.validation_decision == ValidationDecision.GO and gate.recommendation != ValidationDecision.GO:
        # Preserve the original GO in decision_log, but never leave the live state
        # claiming GO after its required evidence has been corrected away.
        state.validation_decision = None
        state.phase = Phase.VALIDATION
        state.metrics["approval_error"] = (
            "The prior GO was withdrawn because corrected evidence no longer clears the locked gates."
        )
    state.last_updated = datetime.now(UTC)
    save_state(venture_id, state, owner_id=user.user_id, access_token=user.access_token)
    return RedirectResponse(f"/v/{quote(venture_id)}", status_code=303)


@app.post("/v/{venture_id}/pivot")
def start_pivot(request: Request, venture_id: str, idea: str = Form(...)):
    """Create a new hypothesis with a fresh locked contract; never rewrite the parent evidence."""
    session = _session(request)
    if not session.user:
        return _login_redirect(request)
    user = session.user
    try:
        allowed = limiter.allow(f"pivot:{user.user_id}", Limit(20, 3600))
    except RateLimitUnavailable:
        return HTMLResponse("Pivot creation is temporarily unavailable. Try again shortly.", status_code=503)
    if not allowed:
        return HTMLResponse("Too many pivot requests. Try again later.", status_code=429)

    parent = load_state(venture_id, owner_id=user.user_id, access_token=user.access_token)
    if not parent:
        return HTMLResponse("Idea not found", status_code=404)
    if parent.validation_decision is not None:
        return HTMLResponse("This hypothesis already has a final decision. Create a new idea instead.", status_code=409)

    gate = evaluate_validation_gate(parent)
    research_recommendation = str(parent.metrics.get("last_research") or "").upper()
    if (
        research_recommendation not in {"RESEARCH_FAIL", "RESEARCH_PIVOT"}
        and gate.recommendation not in {ValidationDecision.PIVOT, ValidationDecision.KILL}
    ):
        return HTMLResponse("The current evidence does not call for a pivot yet.", status_code=409)

    idea = idea.strip()[:MAX_SHARED_IDEA_LENGTH]
    if len(idea) < 10:
        return HTMLResponse("A pivot hypothesis needs at least 10 characters.", status_code=400)
    if hypothesis_fingerprint(idea) == hypothesis_fingerprint(parent.hypothesis):
        return HTMLResponse(
            "A pivot must materially change the hypothesis; the same normalized idea cannot receive a fresh contract.",
            status_code=400,
        )

    child_id = new_venture_id()
    child = SystemState(current_day=1, phase=Phase.VALIDATION, hypothesis=idea)
    child.metrics["pivot_parent_venture_id"] = venture_id
    child.metrics["pass_family_id"] = _family_id(parent, venture_id)
    child.metrics["pivot_parent_hypothesis"] = parent.hypothesis[:2000]
    child.metrics["pivot_origin_recommendation"] = research_recommendation or gate.recommendation.value
    parent_run_id = str(parent.metrics.get("research_run_id") or "").strip()
    if parent_run_id:
        child.metrics["deep_research_previous_run_id"] = parent_run_id
    child.metrics["pivot_created_at"] = datetime.now(UTC).isoformat()
    ensure_validation_contract(child)
    save_state(child_id, child, owner_id=user.user_id, access_token=user.access_token)
    return RedirectResponse(f"/v/{quote(child_id)}", status_code=303)


@app.post("/v/{venture_id}/approve")
def approve(request: Request, venture_id: str, decision: str = Form(...)):
    session = _session(request)
    if not session.user:
        return _login_redirect(request)
    user = session.user
    state = load_state(venture_id, owner_id=user.user_id, access_token=user.access_token)
    if not state:
        return RedirectResponse("/", status_code=303)
    if state.validation_decision is not None:
        return HTMLResponse(
            "This validation already has a final decision. Start a new/pivoted idea instead of rewriting its audit history.",
            status_code=409,
        )
    try:
        validation_decision = ValidationDecision(decision.lower())
    except ValueError:
        return HTMLResponse("Unsupported validation decision.", status_code=400)
    if validation_decision not in {ValidationDecision.GO, ValidationDecision.KILL}:
        return HTMLResponse(
            "Only GO or KILL can be accepted as a final decision. PIVOT and CONTINUE VALIDATION are recommendations that require more/new evidence.",
            status_code=400,
        )

    gate = evaluate_validation_gate(state)
    if validation_decision == ValidationDecision.GO and not go_is_allowed(state):
        state.metrics["approval_error"] = "GO blocked by the locked Validation Contract: " + " ".join(gate.blockers[:4])
        save_state(venture_id, state, owner_id=user.user_id, access_token=user.access_token)
        return RedirectResponse(f"/v/{quote(venture_id)}", status_code=303)

    state.metrics.pop("approval_error", None)
    state.validation_decision = validation_decision
    append_decision(state, validation_decision, gate, rationale="Accepted from the web approval control.")
    if validation_decision == ValidationDecision.KILL:
        state.phase = Phase.KILL
    elif validation_decision == ValidationDecision.GO:
        state.phase = Phase.BUILD
    state.last_updated = datetime.now(UTC)
    save_state(venture_id, state, owner_id=user.user_id, access_token=user.access_token)
    return RedirectResponse(f"/v/{quote(venture_id)}", status_code=303)


@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request, next: str = "/", error: str = ""):
    if _session(request).user:
        return RedirectResponse(_safe_next(next), status_code=303)
    msg = f'<p class="callout caution">{escape(error)}</p>' if error else ""
    body = f'''<section class="hero compact"><img class="auth-art" src="/static/brand/hero-atmosphere.jpg" alt="" width="420" height="220"><span class="eyebrow">VALIDATE BEFORE YOU BUILD</span><h1>Sign in to your private Killgate workspace.</h1><p>Killgate helps you test whether an idea is worth building by checking public evidence first, then guiding you to collect proof from real buyers.</p><a class="text-link" href="/how-it-works">See what Killgate does</a></section>
    <section class="panel auth-panel">{msg}<form method="post" action="/login"><input type="hidden" name="next" value="{escape(_safe_next(next), quote=True)}"><label for="login-email">Email</label><input id="login-email" name="email" type="email" autocomplete="email" autocapitalize="none" spellcheck="false" required><label for="login-password">Password</label>{_password_field("login-password", "current-password")}<button type="submit">Sign in</button></form><p class="muted small">No account yet? <a href="/signup?next={quote(_safe_next(next))}">Create one</a>.</p></section>{_render_product_explainer("login-product-journey")}'''
    return page("Sign in · Killgate", body, page_class="auth-page")


@app.post("/login")
def login_submit(request: Request, email: str = Form(...), password: str = Form(...), next: str = Form("/")):
    if auth_mode() != "supabase":
        return RedirectResponse(_safe_next(next), status_code=303)
    normalized_email = email.strip()[:320].casefold()
    client_host = request.client.host if request.client else "unknown"
    try:
        allowed = (
            limiter.allow_pre_auth(normalized_email, "login-account", _pre_auth_limit("KILLGATE_LOGIN_ACCOUNT_LIMIT_15M", 10, 15 * 60))
            and limiter.allow_pre_auth(client_host, "login-source", _pre_auth_limit("KILLGATE_LOGIN_SOURCE_LIMIT_15M", 50, 15 * 60))
            and limiter.allow_pre_auth("global", "login-global", _pre_auth_limit("KILLGATE_LOGIN_GLOBAL_LIMIT_15M", 500, 15 * 60))
        )
    except RateLimitUnavailable:
        return HTMLResponse("Sign-in protection is temporarily unavailable. Try again shortly.", status_code=503)
    if not allowed:
        return HTMLResponse("Too many sign-in attempts. Wait a few minutes and try again.", status_code=429)
    try:
        session = sign_in(normalized_email, password)
    except ValueError as exc:
        return RedirectResponse(f"/login?next={quote(_safe_next(next))}&error={quote(str(exc))}", status_code=303)
    except AuthUnavailable:
        return HTMLResponse("Sign-in service is temporarily unavailable. Try again shortly.", status_code=503)
    response = RedirectResponse(_safe_next(next), status_code=303)
    set_session_cookies(response, session)
    return response


@app.get("/signup", response_class=HTMLResponse)
def signup_page(request: Request, next: str = "/", message: str = "", error: str = ""):
    if _session(request).user:
        return RedirectResponse(_safe_next(next), status_code=303)
    notice = (f'<p class="callout">{escape(message)}</p>' if message else "") + (f'<p class="callout caution">{escape(error)}</p>' if error else "")
    body = f'''<section class="hero compact"><img class="auth-art" src="/static/brand/hero-atmosphere.jpg" alt="" width="420" height="220"><span class="eyebrow">PRIVATE VALIDATION WORKSPACE</span><h1>Test an idea before you commit to building it.</h1><p>Killgate turns a rough idea into a clear test plan, checks public evidence, and shows you exactly what buyer proof is still needed.</p></section>
    <section class="panel auth-panel">{notice}<form method="post" action="/signup"><input type="hidden" name="next" value="{escape(_safe_next(next), quote=True)}"><label for="signup-email">Email</label><input id="signup-email" name="email" type="email" autocomplete="email" autocapitalize="none" spellcheck="false" required><label for="signup-password">Password</label>{_password_field("signup-password", "new-password")}<button type="submit">Create account</button></form><p class="muted small">Use your real email so you can confirm your account and restore your session on another device.</p><p class="muted small">Already have an account? <a href="/login?next={quote(_safe_next(next))}">Sign in</a>.</p></section>{_render_product_explainer("signup-product-journey")}{_render_sample_reactions("signup-reactions")}{_render_sample_reports("signup-sample-reports", limit=3)}'''
    return page("Create account · Killgate", body, page_class="auth-page")


@app.post("/signup")
def signup_submit(request: Request, email: str = Form(...), password: str = Form(...), next: str = Form("/")):
    if auth_mode() != "supabase":
        return RedirectResponse(_safe_next(next), status_code=303)
    normalized_email = email.strip()[:320].casefold()
    client_host = request.client.host if request.client else "unknown"
    try:
        allowed = (
            limiter.allow_pre_auth(normalized_email, "signup-account", _pre_auth_limit("KILLGATE_SIGNUP_ACCOUNT_LIMIT_1H", 5, 60 * 60))
            and limiter.allow_pre_auth(client_host, "signup-source", _pre_auth_limit("KILLGATE_SIGNUP_SOURCE_LIMIT_1H", 40, 60 * 60))
            and limiter.allow_pre_auth("global", "signup-global", _pre_auth_limit("KILLGATE_SIGNUP_GLOBAL_LIMIT_1H", 1000, 60 * 60))
        )
    except RateLimitUnavailable:
        return HTMLResponse("Account-creation protection is temporarily unavailable. Try again shortly.", status_code=503)
    if not allowed:
        return HTMLResponse("Too many account-creation attempts. Wait and try again later.", status_code=429)
    try:
        session = sign_up(normalized_email, password)
    except ValueError as exc:
        return RedirectResponse(f"/signup?next={quote(_safe_next(next))}&error={quote(str(exc))}", status_code=303)
    except AuthRateLimited as exc:
        return RedirectResponse(f"/signup?next={quote(_safe_next(next))}&error={quote(str(exc))}", status_code=303)
    except AuthUnavailable:
        return HTMLResponse("Account creation is temporarily unavailable. Try again shortly.", status_code=503)
    if not session.user:
        return RedirectResponse(f"/signup?next={quote(_safe_next(next))}&message={quote('Check your email to confirm the account, then sign in.')}", status_code=303)
    response = RedirectResponse(_safe_next(next), status_code=303)
    set_session_cookies(response, session)
    return response


@app.post("/logout")
def logout(request: Request):
    session = _session(request)
    if session.user:
        sign_out(session.user.access_token)
    response = RedirectResponse("/login", status_code=303)
    clear_session_cookies(response)
    return response


@app.post("/billing/local-grant")
def local_grant(
    request: Request,
    kind: str = Form(...),
    family_id: str = Form(""),
    next: str = Form("/account"),
):
    """Development-only catalog grant. Production refuses this path."""
    session = _session(request)
    if not session.user:
        return _login_redirect(request)
    if os.getenv("BILLING_ENFORCED", "0").strip() == "1" or os.getenv("APP_ENV", "development").strip().lower() == "production":
        return HTMLResponse("Local catalog grants are disabled when billing is enforced.", status_code=403)
    from app.services.catalog import PRODUCTS

    match = next((item for item in PRODUCTS if item.kind == kind.strip()), None)
    if not match:
        return HTMLResponse("Unknown catalog item.", status_code=400)
    wallet = load_wallet(session.user.user_id)
    active_local_pro = bool(wallet.subscription_period_id and wallet.subscription_credits_expire_at)
    try:
        grant_product(
            wallet,
            match,
            product_id=f"local:{match.kind}",
            family_id=family_id.strip(),
            active_subscription=active_local_pro,
        )
    except ValueError as exc:
        return HTMLResponse(escape(str(exc)), status_code=400)
    target = _safe_next(next) or "/account"
    return RedirectResponse(target, status_code=303)


@app.get("/account", response_class=HTMLResponse)
def account_page(request: Request, billing: str = ""):
    session = _session(request)
    if not session.user:
        return _login_redirect(request)
    user = session.user
    try:
        entitlement = get_entitlement(user.user_id, user.access_token)
    except BillingUnavailable:
        return HTMLResponse(
            "Subscription status is temporarily unavailable. Try again shortly.",
            status_code=503,
        )
    product_id = configured_product_id()
    active = entitlement_is_current(entitlement)
    wallet = load_wallet(user.user_id)
    billing_note = '<p class="callout caution">Live research needs a Venture Pass, an idea-bound Extra Evidence Run, or available Founder Pro passes. Founder Pro is optional.</p>' if billing == "required" else ""
    package_name = os.getenv("GOOGLE_PLAY_PACKAGE_NAME", "").strip()
    manage_url = (
        "https://play.google.com/store/account/subscriptions"
        f"?sku={quote(product_id)}&package={quote(package_name)}"
        if product_id and package_name
        else "https://play.google.com/store/account/subscriptions"
    )
    wallet_html = (
        f'<section class="panel"><h2>Credits</h2>'
        f'<p>Wallet credits: <strong>{wallet.wallet_credits}</strong> · '
        f'Founder Pro passes this period: <strong>{wallet.subscription_credits}</strong> · '
        f'Unbound Venture Passes: <strong>{len(unbound_passes(wallet))}</strong></p>'
        f'<p class="muted small">Attach a pass on the idea brief. Pivot children share the parent family.</p></section>'
    )
    offers = f'<section class="panel"><h2>Buy research</h2>{billing_note}<p>Default offer is the Venture Pass. Founder Pro is for serial founders and consultants who expect to use roughly nine live passes per month.</p>{_render_offer_cards("/account", active_subscription=active)}</section>'
    if billing_enabled() and product_id:
        subscription = (
            f'<section class="panel"><h2>Google Play subscription status</h2>'
            f'<p>{"Founder Pro active" if active else "No active Founder Pro subscription verified"}</p>'
            f'<p><a href="{escape(manage_url, quote=True)}" target="_blank" rel="noopener">Manage, restore, or cancel in Google Play</a></p></section>'
        )
    else:
        subscription = '<section class="panel"><h2>Google Play</h2><p class="muted">Play product IDs are owner-configured. Local development can grant test catalog items.</p></section>'
    body = f'''<section class="hero compact"><span class="eyebrow">ACCOUNT</span><h1>Your private Killgate workspace.</h1><p>{escape(user.email)}</p></section>{wallet_html}{offers}{subscription}<section class="panel"><h2>Your data</h2><p>Download a copy of your ideas, evidence, validation plans, and decisions.</p><a class="button-link" href="/account/export">Export my data</a></section><section class="panel"><h2>Privacy & deletion</h2><p><a href="/privacy">Privacy policy</a> · <a href="/delete-account">Delete account</a></p></section>'''
    return page("Account · Killgate", body, page_class="account-page", user=user)


@app.get("/api/entitlement")
def entitlement_api(request: Request):
    session = _session(request)
    if not session.user:
        return JSONResponse({"authenticated": False}, status_code=401)
    try:
        entitlement = get_entitlement(session.user.user_id, session.user.access_token)
    except BillingUnavailable:
        return JSONResponse(
            {"authenticated": True, "error": "Subscription status is temporarily unavailable."},
            status_code=503,
        )
    return {"authenticated": True, "billing_enabled": billing_enabled(), "product_id": configured_product_id(), "entitlement": entitlement}


@app.post("/billing/google-play/verify")
async def verify_google_play(request: Request):
    session = _session(request)
    if not session.user:
        return JSONResponse({"ok": False, "error": "Authentication required."}, status_code=401)
    try:
        billing_allowed = limiter.allow(f"billing:{session.user.user_id}", Limit(20, 3600))
    except RateLimitUnavailable:
        return JSONResponse({"ok": False, "error": "Billing verification is temporarily unavailable."}, status_code=503)
    if not billing_allowed:
        return JSONResponse({"ok": False, "error": "Too many billing checks."}, status_code=429)
    try:
        payload = await request.json()
        token = str(payload.get("purchase_token") or "")[:10000]
        requested_product = str(payload.get("product_id") or "").strip()[:300]
        family_id = str(payload.get("family_id") or "").strip()[:200]
        configured_subscription = configured_product_id()
        catalog_item = find_product(requested_product) if requested_product else None
        configured_product = requested_product or configured_subscription
        if not configured_product:
            raise RuntimeError("Google Play product ID is not configured.")
        if (
            requested_product
            and configured_subscription
            and requested_product != configured_subscription
            and catalog_item is None
        ):
            raise ValueError("Purchase product is not in the Killgate catalog.")

        if catalog_item and catalog_item.kind != "subscription":
            if catalog_item.requires_family and not family_id:
                raise ValueError("This purchase must be attached to the idea you are validating.")
            active_pro = False
            if catalog_item.requires_active_subscription:
                entitlement_row = get_entitlement(session.user.user_id, session.user.access_token)
                active_pro = entitlement_is_current(entitlement_row)
                if not active_pro:
                    raise ValueError("Founder Pro must be active before buying a top-up.")
            one_time = verify_one_time_product(token, configured_product)
            if not one_time.active:
                raise ValueError("Google Play has not completed this purchase.")
            wallet = load_wallet(session.user.user_id)
            grant_product(
                wallet,
                catalog_item,
                product_id=configured_product,
                purchase_hash=one_time.purchase_token_hash,
                family_id=family_id,
                active_subscription=active_pro,
            )
            # Consumables are consumed only after Killgate's durable ledger has
            # accepted the grant, which makes the SKU safely repurchasable.
            consume_one_time_product(token, one_time)
            return {
                "ok": True,
                "active": one_time.active,
                "product_id": configured_product,
                "kind": catalog_item.kind,
            }

        entitlement = verify_subscription(token, configured_product)
        updated_current = persist_entitlement(session.user.user_id, entitlement)
        if updated_current is not True:
            return {"ok": True, "status": "stale_purchase_ignored", "updated_current": False}
        if entitlement.active:
            product = catalog_item or find_product(configured_product)
            if product:
                period_id = entitlement.expires_at.isoformat() if entitlement.expires_at else entitlement.purchase_token_hash
                grant = grant_product(
                    load_wallet(session.user.user_id),
                    product,
                    product_id=configured_product,
                    purchase_hash=entitlement.purchase_token_hash,
                    subscription_period_id=period_id,
                    subscription_expires_at=entitlement.expires_at,
                    active_subscription=True,
                )
                if grant.get("error") == "stale_purchase_ignored":
                    return {"ok": True, "status": "stale_purchase_ignored", "updated_current": False}
                if grant.get("ok") is not True:
                    raise WalletStoreUnavailable("Subscription credit grant was not confirmed.")
        acknowledge_subscription(token, entitlement)
    except ValueError as exc:
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=400)
    except (RuntimeError, WalletStoreUnavailable):
        # Configuration/provider/database failures are operational errors, not bad purchases.
        return JSONResponse({"ok": False, "error": "Billing verification is temporarily unavailable."}, status_code=503)
    return {
        "ok": True,
        "active": entitlement.active,
        "subscription_state": entitlement.subscription_state,
        "expires_at": entitlement.expires_at.isoformat() if entitlement.expires_at else None,
        "product_id": entitlement.product_id,
    }


@app.post("/billing/google-play/rtdn")
async def google_play_rtdn(request: Request):
    """Authenticated Cloud Pub/Sub push endpoint for Google Play RTDN."""
    try:
        verify_pubsub_push_authorization(request.headers.get("authorization", ""))
    except RuntimeError as exc:
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=503)
    except (ValueError, TypeError):
        return JSONResponse({"ok": False, "error": "Invalid Pub/Sub push authentication."}, status_code=401)

    try:
        message = decode_rtdn_envelope(await request.json())
    except (ValueError, TypeError):
        return JSONResponse({"ok": False, "error": "Invalid RTDN payload."}, status_code=400)

    expected_package = os.getenv("GOOGLE_PLAY_PACKAGE_NAME", "").strip()
    if not expected_package or message.package_name != expected_package:
        return JSONResponse({"ok": False, "error": "RTDN package does not match Killgate."}, status_code=400)

    try:
        if rtdn_event_processed(message.message_id):
            return Response(status_code=204)

        if message.notification_kind in {"subscription", "voided_subscription"}:
            if not message.purchase_token:
                return JSONResponse({"ok": False, "error": "RTDN subscription token is missing."}, status_code=400)
            # Google says the Developer API is the source of truth after RTDN. Verify
            # first so a new replacement/resubscribe token can be associated through
            # linkedPurchaseToken or outOfAppPurchaseContext when the new hash is not known yet.
            entitlement = verify_subscription(message.purchase_token)
            owner_id = find_entitlement_owner_by_token(message.purchase_token)
            if not owner_id:
                for predecessor_hash in entitlement.predecessor_token_hashes:
                    owner_id = find_entitlement_owner_by_token_hash(predecessor_hash)
                    if owner_id:
                        break
            if not owner_id:
                # First-ever/out-of-app purchase may not be attributable until the signed-in
                # user opens Killgate and the restore flow verifies the token. Ask Pub/Sub to retry.
                return JSONResponse({"ok": False, "error": "RTDN purchase is not associated yet."}, status_code=503)
            updated_current = persist_entitlement(owner_id, entitlement)
            if updated_current is True and entitlement.active:
                product = find_product(entitlement.product_id)
                if product and product.kind == "subscription":
                    period_id = entitlement.expires_at.isoformat() if entitlement.expires_at else entitlement.purchase_token_hash
                    grant = grant_product(
                        load_wallet(owner_id),
                        product,
                        product_id=entitlement.product_id,
                        purchase_hash=entitlement.purchase_token_hash,
                        subscription_period_id=period_id,
                        subscription_expires_at=entitlement.expires_at,
                        active_subscription=True,
                    )
                    if grant.get("error") == "stale_purchase_ignored":
                        updated_current = False
                    elif grant.get("ok") is not True:
                        raise WalletStoreUnavailable("Subscription credit grant was not confirmed.")
            if updated_current is True:
                acknowledge_subscription(message.purchase_token, entitlement)

        # Test, one-time-product, pending-refund-review, and unknown notifications do not
        # alter the v1 subscription entitlement directly, but are deduplicated and audited.
        record_rtdn_event(message)
    except (ValueError, RuntimeError):
        # Pub/Sub retries non-2xx responses. For a Google-originated purchase token, a
        # verification/database failure is safer to retry than silently dropping lifecycle state.
        return JSONResponse({"ok": False, "error": "RTDN processing failed; retry requested."}, status_code=503)

    return Response(status_code=204)


@app.get("/account/export")
def account_export(request: Request):
    session = _session(request)
    if not session.user:
        return _login_redirect(request)
    payload = export_user_data(owner_id=session.user.user_id, access_token=session.user.access_token)
    return JSONResponse(payload, headers={"Content-Disposition": 'attachment; filename="killgate-export.json"'})


@app.get("/delete-account", response_class=HTMLResponse)
def delete_account_page(request: Request):
    session = _session(request)
    if not session.user:
        return page("Delete account · Killgate", '<section class="hero compact"><span class="eyebrow">ACCOUNT DELETION</span><h1>Delete a Killgate account.</h1><p>Sign in first so Killgate can verify the private account to remove.</p><a class="button-link" href="/login?next=/delete-account">Sign in to continue</a></section>', page_class="account-page")
    user = session.user
    package_name = os.getenv("GOOGLE_PLAY_PACKAGE_NAME", "").strip()
    product_id = configured_product_id()
    manage_url = "https://play.google.com/store/account/subscriptions"
    if package_name and product_id:
        manage_url += f"?sku={quote(product_id)}&package={quote(package_name)}"
    body = f'''<section class="hero compact"><span class="eyebrow">PERMANENT DELETION</span><h1>Delete {escape(user.email)}?</h1><p>This permanently removes the account and associated venture data.</p></section><section class="panel"><div class="callout caution"><strong>Deleting Killgate does not cancel a Google Play subscription.</strong><p>Cancel it in Google Play first if you do not want future renewal charges. You keep paid access through the end of the current billing period.</p><p><a href="{escape(manage_url, quote=True)}" target="_blank" rel="noopener">Manage or cancel the subscription in Google Play</a> · <a href="/support">Get support</a></p></div><a class="button-link" href="/account/export">Export first</a><form method="post" action="/account/delete"><label>Type DELETE to confirm</label><input name="confirm_delete" autocomplete="off" required><button class="danger" type="submit">Delete my account and data</button></form></section>'''
    return page("Delete account · Killgate", body, page_class="account-page", user=user)


@app.post("/account/delete")
def account_delete(request: Request, confirm_delete: str = Form(...)):
    session = _session(request)
    if not session.user:
        return _login_redirect(request)
    if confirm_delete.strip().upper() != "DELETE":
        return RedirectResponse("/delete-account", status_code=303)
    if auth_mode() == "supabase":
        try:
            request_account_deletion(session.user.access_token)
        except AuthUnavailable:
            return HTMLResponse(
                "Account deletion is temporarily unavailable. Nothing was deleted; try again shortly.",
                status_code=503,
            )
    else:
        delete_all_user_data(owner_id=session.user.user_id, access_token=session.user.access_token)
    response = RedirectResponse("/login?message=Account%20deleted", status_code=303)
    clear_session_cookies(response)
    return response


@app.get("/privacy", response_class=HTMLResponse)
def privacy(request: Request):
    user = _session(request).user
    privacy_email = os.getenv("PRIVACY_CONTACT_EMAIL", "").strip()
    contact = (
        f'<a href="mailto:{escape(privacy_email, quote=True)}">{escape(privacy_email)}</a>'
        if privacy_email
        else '<span class="muted">Privacy contact not configured in this deployment.</span>'
    )
    body = f'''<section class="hero compact"><span class="eyebrow">PRIVACY POLICY</span><h1>Killgate privacy.</h1><p>Killgate stores the information needed to validate your ideas. It does not sell your personal data.</p></section><section class="panel"><h2>Data Killgate handles</h2><p>Account email; ideas; Validation Contracts; public research results and source links; buyer-interview notes and quotes; payment-reference evidence you enter; decisions and audit history; subscription entitlement identifiers; and basic security/error telemetry when enabled.</p><h2>Why it is used</h2><p>To provide validation, sync your private workspace, secure the service, recover errors, prevent abuse, and manage paid access.</p><h2>AI and research providers</h2><p>Idea/research content may be sent from Killgate's server to configured AI and search providers to perform validation you request. Provider credentials are never placed in the Android package.</p><h2>Payments</h2><p>Google Play handles purchase and subscription payment credentials. Killgate stores only identifiers and status needed to verify entitlement. Never enter card or bank credentials into buyer-evidence fields.</p><h2>Retention and deletion</h2><p>Venture data is kept while the account exists unless deleted earlier. Export is available in the account screen. Permanent account deletion is available in-app and at <a href="/delete-account">this deletion page</a>. Limited records may be retained only where required for fraud, security, tax, or legal compliance.</p><h2>Contact</h2><p>{contact}</p><p class="muted small">Last updated: August 24, 2026.</p></section>'''
    return page("Privacy · Killgate", body, page_class="privacy-page", user=user)


@app.get("/support", response_class=HTMLResponse)
def support(request: Request):
    user = _session(request).user
    support_email = os.getenv("SUPPORT_EMAIL", "").strip()
    contact = (
        f'<a class="button-link" href="mailto:{escape(support_email, quote=True)}">Email {escape(support_email)}</a>'
        if support_email
        else '<p class="muted">Support contact is not configured in this deployment.</p>'
    )
    body = f'''<section class="hero compact"><span class="eyebrow">SUPPORT</span><h1>Killgate support.</h1><p>For account, billing, deletion, or validation-workflow issues, contact the monitored support address below.</p></section><section class="panel">{contact}<p class="muted small">Never email passwords, Google Play purchase tokens, card numbers, or bank credentials.</p></section>'''
    return page("Support · Killgate", body, page_class="account-page", user=user)
