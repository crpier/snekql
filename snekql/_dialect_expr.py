"""Open-AST dialect expressions: the seam a Backend Namespace extends (ADR 0004).

A dialect-specific operator (e.g. MariaDB ``JSON_EXTRACT``) is added by the
Backend Namespace as an expression object that satisfies these *structural*
protocols, never as a new core AST node or ``kind`` branch. The core renders and
materializes it by calling the protocol methods, so it stays dialect-blind: it
never imports or names the leaf type.

Two seams, matching the two places an expression can appear:

* :class:`SqlCompilable` -- the operand-render seam, so the expression works as a
  predicate operand in ``WHERE``;
* :class:`DialectSelectable` -- the projection seam (operand render plus
  ``__decode__``), so it can be projected in ``SELECT`` and Materialized to a
  typed value.

:class:`CompileCtx` is the only thing the core hands an expression at compile
time: the Dialect facts it needs to render itself (placeholder, identifier
quoting) plus a column-reference renderer that already honours the enclosing
statement's qualification strategy.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:
    from snekql.model import Table


@dataclass(frozen=True)
class CompileCtx:
    """Dialect facts the core injects so an expression can render itself.

    This is the contract between the core compiler and a dialect expression:
    ``placeholder`` and ``quote_identifier`` are the backend's SQL facts, and
    ``render_column`` renders an owned column descriptor as the SQL reference the
    enclosing statement would use (bare or table-qualified), so an expression
    never reimplements column qualification.
    """

    placeholder: str
    quote_identifier: Callable[[str], str]
    render_column: Callable[[Any], str]


@runtime_checkable
class SqlCompilable(Protocol):
    """A dialect operand the core renders structurally, without naming the leaf.

    ``__owner_model__`` lets the core scope-check the operand (which table it
    belongs to) without knowing the concrete type; ``__compile_sql__`` renders it
    as a predicate operand against the injected :class:`CompileCtx`.
    """

    def __owner_model__(self) -> type[Table[Any]]: ...

    def __compile_sql__(self, ctx: CompileCtx) -> str: ...


@runtime_checkable
class DialectSelectable[T](Protocol):
    """A dialect expression that is also projectable and decodes to ``T``.

    Adds the projection seam to :class:`SqlCompilable`: ``__compile_select_sql__``
    renders it in a ``SELECT`` list and ``__decode__`` converts the raw driver
    value to ``T``. ``T`` flows into the query's result type purely through the
    ``select`` overloads; the core materializes by calling ``__decode__`` and
    never names the leaf.
    """

    def __owner_model__(self) -> type[Table[Any]]: ...

    def __compile_sql__(self, ctx: CompileCtx) -> str: ...

    def __compile_select_sql__(self, ctx: CompileCtx) -> str: ...

    def __decode__(self, raw: object) -> T: ...
