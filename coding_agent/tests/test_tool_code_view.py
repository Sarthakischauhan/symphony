from rich.syntax import Syntax
from rich.text import Text

from coding_agent.tui.tools.code_view import code_view


def test_empty_code_view_is_a_muted_notice() -> None:
    rendered = code_view("")
    assert isinstance(rendered, Text)
    assert "No details yet." in rendered.plain


def test_plain_code_view_is_highlighted() -> None:
    rendered = code_view("alpha\nbeta")
    assert isinstance(rendered, Syntax)
    assert rendered.lexer.name == "Text only"
    assert rendered.line_numbers is True


def test_code_view_truncates_after_the_limit() -> None:
    rendered = code_view("one\ntwo\nthree", limit=2)
    plain = "\n".join(str(item) for item in rendered.renderables)
    assert "three" not in plain
    assert "1 lines hidden" in plain


def test_bash_code_view_uses_syntax_highlighting() -> None:
    rendered = code_view("echo hello", lexer="bash")
    assert isinstance(rendered, Syntax)
    assert rendered.lexer.name == "Bash"
    assert rendered.line_numbers is True
