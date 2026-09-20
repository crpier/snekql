"""Conservative catalog recognition for the supported CHECK expression grammar."""

from dataclasses import dataclass

from snekql._checks import CheckExpression
from snekql.defaults import LiteralDefault
from snekql.errors import SchemaError


class _UnsupportedCheckError(SchemaError):
    """A catalog expression cannot be represented without guessing semantics."""


@dataclass(frozen=True)
class CheckShape:
    """A catalog name can be known even when expression structure is unknown."""

    name: str | None
    expression: CheckExpression | None


@dataclass(frozen=True)
class _Token:
    kind: str
    text: str


def _tokens(sql: str, *, mariadb: bool = False) -> tuple[_Token, ...]:  # noqa: C901, PLR0912, PLR0915
    """Keep every non-comment token; unknown punctuation must not disappear."""
    tokens: list[_Token] = []
    position = 0
    while position < len(sql):
        character = sql[position]
        if character in " \t\n\r\f":
            position += 1
            continue
        if sql.startswith("--", position) and (
            not mariadb or position + 2 == len(sql) or sql[position + 2] in " \t\n\r\f"
        ):
            newline = sql.find("\n", position + 2)
            position = len(sql) if newline < 0 else newline + 1
            continue
        if sql.startswith("/*", position):
            closing = sql.find("*/", position + 2)
            if closing < 0 or sql.startswith(("/*!", "/*M!"), position):
                raise _UnsupportedCheckError
            position = closing + 2
            continue
        if character in "'\"`[":
            closing_quote = "]" if character == "[" else character
            kind = "literal" if character == "'" else "identifier"
            position += 1
            value: list[str] = []
            while position < len(sql):
                if sql[position] != closing_quote:
                    value.append(sql[position])
                    position += 1
                elif (
                    position + 1 < len(sql)
                    and sql[position + 1] == closing_quote
                    and character != "["
                ):
                    value.append(closing_quote)
                    position += 2
                else:
                    position += 1
                    break
            else:
                raise _UnsupportedCheckError
            tokens.append(_Token(kind, "".join(value)))
            continue
        if character.isalpha() or character == "_":
            end = position + 1
            while end < len(sql) and (sql[end].isalnum() or sql[end] in "_$"):
                end += 1
            tokens.append(
                _Token(
                    "word" if sql[position:end].isascii() else "identifier",
                    sql[position:end],
                )
            )
            position = end
            continue
        if character.isascii() and character.isdigit():
            end = position + 1
            while end < len(sql) and sql[end].isascii() and sql[end].isdigit():
                end += 1
            tokens.append(_Token("number", sql[position:end]))
            position = end
            continue
        pair = sql[position : position + 2]
        if pair in (">=", "<=", "<>", "!=", "=="):
            tokens.append(_Token("symbol", pair))
            position += 2
        else:
            tokens.append(_Token("symbol", character))
            position += 1
    return tuple(tokens)


class _Parser:
    """Parse only represented operators with SQL boolean precedence."""

    def __init__(
        self, tokens: tuple[_Token, ...], *, literal_keywords: bool = False
    ) -> None:
        self.tokens: tuple[_Token, ...] = tokens
        self.position: int = 0
        self.literal_keywords: bool = literal_keywords

    def parse(self) -> CheckExpression:
        expression = self._boolean("OR")
        if self.position != len(self.tokens):
            raise _UnsupportedCheckError
        return expression

    def _accept(self, text: str) -> bool:
        if self.position >= len(self.tokens):
            return False
        token = self.tokens[self.position]
        if token.kind not in ("word", "symbol") or token.text.upper() != text:
            return False
        self.position += 1
        return True

    def _require(self, text: str) -> None:
        if not self._accept(text):
            raise _UnsupportedCheckError

    def _boolean(self, operator: str) -> CheckExpression:
        child = self._comparison if operator == "AND" else lambda: self._boolean("AND")
        expression = child()
        while self._accept(operator):
            expression = CheckExpression(operator, (expression, child()))
        return expression

    def _comparison(self) -> CheckExpression:
        if self._accept("NOT"):
            return CheckExpression("NOT", (self._comparison(),))
        left = self._operand()
        if self._accept("IS"):
            operator = "IS NOT NULL" if self._accept("NOT") else "IS NULL"
            self._require("NULL")
            return CheckExpression(operator, (left,))
        negated = self._accept("NOT")
        if self._accept("IN"):
            self._require("(")
            values = [self._operand()]
            while self._accept(","):
                values.append(self._operand())
            self._require(")")
            return CheckExpression("NOT IN" if negated else "IN", (left, *values))
        if self._accept("BETWEEN"):
            low = self._operand()
            self._require("AND")
            expression = CheckExpression("BETWEEN", (left, low, self._operand()))
            return CheckExpression("NOT", (expression,)) if negated else expression
        if negated:
            raise _UnsupportedCheckError
        for spelling, operator in (
            ("=", "eq"),
            ("==", "eq"),
            ("<>", "ne"),
            ("!=", "ne"),
            (">", "gt"),
            (">=", "gte"),
            ("<", "lt"),
            ("<=", "lte"),
        ):
            if self._accept(spelling):
                return CheckExpression(operator, (left, self._operand()))
        return left

    def _operand(self) -> CheckExpression:  # noqa: C901
        if self._accept("("):
            expression = self._boolean("OR")
            self._require(")")
            return expression
        sign = -1 if self._accept("-") else 1
        explicit_plus = sign == 1 and self._accept("+")
        if self.position >= len(self.tokens):
            raise _UnsupportedCheckError
        token = self.tokens[self.position]
        self.position += 1
        if token.kind == "number":
            return CheckExpression("literal", value=sign * int(token.text))
        if sign != 1 or explicit_plus:
            raise _UnsupportedCheckError
        if token.kind == "literal":
            return CheckExpression("literal", value=token.text)
        if token.kind == "word" and token.text.upper() in ("CONVERT", "CAST"):
            self._require("(")
            self._require("X")
            if (
                self.position >= len(self.tokens)
                or self.tokens[self.position].kind != "literal"
            ):
                raise _UnsupportedCheckError
            encoded = self.tokens[self.position].text
            self.position += 1
            self._require("USING" if token.text.upper() == "CONVERT" else "AS")
            self._require("UTF8MB4" if token.text.upper() == "CONVERT" else "TEXT")
            self._require(")")
            return CheckExpression(
                "literal", value=bytes.fromhex(encoded).decode("utf-8")
            )
        if (
            self.literal_keywords
            and token.kind == "word"
            and token.text.upper() in ("TRUE", "FALSE", "NULL")
        ):
            return CheckExpression(
                "literal",
                value={"TRUE": 1, "FALSE": 0, "NULL": None}[token.text.upper()],
            )
        if token.kind in ("word", "identifier"):
            if token.kind == "word" and token.text.upper() in (
                "TRUE",
                "FALSE",
                "NULL",
                "CURRENT_DATE",
                "CURRENT_TIME",
                "CURRENT_TIMESTAMP",
                "CURRENT_USER",
                "SESSION_USER",
                "SYSTEM_USER",
            ):
                raise _UnsupportedCheckError
            return CheckExpression("column", value=token.text)
        raise _UnsupportedCheckError


def normalize_check(expression: CheckExpression) -> CheckExpression:
    """Account for catalog NOT-comparison rewrites and boolean association only."""
    arguments = tuple(normalize_check(child) for child in expression.arguments)
    if expression.operator == "NOT" and arguments:
        child = arguments[0]
        complements = {
            "eq": "ne",
            "ne": "eq",
            "gt": "lte",
            "gte": "lt",
            "lt": "gte",
            "lte": "gt",
            "IS NULL": "IS NOT NULL",
            "IS NOT NULL": "IS NULL",
            "IN": "NOT IN",
            "NOT IN": "IN",
        }
        if child.operator in ("AND", "OR"):
            return normalize_check(
                CheckExpression(
                    "OR" if child.operator == "AND" else "AND",
                    tuple(
                        CheckExpression("NOT", (member,)) for member in child.arguments
                    ),
                )
            )
        if child.operator in complements:
            return CheckExpression(complements[child.operator], child.arguments)
        if child.operator == "NOT":
            return child.arguments[0]
    if expression.operator in ("AND", "OR"):
        arguments = tuple(
            member
            for child in arguments
            for member in (
                child.arguments if child.operator == expression.operator else (child,)
            )
        )
    return CheckExpression(expression.operator, arguments, expression.value)


def parse_check(sql: str) -> CheckExpression | None:
    """Unknown SQL stays unknown, not a normalized match or fabricated drift."""
    try:
        tokens = _tokens(sql, mariadb=True)
        if any(token.kind == "literal" and "\\" in token.text for token in tokens):
            return None
        return _Parser(tokens).parse()
    except _UnsupportedCheckError, ValueError, UnicodeError, RecursionError:
        return None


def sqlite_checks(sql: str | None) -> tuple[CheckShape, ...] | None:  # noqa: C901, PLR0912
    """Extract CHECK bodies only at the outer table-definition depth."""
    if sql is None:
        return None
    try:
        tokens = _tokens(sql)
    except _UnsupportedCheckError:
        return None
    checks: list[CheckShape] = []
    depth = 0
    position = 0
    while position < len(tokens):
        token = tokens[position]
        if token == _Token("symbol", "("):
            depth += 1
        elif token == _Token("symbol", ")"):
            depth -= 1
        elif depth == 1 and token.kind == "word" and token.text.upper() == "CHECK":
            name = None
            if (
                position >= len(("CONSTRAINT", "name"))
                and tokens[position - 2].kind == "word"
                and tokens[position - 2].text.upper() == "CONSTRAINT"
            ):
                name = tokens[position - 1].text
            opening = position + 1
            if opening >= len(tokens) or tokens[opening] != _Token("symbol", "("):
                return None
            closing = opening + 1
            nested = 1
            while closing < len(tokens):
                if tokens[closing] == _Token("symbol", "("):
                    nested += 1
                elif tokens[closing] == _Token("symbol", ")"):
                    nested -= 1
                    if nested == 0:
                        break
                closing += 1
            if nested:
                return None
            try:
                expression = _Parser(tokens[opening + 1 : closing]).parse()
            except _UnsupportedCheckError, ValueError, UnicodeError, RecursionError:
                expression = None
            checks.append(CheckShape(name, expression))
            position = closing
        position += 1
    return tuple(checks)


def parse_default_literal(sql: str, *, mariadb: bool) -> LiteralDefault[object] | None:
    """Recognize complete constant expressions without executing catalog SQL."""
    try:
        tokens = _tokens(sql, mariadb=mariadb)
        # Parentheses around a sole literal are cosmetic. Parsing below still
        # rejects unbalanced syntax and all nonliteral expressions.
        if mariadb and any(
            token.kind == "literal" and "\\" in token.text for token in tokens
        ):
            return None
        expression = _Parser(tokens, literal_keywords=True).parse()
        if expression.operator == "literal":
            return LiteralDefault(expression.value)
    except _UnsupportedCheckError, ValueError, UnicodeError, RecursionError:
        pass
    return None


def sqlite_index_predicate(  # noqa: C901
    sql: str | None, *, column_names: tuple[str, ...]
) -> CheckExpression | None:
    """Read a top-level index WHERE without treating names or comments as SQL."""
    if sql is None:
        return None
    ascii_lower = str.maketrans(
        "ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz"
    )
    columns = {name.translate(ascii_lower): name for name in column_names}

    def canonical_columns(expression: CheckExpression) -> CheckExpression:
        if expression.operator == "column":
            name = columns.get(str(expression.value).translate(ascii_lower))
            if name is None:
                # SQLite can treat unknown double-quoted names as string literals.
                # Without an actual column identity, this is not a supported operand.
                raise _UnsupportedCheckError
            return CheckExpression("column", value=name)
        return CheckExpression(
            expression.operator,
            tuple(canonical_columns(child) for child in expression.arguments),
            expression.value,
        )

    try:
        tokens = _tokens(sql)
        if tokens and tokens[-1] == _Token("symbol", ";"):
            tokens = tokens[:-1]
        depth = 0
        columns_closed = False
        for position, token in enumerate(tokens):
            if token == _Token("symbol", "("):
                depth += 1
            elif token == _Token("symbol", ")"):
                depth -= 1
                if depth < 0:
                    return None
                columns_closed = depth == 0
            elif (
                depth == 0
                and columns_closed
                and token.kind == "word"
                and token.text.upper() == "WHERE"
            ):
                return canonical_columns(_Parser(tokens[position + 1 :]).parse())
    except _UnsupportedCheckError, ValueError, UnicodeError, RecursionError:
        pass
    return None
