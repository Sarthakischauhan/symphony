"""Settings loading without a packaged defaults JSON."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from core_harness import CoreHarness, HarnessConfig, load_harness_config
from core_harness.config import DEFAULT_SUBAGENT_SYSTEM_PROMPT


def test_load_harness_config_requires_a_file(tmp_path: Path) -> None:
    missing = tmp_path / "missing.json"
    with pytest.raises(ValueError, match="does not exist"):
        load_harness_config(missing)


def test_load_harness_config_fills_omitted_keys_from_model_defaults(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"max_turns": 3}), encoding="utf-8")
    config = load_harness_config(path)
    assert config.max_turns == 3
    assert config.tool_result_max_chars == 32_000
    assert config.context_compact_ratio == 0.8
    assert config.compaction_keep_recent_tools == 32
    assert config.subagent_system_prompt == DEFAULT_SUBAGENT_SYSTEM_PROMPT
    assert "gpt-4o" in config.context_limits


def test_load_harness_config_ignores_removed_context_settings(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    path.write_text(
        json.dumps(
            {
                "max_turns": 3,
                "tool_output_dir": "/tmp/secrets",
                "tool_result_prune_tokens": 12,
                "tool_result_keep_recent": 8,
                "context_compact_threshold": 16_000,
                "compaction_keep_recent": 10,
            }
        ),
        encoding="utf-8",
    )
    config = load_harness_config(path)
    assert config.max_turns == 3
    assert not hasattr(config, "tool_output_dir")
    assert not hasattr(config, "tool_result_prune_tokens")
    assert not hasattr(config, "context_compact_threshold")


def test_load_harness_config_reads_nested_harness_section(tmp_path: Path) -> None:
    path = tmp_path / "product.json"
    path.write_text(json.dumps({"harness": {"max_turns": 16}}), encoding="utf-8")
    assert load_harness_config(path).max_turns == 16


def test_core_harness_reads_settings_from_path(tmp_path: Path) -> None:
    path = tmp_path / "harness.json"
    path.write_text(
        json.dumps({"max_turns": 2, "tool_result_max_chars": 40}),
        encoding="utf-8",
    )

    class EmptyRegistry:
        async def stream(self, model_id, messages, tools):
            del model_id, messages, tools
            if False:  # pragma: no cover
                yield None

    harness = CoreHarness(
        registry=EmptyRegistry(),  # type: ignore[arg-type]
        model_id="fake:test",
        system_prompt="system",
        config=path,
    )
    assert harness.max_turns == 2
    assert harness.tool_result_max_chars == 40
    assert isinstance(harness.config, HarnessConfig)
