"""Lossless token spans for bounded migration edits, not a general SQL parser."""

from dataclasses import dataclass
from string import ascii_lowercase, ascii_uppercase

from snekql.errors import SchemaError

_ASCII_LOWER = str.maketrans(ascii_uppercase, ascii_lowercase)


def ascii_lower(value: str) -> str:
    """Fold SQL keywords and SQLite identifiers without conflating Unicode names."""
    return value.translate(_ASCII_LOWER)


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


def tokens(
    sql: str, *, mysql: bool = False, allow_executable_comments: bool = False
) -> tuple[Token, ...]:
    """Keep strings separate from identifiers and skip comments without rewriting SQL."""
    result: list[Token] = []
    index = 0
    while index < len(sql):
        start = index
        char = sql[index]
        if char.isspace() and (mysql or char.isascii()):
            index += 1
        elif sql.startswith("--", index) and (
            not mysql or index + 2 == len(sql) or ord(sql[index + 2]) <= ord(" ")
        ):
            end = sql.find("\n", index)
            index = len(sql) if end < 0 else end + 1
        elif sql.startswith("/*", index):
            end = sql.find("*/", index + 2)
            if end < 0:
                msg = "unterminated SQL comment"
                raise SchemaError(msg)
            if (
                mysql
                and not allow_executable_comments
                and (sql.startswith("/*!", index) or sql.startswith("/*M!", index))
            ):
                msg = "executable comments require an explicit migration adapter"
                raise SchemaError(msg)
            index = end + 2
        elif char in "'\"`[":
            token = _quoted(sql, start, mysql=mysql)
            result.append(token)
            index = token.end
        elif char.isalnum() or char in "_$" or (not mysql and not char.isascii()):
            index += 1
            # SQLite accepts every non-ASCII character inside bare identifiers,
            # including combining marks and Unicode whitespace. Splitting one
            # can manufacture an AS keyword and incorrectly omit copied data.
            while index < len(sql) and (
                sql[index].isalnum()
                or sql[index] in "_$"
                or (not mysql and not sql[index].isascii())
            ):
                index += 1
            result.append(Token(sql[start:index], start, index, "word"))
        else:
            index += 1
            result.append(Token(char, start, index, "punct"))
    return tuple(result)


def references(sql: str, names: set[str], *, mysql: bool = False) -> bool:
    """Conservatively recognize identifier mentions, never string-literal contents."""
    fold = str.casefold if mysql else ascii_lower
    folded = {fold(name) for name in names}
    return any(
        t.kind in {"word", "identifier"} and fold(t.value) in folded
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
            and ascii_lower(token.value) in constraints
        ):
            if ascii_lower(token.value) == "null":
                return sql[: token.start] + "NOT NULL" + sql[token.end :]
            if (
                ascii_lower(token.value) == "not"
                and ascii_lower(stream[index + 1].value) == "null"
            ):
                return sql
            return sql[: token.start] + "NOT NULL " + sql[token.start :]
    return sql + " NOT NULL"


def split_table(sql: str, *, mysql: bool = False) -> tuple[str, tuple[str, ...], str]:
    """Split ordinary CREATE TABLE definitions, preserving original text."""
    stream = tokens(sql, mysql=mysql)
    if [(t.kind, ascii_lower(t.value)) for t in stream[:3]] == [
        ("word", "create"),
        ("word", "virtual"),
        ("word", "table"),
    ]:
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


def column_name(definition: str, *, mysql: bool = False) -> str | None:
    """Return the column identifier, or None for a table constraint."""
    first = tokens(definition, mysql=mysql)[0]
    if first.kind == "word" and ascii_lower(first.value) in {
        "constraint",
        "primary",
        "unique",
        "check",
        "foreign",
    }:
        return None
    if (
        mysql
        and first.kind == "word"
        and ascii_lower(first.value) in {"key", "index", "fulltext", "spatial"}
    ):
        return None
    return first.value


def without_auto_increment_counter(sql: str, *, backslash_escapes: bool) -> str:
    """Omit only an unquoted table-option counter, never text in COMMENT/defaults."""
    stream = tokens(sql, mysql=backslash_escapes, allow_executable_comments=True)
    depth = 0
    for index, token in enumerate(stream[:-2]):
        if token.kind == "punct" and token.value == "(":
            depth += 1
        elif token.kind == "punct" and token.value == ")":
            depth -= 1
        elif (
            depth == 0
            and token.kind == "word"
            and ascii_lower(token.value) == "auto_increment"
        ):
            equals, number = stream[index + 1 : index + 3]
            if (
                equals.value == "="
                and number.kind == "word"
                and number.value.isdecimal()
            ):
                return sql[: token.start].rstrip() + sql[number.end :]
    return sql


def without_default(definition: str) -> str:
    """Remove one SQLite DEFAULT clause, retaining all other declaration text."""
    stream = tokens(definition)
    depth = 0
    starts: list[int] = []
    for index, token in enumerate(stream):
        if (token.kind, token.value) == ("punct", "("):
            depth += 1
        elif (token.kind, token.value) == ("punct", ")"):
            depth -= 1
        elif depth == 0 and (token.kind, ascii_lower(token.value)) == (
            "word",
            "default",
        ):
            starts.append(index)
    if not starts:
        return definition
    if len(starts) != 1:
        msg = "multiple DEFAULT clauses require an explicit adapter"
        raise SchemaError(msg)
    start = starts[0]
    end = start + 1
    if end < len(stream) and stream[end].value in {"+", "-"}:
        end += 1
    if end >= len(stream):
        msg = "empty DEFAULT clause"
        raise SchemaError(msg)
    end = _default_end(stream, end)
    return definition[: stream[start].start].rstrip() + definition[stream[end].end :]


def _default_end(stream: tuple[Token, ...], end: int) -> int:
    """Locate the last token of a scalar or parenthesized default expression."""
    if (stream[end].kind, stream[end].value) == ("punct", "("):
        depth = 1
        end += 1
        while end < len(stream) and depth:
            if (stream[end].kind, stream[end].value) == ("punct", "("):
                depth += 1
            elif (stream[end].kind, stream[end].value) == ("punct", ")"):
                depth -= 1
            end += 1
        if depth:
            msg = "unbalanced DEFAULT expression"
            raise SchemaError(msg)
        end -= 1
    return end
