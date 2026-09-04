"""Three live locked contracts. Drafts are cheap. Archive frees a slot."""
from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime

from app.models.state import SystemState

MAX_LIVE_LOCKS = 3
SLOT_FULL_MESSAGE = "Three live locks are already open. Archive one before locking another idea."


def is_archived(state: SystemState) -> bool:
    return bool(state.metrics.get("archived_at"))


def is_live_locked(state: SystemState) -> bool:
    if is_archived(state):
        return False
    # Pivot children stay on the parent slot.
    if str(state.metrics.get("pivot_parent_venture_id") or "").strip():
        return False
    return state.validation_contract is not None and state.validation_contract.status == "locked"


def live_locked(states: Iterable[tuple[str, SystemState]]) -> list[tuple[str, SystemState]]:
    return [(vid, state) for vid, state in states if is_live_locked(state)]


def slot_status(states: Iterable[tuple[str, SystemState]]) -> dict:
    live = live_locked(states)
    used = len(live)
    return {
        "used": used,
        "max": MAX_LIVE_LOCKS,
        "remaining": max(0, MAX_LIVE_LOCKS - used),
        "full": used >= MAX_LIVE_LOCKS,
        "live_ids": [vid for vid, _ in live],
    }


def can_open_live_lock(states: Iterable[tuple[str, SystemState]], venture_id: str = "") -> bool:
    rows = list(states)
    if venture_id:
        for vid, state in rows:
            if vid == venture_id and is_live_locked(state):
                return True
    return not slot_status(rows)["full"]


def archive_state(state: SystemState) -> SystemState:
    state.metrics["archived_at"] = datetime.now(UTC).isoformat()
    return state


def unarchive_state(state: SystemState) -> SystemState:
    state.metrics.pop("archived_at", None)
    return state
