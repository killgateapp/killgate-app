"""Rate limiting with local dev windows and atomic Supabase production windows."""
from __future__ import annotations

import hashlib
import hmac
import logging
import os
import threading
import time
import uuid
from collections import defaultdict, deque
from dataclasses import dataclass

import httpx

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Limit:
    requests: int
    seconds: int


class RateLimitUnavailable(RuntimeError):
    """Raised when the production distributed limiter cannot be consulted safely."""


@dataclass(frozen=True)
class ResearchReservation:
    token: str
    local_timestamp: float | None = None


class SlidingWindowLimiter:
    def __init__(self):
        self._events: dict[str, deque[float]] = defaultdict(deque)
        self._research_runs: dict[tuple[str, str], ResearchReservation | None] = {}
        self._lock = threading.RLock()

    @staticmethod
    def _production_mode() -> bool:
        return os.getenv("AUTH_MODE", "local").strip().lower() == "supabase"

    @staticmethod
    def _split_key(key: str) -> tuple[str, str]:
        bucket, separator, user_id = key.partition(":")
        if not separator or not bucket or not user_id:
            raise ValueError("Rate-limit keys must use 'bucket:user_id'.")
        return bucket[:80], user_id

    @staticmethod
    def _validate_limit(limit: Limit) -> bool:
        return 1 <= limit.requests <= 10000 and 1 <= limit.seconds <= 2678400

    def _prune_local(self, key: str, seconds: int, now: float) -> deque[float]:
        cutoff = now - seconds
        events = self._events[key]
        while events and events[0] <= cutoff:
            events.popleft()
        return events

    def _allow_local(self, key: str, limit: Limit) -> bool:
        if not self._validate_limit(limit):
            return False
        now = time.monotonic()
        events = self._prune_local(key, limit.seconds, now)
        if len(events) >= limit.requests:
            return False
        events.append(now)
        return True

    def _allow_supabase(self, key: str, limit: Limit) -> bool:
        if not self._validate_limit(limit):
            return False
        bucket, user_id = self._split_key(key)
        url = os.getenv("SUPABASE_URL", "").rstrip("/")
        secret = os.getenv("SUPABASE_SECRET_KEY", "").strip()
        if not url or not secret:
            raise RateLimitUnavailable(
                "Production rate limiting requires SUPABASE_URL and server-only SUPABASE_SECRET_KEY."
            )
        try:
            response = httpx.post(
                f"{url}/rest/v1/rpc/killgate_rate_limit_allow",
                headers={"apikey": secret, "Content-Type": "application/json"},
                json={
                    "p_user_id": user_id,
                    "p_bucket": bucket,
                    "p_max": limit.requests,
                    "p_window_seconds": limit.seconds,
                },
                timeout=10,
            )
            if response.status_code != 200:
                raise RateLimitUnavailable(
                    f"Distributed rate-limit RPC returned HTTP {response.status_code}."
                )
            value = response.json()
            if not isinstance(value, bool):
                raise RateLimitUnavailable("Distributed rate-limit RPC returned an invalid value.")
            return value
        except RateLimitUnavailable:
            raise
        except (httpx.HTTPError, ValueError) as exc:
            logger.warning(
                "Distributed rate limiter unavailable (%s).", type(exc).__name__
            )
            raise RateLimitUnavailable("Distributed rate limiter is unavailable.") from exc

    @staticmethod
    def _preauth_key_hash(value: str) -> str:
        """Hash login identifiers without storing raw email/IP combinations."""
        secret = os.getenv("SUPABASE_SECRET_KEY", "").strip()
        if SlidingWindowLimiter._production_mode() and not secret:
            raise RateLimitUnavailable(
                "Production pre-authentication limits require the server-only Supabase secret."
            )
        local_secret = secret or "killgate-local-preauth-only"
        return hmac.new(
            local_secret.encode("utf-8"), value.encode("utf-8"), hashlib.sha256
        ).hexdigest()

    def _allow_preauth_supabase(self, key_hash: str, bucket: str, limit: Limit) -> bool:
        if not self._validate_limit(limit):
            return False
        url = os.getenv("SUPABASE_URL", "").rstrip("/")
        secret = os.getenv("SUPABASE_SECRET_KEY", "").strip()
        if not url or not secret:
            raise RateLimitUnavailable(
                "Production pre-authentication limits require Supabase server configuration."
            )
        try:
            response = httpx.post(
                f"{url}/rest/v1/rpc/killgate_pre_auth_rate_limit_allow",
                headers={"apikey": secret, "Content-Type": "application/json"},
                json={
                    "p_key_hash": key_hash,
                    "p_bucket": bucket[:80],
                    "p_max": limit.requests,
                    "p_window_seconds": limit.seconds,
                },
                timeout=10,
            )
            if response.status_code != 200:
                raise RateLimitUnavailable(
                    f"Pre-authentication rate-limit RPC returned HTTP {response.status_code}."
                )
            value = response.json()
            if not isinstance(value, bool):
                raise RateLimitUnavailable(
                    "Pre-authentication rate-limit RPC returned an invalid value."
                )
            return value
        except RateLimitUnavailable:
            raise
        except (httpx.HTTPError, ValueError) as exc:
            logger.warning(
                "Pre-authentication rate limiter unavailable (%s).",
                type(exc).__name__,
            )
            raise RateLimitUnavailable(
                "Pre-authentication rate limiter is unavailable."
            ) from exc

    def allow_pre_auth(self, value: str, bucket: str, limit: Limit) -> bool:
        """Apply a privacy-preserving limit before a user session exists."""
        if not value or not bucket or not self._validate_limit(limit):
            return False
        key_hash = self._preauth_key_hash(value)
        if self._production_mode():
            return self._allow_preauth_supabase(key_hash, bucket, limit)
        return self._allow_local(f"preauth:{bucket}:{key_hash}", limit)

    def _reserve_research_local(
        self, user_id: str, hourly: Limit, rolling: Limit, run_id: str
    ) -> ResearchReservation | None:
        if not self._validate_limit(hourly) or not self._validate_limit(rolling):
            return None
        key = (user_id, run_id)
        if key in self._research_runs:
            return self._research_runs[key]
        now = time.monotonic()
        hourly_key = f"research-hourly:{user_id}"
        rolling_key = f"research-rolling:{user_id}"
        hourly_events = self._prune_local(hourly_key, hourly.seconds, now)
        rolling_events = self._prune_local(rolling_key, rolling.seconds, now)
        if len(hourly_events) >= hourly.requests or len(rolling_events) >= rolling.requests:
            return None
        hourly_events.append(now)
        rolling_events.append(now)
        reservation = ResearchReservation(token=f"run:{run_id}", local_timestamp=now)
        self._research_runs[key] = reservation
        return reservation

    def _reserve_research_supabase(
        self, user_id: str, hourly: Limit, rolling: Limit, run_id: str
    ) -> ResearchReservation | None:
        if not self._validate_limit(hourly) or not self._validate_limit(rolling):
            return None
        url = os.getenv("SUPABASE_URL", "").rstrip("/")
        secret = os.getenv("SUPABASE_SECRET_KEY", "").strip()
        if not url or not secret:
            raise RateLimitUnavailable(
                "Production research quota requires SUPABASE_URL and server-only SUPABASE_SECRET_KEY."
            )
        try:
            response = httpx.post(
                f"{url}/rest/v1/rpc/killgate_research_quota_reserve_once",
                headers={"apikey": secret, "Content-Type": "application/json"},
                json={
                    "p_user_id": user_id,
                    "p_research_run_id": run_id,
                    "p_hourly_max": hourly.requests,
                    "p_rolling_max": rolling.requests,
                    "p_rolling_window_seconds": rolling.seconds,
                },
                timeout=10,
            )
            if response.status_code != 200:
                raise RateLimitUnavailable(
                    f"Research quota reservation RPC returned HTTP {response.status_code}."
                )
            value = response.json()
            if value is None:
                return None
            if not isinstance(value, int) or isinstance(value, bool) or value < 1:
                raise RateLimitUnavailable("Research quota reservation RPC returned an invalid value.")
            return ResearchReservation(token=f"run:{run_id}")
        except RateLimitUnavailable:
            raise
        except (httpx.HTTPError, ValueError) as exc:
            logger.warning("Research quota unavailable (%s).", type(exc).__name__)
            raise RateLimitUnavailable("Research quota is unavailable.") from exc

    def reserve_research(
        self,
        user_id: str,
        *,
        hourly_requests: int = 8,
        rolling_30d_requests: int = 30,
        rolling_window_seconds: int = 30 * 24 * 3600,
        research_run_id: str | None = None,
    ) -> ResearchReservation | None:
        """Reserve a cross-worker research slot; paid entitlement is enforced separately."""
        hourly = Limit(hourly_requests, 3600)
        rolling = Limit(rolling_30d_requests, rolling_window_seconds)
        run_id = str(uuid.UUID(research_run_id)) if research_run_id else str(uuid.uuid4())
        if self._production_mode():
            return self._reserve_research_supabase(user_id, hourly, rolling, run_id)
        with self._lock:
            return self._reserve_research_local(user_id, hourly, rolling, run_id)

    def release_research_run(self, user_id: str, research_run_id: str) -> None:
        """Cancel by caller ID even when the reserve RPC response never arrived.

        Unlike the legacy best-effort release, this must confirm cancellation;
        otherwise the caller keeps the operation blocked for reconciliation.
        """
        run_id = str(uuid.UUID(research_run_id))
        if not self._production_mode():
            with self._lock:
                original = self._research_runs.get((user_id, run_id))
                if original and original.local_timestamp is not None:
                    for key in (f"research-hourly:{user_id}", f"research-rolling:{user_id}"):
                        try:
                            self._events[key].remove(original.local_timestamp)
                        except ValueError:
                            pass
                self._research_runs[(user_id, run_id)] = None
            return
        url = os.getenv("SUPABASE_URL", "").rstrip("/")
        secret = os.getenv("SUPABASE_SECRET_KEY", "").strip()
        if not url or not secret:
            raise RateLimitUnavailable("Research quota reconciliation is not configured.")
        try:
            response = httpx.post(
                f"{url}/rest/v1/rpc/killgate_research_quota_release_run",
                headers={"apikey": secret, "Content-Type": "application/json"},
                json={"p_user_id": user_id, "p_research_run_id": run_id}, timeout=10,
            )
            if response.status_code != 200 or response.json() is not True:
                raise RateLimitUnavailable("Research quota reconciliation was not confirmed.")
        except (httpx.HTTPError, ValueError) as exc:
            raise RateLimitUnavailable("Research quota reconciliation is unavailable.") from exc

    def release_research(self, user_id: str, reservation: ResearchReservation) -> None:
        """Best-effort release of a reservation when provider/search failure produced no result."""
        if reservation.token.startswith("run:"):
            self.release_research_run(user_id, reservation.token.split(":", 1)[1])
            return
        if reservation.token.startswith("local:"):
            timestamp = reservation.local_timestamp
            if timestamp is None:
                return
            for key in (f"research-hourly:{user_id}", f"research-rolling:{user_id}"):
                try:
                    self._events[key].remove(timestamp)
                except ValueError:
                    pass
            return
        if not reservation.token.startswith("supabase:"):
            return
        try:
            event_id = int(reservation.token.split(":", 1)[1])
        except (ValueError, IndexError):
            return
        url = os.getenv("SUPABASE_URL", "").rstrip("/")
        secret = os.getenv("SUPABASE_SECRET_KEY", "").strip()
        if not url or not secret:
            logger.warning("Could not release research quota reservation: Supabase admin config missing.")
            return
        try:
            response = httpx.post(
                f"{url}/rest/v1/rpc/killgate_research_quota_release",
                headers={"apikey": secret, "Content-Type": "application/json"},
                json={"p_user_id": user_id, "p_event_id": event_id},
                timeout=10,
            )
            if response.status_code != 200 or response.json() is not True:
                logger.warning("Research quota reservation %s was not released cleanly.", event_id)
        except (httpx.HTTPError, ValueError) as exc:
            logger.warning(
                "Could not release research quota reservation (%s).",
                type(exc).__name__,
            )

    def allow_research(
        self,
        user_id: str,
        *,
        hourly_requests: int = 8,
        rolling_30d_requests: int = 30,
        rolling_window_seconds: int = 30 * 24 * 3600,
    ) -> bool:
        """Compatibility helper: reserve a research slot and keep it consumed."""
        return self.reserve_research(
            user_id,
            hourly_requests=hourly_requests,
            rolling_30d_requests=rolling_30d_requests,
            rolling_window_seconds=rolling_window_seconds,
        ) is not None

    def allow(self, key: str, limit: Limit) -> bool:
        if not self._validate_limit(limit):
            return False
        if self._production_mode():
            return self._allow_supabase(key, limit)
        return self._allow_local(key, limit)


limiter = SlidingWindowLimiter()
