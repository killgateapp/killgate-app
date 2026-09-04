"""Non-secret runtime and Play-release readiness checks for Killgate."""
from __future__ import annotations

import json
import os
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from urllib.parse import urlparse

from app.services.model_routing import validate_model_routing
from app.services.research_policy import (
    DEFAULT_BETA_DURATION_DAYS,
    beta_policy,
    research_safety_cap_30d,
    test_admin_switch_enabled,
    test_admin_user_ids,
)


@dataclass(frozen=True)
class ReadinessReport:
    runtime_ready: bool
    release_ready: bool
    runtime_blockers: list[str]
    release_blockers: list[str]
    warnings: list[str]

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


def _is_https_origin(value: str) -> bool:
    value = (value or "").strip()
    if not value:
        return False
    parsed = urlparse(value)
    try:
        port = parsed.port
    except ValueError:
        return False
    return bool(
        parsed.scheme == "https"
        and parsed.hostname
        and parsed.username is None
        and parsed.password is None
        and port in {None, 443}
        and parsed.path in {"", "/"}
        and not parsed.params
        and not parsed.query
        and not parsed.fragment
    )


def _looks_like_email(value: str) -> bool:
    value = (value or "").strip()
    if not value or len(value) > 320 or " " in value:
        return False
    local, separator, domain = value.rpartition("@")
    return bool(separator and local and "." in domain and not domain.startswith(".") and not domain.endswith("."))


def _service_account_configured() -> bool:
    raw = os.getenv("GOOGLE_PLAY_SERVICE_ACCOUNT_JSON", "").strip()
    path = os.getenv("GOOGLE_PLAY_SERVICE_ACCOUNT_FILE", "").strip()
    if raw:
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            return False
        return bool(
            isinstance(payload, dict)
            and str(payload.get("client_email") or "").strip()
            and str(payload.get("private_key") or "").strip()
        )
    return bool(path and Path(path).is_file())


def readiness_report() -> ReadinessReport:
    runtime_blockers: list[str] = []
    release_blockers: list[str] = []
    warnings: list[str] = []

    app_env = os.getenv("APP_ENV", "development").strip().lower()
    auth_mode = os.getenv("AUTH_MODE", "local").strip().lower()
    state_backend = os.getenv("STATE_BACKEND", "local").strip().lower()
    wallet_backend = os.getenv("WALLET_BACKEND", state_backend).strip().lower()
    production = app_env == "production"
    test_admin_switch = test_admin_switch_enabled()
    test_admin_ids = test_admin_user_ids()
    if test_admin_switch:
        if not test_admin_ids:
            runtime_blockers.append(
                "KILLGATE_TEST_ADMIN_ENABLED=1 requires KILLGATE_TEST_ADMIN_USER_IDS."
            )
        else:
            release_blockers.append(
                "KILLGATE_TEST_ADMIN_ENABLED must be 0 before a Play release can be declared ready."
            )
            warnings.append(
                "Test-admin entitlement bypass is enabled for an allowlisted account; wallet billing is not production-safe."
            )
    elif test_admin_ids:
        warnings.append(
            "KILLGATE_TEST_ADMIN_USER_IDS is configured but the test-admin bypass is disabled."
        )

    beta = beta_policy()
    if beta.enabled:
        if not beta.user_ids:
            runtime_blockers.append("KILLGATE_BETA_ENABLED=1 requires KILLGATE_BETA_USER_IDS.")
        if beta.start_at is None:
            runtime_blockers.append("KILLGATE_BETA_ENABLED=1 requires KILLGATE_BETA_START_AT.")
        if beta.duration_days != DEFAULT_BETA_DURATION_DAYS:
            runtime_blockers.append("KILLGATE_BETA_DURATION_DAYS must be 14.")
        if not 1 <= beta.max_runs <= 500:
            runtime_blockers.append("KILLGATE_BETA_MAX_RUNS must be between 1 and 500.")
        release_blockers.append("KILLGATE_BETA_ENABLED must be 0 before a Play release can be declared ready.")
        warnings.append(
            "Beta access is enabled for an allowlisted account; beta research is free for 9 runs during a 14-day window."
        )
    elif beta.user_ids:
        warnings.append("KILLGATE_BETA_USER_IDS is configured but beta access is disabled.")

    if app_env != "production":
        release_blockers.append("APP_ENV must be production before a Play release can be declared ready.")

    supabase_url = os.getenv("SUPABASE_URL", "").strip()
    publishable = os.getenv("SUPABASE_PUBLISHABLE_KEY", "").strip()
    secret = os.getenv("SUPABASE_SECRET_KEY", "").strip()

    if auth_mode == "supabase" or state_backend == "supabase":
        if not _is_https_origin(supabase_url):
            runtime_blockers.append("SUPABASE_URL must be a valid HTTPS project origin.")
        if not publishable:
            runtime_blockers.append("SUPABASE_PUBLISHABLE_KEY is missing.")
        if not secret:
            # Production rate limiting and billing lifecycle writes are server-only.
            runtime_blockers.append("SUPABASE_SECRET_KEY is missing from server deployment secrets.")

    try:
        cookie_max_age = int(os.getenv("SESSION_COOKIE_MAX_AGE", str(60 * 60 * 24 * 30)))
    except ValueError:
        cookie_max_age = 0
    if not 60 * 60 <= cookie_max_age <= 60 * 60 * 24 * 90:
        runtime_blockers.append("SESSION_COOKIE_MAX_AGE must be between 1 hour and 90 days.")

    if production:
        if auth_mode != "supabase":
            runtime_blockers.append("Production requires AUTH_MODE=supabase.")
        if state_backend != "supabase":
            runtime_blockers.append("Production requires STATE_BACKEND=supabase.")
        if wallet_backend != "supabase":
            runtime_blockers.append("Production requires WALLET_BACKEND=supabase (or inheritance from STATE_BACKEND=supabase).")
        if os.getenv("COOKIE_SECURE", "0").strip() != "1":
            runtime_blockers.append("Production requires COOKIE_SECURE=1.")

    public_origin = os.getenv("PUBLIC_APP_ORIGIN", "").strip().rstrip("/")
    if not _is_https_origin(public_origin):
        release_blockers.append("PUBLIC_APP_ORIGIN must be the final HTTPS Killgate origin.")

    privacy_email = os.getenv("PRIVACY_CONTACT_EMAIL", "").strip()
    support_email = os.getenv("SUPPORT_EMAIL", "").strip()
    if not _looks_like_email(privacy_email):
        release_blockers.append("PRIVACY_CONTACT_EMAIL must be a monitored email address.")
    if not _looks_like_email(support_email):
        release_blockers.append("SUPPORT_EMAIL must be a monitored email address.")

    package_name = os.getenv("GOOGLE_PLAY_PACKAGE_NAME", "").strip()
    product_id = (
        os.getenv("GOOGLE_PLAY_FOUNDER_PRO_PRODUCT_ID", "").strip()
        or os.getenv("GOOGLE_PLAY_SUBSCRIPTION_PRODUCT_ID", "").strip()
    )
    signing_fingerprint = os.getenv("PLAY_APP_SIGNING_SHA256", "").strip()
    package_pattern = r"[A-Za-z][A-Za-z0-9_]*(?:\.[A-Za-z][A-Za-z0-9_]*)+"
    if (
        not package_name
        or package_name == "com.example.killgate"
        or not re.fullmatch(package_pattern, package_name)
    ):
        release_blockers.append("GOOGLE_PLAY_PACKAGE_NAME must be the final valid Android package ID.")
    compact_fingerprint = re.sub(r"[:\s-]", "", signing_fingerprint)
    if not re.fullmatch(r"[0-9A-Fa-f]{64}", compact_fingerprint):
        release_blockers.append("PLAY_APP_SIGNING_SHA256 must be the Play-installed app signing certificate SHA-256 fingerprint.")
    if not product_id:
        release_blockers.append("GOOGLE_PLAY_FOUNDER_PRO_PRODUCT_ID is missing.")
    if not _service_account_configured():
        release_blockers.append("Google Play service-account credentials are not configured server-side.")

    rtdn_audience = os.getenv("GOOGLE_PLAY_RTDN_AUDIENCE", "").strip()
    rtdn_email = os.getenv("GOOGLE_PLAY_RTDN_SERVICE_ACCOUNT_EMAIL", "").strip()
    expected_audience = f"{public_origin}/billing/google-play/rtdn" if _is_https_origin(public_origin) else ""
    if not rtdn_audience:
        release_blockers.append("GOOGLE_PLAY_RTDN_AUDIENCE is missing.")
    elif expected_audience and rtdn_audience.rstrip("/") != expected_audience:
        release_blockers.append("GOOGLE_PLAY_RTDN_AUDIENCE does not match PUBLIC_APP_ORIGIN + /billing/google-play/rtdn.")
    if not _looks_like_email(rtdn_email):
        release_blockers.append("GOOGLE_PLAY_RTDN_SERVICE_ACCOUNT_EMAIL is missing or invalid.")

    # Bound AI work before a production release so a configuration typo cannot
    # turn a flat-rate subscription into unmetered API spend.
    try:
        hourly_research = int(os.getenv("RESEARCH_RUNS_PER_HOUR", "8"))
    except ValueError:
        hourly_research = 0
    try:
        rolling_research = research_safety_cap_30d()
    except ValueError:
        rolling_research = 0
    try:
        max_output_tokens = int(os.getenv("OPENAI_MAX_OUTPUT_TOKENS", "2400"))
    except ValueError:
        max_output_tokens = 0

    if not 1 <= hourly_research <= 100:
        runtime_blockers.append("RESEARCH_RUNS_PER_HOUR must be between 1 and 100.")
    if not 1 <= rolling_research <= 500:
        runtime_blockers.append("RESEARCH_SAFETY_CAP_30D must be between 1 and 500.")
    if rolling_research and hourly_research and rolling_research < hourly_research:
        warnings.append("RESEARCH_SAFETY_CAP_30D is lower than the hourly cap; the rolling safety ceiling will dominate.")
    if not 256 <= max_output_tokens <= 8000:
        runtime_blockers.append("OPENAI_MAX_OUTPUT_TOKENS must be between 256 and 8000.")

    openai_required = os.getenv("OPENAI_REQUIRED", "1" if production else "0").strip() == "1"
    if production and not openai_required:
        runtime_blockers.append("Production requires OPENAI_REQUIRED=1 so AI failures cannot silently change the research engine.")
    if openai_required and not os.getenv("OPENAI_API_KEY", "").strip():
        runtime_blockers.append("OPENAI_API_KEY is required by this production configuration.")
    elif not os.getenv("OPENAI_API_KEY", "").strip():
        warnings.append("OPENAI_API_KEY is not configured; development research falls back to the conservative non-LLM evaluator.")

    # Keep Deep Research's per-run provider budget explicit. Enabling the
    # feature must never silently inherit an unbounded model or search budget.
    deep_research_enabled = os.getenv("DEEP_RESEARCH_ENABLED", "0").strip() == "1"
    if deep_research_enabled:
        try:
            deep_model_calls = int(os.getenv("DEEP_RESEARCH_MAX_MODEL_CALLS", "12"))
        except ValueError:
            deep_model_calls = 0
        try:
            deep_search_calls = int(os.getenv("DEEP_RESEARCH_MAX_SEARCH_CALLS", "24"))
        except ValueError:
            deep_search_calls = 0
        try:
            deep_soft_cost = float(os.getenv("DEEP_RESEARCH_SOFT_COST_LIMIT_USD", "0.60"))
            deep_hard_cost = float(os.getenv("DEEP_RESEARCH_HARD_COST_LIMIT_USD", "1.25"))
        except ValueError:
            deep_soft_cost = deep_hard_cost = -1.0
        if not 1 <= deep_model_calls <= 100:
            runtime_blockers.append("DEEP_RESEARCH_MAX_MODEL_CALLS must be between 1 and 100 when Deep Research is enabled.")
        if not 1 <= deep_search_calls <= 200:
            runtime_blockers.append("DEEP_RESEARCH_MAX_SEARCH_CALLS must be between 1 and 200 when Deep Research is enabled.")
        if deep_soft_cost < 0 or deep_hard_cost <= deep_soft_cost:
            runtime_blockers.append("DEEP_RESEARCH_HARD_COST_LIMIT_USD must be greater than DEEP_RESEARCH_SOFT_COST_LIMIT_USD.")
        runtime_blockers.extend(validate_model_routing())
        worker_mode = os.getenv("DEEP_RESEARCH_WORKER_MODE", "inline").strip().lower()
        if worker_mode not in {"inline", "cloud_tasks"}:
            runtime_blockers.append("DEEP_RESEARCH_WORKER_MODE must be inline or cloud_tasks when Deep Research is enabled.")
        elif production and worker_mode != "cloud_tasks":
            runtime_blockers.append("Production Deep Research requires DEEP_RESEARCH_WORKER_MODE=cloud_tasks for durable recovery.")
        elif worker_mode == "cloud_tasks":
            queue = os.getenv("DEEP_RESEARCH_TASK_QUEUE", "").strip()
            worker_url = os.getenv("DEEP_RESEARCH_WORKER_URL", "").strip()
            audience = os.getenv("DEEP_RESEARCH_TASK_AUDIENCE", "").strip()
            if not queue:
                runtime_blockers.append("DEEP_RESEARCH_TASK_QUEUE is required for Cloud Tasks worker mode.")
            if not _is_https_origin(worker_url):
                runtime_blockers.append("DEEP_RESEARCH_WORKER_URL must be an HTTPS Cloud Run worker URL.")
            if not audience:
                runtime_blockers.append("DEEP_RESEARCH_TASK_AUDIENCE is required for Cloud Tasks worker authentication.")
        if not production:
            warnings.append("Deep Research is enabled outside production; provider calls remain bounded by the configured per-run ceilings.")

    if os.getenv("BILLING_ENFORCED", "0").strip() != "1":
        release_blockers.append(
            "BILLING_ENFORCED must be 1 before a Play release can be declared ready."
        )
        warnings.append(
            "Billing enforcement is off for internal-track wiring; paid research fails closed in production until it is enabled."
        )

    try:
        entitlement_max_age_hours = int(os.getenv("ENTITLEMENT_MAX_AGE_HOURS", "24"))
    except ValueError:
        entitlement_max_age_hours = 0
    if not 1 <= entitlement_max_age_hours <= 168:
        runtime_blockers.append("ENTITLEMENT_MAX_AGE_HOURS must be between 1 and 168.")

    if not os.getenv("SENTRY_DSN", "").strip():
        warnings.append("SENTRY_DSN is not configured; production error monitoring is optional but recommended.")

    return ReadinessReport(
        runtime_ready=not runtime_blockers,
        release_ready=not runtime_blockers and not release_blockers,
        runtime_blockers=runtime_blockers,
        release_blockers=release_blockers,
        warnings=warnings,
    )
