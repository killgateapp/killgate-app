from __future__ import annotations

import pytest

from app.models.state import SystemState
from app.services import state_store


class FakeResponse:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = [] if payload is None else payload

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


def _supabase_env(monkeypatch):
    monkeypatch.setenv("STATE_BACKEND", "supabase")
    monkeypatch.setenv("SUPABASE_URL", "https://project.supabase.test")
    monkeypatch.setenv("SUPABASE_PUBLISHABLE_KEY", "publishable-test")


def test_local_state_saves_atomically_and_increments_revision(tmp_path, monkeypatch):
    monkeypatch.setenv("STATE_BACKEND", "local")
    monkeypatch.setattr(state_store, "DATA_DIR", tmp_path / "ventures")
    state = SystemState(hypothesis="A detailed enough idea for a concurrency test")

    state_store.save_state("V-LOCAL", state)
    assert state.storage_revision == 1
    state_store.save_state("V-LOCAL", state)
    assert state.storage_revision == 2

    loaded = state_store.load_state("V-LOCAL")
    assert loaded is not None
    assert loaded.storage_revision == 2
    assert not (tmp_path / "ventures" / "V-LOCAL.json.tmp").exists()


def test_supabase_load_uses_database_revision(monkeypatch):
    _supabase_env(monkeypatch)
    stored = SystemState(hypothesis="A detailed enough idea for Supabase").model_dump(mode="json")
    stored["storage_revision"] = 1
    monkeypatch.setattr(
        state_store.httpx,
        "get",
        lambda *args, **kwargs: FakeResponse(200, [{"state": stored, "revision": 7}]),
    )

    loaded = state_store.load_state("V-REMOTE", owner_id="user-1", access_token="token")

    assert loaded is not None
    assert loaded.storage_revision == 7


def test_supabase_stale_save_is_rejected_without_mutating_local_revision(monkeypatch):
    _supabase_env(monkeypatch)
    state = SystemState(
        hypothesis="A detailed enough stale venture",
        storage_revision=4,
    )
    monkeypatch.setattr(
        state_store.httpx,
        "patch",
        lambda *args, **kwargs: FakeResponse(200, []),
    )

    with pytest.raises(state_store.StateConflictError, match="another tab or device"):
        state_store.save_state("V-STALE", state, owner_id="user-1", access_token="token")

    assert state.storage_revision == 4


def test_supabase_successful_save_requires_and_advances_expected_revision(monkeypatch):
    _supabase_env(monkeypatch)
    state = SystemState(
        hypothesis="A detailed enough current venture",
        storage_revision=9,
    )
    seen = {}

    def patch(*args, **kwargs):
        seen.update(kwargs)
        return FakeResponse(200, [{"id": "V-CURRENT"}])

    monkeypatch.setattr(state_store.httpx, "patch", patch)

    state_store.save_state("V-CURRENT", state, owner_id="user-1", access_token="token")

    assert seen["params"]["revision"] == "eq.9"
    assert seen["json"]["revision"] == 10
    assert seen["json"]["state"]["storage_revision"] == 10
    assert state.storage_revision == 10


def test_supabase_new_state_is_inserted_at_revision_one(monkeypatch):
    _supabase_env(monkeypatch)
    state = SystemState(hypothesis="A detailed enough brand new venture")
    seen = {}

    def post(*args, **kwargs):
        seen.update(kwargs)
        return FakeResponse(201, [{"id": "V-NEW"}])

    monkeypatch.setattr(state_store.httpx, "post", post)

    state_store.save_state("V-NEW", state, owner_id="user-1", access_token="token")

    assert seen["json"]["revision"] == 1
    assert seen["json"]["state"]["storage_revision"] == 1
    assert state.storage_revision == 1


def test_new_venture_ids_use_64_bits_of_random_hex():
    first = state_store.new_venture_id()
    second = state_store.new_venture_id()
    assert first != second
    assert len(first) == len("V-") + 16
    assert first.startswith("V-")
    int(f"0x{first[2:]}", 0)


def test_supabase_operational_failure_is_not_misreported_as_missing_state(monkeypatch):
    _supabase_env(monkeypatch)
    monkeypatch.setattr(
        state_store.httpx,
        "get",
        lambda *args, **kwargs: FakeResponse(503, {"message": "unavailable"}),
    )
    with pytest.raises(state_store.StateStoreUnavailable, match="HTTP 503"):
        state_store.load_state("V-REMOTE", owner_id="user-1", access_token="token")


def test_supabase_malformed_payload_fails_closed(monkeypatch):
    _supabase_env(monkeypatch)
    monkeypatch.setattr(
        state_store.httpx,
        "get",
        lambda *args, **kwargs: FakeResponse(200, {"unexpected": "object"}),
    )
    with pytest.raises(state_store.StateStoreUnavailable, match="invalid payload"):
        state_store.load_state("V-REMOTE", owner_id="user-1", access_token="token")
