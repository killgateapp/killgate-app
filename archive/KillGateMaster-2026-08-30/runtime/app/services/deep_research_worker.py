"""Provider-free dispatch contracts for durable Deep Research workers.

This module does not enqueue external work.  It makes the production boundary
explicit so Cloud Tasks configuration can be verified separately from research
logic, while tests and local development can use an inline callback.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum


class WorkerMode(str, Enum):
    INLINE = "inline"
    CLOUD_TASKS = "cloud_tasks"


class WorkerDispatchUnavailable(RuntimeError):
    """Raised when the configured worker dispatch contract is incomplete."""


@dataclass(frozen=True)
class ResearchWorkerJob:
    """Minimal, non-secret worker payload; durable state remains in Supabase."""

    run_id: str
    user_id: str

    def payload(self) -> dict[str, str]:
        if not self.run_id.strip() or not self.user_id.strip():
            raise ValueError("run_id and user_id are required")
        return {"run_id": self.run_id, "user_id": self.user_id}


@dataclass(frozen=True)
class CloudTasksDispatchIntent:
    """Validated configuration required before an external task is submitted."""

    queue: str
    worker_url: str
    audience: str
    job: ResearchWorkerJob


def configured_worker_mode() -> WorkerMode:
    raw = os.getenv("DEEP_RESEARCH_WORKER_MODE", WorkerMode.INLINE.value).strip().lower()
    try:
        return WorkerMode(raw)
    except ValueError as exc:
        raise WorkerDispatchUnavailable("Deep Research worker mode is invalid.") from exc


def cloud_tasks_dispatch_intent(job: ResearchWorkerJob) -> CloudTasksDispatchIntent:
    """Validate, but never submit, the Cloud Tasks dispatch inputs."""
    if configured_worker_mode() is not WorkerMode.CLOUD_TASKS:
        raise WorkerDispatchUnavailable("Cloud Tasks dispatch is not enabled.")
    queue = os.getenv("DEEP_RESEARCH_TASK_QUEUE", "").strip()
    worker_url = os.getenv("DEEP_RESEARCH_WORKER_URL", "").strip()
    audience = os.getenv("DEEP_RESEARCH_TASK_AUDIENCE", "").strip()
    if not queue or not worker_url.startswith("https://") or not audience:
        raise WorkerDispatchUnavailable("Cloud Tasks worker configuration is incomplete.")
    job.payload()
    return CloudTasksDispatchIntent(queue=queue, worker_url=worker_url, audience=audience, job=job)


def dispatch_inline(job: ResearchWorkerJob, handler: Callable[[ResearchWorkerJob], None]) -> None:
    """Execute a test/development worker handler after validating the payload."""
    job.payload()
    handler(job)
