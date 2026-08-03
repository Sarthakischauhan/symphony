from pathlib import Path

from core_ai import ModelRegistry

from coding_agent import CodingAgent
from coding_agent.ast.parser import build_ast_context, summarize_codebase
from coding_agent.ast.semantic import build_semantic_index, query_semantic
from coding_agent.tools import AstQueryTool


def test_ast_context_summarizes_python_source(tmp_path: Path) -> None:
    source = tmp_path / "sample.py"
    source.write_text(
        '"""Sample module."""\n'
        "from pathlib import Path\n\n"
        "MAX_SIZE = 10\n\n"
        "class Runner:\n"
        '    """Runs work."""\n'
        "    def run(self, path: Path) -> str:\n"
        '        """Return a path."""\n'
        "        return str(path)\n\n"
        "async def main(name: str = 'world') -> None:\n"
        "    Runner().run(Path('.'))\n"
        "    return None\n",
        encoding="utf-8",
    )

    summary = summarize_codebase(tmp_path)
    assert len(summary.modules) == 1
    module = summary.modules[0]
    assert module.path == "sample.py"
    assert module.imports == ("pathlib import Path",)
    assert module.constants[0].startswith("MAX_SIZE=")
    assert module.classes[0].name == "Runner"
    assert module.classes[0].methods[0].signature == "(self, path: Path) -> str"
    assert module.functions[0].signature == "(name: str='world') -> None"
    assert module.functions[0].is_async is True
    assert "Runner.run" in module.functions[0].calls or "run" in module.functions[0].calls

    rendered = build_ast_context(tmp_path)
    assert "Codebase AST context:" in rendered
    assert "class Runner" in rendered
    assert "async def main(name: str='world') -> None" in rendered
    assert "Semantic index:" in rendered


def test_semantic_index_finds_symbols_and_calls(tmp_path: Path) -> None:
    (tmp_path / "mod.py").write_text(
        "class Base:\n"
        "    def hook(self) -> None:\n"
        "        return None\n\n"
        "class Child(Base):\n"
        "    def hook(self) -> None:\n"
        "        helper()\n\n"
        "def helper() -> None:\n"
        "    return None\n",
        encoding="utf-8",
    )
    summary = summarize_codebase(tmp_path)
    index = build_semantic_index(summary)

    found = index.find_symbol("Child")
    assert found and found[0].kind == "class"

    inheritance = query_semantic(index, action="inheritance", name="Child")
    assert "Base" in inheritance

    callees = query_semantic(index, action="callees", name="Child.hook")
    assert "helper" in callees

    callers = query_semantic(index, action="callers", name="helper")
    assert "Child.hook" in callers or any("hook" in c for c in callers.splitlines())


def test_ast_query_tool(tmp_path: Path) -> None:
    (tmp_path / "pkg.py").write_text(
        "def alpha() -> int:\n    return 1\n",
        encoding="utf-8",
    )
    tool = AstQueryTool(tmp_path)
    result = tool.run(action="find", name="alpha")
    assert "alpha" in result
    assert "function" in result


def test_coding_agent_adds_ast_context_to_system_prompt(tmp_path: Path) -> None:
    registry = ModelRegistry()
    agent = CodingAgent(
        registry=registry,
        model_id="test:model",
        workspace=tmp_path,
        ast_context_path=tmp_path,
        enable_learning=False,
    )

    assert "Codebase AST context:" in agent.harness.system_prompt
    assert f"- Root: {tmp_path.resolve()}" in agent.harness.system_prompt


def test_coding_agent_defaults_ast_context_to_workspace(tmp_path: Path) -> None:
    (tmp_path / "workspace_module.py").write_text(
        "def workspace_function() -> None:\n    return None\n",
        encoding="utf-8",
    )

    registry = ModelRegistry()
    agent = CodingAgent(
        registry=registry,
        model_id="test:model",
        workspace=tmp_path,
        enable_learning=False,
    )

    assert f"- Root: {tmp_path.resolve()}" in agent.harness.system_prompt
    assert "workspace_function" in agent.harness.system_prompt


def test_coding_agent_can_disable_ast_context(tmp_path: Path) -> None:
    registry = ModelRegistry()
    agent = CodingAgent(
        registry=registry,
        model_id="test:model",
        workspace=tmp_path,
        include_ast_context=False,
        enable_learning=False,
    )

    assert agent.harness.system_prompt == agent.system_prompt
    assert "Codebase AST context:" not in agent.harness.system_prompt


def test_coding_agent_injects_learning_playbook(tmp_path: Path) -> None:
    store_path = tmp_path / ".symphony" / "learning"
    store_path.mkdir(parents=True)
    (store_path / "playbook.md").write_text(
        "# Symphony learning playbook\n\n## What worked\n- patch succeeded\n",
        encoding="utf-8",
    )

    registry = ModelRegistry()
    agent = CodingAgent(
        registry=registry,
        model_id="test:model",
        workspace=tmp_path,
        include_ast_context=False,
        enable_learning=True,
    )
    assert "Lessons from prior tasks" in agent.harness.system_prompt
    assert "patch succeeded" in agent.harness.system_prompt
