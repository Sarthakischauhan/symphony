"""Background bash: job registry, output/stop actions, and the harness completion wake."""

from __future__ import annotations

import asyncio
import time
from pathlib import Path
from types import SimpleNamespace

from core_ai.content import text_from_content
from core_harness import EventSink

from coding_agent import CodingAgent
from coding_agent.config import BashConfig, CodingAgentConfig, LangfuseConfig, LearningConfig, ToolsConfig
from coding_agent.tools import BashJobs, BashTool
from scripted_registry import ScriptedRegistry


def _fake_harness() -> SimpleNamespace:
    return SimpleNamespace(agent_id="parent", session_id="s1", child_tasks={}, _child_results=[])


def test_background_job_outlives_foreground_cap_and_wakes_the_loop_once(tmp_path: Path) -> None:
    command = "sleep 2; echo job-finished"
    registry = ScriptedRegistry({"build it": [[("bash", {"command": command, "background": True})]]})
    sink = EventSink()
    config = CodingAgentConfig(
        learning=LearningConfig(enabled=False),
        langfuse=LangfuseConfig(enabled=False),
        tools=ToolsConfig(bash=BashConfig(default_timeout_seconds=1, max_timeout_seconds=1)),
        unattended=True,
    )
    agent = CodingAgent(registry=registry, model_id="fake:test-model", workspace=tmp_path,  # type: ignore[arg-type]
                        sink=sink, config=config)
    started = time.monotonic()
    result = asyncio.run(agent.run("build it"))
    assert time.monotonic() - started >= 2
    assert result.output_text == "all done"

    types = [event.event_type for event in sink.events]
    assert "waiting_for_children" in types
    bash_calls = [e for e in sink.events if e.event_type == "tool_execution_started" and e.payload["tool_name"] == "bash"]
    assert len(bash_calls) == 1  # no output/poll calls
    assert len(registry.calls) == 3
    woken = registry.calls[2]
    wakes = [text_from_content(m.content) for m in woken if text_from_content(m.content).startswith("Background job")]
    assert len(wakes) == 1
    assert "exit=0" in wakes[0] and "job-finished" in wakes[0] and "Full log:" in wakes[0]
    assert not any(text_from_content(m.content).startswith("Background job") for m in registry.calls[1])


def test_output_and_stop_actions(tmp_path: Path) -> None:
    jobs = BashJobs(tmp_path / "jobs", max_seconds=60)
    harness = _fake_harness()
    jobs.bind(harness)
    tool = BashTool(tmp_path, jobs=jobs)

    async def _run() -> None:
        started = await tool.execute(sink=None, args={"command": "echo hello-job; sleep 30", "background": True})
        assert "servers" not in tool.parameters["properties"]["background"]["description"]
        job_id = started.split()[3]
        assert (tmp_path / "jobs" / f"{job_id}.log").as_posix() in started
        await asyncio.sleep(0.3)
        output = await tool.execute(sink=None, args={"action": "output", "job_id": job_id})
        assert output.startswith(f"job {job_id} running") and "hello-job" in output
        assert list(jobs.running()) == [job_id] and jobs.running()[job_id] > 1
        stopped = await tool.execute(sink=None, args={"action": "stop", "job_id": job_id})
        assert stopped == f"stopped background job {job_id}"
        await harness.child_tasks[job_id].task
        assert jobs.running() == {}
        assert len(harness._child_results) == 1
        assert f"Background job {job_id} exit=-" in harness._child_results[0].content
        missing = await tool.execute(sink=None, args={"action": "output", "job_id": "nope"})
        assert missing.startswith("error: unknown background job")
        assert (await tool.execute(sink=None, args={"action": "stop"})).startswith("error: job_id is required")

    asyncio.run(_run())


def test_cancelling_the_watcher_kills_the_process_group(tmp_path: Path) -> None:
    jobs = BashJobs(tmp_path / "jobs", max_seconds=60)
    harness = _fake_harness()
    jobs.bind(harness)

    async def _run() -> None:
        await jobs.start("sleep 30", tmp_path)
        (record,) = harness.child_tasks.values()
        assert record.status == "background"
        record.task.cancel()
        await asyncio.gather(record.task, return_exceptions=True)
        assert jobs.running() == {}
        assert record.status == "cancelled"
        assert harness._child_results == []

    asyncio.run(_run())


def test_background_timeout_uses_max_background_seconds(tmp_path: Path) -> None:
    jobs = BashJobs(tmp_path / "jobs", max_seconds=1)
    harness = _fake_harness()
    jobs.bind(harness)

    async def _run() -> None:
        await jobs.start("echo before; sleep 30", tmp_path)
        (record,) = harness.child_tasks.values()
        await record.task
        assert "timed out (max_background_seconds=1)" in harness._child_results[0].content
        assert "before" in harness._child_results[0].content

    asyncio.run(_run())


def test_background_without_registry_is_an_error(tmp_path: Path) -> None:
    tool = BashTool(tmp_path)
    result = asyncio.run(tool.execute(sink=None, args={"command": "echo hi", "background": True}))
    assert result.startswith("error: background jobs are not available")
