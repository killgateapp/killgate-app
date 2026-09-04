import httpx
import pytest
from fastapi.testclient import TestClient

from app import web
from app.services import auth


class FakeResponse:
    def __init__(self, status_code, payload=None):
        self.status_code = status_code
        self._payload = payload if payload is not None else {}

    def json(self):
        return self._payload


@pytest.fixture
def supabase_env(monkeypatch):
    monkeypatch.setenv("AUTH_MODE", "supabase")
    monkeypatch.setenv("SUPABASE_URL", "https://project.supabase.test")
    monkeypatch.setenv("SUPABASE_PUBLISHABLE_KEY", "publishable")
    monkeypatch.setenv("PUBLIC_APP_ORIGIN", "http://testserver")
    monkeypatch.setenv("COOKIE_SECURE", "0")


def test_valid_access_token_resolves_without_refresh(monkeypatch, supabase_env):
    seen = {"post": 0}
    monkeypatch.setattr(
        auth.httpx,
        "get",
        lambda *args, **kwargs: FakeResponse(200, {"id": "user-1", "email": "u@example.test"}),
    )
    monkeypatch.setattr(auth.httpx, "post", lambda *a, **k: seen.update(post=seen["post"] + 1))

    request = type("R", (), {"cookies": {auth.ACCESS_COOKIE: "access", auth.REFRESH_COOKIE: "refresh"}})()
    resolution = auth.resolve_request_session(request)
    assert resolution.user.user_id == "user-1"
    assert resolution.refreshed is False
    assert seen["post"] == 0


def test_expired_access_refreshes_session(monkeypatch, supabase_env):
    monkeypatch.setattr(auth.httpx, "get", lambda *a, **k: FakeResponse(401))
    monkeypatch.setattr(
        auth.httpx,
        "post",
        lambda *a, **k: FakeResponse(
            200,
            {
                "access_token": "new-access",
                "refresh_token": "new-refresh",
                "user": {"id": "user-1", "email": "u@example.test"},
            },
        ),
    )
    request = type("R", (), {"cookies": {auth.ACCESS_COOKIE: "old", auth.REFRESH_COOKIE: "refresh"}})()
    resolution = auth.resolve_request_session(request)
    assert resolution.user.user_id == "user-1"
    assert resolution.access_token == "new-access"
    assert resolution.refreshed is True


def test_auth_provider_outage_is_not_interpreted_as_logout(monkeypatch, supabase_env):
    monkeypatch.setattr(auth.httpx, "get", lambda *a, **k: FakeResponse(503))
    request = type("R", (), {"cookies": {auth.ACCESS_COOKIE: "still-valid", auth.REFRESH_COOKIE: "refresh"}})()
    with pytest.raises(auth.AuthUnavailable):
        auth.resolve_request_session(request)


def test_auth_transport_failure_is_not_interpreted_as_logout(monkeypatch, supabase_env):
    monkeypatch.setattr(
        auth.httpx,
        "get",
        lambda *a, **k: (_ for _ in ()).throw(httpx.ConnectError("down")),
    )
    request = type("R", (), {"cookies": {auth.ACCESS_COOKIE: "still-valid"}})()
    with pytest.raises(auth.AuthUnavailable):
        auth.resolve_request_session(request)


def test_login_bad_credentials_remain_user_error(monkeypatch, supabase_env):
    monkeypatch.setattr(auth.httpx, "post", lambda *a, **k: FakeResponse(400))
    with pytest.raises(ValueError, match="Check your email"):
        auth.sign_in("bad@example.test", "wrong")


def test_login_provider_error_is_operational(monkeypatch, supabase_env):
    monkeypatch.setattr(auth.httpx, "post", lambda *a, **k: FakeResponse(503))
    with pytest.raises(auth.AuthUnavailable):
        auth.sign_in("u@example.test", "password123")


def test_signup_sends_public_origin_redirect(monkeypatch, supabase_env):
    seen = {}

    def fake_post(*args, **kwargs):
        seen.update(url=args[0], payload=kwargs["json"])
        return FakeResponse(200)

    monkeypatch.setattr(auth.httpx, "post", fake_post)
    resolution = auth.sign_up("u@example.test", "password123")

    assert resolution.user is None
    assert seen["url"].endswith("/auth/v1/signup")
    assert seen["payload"] == {
        "email": "u@example.test",
        "password": "password123",
        "redirect_to": "http://testserver",
    }


def test_signup_email_rate_limit_is_reported_as_a_retryable_auth_error(monkeypatch, supabase_env):
    monkeypatch.setattr(
        auth.httpx,
        "post",
        lambda *args, **kwargs: FakeResponse(
            429,
            {"code": "over_email_send_rate_limit", "msg": "email rate limit exceeded"},
        ),
    )

    with pytest.raises(auth.AuthRateLimited, match="Confirmation email delivery"):
        auth.sign_up("u@example.test", "password123")


def test_web_signup_explains_email_rate_limit(monkeypatch, supabase_env):
    monkeypatch.setattr(web.limiter, "allow_pre_auth", lambda *args, **kwargs: True)
    monkeypatch.setattr(
        web,
        "sign_up",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            auth.AuthRateLimited(
                "Confirmation email delivery is temporarily rate-limited. "
                "Wait before trying again, or configure custom SMTP for the Supabase project."
            )
        ),
    )

    with TestClient(web.app, base_url="http://testserver") as client:
        response = client.post(
            "/signup",
            data={"email": "u@example.test", "password": "password123", "next": "/"},
            headers={"Origin": "http://testserver"},
            follow_redirects=False,
        )
        page = client.get(response.headers["location"])

    assert response.status_code == 303
    assert "Confirmation email delivery is temporarily rate-limited" in page.text


def test_auth_pages_include_password_visibility_controls(supabase_env):
    with TestClient(web.app, base_url="http://testserver") as client:
        login = client.get("/login")
        signup = client.get("/signup")
        script = client.get("/static/app.js")

    assert login.status_code == 200
    assert signup.status_code == 200
    assert 'data-password-toggle' in login.text
    assert 'aria-controls="login-password"' in login.text
    assert 'data-password-toggle' in signup.text
    assert 'aria-controls="signup-password"' in signup.text
    assert 'autocapitalize="none"' in login.text
    assert 'autocapitalize="none"' in signup.text
    assert "Already have an account?" in signup.text
    assert "Hide password" in script.text


def test_signup_attempt_limits_are_configurable(monkeypatch, supabase_env):
    seen = []

    def fake_allow(value, bucket, limit):
        seen.append((value, bucket, limit.requests, limit.seconds))
        return True

    monkeypatch.setenv("KILLGATE_SIGNUP_ACCOUNT_LIMIT_1H", "7")
    monkeypatch.setenv("KILLGATE_SIGNUP_SOURCE_LIMIT_1H", "80")
    monkeypatch.setenv("KILLGATE_SIGNUP_GLOBAL_LIMIT_1H", "2000")
    monkeypatch.setattr(web.limiter, "allow_pre_auth", fake_allow)
    monkeypatch.setattr(
        web,
        "sign_up",
        lambda email, password: auth.SessionResolution(
            auth.AuthUser("user-1", email, "access"),
            access_token="access",
            refresh_token="refresh",
        ),
    )

    with TestClient(web.app, base_url="http://testserver") as client:
        response = client.post(
            "/signup",
            data={"email": "person@example.test", "password": "password123", "next": "/"},
            headers={"Origin": "http://testserver"},
            follow_redirects=False,
        )

    assert response.status_code == 303
    assert ("person@example.test", "signup-account", 7, 60 * 60) in seen
    assert ("testclient", "signup-source", 80, 60 * 60) in seen
    assert ("global", "signup-global", 2000, 60 * 60) in seen


def test_account_deletion_transport_failure_does_not_claim_success(monkeypatch, supabase_env):
    monkeypatch.setattr(
        auth.httpx,
        "post",
        lambda *a, **k: (_ for _ in ()).throw(httpx.ConnectError("down")),
    )
    with pytest.raises(auth.AuthUnavailable):
        auth.request_account_deletion("access")


def test_web_auth_outage_returns_503_without_login_redirect(monkeypatch, supabase_env):
    monkeypatch.setattr(
        web,
        "resolve_request_session",
        lambda request: (_ for _ in ()).throw(auth.AuthUnavailable("temporary")),
    )
    with TestClient(web.app) as client:
        response = client.get("/account", follow_redirects=False)
    assert response.status_code == 503
    assert "session was not cleared" in response.text


def test_login_is_blocked_before_password_provider_when_attempt_limit_is_reached(monkeypatch, supabase_env):
    monkeypatch.setattr(web.limiter, "allow_pre_auth", lambda *args, **kwargs: False)
    monkeypatch.setattr(
        web,
        "sign_in",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("Password provider must not be called after the attempt cap")
        ),
    )
    with TestClient(web.app, base_url="http://testserver") as client:
        response = client.post(
            "/login",
            data={"email": "person@example.test", "password": "password123", "next": "/"},
            headers={"Origin": "http://testserver"},
        )

    assert response.status_code == 429
    assert "Too many sign-in attempts" in response.text


def test_invalid_session_cookies_are_cleared_after_confirmed_auth_failure(monkeypatch, supabase_env):
    monkeypatch.setattr(web, "resolve_request_session", lambda request: auth.SessionResolution(user=None))
    with TestClient(web.app) as client:
        client.cookies.set(auth.ACCESS_COOKIE, "expired-access")
        client.cookies.set(auth.REFRESH_COOKIE, "expired-refresh")
        response = client.get("/login", follow_redirects=False)

    assert response.status_code == 200
    set_cookies = response.headers.get_list("set-cookie")
    assert any(f"{auth.ACCESS_COOKIE}=" in item and "Max-Age=0" in item for item in set_cookies)
    assert any(f"{auth.REFRESH_COOKIE}=" in item and "Max-Age=0" in item for item in set_cookies)
