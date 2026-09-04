import logging

import pytest

from app.services import rate_limit


def test_local_rate_limit_blocks_after_cap(monkeypatch):
    monkeypatch.setenv("AUTH_MODE", "local")
    limiter = rate_limit.SlidingWindowLimiter()
    limit = rate_limit.Limit(2, 3600)

    assert limiter.allow("research:local-user", limit) is True
    assert limiter.allow("research:local-user", limit) is True
    assert limiter.allow("research:local-user", limit) is False


def test_supabase_rate_limit_uses_server_only_atomic_rpc(monkeypatch):
    monkeypatch.setenv("AUTH_MODE", "supabase")
    monkeypatch.setenv("SUPABASE_URL", "https://project.example")
    monkeypatch.setenv("SUPABASE_SECRET_KEY", "server-secret")
    seen = {}

    class Response:
        status_code = 200

        @staticmethod
        def json():
            return True

    def fake_post(url, *, headers, json, timeout):
        seen.update(url=url, headers=headers, json=json, timeout=timeout)
        return Response()

    monkeypatch.setattr(rate_limit.httpx, "post", fake_post)
    limiter = rate_limit.SlidingWindowLimiter()

    allowed = limiter.allow(
        "research:11111111-1111-1111-1111-111111111111",
        rate_limit.Limit(8, 3600),
    )

    assert allowed is True
    assert seen["url"].endswith("/rest/v1/rpc/killgate_rate_limit_allow")
    assert seen["headers"] == {"apikey": "server-secret", "Content-Type": "application/json"}
    assert seen["json"] == {
        "p_user_id": "11111111-1111-1111-1111-111111111111",
        "p_bucket": "research",
        "p_max": 8,
        "p_window_seconds": 3600,
    }


def test_supabase_rate_limit_fails_closed_when_server_secret_is_missing(monkeypatch):
    monkeypatch.setenv("AUTH_MODE", "supabase")
    monkeypatch.setenv("SUPABASE_URL", "https://project.example")
    monkeypatch.delenv("SUPABASE_SECRET_KEY", raising=False)
    limiter = rate_limit.SlidingWindowLimiter()

    with pytest.raises(rate_limit.RateLimitUnavailable):
        limiter.allow(
            "research:11111111-1111-1111-1111-111111111111",
            rate_limit.Limit(8, 3600),
        )


def test_supabase_rate_limit_transport_detail_is_not_logged(monkeypatch, caplog):
    sentinel = "synthetic-supabase-transport-detail-should-not-reach-logs"
    monkeypatch.setenv("AUTH_MODE", "supabase")
    monkeypatch.setenv("SUPABASE_URL", "https://project.example")
    monkeypatch.setenv("SUPABASE_SECRET_KEY", "server-secret")
    monkeypatch.setattr(
        rate_limit.httpx,
        "post",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            rate_limit.httpx.ConnectError(sentinel)
        ),
    )
    caplog.set_level(logging.WARNING, logger=rate_limit.__name__)

    with pytest.raises(rate_limit.RateLimitUnavailable):
        rate_limit.SlidingWindowLimiter().allow("research:user-1", rate_limit.Limit(8, 3600))

    assert "Distributed rate limiter unavailable (ConnectError)." in caplog.text
    assert sentinel not in caplog.text


def test_supabase_pre_auth_limit_uses_hmac_key_and_server_only_rpc(monkeypatch):
    monkeypatch.setenv("AUTH_MODE", "supabase")
    monkeypatch.setenv("SUPABASE_URL", "https://project.example")
    monkeypatch.setenv("SUPABASE_SECRET_KEY", "server-secret")
    seen = {}

    class Response:
        status_code = 200

        @staticmethod
        def json():
            return True

    def fake_post(url, *, headers, json, timeout):
        seen.update(url=url, headers=headers, json=json, timeout=timeout)
        return Response()

    monkeypatch.setattr(rate_limit.httpx, "post", fake_post)
    limiter = rate_limit.SlidingWindowLimiter()

    assert limiter.allow_pre_auth("person@example.test", "login-account", rate_limit.Limit(10, 900)) is True
    assert seen["url"].endswith("/rest/v1/rpc/killgate_pre_auth_rate_limit_allow")
    assert seen["json"]["p_key_hash"] != "person@example.test"
    assert len(seen["json"]["p_key_hash"]) == 64
    assert seen["json"]["p_bucket"] == "login-account"


def test_local_research_quota_consumes_only_after_both_windows_clear(monkeypatch):
    monkeypatch.setenv("AUTH_MODE", "local")
    limiter = rate_limit.SlidingWindowLimiter()

    assert limiter.allow_research("local-user", hourly_requests=2, rolling_30d_requests=3) is True
    assert limiter.allow_research("local-user", hourly_requests=2, rolling_30d_requests=3) is True
    assert limiter.allow_research("local-user", hourly_requests=2, rolling_30d_requests=3) is False

    # A blocked hourly attempt must not consume the rolling allowance.
    assert len(limiter._events["research-rolling:local-user"]) == 2


def test_supabase_research_quota_uses_atomic_rpc(monkeypatch):
    monkeypatch.setenv("AUTH_MODE", "supabase")
    monkeypatch.setenv("SUPABASE_URL", "https://project.example")
    monkeypatch.setenv("SUPABASE_SECRET_KEY", "server-secret")
    seen = {}

    class Response:
        status_code = 200

        @staticmethod
        def json():
            return 123

    def fake_post(url, *, headers, json, timeout):
        seen.update(url=url, headers=headers, json=json, timeout=timeout)
        return Response()

    monkeypatch.setattr(rate_limit.httpx, "post", fake_post)
    limiter = rate_limit.SlidingWindowLimiter()

    allowed = limiter.allow_research(
        "11111111-1111-1111-1111-111111111111",
        hourly_requests=8,
        rolling_30d_requests=30,
    )

    assert allowed is True
    assert seen["url"].endswith("/rest/v1/rpc/killgate_research_quota_reserve_once")
    import uuid
    assert str(uuid.UUID(seen["json"]["p_research_run_id"])) == seen["json"]["p_research_run_id"]
    assert seen["json"] == {
        "p_user_id": "11111111-1111-1111-1111-111111111111",
        "p_research_run_id": seen["json"]["p_research_run_id"],
        "p_hourly_max": 8,
        "p_rolling_max": 30,
        "p_rolling_window_seconds": 30 * 24 * 3600,
    }


def test_supabase_research_quota_supports_a_fourteen_day_window(monkeypatch):
    monkeypatch.setenv("AUTH_MODE", "supabase")
    monkeypatch.setenv("SUPABASE_URL", "https://project.example")
    monkeypatch.setenv("SUPABASE_SECRET_KEY", "server-secret")
    seen = {}

    class Response:
        status_code = 200

        @staticmethod
        def json():
            return 123

    def fake_post(url, *, headers, json, timeout):
        seen.update(url=url, json=json)
        return Response()

    monkeypatch.setattr(rate_limit.httpx, "post", fake_post)
    limiter = rate_limit.SlidingWindowLimiter()

    assert limiter.reserve_research(
        "11111111-1111-1111-1111-111111111111",
        hourly_requests=8,
        rolling_30d_requests=9,
        rolling_window_seconds=14 * 24 * 3600,
    ) is not None
    assert seen["json"]["p_rolling_max"] == 9
    assert seen["json"]["p_rolling_window_seconds"] == 14 * 24 * 3600


def test_local_failed_research_reservation_can_be_released(monkeypatch):
    monkeypatch.setenv("AUTH_MODE", "local")
    limiter = rate_limit.SlidingWindowLimiter()
    reservation = limiter.reserve_research("user-1", hourly_requests=1, rolling_30d_requests=1)
    assert reservation is not None
    assert limiter.reserve_research("user-1", hourly_requests=1, rolling_30d_requests=1) is None
    limiter.release_research("user-1", reservation)
    assert limiter.reserve_research("user-1", hourly_requests=1, rolling_30d_requests=1) is not None


def test_supabase_research_release_uses_server_only_rpc(monkeypatch):
    monkeypatch.setenv("AUTH_MODE", "supabase")
    monkeypatch.setenv("SUPABASE_URL", "https://project.example")
    monkeypatch.setenv("SUPABASE_SECRET_KEY", "server-secret")
    seen = []

    class Response:
        status_code = 200
        def json(self): return True

    monkeypatch.setattr(
        rate_limit.httpx,
        "post",
        lambda url, **kwargs: (seen.append((url, kwargs)) or Response()),
    )
    limiter = rate_limit.SlidingWindowLimiter()
    limiter.release_research(
        "11111111-1111-1111-1111-111111111111",
        rate_limit.ResearchReservation(token="supabase:42"),
    )
    assert seen[0][0].endswith("/rest/v1/rpc/killgate_research_quota_release")
    assert seen[0][1]["json"]["p_event_id"] == 42
