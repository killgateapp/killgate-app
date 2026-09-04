"""Supabase Auth session handling for Killgate's single-person account model."""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

import httpx
from fastapi import Request
from fastapi.responses import Response

ACCESS_COOKIE = "kg_access"
REFRESH_COOKIE = "kg_refresh"


class AuthUnavailable(RuntimeError):
    """Temporary Supabase/Auth transport failure; do not reinterpret as signed-out."""


class AuthRateLimited(AuthUnavailable):
    """Supabase accepted the signup path but throttled confirmation email delivery."""


@dataclass
class AuthUser:
    user_id: str
    email: str
    access_token: str = ""


@dataclass
class SessionResolution:
    user: AuthUser | None
    access_token: str = ""
    refresh_token: str = ""
    refreshed: bool = False


def auth_mode() -> str:
    return os.getenv("AUTH_MODE", "local").strip().lower()


def _config() -> tuple[str, str]:
    url = os.getenv("SUPABASE_URL", "").rstrip("/")
    key = os.getenv("SUPABASE_PUBLISHABLE_KEY", "").strip()
    if not url or not key:
        raise AuthUnavailable("Supabase auth is not configured.")
    return url, key


def _headers(*, token: str = "") -> dict[str, str]:
    _, key = _config()
    headers = {"apikey": key, "Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _user(payload: dict[str, Any], token: str) -> AuthUser | None:
    user_id = str(payload.get("id") or "").strip()
    email = str(payload.get("email") or "").strip()
    return AuthUser(user_id, email, token) if user_id else None


def _request_json(response: httpx.Response, *, context: str) -> dict[str, Any]:
    try:
        payload = response.json()
    except ValueError as exc:
        raise AuthUnavailable(f"{context} returned invalid JSON.") from exc
    if not isinstance(payload, dict):
        raise AuthUnavailable(f"{context} returned an invalid payload.")
    return payload


def _get_user(token: str) -> AuthUser | None:
    if not token:
        return None
    url, _ = _config()
    try:
        response = httpx.get(
            f"{url}/auth/v1/user",
            headers=_headers(token=token),
            timeout=15,
        )
    except httpx.HTTPError as exc:
        raise AuthUnavailable("The authentication service could not be reached.") from exc
    if response.status_code == 200:
        return _user(_request_json(response, context="Authentication service"), token)
    if response.status_code in {400, 401, 403}:
        return None
    raise AuthUnavailable(
        f"Authentication service returned HTTP {response.status_code}."
    )


def _refresh(refresh: str) -> SessionResolution:
    if not refresh:
        return SessionResolution(None)
    url, _ = _config()
    try:
        response = httpx.post(
            f"{url}/auth/v1/token?grant_type=refresh_token",
            headers=_headers(),
            json={"refresh_token": refresh},
            timeout=15,
        )
    except httpx.HTTPError as exc:
        raise AuthUnavailable("The authentication service could not refresh the session.") from exc
    if response.status_code in {400, 401, 403}:
        return SessionResolution(None)
    if response.status_code != 200:
        raise AuthUnavailable(
            f"Authentication refresh returned HTTP {response.status_code}."
        )
    payload = _request_json(response, context="Authentication refresh")
    access = str(payload.get("access_token") or "").strip()
    new_refresh = str(payload.get("refresh_token") or refresh).strip()
    if not access:
        raise AuthUnavailable("Authentication refresh returned no access token.")
    embedded = payload.get("user")
    user = _user(embedded, access) if isinstance(embedded, dict) else None
    user = user or _get_user(access)
    if not user:
        return SessionResolution(None)
    return SessionResolution(user, access, new_refresh, refreshed=True)


def resolve_request_session(request: Request) -> SessionResolution:
    if auth_mode() != "supabase":
        return SessionResolution(
            AuthUser(
                os.getenv("LOCAL_USER_ID", "local-user"),
                os.getenv("LOCAL_USER_EMAIL", "local@killgate.dev"),
                "",
            )
        )
    access = request.cookies.get(ACCESS_COOKIE, "")
    refresh = request.cookies.get(REFRESH_COOKIE, "")
    user = _get_user(access)
    return SessionResolution(user, access, refresh) if user else _refresh(refresh)


def sign_in(email: str, password: str) -> SessionResolution:
    url, _ = _config()
    try:
        response = httpx.post(
            f"{url}/auth/v1/token?grant_type=password",
            headers=_headers(),
            json={"email": email, "password": password},
            timeout=20,
        )
    except httpx.HTTPError as exc:
        raise AuthUnavailable("Sign-in service could not be reached.") from exc
    if response.status_code in {400, 401, 403}:
        raise ValueError("Sign-in failed. Check your email and password.")
    if response.status_code != 200:
        raise AuthUnavailable(f"Sign-in service returned HTTP {response.status_code}.")
    payload = _request_json(response, context="Sign-in service")
    access = str(payload.get("access_token") or "").strip()
    refresh = str(payload.get("refresh_token") or "").strip()
    embedded = payload.get("user")
    user = _user(embedded, access) if isinstance(embedded, dict) else None
    if not user or not access or not refresh:
        raise AuthUnavailable("Sign-in returned an incomplete session.")
    return SessionResolution(user, access, refresh)


def sign_up(email: str, password: str) -> SessionResolution:
    url, _ = _config()
    payload = {"email": email, "password": password}
    redirect_to = os.getenv("PUBLIC_APP_ORIGIN", "").strip().rstrip("/")
    if redirect_to:
        payload["redirect_to"] = redirect_to
    try:
        response = httpx.post(
            f"{url}/auth/v1/signup",
            headers=_headers(),
            json=payload,
            timeout=20,
        )
    except httpx.HTTPError as exc:
        raise AuthUnavailable("Account creation service could not be reached.") from exc
    if response.status_code == 429:
        try:
            error_payload = response.json()
            error_code = str(error_payload.get("code") or "").strip().lower()
            error_message = str(
                error_payload.get("msg") or error_payload.get("message") or ""
            ).strip().lower()
        except (ValueError, AttributeError):
            error_code = ""
            error_message = ""
        if error_code == "over_email_send_rate_limit" or "email rate limit" in error_message:
            raise AuthRateLimited(
                "Confirmation email delivery is temporarily rate-limited. "
                "Wait before trying again, or configure custom SMTP for the Supabase project."
            )
        raise AuthUnavailable("Account creation service returned HTTP 429.")
    if response.status_code in {400, 409, 422}:
        try:
            payload = response.json()
            message = str(
                payload.get("msg") or payload.get("message") or "Account creation failed."
            )
        except (ValueError, AttributeError):
            message = "Account creation failed."
        raise ValueError(message)
    if response.status_code not in (200, 201):
        raise AuthUnavailable(
            f"Account creation service returned HTTP {response.status_code}."
        )
    payload = _request_json(response, context="Account creation service")
    access = str(payload.get("access_token") or "").strip()
    refresh = str(payload.get("refresh_token") or "").strip()
    embedded = payload.get("user")
    user = _user(embedded, access) if access and isinstance(embedded, dict) else None
    return SessionResolution(user, access, refresh)


def set_session_cookies(response: Response, session: SessionResolution) -> None:
    secure = os.getenv("COOKIE_SECURE", "1" if auth_mode() == "supabase" else "0") == "1"
    try:
        max_age = int(os.getenv("SESSION_COOKIE_MAX_AGE", str(60 * 60 * 24 * 30)))
    except ValueError:
        max_age = 60 * 60 * 24 * 30
    max_age = max(60 * 60, min(max_age, 60 * 60 * 24 * 90))
    if session.access_token:
        response.set_cookie(
            ACCESS_COOKIE,
            session.access_token,
            httponly=True,
            secure=secure,
            samesite="strict",
            max_age=max_age,
            path="/",
        )
    if session.refresh_token:
        response.set_cookie(
            REFRESH_COOKIE,
            session.refresh_token,
            httponly=True,
            secure=secure,
            samesite="strict",
            max_age=max_age,
            path="/",
        )


def clear_session_cookies(response: Response) -> None:
    response.delete_cookie(ACCESS_COOKIE, path="/")
    response.delete_cookie(REFRESH_COOKIE, path="/")


def sign_out(access_token: str) -> None:
    if auth_mode() != "supabase" or not access_token:
        return
    url, _ = _config()
    try:
        httpx.post(
            f"{url}/auth/v1/logout?scope=global",
            headers=_headers(token=access_token),
            timeout=10,
        )
    except (httpx.HTTPError, AuthUnavailable):
        # Local cookie deletion still signs this device out. Remote global logout
        # is best-effort and must never trap the user on the logout action.
        pass


def request_account_deletion(access_token: str) -> None:
    url, key = _config()
    try:
        response = httpx.post(
            f"{url}/functions/v1/delete-killgate-account",
            headers={
                "apikey": key,
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json",
            },
            json={"confirm": True},
            timeout=20,
        )
    except httpx.HTTPError as exc:
        raise AuthUnavailable("Account deletion service could not be reached.") from exc
    if response.status_code not in (200, 204):
        raise AuthUnavailable("Account deletion could not be completed.")
