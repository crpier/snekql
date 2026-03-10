from snektest import test

from snekql.lexer import Lexer
from snekql.tstring_compat import Interpolation, Template


@test()
def test_eof_empty_template():
    s = Lexer(Template())
    assert s.at_end() is True


@test()
def test_eof_not_at_eof_with_string():
    s = Lexer(Template("some text"))
    assert s.at_end() is False


@test()
def test_eof_not_at_eof_with_interpolations():
    s = Lexer(
        Template(
            Interpolation("some value", "some expression", None, ""),
            Interpolation("some other value", "some other expression", None, ""),
        )
    )
    assert s.at_end() is False


@test()
def test_eof_not_at_eof_with_str_and_interpolation():
    s = Lexer(
        Template(
            "s",
            Interpolation("some other value", "some other expression", None, ""),
        )
    )
    assert s.at_end() is False


@test()
def test_eof_not_at_eof_with_interpolation_and_str():
    s = Lexer(Template(Interpolation("some value", "some expression", None, ""), "s"))
    assert s.at_end() is False


@test()
def test_eof_at_eof_with_interpolation():
    s = Lexer(Template(Interpolation(1, "some value", None, "")))
    assert s.at_end() is True


@test()
def test_eof_at_eof_with_string():
    s = Lexer(Template("s"))
    s.current_index = 0
    assert s.at_end() is True


@test()
def test_eof_beyond_eof():
    s = Lexer(Template("s"))
    s.current_index = 10
    assert s.at_end() is True
