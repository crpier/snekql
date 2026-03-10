from typing import Any, Iterator, Literal

Conversion = Literal["a", "r", "s"]


class Interpolation:
    __match_args__ = ("value", "expression", "conversion", "format_spec")
    value: Any
    expression: str
    conversion: Conversion | None
    format_spec: str

    def __init__(
        self,
        value: Any,
        expression: str,
        conversion: Conversion | None,
        format_spec: str,
    ):
        self.value = value
        self.expression = expression
        self.conversion = conversion
        self.format_spec = format_spec

    def __repr__(self) -> str:
        return f"Interpolation({self.value!r}, {self.expression!r}, {self.conversion!r}, {self.format_spec!r})"


class Template:
    def __init__(self, *args: str | Interpolation):
        self._args = args
        self.strings = tuple([arg for arg in args if isinstance(arg, str)])
        self.interpolations = tuple([arg for arg in args if isinstance(arg, Interpolation)])

    @property
    def values(self) -> list[Any]:
        return [interpolation.value for interpolation in self.interpolations]

    def __iter__(self) -> Iterator[str | Interpolation]:
        return iter(self._args)

    def __repr__(self) -> str:
        return f"Template(strings={self.strings}, interpolations={self.interpolations})"


def convert(value: object, conversion: Conversion | None) -> object:
    if conversion == "a":
        return ascii(value)
    elif conversion == "r":
        return repr(value)
    elif conversion == "s":
        return str(value)
    return value


def to_string(template: Template) -> str:
    parts = []
    for item in template:
        match item:
            case str() as s:
                parts.append(s)
            case Interpolation(value, _, conversion, format_spec):
                value = convert(value, conversion)
                value = format(value, format_spec)
                parts.append(value)
    return "".join(parts)
