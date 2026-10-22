"""Cheap negative extension checks for known column descriptor implementations.

Unknown columns and expressions retain structural dispatch. No capability result
is cached: a bound descriptor can still inherit newly installed class hooks.
"""

lazy from typing import Any, TypeIs

lazy from snekql._dialect_expr import DialectSelectable, PolicySelectable, SqlCompilable
lazy from snekql.storage import Attr, FKAttr, _DeferredFKAttr


def _plain_column_lacks_hook(value: object, protocol: type, hook: str) -> bool:
    """Prove a required method absent without generic static attribute traversal.

    Exact builtins have ordinary instance dictionaries and class lookup. Keep
    nominal/registered membership on the original path, and inspect both places
    where an extension can install its hook, without invoking descriptors or
    customized dictionary membership. Subclasses may redefine lookup and
    must use the protocol's full rules instead.
    """
    cls = type(value)
    return (
        (cls is Attr or cls is FKAttr or cls is _DeferredFKAttr)
        and not issubclass(cls, protocol)
        and not dict.__contains__(vars(value), hook)
        and all(hook not in base.__dict__ for base in cls.__mro__)
    )


def is_sql_compilable(value: object) -> TypeIs[SqlCompilable]:
    """Keep open-AST rendering precedence, including per-instance hooks."""
    return not _plain_column_lacks_hook(
        value, SqlCompilable, "__compile_sql__"
    ) and isinstance(value, SqlCompilable)


def is_policy_selectable(value: object) -> TypeIs[PolicySelectable]:
    """A custom policy still takes precedence over the ordinary column codec."""
    return not _plain_column_lacks_hook(
        value, PolicySelectable, "__decode_with_policy__"
    ) and isinstance(value, PolicySelectable)


def is_dialect_selectable(value: object) -> TypeIs[DialectSelectable[Any, Any]]:
    """A required rendering hook distinguishes extension projections."""
    return not _plain_column_lacks_hook(
        value, DialectSelectable, "__compile_sql__"
    ) and isinstance(value, DialectSelectable)
