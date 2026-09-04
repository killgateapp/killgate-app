from __future__ import annotations

import pytest

from app.services.deep_research_worker import (
    ResearchWorkerJob,
    WorkerDispatchUnavailable,
    WorkerMode,
    cloud_tasks_dispatch_intent,
    configured_worker_mode,
    dispatch_inline,
)


def test_inline_worker_dispatch_validates_only_minimal_job_payload(monkeypatch):
    monkeypatch.setenv("DEEP_RESEARCH_WORKER_MODE", "inline")
    job = ResearchWorkerJob(run_id="run-1", user_id="user-1")
    seen = []
    dispatch_inline(job, seen.append)
    assert configured_worker_mode() is WorkerMode.INLINE
    assert seen == [job]


def test_cloud_tasks_intent_requires_non_secret_explicit_configuration(monkeypatch):
    monkeypatch.setenv("DEEP_RESEARCH_WORKER_MODE", "cloud_tasks")
    job = ResearchWorkerJob(run_id="run-1", user_id="user-1")
    with pytest.raises(WorkerDispatchUnavailable):
        cloud_tasks_dispatch_intent(job)
    monkeypatch.setenv("DEEP_RESEARCH_TASK_QUEUE", "projects/p/locations/l/queues/q")
    monkeypatch.setenv("DEEP_RESEARCH_WORKER_URL", "https://worker.example.com/internal/deep-research")
    monkeypatch.setenv("DEEP_RESEARCH_TASK_AUDIENCE", "https://worker.example.com")
    intent = cloud_tasks_dispatch_intent(job)
    assert intent.queue.endswith("/q")
    assert intent.job.payload() == {"run_id": "run-1", "user_id": "user-1"}
