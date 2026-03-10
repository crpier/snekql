from snekql import lexer
from snekql.model import Base
from snekql.parser import Parser
from snekql.tstring_compat import Interpolation, Template

if __name__ == "__main__":

    class Person(Base):
        name: str
        age: int

    tokens, _ = lexer.Lexer(
        Template(
            "select ",
            Interpolation(
                (Person.name, Person.age), "Person.name, Person.age", None, ""
            ),
            " from users;",
        )
    ).scan_tokens()
    parser = Parser(tokens)
    ast = parser.parse()
    print(ast)
