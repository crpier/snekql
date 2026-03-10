from snektest import test

from snekql.lexer import Lexer, Token, TokenType
from snekql.model import Base
from snekql.tstring_compat import Interpolation, Template


@test()
def test_scan_empty_string():
    s = Lexer(Template())
    assert s.scan_tokens() == ([], [])


@test()
def test_scan_select_start_query():
    s = Lexer(Template("select * from users"))
    tokens, errors = s.scan_tokens()

    assert errors == []
    assert tokens == [
        Token(TokenType.SELECT, "select", "select", 1, 1),
        Token(TokenType.STAR, "*", "*", 1, 8),
        Token(TokenType.FROM, "from", "from", 1, 10),
        Token(TokenType.IDENTIFIER, "users", "users", 1, 15),
    ]


@test()
def test_scan_select_query():
    s = Lexer(Template("select name, age from users"))
    tokens, errors = s.scan_tokens()

    assert errors == []
    assert tokens == [
        Token(TokenType.SELECT, "select", "select", 1, 1),
        Token(TokenType.IDENTIFIER, "name", "name", 1, 8),
        Token(TokenType.COMMA, ",", ",", 1, 12),
        Token(TokenType.IDENTIFIER, "age", "age", 1, 14),
        Token(TokenType.FROM, "from", "from", 1, 18),
        Token(TokenType.IDENTIFIER, "users", "users", 1, 23),
    ]


@test()
def test_scan_select_star_with_interpolation():
    class User(Base): ...

    s = Lexer(Template("select * from ", Interpolation(User, "User", None, "")))
    tokens, errors = s.scan_tokens()

    assert errors == []
    assert tokens == [
        Token(TokenType.SELECT, "select", "select", 1, 1),
        Token(TokenType.STAR, "*", "*", 1, 8),
        Token(TokenType.FROM, "from", "from", 1, 10),
        Token(TokenType.MODEL, User, "User", 1, 15),
    ]


@test()
def test_scan_select_with_interpolation_single_attribute():
    class User(Base):
        name: str

    s = Lexer(
        Template(
            "select ", Interpolation(User.name, "User.name", None, ""), " from users"
        )
    )
    tokens, errors = s.scan_tokens()

    assert errors == []
    assert tokens == [
        Token(TokenType.SELECT, "select", "select", 1, 1),
        Token(TokenType.ATTR, User.name, "User.name", 1, 8),
        Token(TokenType.FROM, "from", "from", 1, 10),
        Token(TokenType.IDENTIFIER, "users", "users", 1, 15),
    ]


@test()
def test_scan_select_with_interpolation_multiple_attributes():
    class User(Base):
        name: str
        age: int

    s = Lexer(
        Template(
            "select ",
            Interpolation((User.name, User.age), "User.name, User.age", None, ""),
            " from users",
        )
    )
    tokens, errors = s.scan_tokens()

    assert errors == []
    assert tokens == [
        Token(TokenType.SELECT, "select", "select", 1, 1),
        Token(TokenType.ATTR, (User.name, User.age), "User.name, User.age", 1, 8),
        Token(TokenType.FROM, "from", "from", 1, 10),
        Token(TokenType.IDENTIFIER, "users", "users", 1, 15),
    ]


@test()
def test_scan_delete_query():
    s = Lexer(Template("delete from users"))
    tokens, errors = s.scan_tokens()

    assert errors == []
    assert tokens == [
        Token(TokenType.DELETE, "delete", "delete", 1, 1),
        Token(TokenType.FROM, "from", "from", 1, 8),
        Token(TokenType.IDENTIFIER, "users", "users", 1, 13),
    ]
