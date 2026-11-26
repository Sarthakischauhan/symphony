import asyncio
import json
import sys

import pytest

from core_ai.models import get_model, unregister_model
from core_ai.models import discovery


def test_refresh_uses_child_and_registers_result(monkeypatch):
    record = {"id": "future-background-test", "provider": "openai", "api": "responses", "reasoning": True,
              "thinking_level_map": [["low", "low"]], "context_limit": 123456,
              "price": {"input": 1, "output": 2, "cache_read": None, "cache_write": None}}
    class Process:
        returncode = 0
        async def communicate(self):
            await asyncio.sleep(0)
            return json.dumps([record]).encode(), b""
    async def spawn(*args, **kwargs):
        assert args[:3] == (sys.executable, "-m", "core_ai.models.discovery")
        return Process()
    monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)
    try:
        assert asyncio.run(discovery.refresh_models(("openai",))) == 1
        model = get_model("openai", record["id"])
        assert model.context_limit == 123456 and model.price.output == 2
    finally:
        unregister_model("openai", record["id"])


def test_cancelled_refresh_kills_child(monkeypatch):
    class Process:
        returncode = None
        killed = False
        async def communicate(self):
            await asyncio.sleep(60)
        def kill(self):
            self.killed = True
            self.returncode = -9
        async def wait(self):
            return self.returncode
    process = Process()
    async def spawn(*args, **kwargs):
        return process
    monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)
    async def run():
        task = asyncio.create_task(discovery.refresh_models(("openai",)))
        await asyncio.sleep(0)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    asyncio.run(run())
    assert process.killed
