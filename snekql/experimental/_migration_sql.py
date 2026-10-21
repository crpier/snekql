"""Lossless token spans for bounded migration edits, not a general SQL parser."""

from dataclasses import dataclass

from snekql.errors import SchemaError


@dataclass(frozen=True)
class Token:
    """A significant token with its original source span."""

    value: str
    start: int
    end: int
    kind: str


def _quoted(sql: str, start: int, *, mysql: bool) -> Token:
    char = sql[start]
    close = "]" if char == "[" else char
    index = start + 1
    value = ""
    while index < len(sql):
        if mysql and sql[index] == "\\" and char == "'":
            value += sql[index : index + 2]
            index += 2
        elif sql[index] == close:
            if char != "[" and sql[index : index + 2] == close * 2:
                value += close
                index += 2
            else:
                index += 1
                break
        else:
            value += sql[index]
            index += 1
    else:
        msg = "unterminated SQL quote"
        raise SchemaError(msg)
    return Token(value, start, index, "string" if char == "'" else "identifier")


def tokens(sql: str, *, mysql: bool = False) -> tuple[Token, ...]:
    """Keep strings separate from identifiers and skip comments without rewriting SQL."""
    result: list[Token] = []
    index = 0
    while index < len(sql):
        start = index
        char = sql[index]
        if char.isspace():
            index += 1
        elif sql.startswith("--", index):
            end = sql.find("\n", index)
            index = len(sql) if end < 0 else end + 1
        elif sql.startswith("/*", index):
            end = sql.find("*/", index + 2)
            if end < 0:
                msg = "unterminated SQL comment"
                raise SchemaError(msg)
            if mysql and (
                sql.startswith("/*!", index) or sql.startswith("/*M!", index)
            ):
                msg = "executable comments require an explicit migration adapter"
                raise SchemaError(msg)
            index = end + 2
        elif char in "'\"`[":
            token = _quoted(sql, start, mysql=mysql)
            result.append(token)
            index = token.end
        elif char.isalnum() or char in "_$":
            index += 1
            while index < len(sql) and (sql[index].isalnum() or sql[index] in "_$"):
                index += 1
            result.append(Token(sql[start:index], start, index, "word"))
        else:
            index += 1
            result.append(Token(char, start, index, "punct"))
    return tuple(result)


def references(sql: str, names: set[str], *, mysql: bool = False) -> bool:
    """Conservatively recognize identifier mentions, never string-literal contents."""
    folded = {name.casefold() for name in names}
    return any(
        t.kind in {"word", "identifier"} and t.value.casefold() in folded
        for t in tokens(sql, mysql=mysql)
    )


def required_definition(sql: str, *, mysql: bool = False) -> str:
    """Add NOT NULL without removing defaults, collations or other column clauses."""
    stream = tokens(sql, mysql=mysql)
    depth = 0
    constraints = {
        "constraint",
        "primary",
        "not",
        "null",
        "unique",
        "check",
        "default",
        "references",
        "generated",
        "as",
    }
    for index, token in enumerate(stream[1:], start=1):
        if token.kind == "punct" and token.value == "(":
            depth += 1
        elif token.kind == "punct" and token.value == ")":
            depth -= 1
        elif (
            depth == 0
            and token.kind == "word"
            and token.value.casefold() in constraints
        ):
            if token.value.casefold() == "null":
                return sql[: token.start] + "NOT NULL" + sql[token.end :]
            if (
                token.value.casefold() == "not"
                and stream[index + 1].value.casefold() == "null"
            ):
                return sql
            return sql[: token.start] + "NOT NULL " + sql[token.start :]
    return sql + " NOT NULL"


def split_table(sql: str) -> tuple[str, tuple[str, ...], str]:
    """Split ordinary SQLite CREATE TABLE definitions, preserving original text."""
    stream = tokens(sql)
    if any(t.value.casefold() == "virtual" for t in stream[:3]):
        msg = "virtual-table rebuild requires an explicit adapter"
        raise SchemaError(msg)
    depth = 0
    start = -1
    opening = -1
    parts: list[str] = []
    for token in stream:
        if token.value == "(" and token.kind == "punct":
            if depth == 0:
                opening = token.start
                start = token.end
            depth += 1
        elif token.value == ")" and token.kind == "punct":
            depth -= 1
            if depth == 0:
                parts.append(sql[start : token.start].strip())
                return sql[:opening], tuple(parts), sql[token.end :]
        elif token.value == "," and token.kind == "punct" and depth == 1:
            parts.append(sql[start : token.start].strip())
            start = token.end
    msg = "unsupported CREATE TABLE definition"
    raise SchemaError(msg)


def column_name(definition: str) -> str | None:
    """Return the column identifier, or None for a table constraint."""
    first = tokens(definition)[0]
    if first.kind == "word" and first.value.casefold() in {
        "constraint",
        "primary",
        "unique",
        "check",
        "foreign",
    }:
        return None
    return first.value
