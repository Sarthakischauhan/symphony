from pathlib import Path

from core_ai import ModelRegistry

from coding_agent import CodingAgent
from coding_agent.ast.parser import build_ast_context, summarize_codebase


def test_ast_context_summarizes_python_source(tmp_path: Path) -> None:
    source = tmp_path / "sample.py"
    source.write_text(
        '"""Sample module."""\n'
        "from pathlib import Path\n\n"
        "class Runner:\n"
        '    """Runs work."""\n'
        "    def run(self, path: Path) -> str:\n"
        '        """Return a path."""\n'
        "        return str(path)\n\n"
        "async def main(name: str = 'world') -> None:\n"
        "    return None\n",
        encoding="utf-8",
    )

    summary = summarize_codebase(tmp_path)
    assert len(summary.modules) == 1
    module = summary.modules[0]
    assert module.path == "sample.py"
    assert module.imports == ("pathlib import Path",)
    assert module.classes[0].name == "Runner"
    assert module.classes[0].methods[0].signature == "(self, path: Path) -> str"
    assert module.functions[0].signature == "(name: str='world') -> None"
    assert module.functions[0].is_async is True

    rendered = build_ast_context(tmp_path)
    assert "Codebase AST context:" in rendered
    assert "class Runner" in rendered
    assert "async def main(name: str='world') -> None" in rendered


def test_coding_agent_adds_ast_context_to_system_prompt(tmp_path: Path) -> None:
    registry = ModelRegistry()
    agent = CodingAgent(
        registry=registry,
        model_id="test:model",
        workspace=tmp_path,
        ast_context_path=tmp_path,
    )

    assert "Codebase AST context:" in agent.harness.system_prompt
    assert f"- Root: {tmp_path.resolve()}" in agent.harness.system_prompt


def test_coding_agent_can_disable_ast_context(tmp_path: Path) -> None:
    registry = ModelRegistry()
    agent = CodingAgent(
        registry=registry,
        model_id="test:model",
        workspace=tmp_path,
        include_ast_context=False,
    )

    assert agent.harness.system_prompt == agent.system_prompt
    assert "Codebase AST context:" not in agent.harness.system_prompt
