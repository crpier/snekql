"""Custom field specifiers lose their result type inside class bodies."""
from typing import dataclass_transform, reveal_type

class Token[Value]:
    def identity(self, value: Value) -> Value:
        return value

def field(*, default: Token[int] | None = None) -> Token[int]:
    return Token[int]() if default is None else default

def needs_text(token: Token[str]) -> None:
    pass

@dataclass_transform(field_specifiers=(field,))
class Meta(type):
    pass

class MissingDefault(metaclass=Meta):
    token: Token[int] = field()
    reveal_type(token)
    needs_text(token)

class ExplicitDefault(metaclass=Meta):
    token: Token[int] = field(default=Token[int]())
    reveal_type(token)
    needs_text(token)

class Plain:
    token: Token[int] = field()
    reveal_type(token)
    needs_text(token)
