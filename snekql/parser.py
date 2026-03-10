from snekql.lexer import Token, TokenType


class Expression: ...


class SELECT(Expression):
    def __init__(self, columns: "COLUMNS", table: "TABLE") -> None:
        self.columns = columns
        self.table = table

    def __repr__(self) -> str:
        return f"(SELECT {self.columns} {self.table})"


class DELETE(Expression):
    def __init__(self, table: "TABLE") -> None:
        self.table = table

    def __repr__(self) -> str:
        return f"(DELETE {self.table})"


class COLUMNS(Expression):
    def __init__(self, columns: list[Token]) -> None:
        self.columns = columns

    def __repr__(self) -> str:
        return f"(COLUMNS {', '.join([repr(c) for c in self.columns])})"


class TABLE(Expression):
    def __init__(self, name: Token) -> None:
        self.name = name

    def __repr__(self) -> str:
        return f"(TABLE {self.name})"


class Parser:
    def __init__(self, tokens: list[Token]) -> None:
        self.tokens = tokens
        self.current_index = 0

    def parse(self) -> Expression:
        return self.statement()

    def statement(self) -> Expression:
        if self.match(TokenType.SELECT):
            return self.select_statement()
        elif self.match(TokenType.DELETE):
            return self.delete_statement()
        else:
            raise SyntaxError(
                f"Expected 'SELECT' or 'DELETE' at line {self.peek().line}."
            )

    def select_statement(self) -> SELECT:
        columns = self.columns()
        self.consume(TokenType.FROM, "Expected 'FROM' after SELECT columns.")
        table = self.table()
        return SELECT(columns=columns, table=table)

    def columns(self) -> COLUMNS:
        if self.match(TokenType.STAR):
            return COLUMNS(columns=[self.previous()])

        match self.peek().type:
            case TokenType.IDENTIFIER:
                columns = []
                first_column = self.consume(
                    TokenType.IDENTIFIER, "Expected column name."
                )
                columns.append(first_column)

                while self.match(TokenType.COMMA):
                    next_column = self.consume(
                        TokenType.IDENTIFIER, "Expected column name after ','."
                    )
                    columns.append(next_column)
                return COLUMNS(columns=columns)
            case TokenType.ATTR:
                return COLUMNS(columns=[self.advance()])
            case _:
                raise SyntaxError(
                    f"Expected column name or attribute after '*' at line {self.peek().line}."
                )

    def delete_statement(self) -> DELETE:
        self.consume(TokenType.FROM, "Expected 'FROM' after 'DELETE'.")
        table = self.table()
        return DELETE(table=table)

    def table(self) -> TABLE:
        table_name = self.consume(
            TokenType.IDENTIFIER, "Expected table name after 'FROM'."
        )
        return TABLE(name=table_name)

    def consume(self, token_type: TokenType, message: str) -> Token:
        if self.check(token_type):
            return self.advance()
        raise SyntaxError(f"{message} at line {self.peek().line}")

    def match(self, *types: TokenType) -> bool:
        for token_type in types:
            if self.check(token_type):
                _ = self.advance()
                return True
        return False

    def check(self, token_type: TokenType) -> bool:
        if self.is_at_end():
            return False
        return self.peek().type == token_type

    def advance(self) -> Token:
        if not self.is_at_end():
            self.current_index += 1

        return self.previous()

    def is_at_end(self) -> bool:
        return self.peek().type == TokenType.EOF

    def peek(self) -> Token:
        return self.tokens[self.current_index]

    def previous(self) -> Token:
        return self.tokens[self.current_index - 1]
