#!/usr/bin/env python3
"""Verify Killgate's exact server-only Supabase release contract without printing secrets."""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import httpx


def _config() -> tuple[str, str, str]:
    url = os.getenv("SUPABASE_URL", "").strip().rstrip("/")
    secret = os.getenv("SUPABASE_SECRET_KEY", "").strip()
    publishable = os.getenv("SUPABASE_PUBLISHABLE_KEY", "").strip()
    if not url.startswith("https://") or not secret:
        raise RuntimeError("SUPABASE_URL and server-only SUPABASE_SECRET_KEY are required.")
    return url, secret, publishable


def _headers(key: str) -> dict[str, str]:
    return {"apikey": key, "Content-Type": "application/json"}


def _json(response: httpx.Response):
    return response.json()


def check_schema() -> list[str]:
    url, secret, publishable = _config()
    failures: list[str] = []

    # Tables/columns the current runtime actually reads or writes.
    for table, column in (
        ("play_rtdn_events", "message_id"),
        ("request_rate_events", "id,research_run_id,released_at"),
        ("pre_auth_rate_events", "id"),
        ("play_purchase_token_owners", "purchase_token_hash"),
        ("ventures", "revision"),
        ("killgate_wallets", "user_id"),
        ("killgate_venture_passes", "pass_id"),
        ("killgate_credit_ledger", "id,research_run_id"),
        ("deep_research_runs", "run_id,user_id,venture_id,revision,status,worker_lease_token,worker_lease_expires_at,worker_attempt_count"),
        ("deep_research_snapshots", "research_run_id,user_id,venture_id,completed_at,competitors,pricing_observations"),
    ):
        response = httpx.get(
            f"{url}/rest/v1/{table}",
            headers={"apikey": secret},
            params={"select": column, "limit": "1"},
            timeout=15,
        )
        if response.status_code != 200:
            failures.append(f"server cannot access required table public.{table}")

    # All safe probes are non-mutating because p_user_id=None fails before insert/update.
    rpc_probes = (
        (
            "killgate_rate_limit_allow",
            {"p_user_id": None, "p_bucket": "schema-probe", "p_max": 1, "p_window_seconds": 60},
            False,
        ),
        (
            "killgate_pre_auth_rate_limit_allow",
            {"p_key_hash": None, "p_bucket": "schema-probe", "p_max": 1, "p_window_seconds": 60},
            False,
        ),
        (
            "killgate_research_quota_reserve_once",
            {
                "p_user_id": None,
                "p_research_run_id": None,
                "p_hourly_max": 8,
                "p_rolling_max": 9,
                "p_rolling_window_seconds": 14 * 24 * 3600,
            },
            None,
        ),
        (
            "killgate_research_quota_release_run",
            {"p_user_id": None, "p_research_run_id": None},
            False,
        ),
        (
            "killgate_deep_research_run_create",
            {
                "p_user_id": None,
                "p_run_id": None,
                "p_venture_id": "schema-probe",
                "p_venture_family_id": "schema-probe",
                "p_validation_contract_fingerprint": "0" * 64,
                "p_hypothesis_fingerprint": "0" * 64,
            },
            None,
        ),
        (
            "killgate_deep_research_run_checkpoint",
            {
                "p_user_id": None,
                "p_run_id": None,
                "p_expected_revision": 0,
                "p_status": "queued",
            },
            None,
        ),
        (
            "killgate_wallet_bind_pass",
            {"p_user_id": None, "p_pass_id": "schema-probe", "p_family_id": "schema-probe"},
            False,
        ),
    )
    for name, payload, expected in rpc_probes:
        response = httpx.post(
            f"{url}/rest/v1/rpc/{name}",
            headers=_headers(secret),
            json=payload,
            timeout=15,
        )
        try:
            value = _json(response)
        except ValueError:
            value = object()
        if response.status_code != 200 or value is not expected:
            failures.append(f"server-only {name} RPC is missing or has unexpected behavior")

    # The ordered entitlement RPC deliberately raises SQLSTATE 22023 on null user.
    # That verifies the exact 8-argument function is present without mutating a row.
    entitlement_name = "killgate_persist_play_entitlement"
    entitlement_probe = {
        "p_user_id": None,
        "p_product_id": "schema-probe",
        "p_purchase_token_hash": "0" * 64,
        "p_active": False,
        "p_subscription_state": "SCHEMA_PROBE",
        "p_expires_at": None,
        "p_verified_at": None,
        "p_linked_purchase_token_hash": None,
    }
    response = httpx.post(
        f"{url}/rest/v1/rpc/{entitlement_name}",
        headers=_headers(secret),
        json=entitlement_probe,
        timeout=15,
    )
    try:
        error_payload = _json(response)
    except ValueError:
        error_payload = {}
    if not (
        response.status_code == 400
        and isinstance(error_payload, dict)
        and str(error_payload.get("code") or "") == "22023"
    ):
        failures.append(
            "server-only killgate_persist_play_entitlement RPC is missing or not the ordered runtime signature"
        )

    wallet_error_probes = (
        (
            "killgate_wallet_snapshot",
            {"p_user_id": None},
        ),
        (
            "killgate_wallet_grant",
            {
                "p_user_id": None,
                "p_product_id": "schema-probe",
                "p_product_kind": "venture_pass",
                "p_purchase_hash": None,
                "p_wallet_credits": 0,
                "p_venture_passes": 0,
                "p_credits_per_pass": 0,
                "p_period_days": 365,
                "p_subscription_period_id": "",
                "p_subscription_expires_at": None,
                "p_family_id": "",
                "p_requires_active_subscription": False,
            },
        ),
        (
            "killgate_wallet_refund",
            {"p_user_id": None, "p_debit_id": None},
        ),
        (
            "killgate_wallet_debit_once",
            {"p_user_id": None, "p_family_id": "schema-probe", "p_research_run_id": None},
        ),
        (
            "killgate_wallet_cancel_research",
            {"p_user_id": None, "p_research_run_id": None},
        ),
        (
            "killgate_reconcile_research_run",
            {"p_user_id": None, "p_venture_id": "schema-probe", "p_research_run_id": None},
        ),
        (
            "killgate_deep_research_run_claim",
            {"p_user_id": None, "p_run_id": None, "p_lease_token": None, "p_lease_seconds": 300},
        ),
        (
            "killgate_deep_research_run_release",
            {"p_user_id": None, "p_run_id": None, "p_lease_token": None},
        ),
        (
            "killgate_create_venture_with_slot",
            {"p_user_id": None, "p_venture_id": "schema-probe", "p_state": {}, "p_updated_at": None},
        ),
        (
            "killgate_unarchive_venture_with_slot",
            {"p_user_id": None, "p_venture_id": "schema-probe", "p_expected_revision": 1, "p_state": {}, "p_updated_at": None},
        ),
    )
    for name, payload in wallet_error_probes:
        response = httpx.post(
            f"{url}/rest/v1/rpc/{name}",
            headers=_headers(secret),
            json=payload,
            timeout=15,
        )
        try:
            error_payload = _json(response)
        except ValueError:
            error_payload = {}
        if not (
            response.status_code == 400
            and isinstance(error_payload, dict)
            and str(error_payload.get("code") or "") == "22023"
        ):
            failures.append(f"server-only {name} RPC is missing or has unexpected behavior")

    if publishable:
        # Server-only ledgers must not be anonymously queryable.
        for table, column in (
            ("play_rtdn_events", "message_id"),
            ("request_rate_events", "id"),
            ("pre_auth_rate_events", "id"),
            ("play_purchase_token_owners", "purchase_token_hash"),
            ("killgate_wallets", "user_id"),
            ("killgate_venture_passes", "pass_id"),
            ("killgate_credit_ledger", "id"),
            ("deep_research_runs", "run_id"),
            ("deep_research_snapshots", "research_run_id"),
        ):
            response = httpx.get(
                f"{url}/rest/v1/{table}",
                headers={"apikey": publishable},
                params={"select": column, "limit": "1"},
                timeout=15,
            )
            if response.status_code == 200:
                failures.append(f"anonymous publishable-key access can query server-only table public.{table}")

        # Likewise customers must not be able to execute any server-only mutation RPC.
        for name, payload, _ in rpc_probes:
            response = httpx.post(
                f"{url}/rest/v1/rpc/{name}",
                headers=_headers(publishable),
                json=payload,
                timeout=15,
            )
            if response.status_code not in {401, 403, 404}:
                failures.append(f"anonymous publishable-key access can execute server-only RPC {name}")
        response = httpx.post(
            f"{url}/rest/v1/rpc/{entitlement_name}",
            headers=_headers(publishable),
            json=entitlement_probe,
            timeout=15,
        )
        if response.status_code not in {401, 403, 404}:
            failures.append(
                f"anonymous publishable-key access can execute server-only RPC {entitlement_name}"
            )
        for name, payload in wallet_error_probes:
            response = httpx.post(
                f"{url}/rest/v1/rpc/{name}",
                headers=_headers(publishable),
                json=payload,
                timeout=15,
            )
            if response.status_code not in {401, 403, 404}:
                failures.append(f"anonymous publishable-key access can execute server-only RPC {name}")
    return failures


def main() -> int:
    try:
        failures = check_schema()
    except (RuntimeError, httpx.HTTPError, ValueError) as exc:
        print(f"Supabase release schema: NOT VERIFIED ({type(exc).__name__})")
        return 1

    if failures:
        print("Supabase release schema: NOT READY")
        for failure in failures:
            print(f"  BLOCK: {failure}")
        return 1

    print("Supabase release schema: READY")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
