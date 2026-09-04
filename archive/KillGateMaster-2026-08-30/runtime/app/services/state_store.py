"""Persistence for Killgate venture state.

Local mode keeps the zero-config developer workflow and writes files atomically.
Supabase mode stores the same SystemState JSON in Postgres, relies on Row Level
Security for per-account isolation, and uses an optimistic revision column so a
stale browser tab cannot silently overwrite newer evidence.
"""
from __future__ import annotations

import json
import os
import secrets
import threading
from pathlib import Path

import httpx

from app.models.state import SystemState

DATA_DIR = Path(__file__).resolve().parents[2] / "data" / "ventures"
_LOCAL_SLOT_LOCK = threading.RLock()


class StateConflictError(RuntimeError):
    """Raised when a stale venture state tries to overwrite a newer revision."""


class StateStoreUnavailable(RuntimeError):
    """Persistence backend failed or returned data Killgate cannot safely trust."""


def new_venture_id() -> str:
    """Generate a compact 64-bit venture reference while preserving the V- prefix."""
    return f"V-{secrets.token_hex(8).upper()}"


def _backend() -> str:
    return os.getenv("STATE_BACKEND", "local").strip().lower()


def _path(venture_id: str) -> Path:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    return DATA_DIR / f"{venture_id}.json"


def _supabase_config() -> tuple[str, str]:
    url = os.getenv("SUPABASE_URL", "").rstrip("/")
    key = os.getenv("SUPABASE_PUBLISHABLE_KEY", "")
    if not url or not key:
        raise StateStoreUnavailable("Supabase persistence is not configured.")
    return url, key


def _headers(access_token: str, *, prefer: str = "") -> dict[str, str]:
    _, key = _supabase_config()
    if not access_token:
        raise StateStoreUnavailable("Supabase persistence requires an authenticated session.")
    headers = {
        "apikey": key,
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
    }
    if prefer:
        headers["Prefer"] = prefer
    return headers


def _admin_headers() -> dict[str, str]:
    url, _ = _supabase_config()
    del url
    secret = os.getenv("SUPABASE_SECRET_KEY", "").strip()
    if not secret:
        raise StateStoreUnavailable("Supabase server-side persistence is not configured.")
    return {
        "apikey": secret,
        "Authorization": f"Bearer {secret}",
        "Content-Type": "application/json",
    }


def _request_json(response: httpx.Response, *, context: str):
    try:
        return response.json()
    except ValueError as exc:
        raise StateStoreUnavailable(f"{context} returned invalid JSON.") from exc


def _ensure_success(response: httpx.Response, *, context: str) -> None:
    if not 200 <= response.status_code < 300:
        raise StateStoreUnavailable(f"{context} returned HTTP {response.status_code}.")


def _atomic_local_write(path: Path, state: SystemState) -> None:
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(state.model_dump_json(indent=2), encoding="utf-8")
    os.replace(temp, path)


def save_state(
    venture_id: str,
    state: SystemState,
    *,
    owner_id: str = "local-user",
    access_token: str = "",
) -> None:
    """Persist a state without allowing stale writes to overwrite newer revisions."""
    if _backend() != "supabase":
        with _LOCAL_SLOT_LOCK:
            current = load_state(venture_id, owner_id=owner_id, access_token=access_token)
            if (current.storage_revision if current else 0) != state.storage_revision:
                raise StateConflictError("This venture changed. Refresh before saving again.")
            persisted = state.model_copy(deep=True)
            persisted.storage_revision += 1
            _atomic_local_write(_path(venture_id), persisted)
            state.storage_revision = persisted.storage_revision
        return

    url, _ = _supabase_config()
    expected_revision = max(0, int(state.storage_revision))
    next_revision = expected_revision + 1
    persisted = state.model_copy(deep=True)
    persisted.storage_revision = next_revision
    payload = {
        "state": persisted.model_dump(mode="json"),
        "updated_at": state.last_updated.isoformat(),
        "revision": next_revision,
    }

    if expected_revision == 0:
        try:
            response = httpx.post(
                f"{url}/rest/v1/ventures",
                headers=_headers(access_token, prefer="return=representation"),
                json={"id": venture_id, "user_id": owner_id, **payload},
                timeout=20,
            )
        except httpx.HTTPError as exc:
            raise StateStoreUnavailable("Venture storage could not be reached.") from exc
        if response.status_code in (409, 412):
            raise StateConflictError("This venture was created concurrently. Refresh and try again.")
        _ensure_success(response, context="Venture storage")
        rows = _request_json(response, context="Venture storage")
        if not isinstance(rows, list) or len(rows) != 1:
            raise StateStoreUnavailable("Venture storage did not confirm the newly saved revision.")
        state.storage_revision = next_revision
        return

    try:
        response = httpx.patch(
            f"{url}/rest/v1/ventures",
            headers=_headers(access_token, prefer="return=representation"),
            params={
                "id": f"eq.{venture_id}",
                "user_id": f"eq.{owner_id}",
                "revision": f"eq.{expected_revision}",
            },
            json=payload,
            timeout=20,
        )
    except httpx.HTTPError as exc:
        raise StateStoreUnavailable("Venture storage could not be reached.") from exc
    _ensure_success(response, context="Venture storage")
    rows = _request_json(response, context="Venture storage")
    if not isinstance(rows, list) or len(rows) != 1:
        raise StateConflictError(
            "This venture changed in another tab or device. Refresh before saving again."
        )
    state.storage_revision = next_revision


def load_state(
    venture_id: str,
    *,
    owner_id: str = "local-user",
    access_token: str = "",
) -> SystemState | None:
    if _backend() != "supabase":
        path = _path(venture_id)
        if not path.exists():
            return None
        return _upgrade_state(SystemState.model_validate(json.loads(path.read_text(encoding="utf-8"))))

    url, _ = _supabase_config()
    try:
        response = httpx.get(
            f"{url}/rest/v1/ventures",
            headers=_headers(access_token),
            params={
                "select": "state,revision",
                "id": f"eq.{venture_id}",
                "user_id": f"eq.{owner_id}",
                "limit": "1",
            },
            timeout=20,
        )
    except httpx.HTTPError as exc:
        raise StateStoreUnavailable("Venture storage could not be reached.") from exc
    _ensure_success(response, context="Venture storage")
    rows = _request_json(response, context="Venture storage")
    if not isinstance(rows, list):
        raise StateStoreUnavailable("Venture storage returned an invalid payload.")
    if not rows:
        return None
    if not isinstance(rows[0], dict) or "state" not in rows[0]:
        raise StateStoreUnavailable("Venture storage returned an invalid venture record.")
    try:
        state = SystemState.model_validate(rows[0]["state"])
        state.storage_revision = int(rows[0].get("revision") or state.storage_revision or 1)
    except (ValueError, TypeError, KeyError) as exc:
        raise StateStoreUnavailable("Stored venture state could not be validated safely.") from exc
    return _upgrade_state(state)


def _upgrade_state(state: SystemState) -> SystemState:
    from app.services.audit_trail import backfill_evidence_linkage

    backfill_evidence_linkage(state)
    return state


def list_ventures(*, owner_id: str = "local-user", access_token: str = "") -> list[str]:
    if _backend() != "supabase":
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        return sorted(p.stem for p in DATA_DIR.glob("*.json"))
    url, _ = _supabase_config()
    try:
        response = httpx.get(
            f"{url}/rest/v1/ventures",
            headers=_headers(access_token),
            params={"select": "id", "user_id": f"eq.{owner_id}", "order": "updated_at.desc"},
            timeout=20,
        )
    except httpx.HTTPError as exc:
        raise StateStoreUnavailable("Venture storage could not be reached.") from exc
    _ensure_success(response, context="Venture storage")
    rows = _request_json(response, context="Venture storage")
    if not isinstance(rows, list) or any(not isinstance(item, dict) or "id" not in item for item in rows):
        raise StateStoreUnavailable("Venture storage returned an invalid venture list.")
    return [str(item["id"]) for item in rows]


def list_states(
    *,
    owner_id: str = "local-user",
    access_token: str = "",
    archived: bool | None = None,
    limit: int | None = None,
    offset: int = 0,
) -> list[tuple[str, SystemState]]:
    """Bulk-load validated states, with bounded archive pages and no N+1 reads.

    Unbounded callers page through PostgREST rather than silently accepting its
    default row cap. The home page requests active states and one archive page.
    """
    from app.services.slots import is_archived

    if offset < 0 or (limit is not None and limit < 1):
        raise ValueError("Invalid state page.")
    if _backend() != "supabase":
        rows: list[tuple[str, SystemState]] = []
        for venture_id in list_ventures(owner_id=owner_id, access_token=access_token):
            state = load_state(venture_id, owner_id=owner_id, access_token=access_token)
            if state is not None and (archived is None or is_archived(state) == archived):
                rows.append((venture_id, state))
        rows.sort(key=lambda row: (row[1].last_updated, row[0]), reverse=True)
        return rows[offset:offset + limit] if limit is not None else rows[offset:]

    url, _ = _supabase_config()
    payload = []
    while limit is None or len(payload) < limit:
        page_size = min(500, limit - len(payload)) if limit else 500
        params = {
            "select": "id,state,revision",
            "user_id": f"eq.{owner_id}",
            "order": "updated_at.desc,id.desc",
            "limit": str(page_size),
            "offset": str(offset + len(payload)),
        }
        if archived is False:
            params["or"] = "(state->metrics->>archived_at.is.null,state->metrics->>archived_at.eq.)"
        elif archived is True:
            params["and"] = "(state->metrics->>archived_at.not.is.null,state->metrics->>archived_at.neq.)"
        try:
            response = httpx.get(
                f"{url}/rest/v1/ventures", headers=_headers(access_token, prefer="count=exact"), params=params, timeout=20,
            )
        except httpx.HTTPError as exc:
            raise StateStoreUnavailable("Venture storage could not be reached.") from exc
        _ensure_success(response, context="Venture storage")
        page = _request_json(response, context="Venture storage")
        if not isinstance(page, list):
            raise StateStoreUnavailable("Venture storage returned an invalid state list.")
        payload.extend(page)
        total = getattr(response, "headers", {}).get("Content-Range", "").rsplit("/", 1)[-1]
        if not page or (total.isdigit() and offset + len(payload) >= int(total)):
            break
        if not total.isdigit() and len(page) < page_size:
            break

    rows: list[tuple[str, SystemState]] = []
    try:
        for item in payload:
            if not isinstance(item, dict) or "id" not in item or "state" not in item:
                raise ValueError("invalid venture row")
            state = SystemState.model_validate(item["state"])
            state.storage_revision = int(item.get("revision") or state.storage_revision or 1)
            rows.append((str(item["id"]), _upgrade_state(state)))
    except (TypeError, ValueError, KeyError) as exc:
        raise StateStoreUnavailable("Stored venture state list could not be validated safely.") from exc
    return rows


def _slot_rpc(name: str, payload: dict[str, object]) -> dict[str, object]:
    url, _ = _supabase_config()
    try:
        response = httpx.post(
            f"{url}/rest/v1/rpc/{name}",
            headers=_admin_headers(),
            json=payload,
            timeout=20,
        )
    except httpx.HTTPError as exc:
        raise StateStoreUnavailable("Atomic live-slot storage could not be reached.") from exc
    _ensure_success(response, context="Atomic live-slot storage")
    value = _request_json(response, context="Atomic live-slot storage")
    if not isinstance(value, dict):
        raise StateStoreUnavailable("Atomic live-slot storage returned an invalid result.")
    return value


def create_state_with_slot(
    venture_id: str,
    state: SystemState,
    *,
    owner_id: str = "local-user",
    access_token: str = "",
) -> bool:
    """Atomically admit and create one new root live lock for an owner."""
    if _backend() != "supabase":
        from app.services.slots import can_open_live_lock

        with _LOCAL_SLOT_LOCK:
            if not can_open_live_lock(list_states(owner_id=owner_id, access_token=access_token)):
                return False
            save_state(venture_id, state, owner_id=owner_id, access_token=access_token)
            return True

    if state.storage_revision != 0:
        raise StateConflictError("A new venture must not already have a persisted revision.")
    persisted = state.model_copy(deep=True)
    persisted.storage_revision = 1
    value = _slot_rpc(
        "killgate_create_venture_with_slot",
        {
            "p_user_id": owner_id,
            "p_venture_id": venture_id,
            "p_state": persisted.model_dump(mode="json"),
            "p_updated_at": state.last_updated.isoformat(),
        },
    )
    if value.get("ok") is True:
        state.storage_revision = 1
        return True
    if value.get("error") == "slot_full":
        return False
    if value.get("error") == "venture_exists":
        raise StateConflictError("This venture was created concurrently. Refresh and try again.")
    raise StateStoreUnavailable("Atomic venture creation was rejected by storage.")


def save_unarchived_state_with_slot(
    venture_id: str,
    state: SystemState,
    *,
    owner_id: str = "local-user",
    access_token: str = "",
) -> bool:
    """Atomically reserve a root live slot and persist an unarchived state."""
    if _backend() != "supabase":
        from app.services.slots import can_open_live_lock, is_live_locked

        with _LOCAL_SLOT_LOCK:
            others = [
                (row_id, row_state)
                for row_id, row_state in list_states(owner_id=owner_id, access_token=access_token)
                if row_id != venture_id
            ]
            if is_live_locked(state) and not can_open_live_lock(others):
                return False
            save_state(venture_id, state, owner_id=owner_id, access_token=access_token)
            return True

    expected_revision = max(0, int(state.storage_revision))
    if expected_revision < 1:
        raise StateConflictError("An archived venture must have a persisted revision.")
    persisted = state.model_copy(deep=True)
    persisted.storage_revision = expected_revision + 1
    value = _slot_rpc(
        "killgate_unarchive_venture_with_slot",
        {
            "p_user_id": owner_id,
            "p_venture_id": venture_id,
            "p_expected_revision": expected_revision,
            "p_state": persisted.model_dump(mode="json"),
            "p_updated_at": state.last_updated.isoformat(),
        },
    )
    if value.get("ok") is True:
        state.storage_revision = expected_revision + 1
        return True
    if value.get("error") == "slot_full":
        return False
    if value.get("error") in {"not_found", "revision_conflict"}:
        raise StateConflictError("This venture changed in another tab or device. Refresh and try again.")
    raise StateStoreUnavailable("Atomic venture unarchive was rejected by storage.")


def delete_all_user_data(*, owner_id: str = "local-user", access_token: str = "") -> None:
    if _backend() != "supabase":
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        for path in DATA_DIR.glob("*.json"):
            path.unlink(missing_ok=True)
        return
    url, _ = _supabase_config()
    try:
        response = httpx.delete(
            f"{url}/rest/v1/ventures",
            headers=_headers(access_token, prefer="return=minimal"),
            params={"user_id": f"eq.{owner_id}"},
            timeout=20,
        )
    except httpx.HTTPError as exc:
        raise StateStoreUnavailable("Venture storage could not be reached.") from exc
    _ensure_success(response, context="Venture storage")


def export_user_data(*, owner_id: str = "local-user", access_token: str = "") -> dict[str, object]:
    ventures = []
    for venture_id in list_ventures(owner_id=owner_id, access_token=access_token):
        state = load_state(venture_id, owner_id=owner_id, access_token=access_token)
        if state is not None:
            customer_state = state.model_dump(mode="json")
            contract = customer_state.get("validation_contract")
            if isinstance(contract, dict):
                for key in (
                    "contract_version",
                    "source",
                    "hypothesis_fingerprint",
                    "research_rules",
                    "decision_rules",
                    "notes",
                ):
                    contract.pop(key, None)
            metrics = customer_state.get("metrics")
            if isinstance(metrics, dict):
                proprietary_metric_keys = {
                    "evaluator_notes",
                    "last_mechanism_scoreboard",
                    "last_decision_rules",
                    "last_kill_criteria",
                    "rejected_by_evaluator",
                    "search_hit_count",
                    "direct_source_count",
                    "indirect_source_count",
                    "irrelevant_source_count",
                    "independent_domain_count",
                }
                for key in list(metrics):
                    if key in proprietary_metric_keys or key.startswith("llm_"):
                        metrics.pop(key, None)
            ventures.append({"venture_id": venture_id, "state": customer_state})
    return {"export_version": "1.1", "account_id": owner_id, "ventures": ventures}
