"""Background children return identity immediately and have explicit lifetimes."""

import asyncio
import json
from core_ai.types import StreamEvent
from core_harness import CoreHarness, HarnessConfig, EventSink, SubagentAddon


class GatedRegistry:
    def __init__(self):
        self.release = asyncio.Event()
        self.started = asyncio.Event()
        self.parent_turns = 0
        self.parent_continued = asyncio.Event()
        self.requests = []

    async def stream(self, model_id, messages, tools):
        self.requests.append(list(messages))
        if model_id == "fake:child":
            self.started.set()
            await self.release.wait()
            yield StreamEvent(type="text_delta", delta="Child result")
        elif self.parent_turns == 0:
            self.parent_turns += 1
            yield StreamEvent(type="toolcall_start", content_index=0, tool_call_id="spawn-call", tool_name="spawn_agent")
            yield StreamEvent(type="toolcall_delta", content_index=0, delta=json.dumps({"prompt": "Child task", "model_id": "fake:child"}))
        else:
            if any(message.role == "user" and "Child result" in str(message.content) for message in messages):
                yield StreamEvent(type="text_delta", delta="Integrated child result")
            else:
                self.parent_continued.set()
                yield StreamEvent(type="text_delta", delta="Parent independent work finished")
        yield StreamEvent(type="done")


def test_background_child_does_not_hold_parent_and_keeps_run_identity() -> None:
    async def run():
        registry = GatedRegistry()
        plane = EventSink()
        parent = CoreHarness(registry=registry, model_id="fake:parent", system_prompt="Parent",
                             config=HarnessConfig(), sink=plane,
                             session_id="parent-session", addons=[SubagentAddon(background=True)])
        run_task = asyncio.create_task(parent.run("Start a child and continue"))
        await asyncio.wait_for(registry.parent_continued.wait(), timeout=2)
        first = await asyncio.wait_for(run_task, timeout=2)
        assert first.output_text == "Parent independent work finished"
        child_id, child = next(iter(parent.child_tasks.items()))
        assert child.status == "running"
        assert not child.task.done()
        spawn = next(e.payload for e in plane.events if e.event_type == "agent_spawned")
        parent_start = next(e.payload for e in plane.events if e.event_type == "run_started")
        assert spawn["tool_call_id"] == "spawn-call"
        assert spawn["run_id"] == parent_start["run_id"]
        assert spawn["parent_session_id"] == "parent-session"
        registry.release.set()
        await asyncio.wait_for(child.task, timeout=2)
        result = await asyncio.wait_for(parent.run("Follow up"), timeout=2)
        assert result.output_text == "Integrated child result"
        assert child.status == "completed"
        assert child.output_text == "Child result"
        assert [call.name for call in first.tool_calls] == ["spawn_agent"]
        assert list(parent.tools) == ["spawn_agent", "message_agent"]
        assert sum(message.role == "user" and "Child result" in str(message.content)
                   for message in result.messages) == 1
        assert parent.drain_child_results() == []
        identities = [(e.payload["run_id"], e.payload["seq"]) for e in plane.events]
        assert len(identities) == len(set(identities))
        await parent.shutdown_children()

    asyncio.run(run())


def test_message_running_and_continue_completed_child() -> None:
    async def run():
        registry = GatedRegistry()
        parent = CoreHarness(registry=registry, model_id="fake:parent", system_prompt="Parent",
                             config=HarnessConfig(), addons=[SubagentAddon(background=True)])
        response = json.loads(await parent.tools["spawn_agent"].execute(
            sink=parent.sink, args={"prompt": "task", "model_id": "fake:child"}))
        child = parent.child_tasks[response["child_id"]]
        await registry.started.wait()
        tool = parent.tools["message_agent"]
        assert await tool.execute(sink=parent.sink, args={"child_id": child.child_id, "message": "Focus on tests"}) == "Message queued"
        assert child.child.drain_user_inputs() == ["Focus on tests"]
        assert json.loads(await tool.execute(sink=parent.sink, args={"child_id": ""}))[0]["status"] == "running"
        registry.release.set()
        await child.task
        assert await tool.execute(sink=parent.sink, args={"child_id": child.child_id, "message": "Follow up"}) == "Child continued"
        await child.task
        assert child.status == "completed"
        assert any("Follow up" in str(m.content) for m in registry.requests[-1])
        assert any("Child result" in str(m.content) for m in registry.requests[-1])
        assert await tool.execute(sink=parent.sink, args={"child_id": "bad", "message": "hi"}) == "error: unknown child"
        await parent.shutdown_children()
    asyncio.run(run())


def test_stalled_child_wakes_waiting_parent(monkeypatch) -> None:
    async def run():
        import core_harness.addons.subagent.background as background
        monkeypatch.setattr(background, "STALL_SECONDS", 0.02)
        monkeypatch.setattr(background, "STALL_POLL_SECONDS", 0.01)
        registry = GatedRegistry()
        parent = CoreHarness(registry=registry, model_id="fake:parent", system_prompt="Parent",
                             config=HarnessConfig(), addons=[SubagentAddon(background=True)])
        response = json.loads(await parent.tools["spawn_agent"].execute(
            sink=parent.sink, args={"prompt": "task", "model_id": "fake:child"}))
        child = parent.child_tasks[response["child_id"]]
        await registry.started.wait()
        await child.child.emit("tool_execution_started", {"tool_name": "bash", "tool_call_id": "shell"})
        await asyncio.wait_for(background.wait_for_child_result(parent, None), 1)
        assert child.snapshot()["stalled"] is True
        assert child.snapshot()["current_tool"] == "bash"
        assert "no output" in str(parent.drain_child_results()[0].content)
        assert any(e.event_type == "child_progress" for e in parent.sink.events)
        await parent.shutdown_children()
    asyncio.run(run())


def test_cancelling_a_waiter_keeps_child_alive_and_explicit_cancel_stops_it() -> None:
    async def run():
        registry = GatedRegistry()
        parent = CoreHarness(registry=registry, model_id="fake:parent", system_prompt="Parent",
                             config=HarnessConfig(max_parallel_tool_calls=1), addons=[SubagentAddon(background=True)])
        async def spawn():
            return await parent.tools["spawn_agent"].execute(sink=parent.sink,
                args={"prompt": "task", "model_id": "fake:child"})
        response = json.loads(await spawn())
        child_id = response["child_id"]
        second = json.loads(await spawn())
        assert second["child_id"] != child_id
        from core_harness.addons.subagent.background import wait_for_child_result
        waiter = asyncio.create_task(wait_for_child_result(parent, timeout=None))
        await asyncio.sleep(0)
        waiter.cancel()
        await asyncio.gather(waiter, return_exceptions=True)
        child = parent.child_tasks[child_id]
        assert not child.task.done()
        child.task.cancel()
        await asyncio.gather(child.task, return_exceptions=True)
        assert child.status == "cancelled"
        assert child.task.done()
        await spawn()
        await parent.shutdown_children()
        assert all(task.task.done() for task in parent.child_tasks.values())

    asyncio.run(run())


def test_cancelling_parent_while_waiting_stops_owned_children() -> None:
    async def run():
        registry = GatedRegistry()
        parent = CoreHarness(registry=registry, model_id="fake:parent", system_prompt="Parent",
                             config=HarnessConfig(), addons=[SubagentAddon(background=True)])
        task = asyncio.create_task(parent.run("Delegate"))
        await asyncio.wait_for(registry.parent_continued.wait(), timeout=2)
        await task
        assert any(not child.task.done() for child in parent.child_tasks.values())
        await parent.shutdown_children()
        assert all(child.task.done() for child in parent.child_tasks.values())

    asyncio.run(run())
