import asyncio
import os
import subprocess
import sys
from pathlib import Path

import pytest
from dotenv import load_dotenv

from core_ai import ModelRegistry
from core_ai.providers.openai import OpenAIProvider
from coding_agent import CodingAgent

load_dotenv(override=True)


def _build_live_agent(tmp_path: Path) -> CodingAgent:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        pytest.skip("Set OPENAI_API_KEY to run the coding-agent integration test.")

    base_url = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
    model_name = os.getenv("OPENAI_TEST_MODEL", "gpt-4o-mini")

    registry = ModelRegistry()
    registry.register("openai", OpenAIProvider(api_key=api_key, base_url=base_url))

    return CodingAgent(
        registry=registry,
        model_id=f"openai:{model_name}",
        workspace=tmp_path,
    )


def test_coding_agent_writes_and_runs_bubble_sort(tmp_path: Path) -> None:
    agent = _build_live_agent(tmp_path)

    result = asyncio.run(
        agent.run(
            "Create a file named sort_test.py in the workspace. "
            "Implement bubble sort for the array [14, 2, 19, 13, 3, 24]. "
            "Make the script runnable from the command line, run it with bash, "
            "and ensure it prints the sorted result [2, 3, 13, 14, 19, 24]. "
            "Use the write, read, and bash tools as needed."
        )
    )
    print(result)
    sort_test = tmp_path / "sort_test.py"
    assert sort_test.exists()
    source = sort_test.read_text(encoding="utf-8")
    assert "bubble_sort" in source
    assert "def" in source

    run_result = subprocess.run(
        [sys.executable, "sort_test.py"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=True,
        timeout=10,
    )
    assert run_result.stdout.strip() == "[2, 3, 13, 14, 19, 24]"
    assert result.output_text
    assert "[2, 3, 13, 14, 19, 24]" in result.output_text
