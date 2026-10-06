"""Durable capture tests: disk queue and mocked registry, no provider calls."""
import asyncio
import json
from functools import wraps

import pytest
from pydantic import ValidationError

from core_ai.types import Message, StreamEvent
from coding_agent.addons.learning.loop import LearningLoop, Observation


def run_async(function):
    @wraps(function)
    def run(*args, **kwargs):
        return asyncio.run(function(*args, **kwargs))
    return run


class DiskQueue:
    def __init__(self, path):
        self.path = path
        self.session_id = "session-1"
        self.completed = []
        self.consolidations = 0

    def pending_jobs(self):
        return json.loads(self.path.read_text()) if self.path.exists() else []

    def enqueue_capture(self, task, messages, session_id):
        jobs = self.pending_jobs()
        job_id = str(len(jobs) + len(self.completed))
        jobs.append(dict(id=job_id, task=task, messages=messages, session_id=session_id))
        self.path.write_text(json.dumps(jobs))
        return job_id

    def complete_job(self, job_id, observations):
        self.completed.append((job_id, observations))
        self.path.write_text(json.dumps([j for j in self.pending_jobs() if j["id"] != job_id]))

    def consolidate(self):
        self.consolidations += 1
        return {}

    def archive_context(self, *args):
        pass


class Registry:
    def __init__(self, *, blocked=False, fail=False, payload=None):
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        if not blocked:
            self.release.set()
        self.fail = fail
        self.calls = 0
        self.active = 0
        self.max_active = 0
        self.payload = payload if payload is not None else {"observations": [
            {"text": "Tests use pytest", "topic": "tests", "confidence": 0.9}]}

    async def stream(self, *args, **kwargs):
        self.calls += 1
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        self.started.set()
        try:
            await self.release.wait()
            if self.fail:
                raise ValueError("offline")
            yield StreamEvent(type="text_delta", delta=json.dumps(self.payload))
        finally:
            self.active -= 1


def make_loop(store, registry):
    return LearningLoop(store, registry=registry, model_id="mock")


@run_async
async def test_capture_persists_before_execution_and_shutdown_survives_restart(tmp_path):
    path = tmp_path / "jobs.json"
    store = DiskQueue(path)
    registry = Registry(blocked=True)
    loop = make_loop(store, registry)
    job_id = loop.capture("test", [Message(role="user", content="password=secret")])
    assert registry.calls == 0
    assert store.pending_jobs()[0]["id"] == job_id
    assert "secret" not in path.read_text()
    await registry.started.wait()
    await loop.shutdown()
    assert len(store.pending_jobs()) == 1
    restarted_store = DiskQueue(path)
    restarted = make_loop(restarted_store, Registry())
    restarted.resume()
    await restarted.wait()
    assert restarted_store.pending_jobs() == []
    assert restarted_store.completed[0][1][0]["scope"] == "workspace"
    assert restarted_store.consolidations == 2


@run_async
async def test_independent_captures_serialized_not_cancelled(tmp_path):
    store = DiskQueue(tmp_path / "jobs.json")
    registry = Registry(blocked=True)
    loop = make_loop(store, registry)
    loop.capture("first", [])
    await registry.started.wait()
    loop.capture("second", [])
    registry.release.set()
    await loop.wait()
    assert registry.calls == 2
    assert registry.max_active == 1
    assert len(store.completed) == 2
    assert not store.pending_jobs()


@run_async
async def test_failed_jobs_retry_only_on_next_resume(tmp_path):
    store = DiskQueue(tmp_path / "jobs.json")
    registry = Registry(fail=True)
    loop = make_loop(store, registry)
    loop.capture("task", [])
    await loop.wait()
    assert registry.calls == 1
    assert len(store.pending_jobs()) == 1
    registry.fail = False
    loop.resume()
    await loop.wait()
    assert registry.calls == 2
    assert not store.pending_jobs()


@run_async
async def test_global_observations_rejected_and_empty_list_valid(tmp_path):
    store = DiskQueue(tmp_path / "jobs.json")
    registry = Registry(payload={"observations": [{"text": "fact", "topic": "x", "scope": "global"}]})
    loop = make_loop(store, registry)
    loop.capture("task", [])
    await loop.wait()
    assert len(store.pending_jobs()) == 1
    assert not store.completed
    registry.payload = []
    loop.resume()
    await loop.wait()
    assert store.completed[0][1] == []
    assert store.consolidations >= 1


def test_observation_validation_and_sanitization():
    assert "secret" not in Observation(text="token=secret", topic="auth").text
    for fields in ({"text": " "}, {"text": "x" * 601}, {"confidence": 2}, {"topic": "x" * 121}):
        with pytest.raises(ValidationError):
            Observation.model_validate({"text": "fact", "topic": "tests", **fields})


@run_async
async def test_schedule_compatibility_has_no_debounce_and_emits_recap(tmp_path):
    from core_harness import HarnessResult
    from core_harness.models import UsageTotals

    store = DiskQueue(tmp_path / "jobs.json")
    registry = Registry(payload={"observations": [], "transcript_summary": "Done.\nVerified."})
    loop = make_loop(store, registry)
    events = []

    async def emit(kind, payload):
        events.append((kind, payload))

    loop.schedule("task", HarnessResult(output_text="Done", messages=[], usage=UsageTotals()),
                  emit=emit, delay_seconds=999)
    assert len(store.pending_jobs()) == 1
    await loop.wait()
    assert events == [("run_summary", {"label": "summary so far", "summary": "Done.\nVerified."})]


def test_capture_without_running_loop_is_durable(tmp_path):
    store = DiskQueue(tmp_path / "jobs.json")
    loop = make_loop(store, None)
    loop.capture("task", [])
    assert len(store.pending_jobs()) == 1
    assert loop._worker is None
