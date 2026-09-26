"""SQLite write verbs whose docstrings describe SQLite's own write semantics.

The Query Builder in ``snekql.query`` is dialect-blind, so the neutral
``insert`` / ``update`` / ``delete`` carry only a backend-agnostic description.
These thin wrappers delegate to that builder unchanged but document what SQLite
actually does on execution -- most notably how SQLite reports affected rows --
so the ``snekql.sqlite`` namespace surfaces SQLite-specific guidance.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Literal, Never, cast, overload

from pydantic import BaseModel

from snekql._aliases import TableAlias, _AliasOwner, build_alias
from snekql._cte import _Cte, _CteOwner, build_cte_alias
from snekql._dialect_expr import DialectSelectable
from snekql._query_readiness import _ExecutableQuery, _IncompleteQuery
from snekql._query_state import selectable_owner_model
from snekql.errors import QueryConstructionError
from snekql.expressions import Aggregate, ColumnRef, Predicate, Scalar, _Scalar
from snekql.model import Pending, Row, Table, require_model_backend
from snekql.query import (
    DeleteQuery,
    InsertableModel,
    InsertManyQuery,
    InsertQuery,
    SelectModelQuery,
    SelectTupleQuery,
    SelectValueQuery,
    UpdateQuery,
    _check_read_query,
    _DeclarationSource,
    _ExecutableOptionalSelect,
    _ExecutableSelect,
    _SelectableModelClass,
    build_insert,
    build_insert_many,
    build_select,
)
from snekql.query import (
    delete as build_delete,
)
from snekql.query import exists as build_exists
from snekql.query import not_exists as build_not_exists
from snekql.query import scalar as build_scalar
from snekql.query import (
    update as build_update,
)
from snekql.sqlite.model import Model
from snekql.storage import Attr

type ReadQuery[Scope, Result] = _ExecutableSelect[
    Literal["sqlite"], Scope, Scope, Result
]
"""An executable read retaining the tables its expressions reference."""
type OptionalRead[Scope, Result] = _ExecutableOptionalSelect[
    Literal["sqlite"], Scope, Scope, Result
]
"""A read whose missing row is distinct from every possible row value."""
type ClosedRead[Result] = ReadQuery[Never, Result]
"""An execution/inspection view checked by ready, without fluent composition."""
type ClosedOptional[Result] = OptionalRead[Never, Result]
"""A checked read that still permits fetch_one_or_none."""
type PendingInput[Owner: Model[Pending], Result: Table[Row]] = InsertableModel[
    Literal["sqlite"], Owner, Result
]
"""Pending insertion input retaining its exact model owner and Row result."""


def _require_sqlite_model(model: type[Table[Any]] | None) -> None:
    """Back-stop static family constraints for dynamically typed callers."""

    if model is None:
        return
    if isinstance(model, TableAlias):
        msg = "aliases cannot be mutation targets"
        raise QueryConstructionError(msg)
    if isinstance(model, _Cte):
        msg = "CTEs cannot be mutation targets"
        raise QueryConstructionError(msg)
    if not isinstance(model, type) or not issubclass(model, Table):
        msg = "query source requires a table model or native query role"
        raise QueryConstructionError(msg)
    received = require_model_backend(model)
    if received != "sqlite":
        msg = (
            "backend mismatch: expected sqlite model, "
            f"received {received} model {model.__name__}"
        )
        raise QueryConstructionError(msg)


def exists(
    subquery: _ExecutableSelect[Literal["sqlite"], Any, Any, Any], /
) -> Predicate[Never, Literal["sqlite"]]:
    """Test whether a ready SQLite subquery returns a row; correlation is allowed."""
    return build_exists(subquery)


def not_exists(
    subquery: _ExecutableSelect[Literal["sqlite"], Any, Any, Any], /
) -> Predicate[Never, Literal["sqlite"]]:
    """Test whether a ready SQLite subquery is empty; correlation is allowed."""
    return build_not_exists(subquery)


def scalar[T, CompareT](
    subquery: SelectValueQuery[
        Literal["sqlite"], Any, Any, T, CompareT, _ExecutableQuery
    ],
    /,
) -> Scalar[Never, T | None, CompareT, Literal["sqlite"]]:
    """Read one SQLite subquery value, or NULL when it returns no row."""
    return build_scalar(subquery)


@overload
def ready[Scope, Result](
    query: OptionalRead[Scope, Result], /
) -> ClosedOptional[Result]: ...


@overload
def ready[Scope, Result](query: ReadQuery[Scope, Result], /) -> ClosedRead[Result]: ...


def ready[Scope, Result](query: ReadQuery[Scope, Result], /) -> ClosedRead[Result]:
    """Check a finished read before returning it through a short helper annotation.

    `return ready(select(User).all())` fits `ClosedRead[User[Row]]`.
    This compiles SQL without database I/O and returns the same query. Finish
    fluent composition before closing; ordinary execution does not need ready.
    """
    _check_read_query(query, backend="sqlite")
    # Native compilation checked the references; Never records their closure.
    # This annotation exposes execution and inspection, not more composition.
    return cast("ClosedRead[Result]", query)


@overload
def select[SourceT: Table[Any], ResultT: BaseModel, RoleT, NonNullableOwnerT](
    source: _Cte[Literal["sqlite"], SourceT, ResultT, RoleT, NonNullableOwnerT],
    /,
) -> SelectModelQuery[
    Literal["sqlite"], _CteOwner[Literal["sqlite"], SourceT, RoleT], ResultT
]: ...


# BEGIN GENERATED BACKEND SELECT OVERLOADS
@overload
def select[
    OwnerT: Model[Any]
    | _AliasOwner[Literal["sqlite"], Any, Any]
    | _CteOwner[Literal["sqlite"], Any, Any],
    ReadT: Table[Any],
](
    model: _SelectableModelClass[Literal["sqlite"], OwnerT, ReadT],
    /,
) -> SelectModelQuery[Literal["sqlite"], OwnerT, ReadT]: ...


@overload
def select[
    OwnerT: Model[Any]
    | _AliasOwner[Literal["sqlite"], Any, Any]
    | _CteOwner[Literal["sqlite"], Any, Any],
    ValueT,
    CompareT,
](
    field: Attr[Any, Any, OwnerT, Any, ValueT, Any, CompareT]
    | Aggregate[OwnerT, ValueT, CompareT]
    | DialectSelectable[OwnerT, ValueT, CompareT],
    /,
) -> SelectValueQuery[Literal["sqlite"], OwnerT, OwnerT, ValueT, CompareT]: ...


@overload
def select[
    OwnerT: Model[Any]
    | _AliasOwner[Literal["sqlite"], Any, Any]
    | _CteOwner[Literal["sqlite"], Any, Any],
    ValueT,
](
    field: ColumnRef[OwnerT, ValueT, Literal["sqlite"]],
    /,
) -> SelectValueQuery[Literal["sqlite"], OwnerT, OwnerT, ValueT, ValueT]: ...


@overload
def select[
    Owner1T: Model[Any]
    | _AliasOwner[Literal["sqlite"], Any, Any]
    | _CteOwner[Literal["sqlite"], Any, Any],
    T1,
    Owner2T: Model[Any]
    | _AliasOwner[Literal["sqlite"], Any, Any]
    | _CteOwner[Literal["sqlite"], Any, Any],
    T2,
](
    field1: Attr[Any, Any, Owner1T, Any, T1]
    | ColumnRef[Owner1T, T1, Literal["sqlite"]]
    | Aggregate[Owner1T, T1, Any]
    | DialectSelectable[Owner1T, T1, Any],
    field2: Attr[Any, Any, Owner2T, Any, T2]
    | ColumnRef[Owner2T, T2, Literal["sqlite"]]
    | Aggregate[Owner2T, T2, Any]
    | Scalar[Owner2T, T2, Any, Literal["sqlite"]]
    | DialectSelectable[Owner2T, T2, Any],
    /,
) -> SelectTupleQuery[
    Literal["sqlite"], Owner1T, Owner1T | Owner2T, _IncompleteQuery, T1, T2
]: ...


@overload
def select[
    Owner1T: Model[Any]
    | _AliasOwner[Literal["sqlite"], Any, Any]
    | _CteOwner[Literal["sqlite"], Any, Any],
    T1,
    Owner2T: Model[Any]
    | _AliasOwner[Literal["sqlite"], Any, Any]
    | _CteOwner[Literal["sqlite"], Any, Any],
    T2,
    Owner3T: Model[Any]
    | _AliasOwner[Literal["sqlite"], Any, Any]
    | _CteOwner[Literal["sqlite"], Any, Any],
    T3,
](
    field1: Attr[Any, Any, Owner1T, Any, T1]
    | ColumnRef[Owner1T, T1, Literal["sqlite"]]
    | Aggregate[Owner1T, T1, Any]
    | DialectSelectable[Owner1T, T1, Any],
    field2: Attr[Any, Any, Owner2T, Any, T2]
    | ColumnRef[Owner2T, T2, Literal["sqlite"]]
    | Aggregate[Owner2T, T2, Any]
    | Scalar[Owner2T, T2, Any, Literal["sqlite"]]
    | DialectSelectable[Owner2T, T2, Any],
    field3: Attr[Any, Any, Owner3T, Any, T3]
    | ColumnRef[Owner3T, T3, Literal["sqlite"]]
    | Aggregate[Owner3T, T3, Any]
    | Scalar[Owner3T, T3, Any, Literal["sqlite"]]
    | DialectSelectable[Owner3T, T3, Any],
    /,
) -> SelectTupleQuery[
    Literal["sqlite"],
    Owner1T,
    Owner1T | Owner2T | Owner3T,
    _IncompleteQuery,
    T1,
    T2,
    T3,
]: ...


@overload
def select[
    Owner1T: Model[Any]
    | _AliasOwner[Literal["sqlite"], Any, Any]
    | _CteOwner[Literal["sqlite"], Any, Any],
    T1,
    Owner2T: Model[Any]
    | _AliasOwner[Literal["sqlite"], Any, Any]
    | _CteOwner[Literal["sqlite"], Any, Any],
    T2,
    Owner3T: Model[Any]
    | _AliasOwner[Literal["sqlite"], Any, Any]
    | _CteOwner[Literal["sqlite"], Any, Any],
    T3,
    Owner4T: Model[Any]
    | _AliasOwner[Literal["sqlite"], Any, Any]
    | _CteOwner[Literal["sqlite"], Any, Any],
    T4,
](
    field1: Attr[Any, Any, Owner1T, Any, T1]
    | ColumnRef[Owner1T, T1, Literal["sqlite"]]
    | Aggregate[Owner1T, T1, Any]
    | DialectSelectable[Owner1T, T1, Any],
    field2: Attr[Any, Any, Owner2T, Any, T2]
    | ColumnRef[Owner2T, T2, Literal["sqlite"]]
    | Aggregate[Owner2T, T2, Any]
    | Scalar[Owner2T, T2, Any, Literal["sqlite"]]
    | DialectSelectable[Owner2T, T2, Any],
    field3: Attr[Any, Any, Owner3T, Any, T3]
    | ColumnRef[Owner3T, T3, Literal["sqlite"]]
    | Aggregate[Owner3T, T3, Any]
    | Scalar[Owner3T, T3, Any, Literal["sqlite"]]
    | DialectSelectable[Owner3T, T3, Any],
    field4: Attr[Any, Any, Owner4T, Any, T4]
    | ColumnRef[Owner4T, T4, Literal["sqlite"]]
    | Aggregate[Owner4T, T4, Any]
    | Scalar[Owner4T, T4, Any, Literal["sqlite"]]
    | DialectSelectable[Owner4T, T4, Any],
    /,
) -> SelectTupleQuery[
    Literal["sqlite"],
    Owner1T,
    Owner1T | Owner2T | Owner3T | Owner4T,
    _IncompleteQuery,
    T1,
    T2,
    T3,
    T4,
]: ...


@overload
def select[
    Owner1T: Model[Any]
    | _AliasOwner[Literal["sqlite"], Any, Any]
    | _CteOwner[Literal["sqlite"], Any, Any],
    T1,
    Owner2T: Model[Any]
    | _AliasOwner[Literal["sqlite"], Any, Any]
    | _CteOwner[Literal["sqlite"], Any, Any],
    T2,
    Owner3T: Model[Any]
    | _AliasOwner[Literal["sqlite"], Any, Any]
    | _CteOwner[Literal["sqlite"], Any, Any],
    T3,
    Owner4T: Model[Any]
    | _AliasOwner[Literal["sqlite"], Any, Any]
    | _CteOwner[Literal["sqlite"], Any, Any],
    T4,
    Owner5T: Model[Any]
    | _AliasOwner[Literal["sqlite"], Any, Any]
    | _CteOwner[Literal["sqlite"], Any, Any],
    T5,
](
    field1: Attr[Any, Any, Owner1T, Any, T1]
    | ColumnRef[Owner1T, T1, Literal["sqlite"]]
    | Aggregate[Owner1T, T1, Any]
    | DialectSelectable[Owner1T, T1, Any],
    field2: Attr[Any, Any, Owner2T, Any, T2]
    | ColumnRef[Owner2T, T2, Literal["sqlite"]]
    | Aggregate[Owner2T, T2, Any]
    | Scalar[Owner2T, T2, Any, Literal["sqlite"]]
    | DialectSelectable[Owner2T, T2, Any],
    field3: Attr[Any, Any, Owner3T, Any, T3]
    | ColumnRef[Owner3T, T3, Literal["sqlite"]]
    | Aggregate[Owner3T, T3, Any]
    | Scalar[Owner3T, T3, Any, Literal["sqlite"]]
    | DialectSelectable[Owner3T, T3, Any],
    field4: Attr[Any, Any, Owner4T, Any, T4]
    | ColumnRef[Owner4T, T4, Literal["sqlite"]]
    | Aggregate[Owner4T, T4, Any]
    | Scalar[Owner4T, T4, Any, Literal["sqlite"]]
    | DialectSelectable[Owner4T, T4, Any],
    field5: Attr[Any, Any, Owner5T, Any, T5]
    | ColumnRef[Owner5T, T5, Literal["sqlite"]]
    | Aggregate[Owner5T, T5, Any]
    | Scalar[Owner5T, T5, Any, Literal["sqlite"]]
    | DialectSelectable[Owner5T, T5, Any],
    /,
) -> SelectTupleQuery[
    Literal["sqlite"],
    Owner1T,
    Owner1T | Owner2T | Owner3T | Owner4T | Owner5T,
    _IncompleteQuery,
    T1,
    T2,
    T3,
    T4,
    T5,
]: ...


@overload
def select[
    Owner1T: Model[Any]
    | _AliasOwner[Literal["sqlite"], Any, Any]
    | _CteOwner[Literal["sqlite"], Any, Any],
    T1,
    Owner2T: Model[Any]
    | _AliasOwner[Literal["sqlite"], Any, Any]
    | _CteOwner[Literal["sqlite"], Any, Any],
    T2,
    Owner3T: Model[Any]
    | _AliasOwner[Literal["sqlite"], Any, Any]
    | _CteOwner[Literal["sqlite"], Any, Any],
    T3,
    Owner4T: Model[Any]
    | _AliasOwner[Literal["sqlite"], Any, Any]
    | _CteOwner[Literal["sqlite"], Any, Any],
    T4,
    Owner5T: Model[Any]
    | _AliasOwner[Literal["sqlite"], Any, Any]
    | _CteOwner[Literal["sqlite"], Any, Any],
    T5,
    Owner6T: Model[Any]
    | _AliasOwner[Literal["sqlite"], Any, Any]
    | _CteOwner[Literal["sqlite"], Any, Any],
    T6,
](
    field1: Attr[Any, Any, Owner1T, Any, T1]
    | ColumnRef[Owner1T, T1, Literal["sqlite"]]
    | Aggregate[Owner1T, T1, Any]
    | DialectSelectable[Owner1T, T1, Any],
    field2: Attr[Any, Any, Owner2T, Any, T2]
    | ColumnRef[Owner2T, T2, Literal["sqlite"]]
    | Aggregate[Owner2T, T2, Any]
    | Scalar[Owner2T, T2, Any, Literal["sqlite"]]
    | DialectSelectable[Owner2T, T2, Any],
    field3: Attr[Any, Any, Owner3T, Any, T3]
    | ColumnRef[Owner3T, T3, Literal["sqlite"]]
    | Aggregate[Owner3T, T3, Any]
    | Scalar[Owner3T, T3, Any, Literal["sqlite"]]
    | DialectSelectable[Owner3T, T3, Any],
    field4: Attr[Any, Any, Owner4T, Any, T4]
    | ColumnRef[Owner4T, T4, Literal["sqlite"]]
    | Aggregate[Owner4T, T4, Any]
    | Scalar[Owner4T, T4, Any, Literal["sqlite"]]
    | DialectSelectable[Owner4T, T4, Any],
    field5: Attr[Any, Any, Owner5T, Any, T5]
    | ColumnRef[Owner5T, T5, Literal["sqlite"]]
    | Aggregate[Owner5T, T5, Any]
    | Scalar[Owner5T, T5, Any, Literal["sqlite"]]
    | DialectSelectable[Owner5T, T5, Any],
    field6: Attr[Any, Any, Owner6T, Any, T6]
    | ColumnRef[Owner6T, T6, Literal["sqlite"]]
    | Aggregate[Owner6T, T6, Any]
    | Scalar[Owner6T, T6, Any, Literal["sqlite"]]
    | DialectSelectable[Owner6T, T6, Any],
    /,
) -> SelectTupleQuery[
    Literal["sqlite"],
    Owner1T,
    Owner1T | Owner2T | Owner3T | Owner4T | Owner5T | Owner6T,
    _IncompleteQuery,
    T1,
    T2,
    T3,
    T4,
    T5,
    T6,
]: ...


@overload
def select[
    Owner1T: Model[Any]
    | _AliasOwner[Literal["sqlite"], Any, Any]
    | _CteOwner[Literal["sqlite"], Any, Any],
    T1,
    Owner2T: Model[Any]
    | _AliasOwner[Literal["sqlite"], Any, Any]
    | _CteOwner[Literal["sqlite"], Any, Any],
    T2,
    Owner3T: Model[Any]
    | _AliasOwner[Literal["sqlite"], Any, Any]
    | _CteOwner[Literal["sqlite"], Any, Any],
    T3,
    Owner4T: Model[Any]
    | _AliasOwner[Literal["sqlite"], Any, Any]
    | _CteOwner[Literal["sqlite"], Any, Any],
    T4,
    Owner5T: Model[Any]
    | _AliasOwner[Literal["sqlite"], Any, Any]
    | _CteOwner[Literal["sqlite"], Any, Any],
    T5,
    Owner6T: Model[Any]
    | _AliasOwner[Literal["sqlite"], Any, Any]
    | _CteOwner[Literal["sqlite"], Any, Any],
    T6,
    Owner7T: Model[Any]
    | _AliasOwner[Literal["sqlite"], Any, Any]
    | _CteOwner[Literal["sqlite"], Any, Any],
    T7,
](
    field1: Attr[Any, Any, Owner1T, Any, T1]
    | ColumnRef[Owner1T, T1, Literal["sqlite"]]
    | Aggregate[Owner1T, T1, Any]
    | DialectSelectable[Owner1T, T1, Any],
    field2: Attr[Any, Any, Owner2T, Any, T2]
    | ColumnRef[Owner2T, T2, Literal["sqlite"]]
    | Aggregate[Owner2T, T2, Any]
    | Scalar[Owner2T, T2, Any, Literal["sqlite"]]
    | DialectSelectable[Owner2T, T2, Any],
    field3: Attr[Any, Any, Owner3T, Any, T3]
    | ColumnRef[Owner3T, T3, Literal["sqlite"]]
    | Aggregate[Owner3T, T3, Any]
    | Scalar[Owner3T, T3, Any, Literal["sqlite"]]
    | DialectSelectable[Owner3T, T3, Any],
    field4: Attr[Any, Any, Owner4T, Any, T4]
    | ColumnRef[Owner4T, T4, Literal["sqlite"]]
    | Aggregate[Owner4T, T4, Any]
    | Scalar[Owner4T, T4, Any, Literal["sqlite"]]
    | DialectSelectable[Owner4T, T4, Any],
    field5: Attr[Any, Any, Owner5T, Any, T5]
    | ColumnRef[Owner5T, T5, Literal["sqlite"]]
    | Aggregate[Owner5T, T5, Any]
    | Scalar[Owner5T, T5, Any, Literal["sqlite"]]
    | DialectSelectable[Owner5T, T5, Any],
    field6: Attr[Any, Any, Owner6T, Any, T6]
    | ColumnRef[Owner6T, T6, Literal["sqlite"]]
    | Aggregate[Owner6T, T6, Any]
    | Scalar[Owner6T, T6, Any, Literal["sqlite"]]
    | DialectSelectable[Owner6T, T6, Any],
    field7: Attr[Any, Any, Owner7T, Any, T7]
    | ColumnRef[Owner7T, T7, Literal["sqlite"]]
    | Aggregate[Owner7T, T7, Any]
    | Scalar[Owner7T, T7, Any, Literal["sqlite"]]
    | DialectSelectable[Owner7T, T7, Any],
    /,
) -> SelectTupleQuery[
    Literal["sqlite"],
    Owner1T,
    Owner1T | Owner2T | Owner3T | Owner4T | Owner5T | Owner6T | Owner7T,
    _IncompleteQuery,
    T1,
    T2,
    T3,
    T4,
    T5,
    T6,
    T7,
]: ...


@overload
def select[
    Owner1T: Model[Any]
    | _AliasOwner[Literal["sqlite"], Any, Any]
    | _CteOwner[Literal["sqlite"], Any, Any],
    T1,
    Owner2T: Model[Any]
    | _AliasOwner[Literal["sqlite"], Any, Any]
    | _CteOwner[Literal["sqlite"], Any, Any],
    T2,
    Owner3T: Model[Any]
    | _AliasOwner[Literal["sqlite"], Any, Any]
    | _CteOwner[Literal["sqlite"], Any, Any],
    T3,
    Owner4T: Model[Any]
    | _AliasOwner[Literal["sqlite"], Any, Any]
    | _CteOwner[Literal["sqlite"], Any, Any],
    T4,
    Owner5T: Model[Any]
    | _AliasOwner[Literal["sqlite"], Any, Any]
    | _CteOwner[Literal["sqlite"], Any, Any],
    T5,
    Owner6T: Model[Any]
    | _AliasOwner[Literal["sqlite"], Any, Any]
    | _CteOwner[Literal["sqlite"], Any, Any],
    T6,
    Owner7T: Model[Any]
    | _AliasOwner[Literal["sqlite"], Any, Any]
    | _CteOwner[Literal["sqlite"], Any, Any],
    T7,
    Owner8T: Model[Any]
    | _AliasOwner[Literal["sqlite"], Any, Any]
    | _CteOwner[Literal["sqlite"], Any, Any],
    T8,
](
    field1: Attr[Any, Any, Owner1T, Any, T1]
    | ColumnRef[Owner1T, T1, Literal["sqlite"]]
    | Aggregate[Owner1T, T1, Any]
    | DialectSelectable[Owner1T, T1, Any],
    field2: Attr[Any, Any, Owner2T, Any, T2]
    | ColumnRef[Owner2T, T2, Literal["sqlite"]]
    | Aggregate[Owner2T, T2, Any]
    | Scalar[Owner2T, T2, Any, Literal["sqlite"]]
    | DialectSelectable[Owner2T, T2, Any],
    field3: Attr[Any, Any, Owner3T, Any, T3]
    | ColumnRef[Owner3T, T3, Literal["sqlite"]]
    | Aggregate[Owner3T, T3, Any]
    | Scalar[Owner3T, T3, Any, Literal["sqlite"]]
    | DialectSelectable[Owner3T, T3, Any],
    field4: Attr[Any, Any, Owner4T, Any, T4]
    | ColumnRef[Owner4T, T4, Literal["sqlite"]]
    | Aggregate[Owner4T, T4, Any]
    | Scalar[Owner4T, T4, Any, Literal["sqlite"]]
    | DialectSelectable[Owner4T, T4, Any],
    field5: Attr[Any, Any, Owner5T, Any, T5]
    | ColumnRef[Owner5T, T5, Literal["sqlite"]]
    | Aggregate[Owner5T, T5, Any]
    | Scalar[Owner5T, T5, Any, Literal["sqlite"]]
    | DialectSelectable[Owner5T, T5, Any],
    field6: Attr[Any, Any, Owner6T, Any, T6]
    | ColumnRef[Owner6T, T6, Literal["sqlite"]]
    | Aggregate[Owner6T, T6, Any]
    | Scalar[Owner6T, T6, Any, Literal["sqlite"]]
    | DialectSelectable[Owner6T, T6, Any],
    field7: Attr[Any, Any, Owner7T, Any, T7]
    | ColumnRef[Owner7T, T7, Literal["sqlite"]]
    | Aggregate[Owner7T, T7, Any]
    | Scalar[Owner7T, T7, Any, Literal["sqlite"]]
    | DialectSelectable[Owner7T, T7, Any],
    field8: Attr[Any, Any, Owner8T, Any, T8]
    | ColumnRef[Owner8T, T8, Literal["sqlite"]]
    | Aggregate[Owner8T, T8, Any]
    | Scalar[Owner8T, T8, Any, Literal["sqlite"]]
    | DialectSelectable[Owner8T, T8, Any],
    /,
) -> SelectTupleQuery[
    Literal["sqlite"],
    Owner1T,
    Owner1T | Owner2T | Owner3T | Owner4T | Owner5T | Owner6T | Owner7T | Owner8T,
    _IncompleteQuery,
    T1,
    T2,
    T3,
    T4,
    T5,
    T6,
    T7,
    T8,
]: ...


# END GENERATED BACKEND SELECT OVERLOADS
def select(*args: object) -> object:
    """Build a SQLite select whose private carrier retains SQLite identity."""

    query = build_select(*args)
    state = cast("Any", query).state
    _require_sqlite_model(state.model)
    for field in state.fields:
        if isinstance(field, _Scalar):
            _require_sqlite_model(field.subquery.state.model)
        else:
            _require_sqlite_model(selectable_owner_model(field))
    return query


def insert[OwnerT: Model[Any], ReadT: Table[Any]](
    row: InsertableModel[Literal["sqlite"], OwnerT, ReadT], /
) -> InsertQuery[Literal["sqlite"], OwnerT, ReadT]:
    """Insert one SQLite Pending value; use insert_many(Model, rows) for batches.

    `insert(user)` executes to `None`. `insert(user).returning()` returns the
    Row produced by the database, including generated values. Conflict handling
    remains available through `on_conflict` with `DoUpdate` or `DoNothing`.
    RETURNING includes generated INTEGER PRIMARY KEY rowids and server defaults.
    Conflict actions use SQLite ON CONFLICT handling.
    """
    query = build_insert(row)
    _require_sqlite_model(query.state.model())
    return query


def insert_many[OwnerT: Model[Pending], ReadT: Table[Row]](
    model: _DeclarationSource[Literal["sqlite"], OwnerT, ReadT],
    rows: Sequence[OwnerT],
    /,
) -> InsertManyQuery[Literal["sqlite"], OwnerT, ReadT]:
    """Insert Pending values into one declared model, including an empty batch.

    `insert_many(User, users).returning()` returns a list of `User[Row]`.
    An empty batch executes as a no-op. Conflict handling, generated values,
    and RETURNING use the same builder as single-row `insert(user)`.
    """
    query = build_insert_many(model, rows)
    # The builder has checked that this is a bare model declaration.
    _require_sqlite_model(cast("type[Table[Any]]", model))
    return query


def update[ModelT: Model[Any], ReadT: Table[Any]](
    model: _DeclarationSource[Literal["sqlite"], ModelT, ReadT], /
) -> UpdateQuery[Literal["sqlite"], ModelT, ReadT]:
    """Build a SQLite ``UPDATE`` for a table model.

    Executed, it returns the affected-row count. SQLite's ``rowcount`` counts
    every row the ``WHERE`` clause matched, so updating a row to its current
    value still increments the count. Chain ``.set(...)`` with assignments and
    ``.where(...)`` / ``.all()`` to scope the statement.
    """

    _require_sqlite_model(cast("type[Table[Any]]", model))
    return build_update(model)


def delete[ModelT: Model[Any], ReadT: Table[Any]](
    model: _DeclarationSource[Literal["sqlite"], ModelT, ReadT], /
) -> DeleteQuery[Literal["sqlite"], ModelT, ReadT]:
    """Build a SQLite ``DELETE`` for a table model.

    Executed, it returns the number of rows deleted (SQLite's ``rowcount``).
    Chain ``.where(...)`` to scope the statement or ``.all()`` to delete every
    row.
    """

    _require_sqlite_model(cast("type[Table[Any]]", model))
    return build_delete(model)


@overload
def alias[
    SourceT: Table[Any],
    ResultT: BaseModel,
    RoleT,
    NonNullableOwnerT,
    AliasRoleT,
](
    model: _Cte[Literal["sqlite"], SourceT, ResultT, RoleT, NonNullableOwnerT],
    role: type[AliasRoleT],
    *,
    name: str,
) -> _Cte[Literal["sqlite"], SourceT, ResultT, AliasRoleT, NonNullableOwnerT]: ...


@overload
def alias[OwnerT: Model[Any], ReadT: Table[Any], RoleT](
    model: _DeclarationSource[Literal["sqlite"], OwnerT, ReadT],
    role: type[RoleT],
    *,
    name: str,
) -> TableAlias[Literal["sqlite"], OwnerT, ReadT, RoleT]: ...


def alias(
    model: object, role: type[object], *, name: str
) -> TableAlias[Any, Any, Any, Any] | _Cte[Any, Any, Any, Any, Any]:
    """Give a table or CTE a typed role without changing its fetched result type."""
    if isinstance(model, _Cte):
        return build_cte_alias(model, role, name=name, backend="sqlite")
    return build_alias(model, role, name=name, backend="sqlite")
