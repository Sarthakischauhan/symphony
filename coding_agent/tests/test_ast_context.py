from pathlib import Path

from core_ai import ModelRegistry

from coding_agent import CodingAgent
from coding_agent.ast.parser import build_ast_context, summarize_codebase
from coding_agent.ast.semantic import build_semantic_index, query_semantic
from coding_agent.context import RepositoryContextProvider
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
    assert any("Path" in item for item in module.imports)
    assert module.constants[0].name == "MAX_SIZE"
    assert module.constants[0].lineno == 4
    assert module.classes[0].name == "Runner"
    assert module.classes[0].methods[0].signature == "(self, path: Path) -> str"
    assert module.functions[0].signature == "(name: str='world') -> None"
    assert module.functions[0].is_async is True

    rendered = build_ast_context(tmp_path)
    assert "Repository map:" in rendered
    assert "Runner" in rendered


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


def test_ast_query_tool_uses_shared_provider(tmp_path: Path) -> None:
    (tmp_path / "pkg.py").write_text(
        "def alpha() -> int:\n    return 1\n",
        encoding="utf-8",
    )
    provider = RepositoryContextProvider(tmp_path)
    tool = AstQueryTool(tmp_path)
    tool.bind_context_provider(provider)
    result = tool.run(action="find", name="alpha")
    assert "alpha" in result
    assert "function" in result
    parses = provider.parse_count
    tool.run(action="find", name="alpha")
    assert provider.parse_count == parses


def test_coding_agent_dynamic_context_includes_repo_map(tmp_path: Path) -> None:
    (tmp_path / "x.py").write_text("def x():\n    return 1\n", encoding="utf-8")
    registry = ModelRegistry()
    agent = CodingAgent(
        registry=registry,
        model_id="test:model",
        workspace=tmp_path,
        ast_context_path=tmp_path,
        enable_learning=False,
    )
    dynamic = agent._dynamic_context()
    assert "Repository map:" in dynamic
    assert "Codebase AST context:" not in agent.harness.system_prompt


def test_coding_agent_can_disable_ast_context(tmp_path: Path) -> None:
    registry = ModelRegistry()
    agent = CodingAgent(
        registry=registry,
        model_id="test:model",
        workspace=tmp_path,
        include_ast_context=False,
        enable_learning=False,
    )
    assert agent._dynamic_context() == ""
    assert "Repository map:" not in agent.harness.system_prompt


def test_coding_agent_injects_verified_lessons_via_dynamic_context(tmp_path: Path) -> None:
    registry = ModelRegistry()
    agent = CodingAgent(
        registry=registry,
        model_id="test:model",
        workspace=tmp_path,
        include_ast_context=False,
        enable_learning=True,
    )
    agent.promote_lesson(
        summary="patch succeeded for indented blocks",
        outcome="worked",
        verification="user_approved",
        evidence="review",
    )
    assert "patch succeeded for indented blocks" in agent._dynamic_context()
