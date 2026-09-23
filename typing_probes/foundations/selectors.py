"""Check whether typed attribute selectors have a practical runtime meaning."""

from collections.abc import Callable
from dataclasses import fields, is_dataclass
from typing import Never, cast


class SelectorError(Exception):
    """A selector is not a direct reference to a declared dataclass column."""


class _ColumnToken:
    def __init__(self, name: str, origin: object) -> None:
        self.name: str = name
        self.origin: object = origin

    def __getattr__(self, name: str) -> Never:
        message = f"Column selectors cannot evaluate attribute {name!r}"
        raise SelectorError(message)

    def __bool__(self) -> Never:
        message = "Column selectors cannot evaluate Python boolean expressions"
        raise SelectorError(message)


class _RowSelector:
    def __init__(self, names: frozenset[str], origin: object) -> None:
        self._names: frozenset[str] = names
        self._origin: object = origin

    def __getattr__(self, name: str) -> _ColumnToken:
        if name not in self._names:
            message = f"Undeclared column {name!r}"
            raise SelectorError(message)
        return _ColumnToken(name, self._origin)


def column_name[Row](row_type: type[Row], selector: Callable[[Row], object]) -> str:
    """Run an attribute-only callback on a guarded token proxy, not a real row.

    This cannot constrain callback bodies statically. Arbitrary Python code is
    not translated to SQL. User-defined properties and methods are unsupported.
    """
    if not is_dataclass(row_type):
        message = "The selector prototype requires a dataclass row"
        raise SelectorError(message)
    origin = object()
    proxy = _RowSelector(frozenset(field.name for field in fields(row_type)), origin)
    # Deliberate dynamic DSL boundary: the callback sees Row for autocomplete,
    # but only a token belonging to this capture may leave it at runtime.
    try:
        selected = selector(cast("Row", proxy))
    except (AttributeError, TypeError) as error:
        message = "Column selectors must return a direct attribute"
        raise SelectorError(message) from error
    if not isinstance(selected, _ColumnToken) or selected.origin is not origin:
        message = "Column selector did not return a column from this row"
        raise SelectorError(message)
    return selected.name
