from datetime import UTC, datetime, timedelta

from app.services import research_policy


def _clear_policy_env(monkeypatch):
    for name in (
        "RESEARCH_SAFETY_CAP_30D",
        "RESEARCH_ABUSE_CAP_30D",
        "KILLGATE_TEST_ADMIN_ENABLED",
        "KILLGATE_TEST_ADMIN_USER_IDS",
        "KILLGATE_BETA_ENABLED",
        "KILLGATE_BETA_USER_IDS",
        "KILLGATE_BETA_START_AT",
        "KILLGATE_BETA_DURATION_DAYS",
        "KILLGATE_BETA_MAX_RUNS",
    ):
        monkeypatch.delenv(name, raising=False)


def test_beta_policy_grants_nine_runs_for_fourteen_days_only(monkeypatch):
    _clear_policy_env(monkeypatch)
    start = datetime(2026, 8, 28, tzinfo=UTC)
    monkeypatch.setenv("KILLGATE_BETA_ENABLED", "1")
    monkeypatch.setenv("KILLGATE_BETA_USER_IDS", "Beta-User")
    monkeypatch.setenv("KILLGATE_BETA_START_AT", start.isoformat())

    policy = research_policy.beta_policy()

    assert policy.valid is True
    assert policy.max_runs == 9
    assert policy.duration_days == 14
    assert research_policy.is_beta_user("beta-user", now=start + timedelta(days=13, hours=23)) is True
    assert research_policy.is_beta_user("beta-user", now=start + timedelta(days=14)) is False
    assert research_policy.is_beta_user("other-user", now=start + timedelta(days=1)) is False


def test_beta_policy_fails_closed_without_a_start(monkeypatch):
    _clear_policy_env(monkeypatch)
    monkeypatch.setenv("KILLGATE_BETA_ENABLED", "1")
    monkeypatch.setenv("KILLGATE_BETA_USER_IDS", "beta-user")

    assert research_policy.beta_policy().valid is False
    assert research_policy.is_beta_user("beta-user") is False


def test_test_admin_requires_explicit_switch_and_allowlist(monkeypatch):
    _clear_policy_env(monkeypatch)
    monkeypatch.setenv("KILLGATE_TEST_ADMIN_USER_IDS", "Admin-User")
    assert research_policy.is_test_admin("admin-user") is False

    monkeypatch.setenv("KILLGATE_TEST_ADMIN_ENABLED", "1")
    assert research_policy.is_test_admin("admin-user") is True
    assert research_policy.is_test_admin("other-user") is False


def test_safety_cap_defaults_to_thirty_and_supports_new_name(monkeypatch):
    _clear_policy_env(monkeypatch)
    assert research_policy.research_safety_cap_30d() == 30

    monkeypatch.setenv("RESEARCH_SAFETY_CAP_30D", "42")
    assert research_policy.research_safety_cap_30d() == 42
