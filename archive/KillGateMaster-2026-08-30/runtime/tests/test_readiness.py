import os

from fastapi.testclient import TestClient

from app import web
from app.services.readiness import readiness_report


def _clear_release_env(monkeypatch):
    for name in (
        "APP_ENV", "AUTH_MODE", "STATE_BACKEND", "WALLET_BACKEND", "COOKIE_SECURE",
        "SUPABASE_URL", "SUPABASE_PUBLISHABLE_KEY", "SUPABASE_SECRET_KEY",
        "PUBLIC_APP_ORIGIN", "PRIVACY_CONTACT_EMAIL", "SUPPORT_EMAIL",
        "GOOGLE_PLAY_PACKAGE_NAME", "PLAY_APP_SIGNING_SHA256", "GOOGLE_PLAY_FOUNDER_PRO_PRODUCT_ID", "GOOGLE_PLAY_SUBSCRIPTION_PRODUCT_ID",
        "GOOGLE_PLAY_SERVICE_ACCOUNT_JSON", "GOOGLE_PLAY_SERVICE_ACCOUNT_FILE",
        "GOOGLE_PLAY_RTDN_AUDIENCE", "GOOGLE_PLAY_RTDN_SERVICE_ACCOUNT_EMAIL",
        "OPENAI_API_KEY", "OPENAI_REQUIRED", "BILLING_ENFORCED", "SENTRY_DSN",
        "DEEP_RESEARCH_ENABLED", "DEEP_RESEARCH_MAX_MODEL_CALLS", "DEEP_RESEARCH_MAX_SEARCH_CALLS",
        "DEEP_RESEARCH_SOFT_COST_LIMIT_USD", "DEEP_RESEARCH_HARD_COST_LIMIT_USD",
        "RESEARCH_RUNS_PER_HOUR", "RESEARCH_SAFETY_CAP_30D", "RESEARCH_ABUSE_CAP_30D", "RESEARCH_RUNS_PER_30_DAYS", "OPENAI_MAX_OUTPUT_TOKENS",
        "ENTITLEMENT_MAX_AGE_HOURS",
        "KILLGATE_TEST_ADMIN_ENABLED", "KILLGATE_TEST_ADMIN_USER_IDS",
        "KILLGATE_BETA_ENABLED", "KILLGATE_BETA_USER_IDS", "KILLGATE_BETA_START_AT",
        "KILLGATE_BETA_DURATION_DAYS", "KILLGATE_BETA_MAX_RUNS",
    ):
        monkeypatch.delenv(name, raising=False)


def test_health_and_local_readiness_endpoints_are_non_secret(monkeypatch):
    _clear_release_env(monkeypatch)
    monkeypatch.setenv("AUTH_MODE", "local")
    monkeypatch.setenv("STATE_BACKEND", "local")
    with TestClient(web.app) as client:
        health = client.get("/healthz")
        assert health.status_code == 200
        assert health.json() == {"status": "ok", "service": "killgate", "version": web.app.version}

        ready = client.get("/readyz")
        assert ready.status_code == 200
        assert ready.json() == {"status": "ready"}
        text = ready.text
        assert "SUPABASE" not in text
        assert "OPENAI" not in text
        assert "secret" not in text.lower()


def test_production_readiness_fails_closed_without_required_runtime_config(monkeypatch):
    _clear_release_env(monkeypatch)
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("AUTH_MODE", "local")
    monkeypatch.setenv("STATE_BACKEND", "local")
    report = readiness_report()
    assert report.runtime_ready is False
    assert report.release_ready is False
    assert "Production requires AUTH_MODE=supabase." in report.runtime_blockers
    assert "Production requires STATE_BACKEND=supabase." in report.runtime_blockers
    assert "Production requires COOKIE_SECURE=1." in report.runtime_blockers
    assert "OPENAI_API_KEY is required by this production configuration." in report.runtime_blockers

    with TestClient(web.app) as client:
        ready = client.get("/readyz")
        assert ready.status_code == 503
        assert ready.json() == {"status": "not_ready"}


def test_complete_production_configuration_can_be_release_ready(monkeypatch, tmp_path):
    _clear_release_env(monkeypatch)
    creds = tmp_path / "play.json"
    creds.write_text('{"client_email":"publisher@example.iam.gserviceaccount.com","private_key":"not-a-real-key"}')
    values = {
        "APP_ENV": "production",
        "AUTH_MODE": "supabase",
        "STATE_BACKEND": "supabase",
        "COOKIE_SECURE": "1",
        "SUPABASE_URL": "https://abc.supabase.co",
        "SUPABASE_PUBLISHABLE_KEY": "publishable-test-value",
        "SUPABASE_SECRET_KEY": "secret-test-value",
        "PUBLIC_APP_ORIGIN": "https://killgate.example",
        "PRIVACY_CONTACT_EMAIL": "privacy@killgate.example",
        "SUPPORT_EMAIL": "support@killgate.example",
        "GOOGLE_PLAY_PACKAGE_NAME": "app.killgate.mobile",
        "PLAY_APP_SIGNING_SHA256": "AB" * 32,
        "GOOGLE_PLAY_FOUNDER_PRO_PRODUCT_ID": "killgate_founder_pro",
        "GOOGLE_PLAY_SERVICE_ACCOUNT_FILE": str(creds),
        "GOOGLE_PLAY_RTDN_AUDIENCE": "https://killgate.example/billing/google-play/rtdn",
        "GOOGLE_PLAY_RTDN_SERVICE_ACCOUNT_EMAIL": "rtdn@example.iam.gserviceaccount.com",
        "OPENAI_API_KEY": "test-value-never-printed",
        "OPENAI_REQUIRED": "1",
        "BILLING_ENFORCED": "1",
        "SENTRY_DSN": "https://example.invalid/1",
    }
    for key, value in values.items():
        monkeypatch.setenv(key, value)
    report = readiness_report()
    assert report.runtime_ready is True
    assert report.release_ready is True
    assert report.runtime_blockers == []
    assert report.release_blockers == []


def test_test_admin_mode_is_explicitly_blocked_from_release(monkeypatch):
    _clear_release_env(monkeypatch)
    monkeypatch.setenv("KILLGATE_TEST_ADMIN_ENABLED", "1")
    monkeypatch.setenv("KILLGATE_TEST_ADMIN_USER_IDS", "711d4ffd-0141-4d1b-a48b-16bce3dcef73")

    report = readiness_report()

    assert report.runtime_ready is True
    assert report.release_ready is False
    assert "KILLGATE_TEST_ADMIN_ENABLED must be 0 before a Play release can be declared ready." in report.release_blockers
    assert any("Test-admin entitlement bypass is enabled" in item for item in report.warnings)


def test_test_admin_mode_requires_an_allowlist(monkeypatch):
    _clear_release_env(monkeypatch)
    monkeypatch.setenv("KILLGATE_TEST_ADMIN_ENABLED", "1")

    report = readiness_report()

    assert report.runtime_ready is False
    assert "KILLGATE_TEST_ADMIN_ENABLED=1 requires KILLGATE_TEST_ADMIN_USER_IDS." in report.runtime_blockers


def test_play_release_requires_production_and_billing_enforcement(monkeypatch):
    _clear_release_env(monkeypatch)
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("BILLING_ENFORCED", "0")

    report = readiness_report()

    assert "APP_ENV must be production before a Play release can be declared ready." in report.release_blockers
    assert "BILLING_ENFORCED must be 1 before a Play release can be declared ready." in report.release_blockers
    assert report.release_ready is False


def test_privacy_and_support_contacts_are_configured_and_escaped(monkeypatch):
    _clear_release_env(monkeypatch)
    monkeypatch.setenv("AUTH_MODE", "local")
    monkeypatch.setenv("STATE_BACKEND", "local")
    monkeypatch.setenv("PRIVACY_CONTACT_EMAIL", "privacy@killgate.example")
    monkeypatch.setenv("SUPPORT_EMAIL", "support@killgate.example")
    with TestClient(web.app) as client:
        privacy = client.get("/privacy")
        support = client.get("/support")
        assert privacy.status_code == 200
        assert 'mailto:privacy@killgate.example' in privacy.text
        assert "privacy@killgate.example" in privacy.text
        assert support.status_code == 200
        assert 'mailto:support@killgate.example' in support.text
        assert "support@killgate.example" in support.text


def test_readiness_cli_runs_directly_from_repo_root(monkeypatch):
    import subprocess
    from pathlib import Path

    repo_root = Path(__file__).resolve().parents[1]
    env = os.environ.copy()
    for key in list(env):
        if key.startswith(("SUPABASE_", "GOOGLE_PLAY_")) or key in {
            "APP_ENV", "AUTH_MODE", "STATE_BACKEND", "WALLET_BACKEND", "COOKIE_SECURE",
            "PUBLIC_APP_ORIGIN", "PRIVACY_CONTACT_EMAIL", "SUPPORT_EMAIL",
            "OPENAI_API_KEY", "OPENAI_REQUIRED", "BILLING_ENFORCED", "SENTRY_DSN",
        "RESEARCH_RUNS_PER_HOUR", "RESEARCH_SAFETY_CAP_30D", "RESEARCH_ABUSE_CAP_30D", "RESEARCH_RUNS_PER_30_DAYS", "OPENAI_MAX_OUTPUT_TOKENS",
        "ENTITLEMENT_MAX_AGE_HOURS",
        "KILLGATE_TEST_ADMIN_ENABLED", "KILLGATE_TEST_ADMIN_USER_IDS",
        "KILLGATE_BETA_ENABLED", "KILLGATE_BETA_USER_IDS", "KILLGATE_BETA_START_AT",
        "KILLGATE_BETA_DURATION_DAYS", "KILLGATE_BETA_MAX_RUNS",
        }:
            env.pop(key, None)
    env.update({"AUTH_MODE": "local", "STATE_BACKEND": "local", "APP_ENV": "development"})
    result = subprocess.run(
        [os.sys.executable, "scripts/check_production_readiness.py", "--json"],
        cwd=repo_root,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    payload = __import__("json").loads(result.stdout)
    assert payload["runtime_ready"] is True
    assert "test-value-never-printed" not in result.stdout


def test_production_readiness_rejects_unbounded_ai_configuration(monkeypatch):
    _clear_release_env(monkeypatch)
    monkeypatch.setenv("AUTH_MODE", "local")
    monkeypatch.setenv("STATE_BACKEND", "local")
    monkeypatch.setenv("RESEARCH_RUNS_PER_HOUR", "1000")
    monkeypatch.setenv("RESEARCH_SAFETY_CAP_30D", "50000")
    monkeypatch.setenv("OPENAI_MAX_OUTPUT_TOKENS", "50000")
    report = readiness_report()
    assert "RESEARCH_RUNS_PER_HOUR must be between 1 and 100." in report.runtime_blockers
    assert "RESEARCH_SAFETY_CAP_30D must be between 1 and 500." in report.runtime_blockers
    assert "OPENAI_MAX_OUTPUT_TOKENS must be between 256 and 8000." in report.runtime_blockers


def test_deep_research_readiness_rejects_invalid_per_run_budget(monkeypatch):
    _clear_release_env(monkeypatch)
    monkeypatch.setenv("DEEP_RESEARCH_ENABLED", "1")
    monkeypatch.setenv("DEEP_RESEARCH_MAX_MODEL_CALLS", "0")
    monkeypatch.setenv("DEEP_RESEARCH_MAX_SEARCH_CALLS", "201")
    monkeypatch.setenv("DEEP_RESEARCH_SOFT_COST_LIMIT_USD", "1.25")
    monkeypatch.setenv("DEEP_RESEARCH_HARD_COST_LIMIT_USD", "0.60")
    report = readiness_report()
    assert any("DEEP_RESEARCH_MAX_MODEL_CALLS" in item for item in report.runtime_blockers)
    assert any("DEEP_RESEARCH_MAX_SEARCH_CALLS" in item for item in report.runtime_blockers)
    assert any("DEEP_RESEARCH_HARD_COST_LIMIT_USD" in item for item in report.runtime_blockers)


def test_deep_research_readiness_warns_when_enabled_in_development(monkeypatch):
    _clear_release_env(monkeypatch)
    monkeypatch.setenv("DEEP_RESEARCH_ENABLED", "1")
    report = readiness_report()
    assert report.runtime_ready is True
    assert any("Deep Research is enabled outside production" in item for item in report.warnings)


def test_cross_origin_login_post_is_rejected_before_auth(monkeypatch):
    _clear_release_env(monkeypatch)
    monkeypatch.setenv("AUTH_MODE", "supabase")
    monkeypatch.setenv("STATE_BACKEND", "supabase")
    monkeypatch.setenv("PUBLIC_APP_ORIGIN", "https://killgate.example")
    with TestClient(web.app, base_url="https://killgate.example") as client:
        response = client.post(
            "/login",
            data={"email": "attacker@example.com", "password": "password123", "next": "/"},
            headers={"Origin": "https://evil.example"},
        )
        assert response.status_code == 403
        assert "Cross-origin request rejected" in response.text


def test_production_cannot_disable_required_ai_path(monkeypatch):
    _clear_release_env(monkeypatch)
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("AUTH_MODE", "supabase")
    monkeypatch.setenv("STATE_BACKEND", "supabase")
    monkeypatch.setenv("COOKIE_SECURE", "1")
    monkeypatch.setenv("SUPABASE_URL", "https://abc.supabase.co")
    monkeypatch.setenv("SUPABASE_PUBLISHABLE_KEY", "publishable")
    monkeypatch.setenv("SUPABASE_SECRET_KEY", "secret")
    monkeypatch.setenv("OPENAI_REQUIRED", "0")
    monkeypatch.setenv("OPENAI_API_KEY", "configured-but-disabled")

    report = readiness_report()

    assert "Production requires OPENAI_REQUIRED=1 so AI failures cannot silently change the research engine." in report.runtime_blockers


def test_safe_next_rejects_backslash_and_external_redirect_tricks():
    assert web._safe_next("//evil.example/path") == "/"
    assert web._safe_next("/\\evil.example/path") == "/"
    assert web._safe_next("https://evil.example") == "/"
    assert web._safe_next("/account?billing=required") == "/account?billing=required"


def test_readiness_rejects_noncanonical_origin_bad_package_and_bad_cookie_age(monkeypatch):
    _clear_release_env(monkeypatch)
    monkeypatch.setenv("PUBLIC_APP_ORIGIN", "https://user:pass@killgate.example:8443")
    monkeypatch.setenv("GOOGLE_PLAY_PACKAGE_NAME", "not-a-package")
    monkeypatch.setenv("SESSION_COOKIE_MAX_AGE", "forever")

    report = readiness_report()

    assert "PUBLIC_APP_ORIGIN must be the final HTTPS Killgate origin." in report.release_blockers
    assert "GOOGLE_PLAY_PACKAGE_NAME must be the final valid Android package ID." in report.release_blockers
    assert "SESSION_COOKIE_MAX_AGE must be between 1 hour and 90 days." in report.runtime_blockers


def test_missing_origin_on_supabase_mutation_is_rejected(monkeypatch):
    _clear_release_env(monkeypatch)
    monkeypatch.setenv("AUTH_MODE", "supabase")
    monkeypatch.setenv("STATE_BACKEND", "supabase")
    monkeypatch.setenv("PUBLIC_APP_ORIGIN", "https://killgate.example")
    monkeypatch.setenv("SUPABASE_URL", "https://project.supabase.test")
    monkeypatch.setenv("SUPABASE_PUBLISHABLE_KEY", "publishable")
    with TestClient(web.app, base_url="https://killgate.example") as client:
        response = client.post(
            "/login",
            data={"email": "user@example.com", "password": "password123", "next": "/"},
        )
    assert response.status_code == 403
    assert "Cross-origin request rejected" in response.text
