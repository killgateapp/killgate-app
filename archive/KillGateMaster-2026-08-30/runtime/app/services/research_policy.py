"""Centralized research entitlement and beta-policy configuration."""
from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

DEFAULT_BETA_MAX_RUNS = 9
DEFAULT_BETA_DURATION_DAYS = 14
DEFAULT_RESEARCH_SAFETY_CAP_30D = 30


def _parse_datetime(value: str) -> datetime | None:
    raw = (value or "").strip()
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).astimezone(UTC)
    except ValueError:
        return None


def _int_env(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)).strip())
    except ValueError:
        return 0


def _user_ids(name: str) -> frozenset[str]:
    return frozenset(
        value.strip().lower()
        for value in os.getenv(name, "").split(",")
        if value.strip()
    )


def research_safety_cap_30d() -> int:
    """Return the non-entitlement API safety ceiling.

    The old environment name remains a compatibility fallback for an existing
    deployment, but the new name and lower default make its purpose explicit.
    """
    raw = os.getenv("RESEARCH_SAFETY_CAP_30D")
    if raw is None:
        raw = os.getenv("RESEARCH_ABUSE_CAP_30D", str(DEFAULT_RESEARCH_SAFETY_CAP_30D))
    try:
        return int(raw.strip())
    except ValueError:
        return 0


def test_admin_user_ids() -> frozenset[str]:
    return _user_ids("KILLGATE_TEST_ADMIN_USER_IDS")


def test_admin_switch_enabled() -> bool:
    return os.getenv("KILLGATE_TEST_ADMIN_ENABLED", "0").strip() == "1"


def test_admin_enabled() -> bool:
    """Return true only when the explicit switch and allowlist are both present."""
    return test_admin_switch_enabled() and bool(test_admin_user_ids())


def is_test_admin(user_id: str) -> bool:
    """Match only an explicitly configured user ID."""
    return test_admin_enabled() and user_id.strip().lower() in test_admin_user_ids()


@dataclass(frozen=True)
class BetaPolicy:
    enabled: bool
    user_ids: frozenset[str]
    start_at: datetime | None
    duration_days: int
    max_runs: int

    @property
    def end_at(self) -> datetime | None:
        if self.start_at is None or self.duration_days < 1:
            return None
        return self.start_at + timedelta(days=self.duration_days)

    @property
    def valid(self) -> bool:
        return bool(
            self.enabled
            and self.user_ids
            and self.start_at is not None
            and self.duration_days == DEFAULT_BETA_DURATION_DAYS
            and 1 <= self.max_runs <= 500
        )


def beta_policy() -> BetaPolicy:
    return BetaPolicy(
        enabled=os.getenv("KILLGATE_BETA_ENABLED", "0").strip() == "1",
        user_ids=_user_ids("KILLGATE_BETA_USER_IDS"),
        start_at=_parse_datetime(os.getenv("KILLGATE_BETA_START_AT", "")),
        duration_days=_int_env("KILLGATE_BETA_DURATION_DAYS", DEFAULT_BETA_DURATION_DAYS),
        max_runs=_int_env("KILLGATE_BETA_MAX_RUNS", DEFAULT_BETA_MAX_RUNS),
    )


def is_beta_user(user_id: str, *, now: datetime | None = None) -> bool:
    policy = beta_policy()
    if not policy.valid or user_id.strip().lower() not in policy.user_ids:
        return False
    stamp = now or datetime.now(UTC)
    return policy.start_at <= stamp < policy.end_at
