from dataclasses import dataclass
from enum import StrEnum, auto
from typing import Any, Literal

from snekql.model import Base, ClassAttr
from snekql.tstring_compat import Interpolation, Template


class LexingError(Exception): ...


class TokenType(StrEnum):
    # Keywords
    ADD = auto()
    ALTER = auto()
    AND = auto()
    AS = auto()
    ASC = auto()
    AVG = auto()
    CONSTRAINT = auto()
    COUNT = auto()
    CREATE = auto()
    CURRENT_TIMESTAMP = auto()
    DEFAULT = auto()
    DELETE = auto()
    DESC = auto()
    DISTINCT = auto()
    DROP = auto()
    FROM = auto()
    GROUP_BY = auto()
    INDEX = auto()
    INNER = auto()
    INTEGER = auto()
    JOIN = auto()
    LEFT = auto()
    LIKE = auto()
    LIMIT = auto()
    MAX = auto()
    MIN = auto()
    NOT_NULL = auto()
    OFFSET = auto()
    ON = auto()
    OR = auto()
    OUTER = auto()
    PRIMARY_KEY = auto()
    REAL = auto()
    RIGHT = auto()
    SELECT = auto()
    SET = auto()
    SUM = auto()
    TABLE = auto()
    TEXT = auto()
    UNIQUE = auto()
    UPDATE = auto()
    WHERE = auto()

    # Operators
    DIVIDE = auto()
    EQUAL = auto()
    GREATER_THAN = auto()
    GREATER_THAN_EQUAL = auto()
    LESS_THAN = auto()
    LESS_THAN_EQUAL = auto()
    MINUS = auto()
    MOD = auto()
    NOT_EQUAL = auto()
    PLUS = auto()
    STAR = auto()

    # Punctuation
    COLON = auto()
    COMMA = auto()
    DOT = auto()
    LEFT_PAREN = auto()
    RIGHT_PAREN = auto()
    SEMICOLON = auto()
    PERIOD = auto()

    # Literals
    IDENTIFIER = auto()
    INTEGER_LITERAL = auto()
    REAL_LITERAL = auto()
    STRING_LITERAL = auto()

    # My own special tokens
    MODEL = auto()
    ATTR = auto()

    # EOF
    EOF = auto()


RESERVED_KEYWORDS = {
    "select": TokenType.SELECT,
    "from": TokenType.FROM,
    "where": TokenType.WHERE,
    "and": TokenType.AND,
    "or": TokenType.OR,
    "delete": TokenType.DELETE,
}


@dataclass
class Token:
    type: TokenType
    value: Any
    expression: str
    line: int
    column: int
    quotes: Literal["DOUBLE", "SINGLE", "BACKTICK"] | None = None

    def __repr__(self) -> str:
        if self.type == TokenType.ATTR and isinstance(self.value, tuple):
            return " ".join([f"<{self.type} {v}>" for v in self.value])
        return f"<{self.type} {self.value}>"


class Lexer:
    def __init__(self, source: Template) -> None:
        self.source: list[str | Interpolation] = []
        for item in source:
            if isinstance(item, str):
                self.source.extend(item)
            else:
                self.source.append(item)
        self.length = len(self.source)
        """Number of individual characters in the source code.
        Note an Interpolation is counted as one character."""
        self.current_index = -1
        """Index of the character under the cursor, 
        which can either be a full string or an Interpolation."""
        self.line = 1
        self.column = 0
        """While columns are 1-indexed, we start at 0 because we advance
        when starting the parsing"""

    def at_end(self) -> bool:
        """Whether the cursor is on the last character of the source code, or beyond."""
        return self.current_index >= self.length - 1

    def advance(self, count: int = 1) -> None:
        self.column += count
        self.current_index += count

    def current_char(self) -> str | Interpolation:
        try:
            return self.source[self.current_index]
        except IndexError:
            return ""

    def peek(self, count: int = 1) -> str | Interpolation:
        if self.at_end():
            return ""
        return self.source[self.current_index + count]

    def scan_tokens(self) -> tuple[list[Token], list[LexingError]]:
        """Scans the source code and returns a list of
        parsed tokens and a list of LexingErrors."""
        tokens: list[Token] = []
        errors: list[LexingError] = []
        while not self.at_end():
            if token := self.scan_token():
                tokens.append(token)
        return tokens, errors

    def scan_identifier(self) -> Token:
        start = self.current_index
        start_column = self.column
        while not self.at_end():
            self.advance()
            next_char = self.peek()
            if isinstance(next_char, str) and next_char.isalnum():
                pass
            else:
                break
        # We validated that only characters are in the word
        word = "".join(self.source[start : self.current_index + 1])  # pyright: ignore[reportCallIssue,reportArgumentType]
        if word in RESERVED_KEYWORDS:
            return Token(
                RESERVED_KEYWORDS[word],
                word,
                word,
                self.line,
                start_column,
            )
        return Token(TokenType.IDENTIFIER, word, word, self.line, start_column)

    def scan_token(self) -> Token | None:
        """Looks at the caracter under the cursor and advance the cursor until it finished
        parsing a valid token.
        If the character is not the start of a valid token (e.g. whitespace), returns None."""
        # TODO: what if this is called when the cursor is at/beyond the end of the source code?
        self.advance()
        match self.source[self.current_index]:
            case "(":
                return Token(TokenType.LEFT_PAREN, "(", "(", self.line, self.column)
            case ")":
                return Token(TokenType.RIGHT_PAREN, ")", ")", self.line, self.column)
            case ",":
                return Token(TokenType.COMMA, ",", ",", self.line, self.column)
            case ".":
                return Token(TokenType.PERIOD, ".", ".", self.line, self.column)
            case ";":
                return Token(TokenType.SEMICOLON, ";", ";", self.line, self.column)
            case "-":
                return Token(TokenType.MINUS, "-", "-", self.line, self.column)
            case "+":
                return Token(TokenType.PLUS, "+", "+", self.line, self.column)
            case "*":
                return Token(TokenType.STAR, "*", "*", self.line, self.column)
            case "=":
                return Token(TokenType.EQUAL, "=", "=", self.line, self.column)
            case "<":
                if self.peek(2) == "=":
                    self.advance()
                    return Token(
                        TokenType.LESS_THAN_EQUAL, "<=", "<=", self.line, self.column
                    )
                return Token(TokenType.LESS_THAN, "<", "<", self.line, self.column)
            case ">":
                if self.peek(2) == "=":
                    self.advance()
                    return Token(
                        TokenType.GREATER_THAN_EQUAL, "<=", "<=", self.line, self.column
                    )
                return Token(TokenType.GREATER_THAN, "<", "<", self.line, self.column)
            case " " | "\t" | "\r":
                return None
            case "\n":
                self.line += 1
                self.column = 1
                return None
            case Interpolation(value=value, expression=expression) if isinstance(
                value, type
            ) and issubclass(value, Base):
                return Token(
                    TokenType.MODEL,
                    value,
                    expression,
                    self.line,
                    self.column,
                )
            case Interpolation(value=value, expression=expression) if (
                isinstance(value, ClassAttr)
                or isinstance(value, tuple)
                and all(isinstance(v, ClassAttr) for v in value)
            ):
                return Token(
                    TokenType.ATTR,
                    value,
                    expression,
                    self.line,
                    self.column,
                )
            case other:
                if isinstance(other, str) and other.isalnum():
                    return self.scan_identifier()
