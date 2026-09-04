import importlib.util
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "check_supabase_schema.py"
spec = importlib.util.spec_from_file_location("check_supabase_schema", SCRIPT)
checker = importlib.util.module_from_spec(spec)
assert spec.loader
spec.loader.exec_module(checker)


class Response:
    def __init__(self, status_code, payload=None):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        return self._payload


def test_supabase_schema_probe_requires_server_config(monkeypatch):
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.delenv("SUPABASE_SECRET_KEY", raising=False)
    with pytest.raises(RuntimeError):
        checker.check_schema()


def test_supabase_schema_probe_checks_exact_runtime_objects_and_anon_denial(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://project.supabase.co")
    monkeypatch.setenv("SUPABASE_SECRET_KEY", "server-secret-placeholder")
    monkeypatch.setenv("SUPABASE_PUBLISHABLE_KEY", "publishable-placeholder")
    calls = []

    def fake_get(url, *, headers, params, timeout):
        calls.append(("get", url, headers["apikey"], params))
        if headers["apikey"] == "publishable-placeholder":
            return Response(403)
        return Response(200, [])

    def fake_post(url, *, headers, json, timeout):
        calls.append(("post", url, headers["apikey"], json))
        if headers["apikey"] == "publishable-placeholder":
            return Response(403, {"message": "permission denied"})
        if url.endswith("/killgate_rate_limit_allow"):
            return Response(200, False)
        if url.endswith("/killgate_pre_auth_rate_limit_allow"):
            return Response(200, False)
        if url.endswith("/killgate_research_quota_reserve"):
            return Response(200, None)
        if url.endswith("/killgate_research_quota_reserve_once"):
            return Response(200, None)
        if url.endswith("/killgate_research_quota_release_run"):
            return Response(200, False)
        if url.endswith("/killgate_deep_research_run_create"):
            return Response(200, None)
        if url.endswith("/killgate_deep_research_run_checkpoint"):
            return Response(200, None)
        if url.endswith("/killgate_wallet_bind_pass"):
            return Response(200, False)
        if url.endswith("/killgate_wallet_debit"):
            return Response(200, {"ok": False, "error": "invalid_family"})
        if url.rsplit("/", 1)[-1] in {
            "killgate_wallet_snapshot", "killgate_wallet_grant", "killgate_wallet_refund",
            "killgate_wallet_debit_once", "killgate_wallet_cancel_research",
            "killgate_reconcile_research_run",
            "killgate_deep_research_run_create", "killgate_deep_research_run_checkpoint",
            "killgate_deep_research_run_claim", "killgate_deep_research_run_release",
            "killgate_create_venture_with_slot", "killgate_unarchive_venture_with_slot",
        }:
            return Response(400, {"code": "22023", "message": "user id is required"})
        if url.endswith("/killgate_persist_play_entitlement"):
            return Response(400, {"code": "22023", "message": "user id is required"})
        raise AssertionError(url)

    monkeypatch.setattr(checker.httpx, "get", fake_get)
    monkeypatch.setattr(checker.httpx, "post", fake_post)

    assert checker.check_schema() == []
    assert any("request_rate_events" in call[1] for call in calls)
    assert any("pre_auth_rate_events" in call[1] for call in calls)
    assert any("play_rtdn_events" in call[1] for call in calls)
    assert any("play_purchase_token_owners" in call[1] for call in calls)
    assert any("ventures" in call[1] and call[3].get("select") == "revision" for call in calls if call[0] == "get")
    assert any("killgate_rate_limit_allow" in call[1] for call in calls)
    assert any("killgate_pre_auth_rate_limit_allow" in call[1] for call in calls)
    assert any("killgate_research_quota_reserve" in call[1] for call in calls)
    assert any("killgate_research_quota_reserve_once" in call[1] for call in calls)
    assert any("killgate_research_quota_release" in call[1] for call in calls)
    assert any("killgate_persist_play_entitlement" in call[1] for call in calls)
    assert any("killgate_wallets" in call[1] for call in calls)
    assert any("killgate_venture_passes" in call[1] for call in calls)
    assert any("killgate_credit_ledger" in call[1] for call in calls)
    assert any("deep_research_runs" in call[1] for call in calls)
    assert any("killgate_wallet_snapshot" in call[1] for call in calls)
    assert any("killgate_wallet_grant" in call[1] for call in calls)
    assert any("killgate_wallet_bind_pass" in call[1] for call in calls)
    assert any("killgate_wallet_debit" in call[1] for call in calls)
    assert any("killgate_wallet_refund" in call[1] for call in calls)


def test_supabase_schema_probe_fails_if_anon_can_query_or_execute_server_boundary(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://project.supabase.co")
    monkeypatch.setenv("SUPABASE_SECRET_KEY", "server-secret-placeholder")
    monkeypatch.setenv("SUPABASE_PUBLISHABLE_KEY", "publishable-placeholder")

    def fake_get(url, *, headers, params, timeout):
        return Response(200, [])

    def fake_post(url, *, headers, json, timeout):
        if headers["apikey"] == "server-secret-placeholder":
            if url.endswith("/killgate_rate_limit_allow"):
                return Response(200, False)
            if url.endswith("/killgate_pre_auth_rate_limit_allow"):
                return Response(200, False)
            if url.endswith("/killgate_research_quota_reserve"):
                return Response(200, None)
            if url.endswith("/killgate_research_quota_reserve_once"):
                return Response(200, None)
            if url.endswith("/killgate_research_quota_release_run"):
                return Response(200, False)
            if url.endswith("/killgate_deep_research_run_create"):
                return Response(400, {"code": "22023"})
            if url.endswith("/killgate_deep_research_run_checkpoint"):
                return Response(400, {"code": "22023"})
            if url.endswith("/killgate_wallet_bind_pass"):
                return Response(200, False)
            if url.endswith("/killgate_wallet_debit"):
                return Response(200, {"ok": False, "error": "invalid_family"})
            if url.rsplit("/", 1)[-1] in {
                "killgate_wallet_snapshot", "killgate_wallet_grant", "killgate_wallet_refund",
                "killgate_wallet_debit_once", "killgate_wallet_cancel_research",
                "killgate_reconcile_research_run",
                "killgate_deep_research_run_create", "killgate_deep_research_run_checkpoint",
                "killgate_deep_research_run_claim", "killgate_deep_research_run_release",
                "killgate_create_venture_with_slot", "killgate_unarchive_venture_with_slot",
            }:
                return Response(400, {"code": "22023"})
            if url.endswith("/killgate_persist_play_entitlement"):
                return Response(400, {"code": "22023"})
        # Anonymous execution is intentionally simulated as exposed.
        return Response(200, False)

    monkeypatch.setattr(checker.httpx, "get", fake_get)
    monkeypatch.setattr(checker.httpx, "post", fake_post)

    failures = checker.check_schema()
    assert sum("anonymous" in failure and "table" in failure for failure in failures) == 9
    assert sum("anonymous" in failure and "RPC" in failure for failure in failures) == 18
