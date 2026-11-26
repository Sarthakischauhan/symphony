"""Exercise discovery through the real model command without provider credentials."""
import asyncio
import os
from pathlib import Path

from coding_agent import CodingAgent
from coding_agent.tui.app import CodingAgentApp
from core_ai.models import unregister_model
from core_ai.models.discovery import parse_models
from scripted_registry import ScriptedRegistry


def test_discovery_to_tui_model_selection(tmp_path, monkeypatch):
    from core_ai.models import register_model
    from core_ai.models import discovery

    model_id = "gpt-99-astra-test"
    async def refresh(providers):
        assert "openai" in providers
        models = parse_models({"openai": {"models": {model_id: {
            "tool_call": True, "reasoning": True, "modalities": {"output": ["text"]},
            "limit": {"context": 123456},
        }}}}, set(providers))
        for model in models:
            register_model(model)
        return len(models)

    monkeypatch.setattr(discovery, "refresh_models", refresh)
    registry = ScriptedRegistry({})
    registry.namespaces = lambda: ("openai",)
    agent = CodingAgent(registry=registry, model_id="openai:gpt-6.2-astra", workspace=tmp_path)
    app = CodingAgentApp(workspace=tmp_path)

    async def run():
        async with app.run_test(size=(120, 30)) as pilot:
            app._agent = agent
            await app._refresh_model_catalog()
            capture = os.getenv("SYMPHONY_E2E_CAPTURE")
            if capture:
                Path(capture).mkdir(parents=True, exist_ok=True)
                app.save_screenshot("before.svg", path=capture)
                await app._run_slash_command("/model")
                await pilot.pause()
                app.save_screenshot("picker.svg", path=capture)
            await app._run_slash_command(f"/model openai:{model_id}")
            await pilot.pause()
            if capture:
                app.save_screenshot("selected.svg", path=capture)
            assert agent.harness.model_id == f"openai:{model_id}"
            assert agent.harness.state.context_limit(agent.harness.model_id) == 123456
            app._agent = None

    try:
        asyncio.run(run())
    finally:
        unregister_model("openai", model_id)
