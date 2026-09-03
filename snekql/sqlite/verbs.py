"""SQLite write verbs whose docstrings describe SQLite's own write semantics.

The Query Builder in ``snekql.query`` is dialect-blind, so the neutral
``insert`` / ``update`` / ``delete`` carry only a backend-agnostic description.
These thin wrappers delegate to that builder unchanged but document what SQLite
actually does on execution -- most notably how SQLite reports affected rows --
so the ``snekql.sqlite`` namespace surfaces SQLite-specific guidance.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Literal, cast, overload

from snekql._dialect_expr import DialectSelectable
from snekql._query_state import selectable_owner_model
from snekql.errors import QueryConstructionError
from snekql.expressions import Aggregate, ColumnRef, Scalar, _Scalar
from snekql.model import Table, require_model_backend
from snekql.query import (
    DeleteQuery,
    InsertableModel,
    InsertManyQuery,
    InsertQuery,
    SelectModelQuery,
    SelectTupleQuery,
    SelectValueQuery,
    UpdateQuery,
    _SelectableModelClass,
    build_insert,
    build_select,
)
from snekql.query import (
    delete as build_delete,
)
from snekql.query import (
    update as build_update,
)
from snekql.sqlite.model import Model
from snekql.storage import Attr


def _require_sqlite_model(model: type[Table[Any]] | None) -> None:
    """Back-stop static family constraints for dynamically typed callers."""

    if model is None:
        return
    received = require_model_backend(model)
    if received != "sqlite":
        msg = (
            "backend mismatch: expected sqlite model, "
            f"received {received} model {model.__name__}"
        )
        raise QueryConstructionError(msg)


# BEGIN GENERATED BACKEND SELECT OVERLOADS
@overload
def select[OwnerT: Model[Any, Any], ReadT: Table[Any]](
    model: _SelectableModelClass[Literal["sqlite"], OwnerT, ReadT],
    /,
) -> SelectModelQuery[Literal["sqlite"], OwnerT, ReadT]: ...


@overload
def select[OwnerT: Model[Any, Any], ValueT, CompareT](
    field: Attr[Any, Any, OwnerT, Any, ValueT, Any, CompareT]
    | Aggregate[OwnerT, ValueT, CompareT]
    | DialectSelectable[OwnerT, ValueT, CompareT],
    /,
) -> SelectValueQuery[Literal["sqlite"], OwnerT, OwnerT, ValueT, CompareT]: ...


@overload
def select[OwnerT: Model[Any, Any], ValueT](
    field: ColumnRef[OwnerT, ValueT],
    /,
) -> SelectValueQuery[Literal["sqlite"], OwnerT, OwnerT, ValueT, Any]: ...


@overload
def select[
    Owner1T: Model[Any, Any],
    T1,
    Owner2T: Model[Any, Any],
    T2,
](
    field1: Attr[Any, Any, Owner1T, Any, T1]
    | ColumnRef[Owner1T, T1]
    | Aggregate[Owner1T, T1, Any]
    | DialectSelectable[Owner1T, T1, Any],
    field2: Attr[Any, Any, Owner2T, Any, T2]
    | ColumnRef[Owner2T, T2]
    | Aggregate[Owner2T, T2, Any]
    | Scalar[Owner2T, T2, Any]
    | DialectSelectable[Owner2T, T2, Any],
    /,
) -> SelectTupleQuery[Literal["sqlite"], Owner1T, Owner1T | Owner2T, T1, T2]: ...


@overload
def select[
    Owner1T: Model[Any, Any],
    T1,
    Owner2T: Model[Any, Any],
    T2,
    Owner3T: Model[Any, Any],
    T3,
](
    field1: Attr[Any, Any, Owner1T, Any, T1]
    | ColumnRef[Owner1T, T1]
    | Aggregate[Owner1T, T1, Any]
    | DialectSelectable[Owner1T, T1, Any],
    field2: Attr[Any, Any, Owner2T, Any, T2]
    | ColumnRef[Owner2T, T2]
    | Aggregate[Owner2T, T2, Any]
    | Scalar[Owner2T, T2, Any]
    | DialectSelectable[Owner2T, T2, Any],
    field3: Attr[Any, Any, Owner3T, Any, T3]
    | ColumnRef[Owner3T, T3]
    | Aggregate[Owner3T, T3, Any]
    | Scalar[Owner3T, T3, Any]
    | DialectSelectable[Owner3T, T3, Any],
    /,
) -> SelectTupleQuery[
    Literal["sqlite"], Owner1T, Owner1T | Owner2T | Owner3T, T1, T2, T3
]: ...


@overload
def select[
    Owner1T: Model[Any, Any],
    T1,
    Owner2T: Model[Any, Any],
    T2,
    Owner3T: Model[Any, Any],
    T3,
    Owner4T: Model[Any, Any],
    T4,
](
    field1: Attr[Any, Any, Owner1T, Any, T1]
    | ColumnRef[Owner1T, T1]
    | Aggregate[Owner1T, T1, Any]
    | DialectSelectable[Owner1T, T1, Any],
    field2: Attr[Any, Any, Owner2T, Any, T2]
    | ColumnRef[Owner2T, T2]
    | Aggregate[Owner2T, T2, Any]
    | Scalar[Owner2T, T2, Any]
    | DialectSelectable[Owner2T, T2, Any],
    field3: Attr[Any, Any, Owner3T, Any, T3]
    | ColumnRef[Owner3T, T3]
    | Aggregate[Owner3T, T3, Any]
    | Scalar[Owner3T, T3, Any]
    | DialectSelectable[Owner3T, T3, Any],
    field4: Attr[Any, Any, Owner4T, Any, T4]
    | ColumnRef[Owner4T, T4]
    | Aggregate[Owner4T, T4, Any]
    | Scalar[Owner4T, T4, Any]
    | DialectSelectable[Owner4T, T4, Any],
    /,
) -> SelectTupleQuery[
    Literal["sqlite"], Owner1T, Owner1T | Owner2T | Owner3T | Owner4T, T1, T2, T3, T4
]: ...


@overload
def select[
    Owner1T: Model[Any, Any],
    T1,
    Owner2T: Model[Any, Any],
    T2,
    Owner3T: Model[Any, Any],
    T3,
    Owner4T: Model[Any, Any],
    T4,
    Owner5T: Model[Any, Any],
    T5,
](
    field1: Attr[Any, Any, Owner1T, Any, T1]
    | ColumnRef[Owner1T, T1]
    | Aggregate[Owner1T, T1, Any]
    | DialectSelectable[Owner1T, T1, Any],
    field2: Attr[Any, Any, Owner2T, Any, T2]
    | ColumnRef[Owner2T, T2]
    | Aggregate[Owner2T, T2, Any]
    | Scalar[Owner2T, T2, Any]
    | DialectSelectable[Owner2T, T2, Any],
    field3: Attr[Any, Any, Owner3T, Any, T3]
    | ColumnRef[Owner3T, T3]
    | Aggregate[Owner3T, T3, Any]
    | Scalar[Owner3T, T3, Any]
    | DialectSelectable[Owner3T, T3, Any],
    field4: Attr[Any, Any, Owner4T, Any, T4]
    | ColumnRef[Owner4T, T4]
    | Aggregate[Owner4T, T4, Any]
    | Scalar[Owner4T, T4, Any]
    | DialectSelectable[Owner4T, T4, Any],
    field5: Attr[Any, Any, Owner5T, Any, T5]
    | ColumnRef[Owner5T, T5]
    | Aggregate[Owner5T, T5, Any]
    | Scalar[Owner5T, T5, Any]
    | DialectSelectable[Owner5T, T5, Any],
    /,
) -> SelectTupleQuery[
    Literal["sqlite"],
    Owner1T,
    Owner1T | Owner2T | Owner3T | Owner4T | Owner5T,
    T1,
    T2,
    T3,
    T4,
    T5,
]: ...


@overload
def select[
    Owner1T: Model[Any, Any],
    T1,
    Owner2T: Model[Any, Any],
    T2,
    Owner3T: Model[Any, Any],
    T3,
    Owner4T: Model[Any, Any],
    T4,
    Owner5T: Model[Any, Any],
    T5,
    Owner6T: Model[Any, Any],
    T6,
](
    field1: Attr[Any, Any, Owner1T, Any, T1]
    | ColumnRef[Owner1T, T1]
    | Aggregate[Owner1T, T1, Any]
    | DialectSelectable[Owner1T, T1, Any],
    field2: Attr[Any, Any, Owner2T, Any, T2]
    | ColumnRef[Owner2T, T2]
    | Aggregate[Owner2T, T2, Any]
    | Scalar[Owner2T, T2, Any]
    | DialectSelectable[Owner2T, T2, Any],
    field3: Attr[Any, Any, Owner3T, Any, T3]
    | ColumnRef[Owner3T, T3]
    | Aggregate[Owner3T, T3, Any]
    | Scalar[Owner3T, T3, Any]
    | DialectSelectable[Owner3T, T3, Any],
    field4: Attr[Any, Any, Owner4T, Any, T4]
    | ColumnRef[Owner4T, T4]
    | Aggregate[Owner4T, T4, Any]
    | Scalar[Owner4T, T4, Any]
    | DialectSelectable[Owner4T, T4, Any],
    field5: Attr[Any, Any, Owner5T, Any, T5]
    | ColumnRef[Owner5T, T5]
    | Aggregate[Owner5T, T5, Any]
    | Scalar[Owner5T, T5, Any]
    | DialectSelectable[Owner5T, T5, Any],
    field6: Attr[Any, Any, Owner6T, Any, T6]
    | ColumnRef[Owner6T, T6]
    | Aggregate[Owner6T, T6, Any]
    | Scalar[Owner6T, T6, Any]
    | DialectSelectable[Owner6T, T6, Any],
    /,
) -> SelectTupleQuery[
    Literal["sqlite"],
    Owner1T,
    Owner1T | Owner2T | Owner3T | Owner4T | Owner5T | Owner6T,
    T1,
    T2,
    T3,
    T4,
    T5,
    T6,
]: ...


@overload
def select[
    Owner1T: Model[Any, Any],
    T1,
    Owner2T: Model[Any, Any],
    T2,
    Owner3T: Model[Any, Any],
    T3,
    Owner4T: Model[Any, Any],
    T4,
    Owner5T: Model[Any, Any],
    T5,
    Owner6T: Model[Any, Any],
    T6,
    Owner7T: Model[Any, Any],
    T7,
](
    field1: Attr[Any, Any, Owner1T, Any, T1]
    | ColumnRef[Owner1T, T1]
    | Aggregate[Owner1T, T1, Any]
    | DialectSelectable[Owner1T, T1, Any],
    field2: Attr[Any, Any, Owner2T, Any, T2]
    | ColumnRef[Owner2T, T2]
    | Aggregate[Owner2T, T2, Any]
    | Scalar[Owner2T, T2, Any]
    | DialectSelectable[Owner2T, T2, Any],
    field3: Attr[Any, Any, Owner3T, Any, T3]
    | ColumnRef[Owner3T, T3]
    | Aggregate[Owner3T, T3, Any]
    | Scalar[Owner3T, T3, Any]
    | DialectSelectable[Owner3T, T3, Any],
    field4: Attr[Any, Any, Owner4T, Any, T4]
    | ColumnRef[Owner4T, T4]
    | Aggregate[Owner4T, T4, Any]
    | Scalar[Owner4T, T4, Any]
    | DialectSelectable[Owner4T, T4, Any],
    field5: Attr[Any, Any, Owner5T, Any, T5]
    | ColumnRef[Owner5T, T5]
    | Aggregate[Owner5T, T5, Any]
    | Scalar[Owner5T, T5, Any]
    | DialectSelectable[Owner5T, T5, Any],
    field6: Attr[Any, Any, Owner6T, Any, T6]
    | ColumnRef[Owner6T, T6]
    | Aggregate[Owner6T, T6, Any]
    | Scalar[Owner6T, T6, Any]
    | DialectSelectable[Owner6T, T6, Any],
    field7: Attr[Any, Any, Owner7T, Any, T7]
    | ColumnRef[Owner7T, T7]
    | Aggregate[Owner7T, T7, Any]
    | Scalar[Owner7T, T7, Any]
    | DialectSelectable[Owner7T, T7, Any],
    /,
) -> SelectTupleQuery[
    Literal["sqlite"],
    Owner1T,
    Owner1T | Owner2T | Owner3T | Owner4T | Owner5T | Owner6T | Owner7T,
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
    Owner1T: Model[Any, Any],
    T1,
    Owner2T: Model[Any, Any],
    T2,
    Owner3T: Model[Any, Any],
    T3,
    Owner4T: Model[Any, Any],
    T4,
    Owner5T: Model[Any, Any],
    T5,
    Owner6T: Model[Any, Any],
    T6,
    Owner7T: Model[Any, Any],
    T7,
    Owner8T: Model[Any, Any],
    T8,
](
    field1: Attr[Any, Any, Owner1T, Any, T1]
    | ColumnRef[Owner1T, T1]
    | Aggregate[Owner1T, T1, Any]
    | DialectSelectable[Owner1T, T1, Any],
    field2: Attr[Any, Any, Owner2T, Any, T2]
    | ColumnRef[Owner2T, T2]
    | Aggregate[Owner2T, T2, Any]
    | Scalar[Owner2T, T2, Any]
    | DialectSelectable[Owner2T, T2, Any],
    field3: Attr[Any, Any, Owner3T, Any, T3]
    | ColumnRef[Owner3T, T3]
    | Aggregate[Owner3T, T3, Any]
    | Scalar[Owner3T, T3, Any]
    | DialectSelectable[Owner3T, T3, Any],
    field4: Attr[Any, Any, Owner4T, Any, T4]
    | ColumnRef[Owner4T, T4]
    | Aggregate[Owner4T, T4, Any]
    | Scalar[Owner4T, T4, Any]
    | DialectSelectable[Owner4T, T4, Any],
    field5: Attr[Any, Any, Owner5T, Any, T5]
    | ColumnRef[Owner5T, T5]
    | Aggregate[Owner5T, T5, Any]
    | Scalar[Owner5T, T5, Any]
    | DialectSelectable[Owner5T, T5, Any],
    field6: Attr[Any, Any, Owner6T, Any, T6]
    | ColumnRef[Owner6T, T6]
    | Aggregate[Owner6T, T6, Any]
    | Scalar[Owner6T, T6, Any]
    | DialectSelectable[Owner6T, T6, Any],
    field7: Attr[Any, Any, Owner7T, Any, T7]
    | ColumnRef[Owner7T, T7]
    | Aggregate[Owner7T, T7, Any]
    | Scalar[Owner7T, T7, Any]
    | DialectSelectable[Owner7T, T7, Any],
    field8: Attr[Any, Any, Owner8T, Any, T8]
    | ColumnRef[Owner8T, T8]
    | Aggregate[Owner8T, T8, Any]
    | Scalar[Owner8T, T8, Any]
    | DialectSelectable[Owner8T, T8, Any],
    /,
) -> SelectTupleQuery[
    Literal["sqlite"],
    Owner1T,
    Owner1T | Owner2T | Owner3T | Owner4T | Owner5T | Owner6T | Owner7T | Owner8T,
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


@overload
def insert[OwnerT: Model[Any, Any], ReadT: Table[Any]](
    row: InsertableModel[Literal["sqlite"], OwnerT, ReadT],
    /,
) -> InsertQuery[Literal["sqlite"], OwnerT, ReadT]: ...
@overload
def insert[OwnerT: Model[Any, Any], ReadT: Table[Any]](
    rows: Sequence[InsertableModel[Literal["sqlite"], OwnerT, ReadT]],
    /,
) -> InsertManyQuery[Literal["sqlite"], OwnerT, ReadT]: ...
def insert(row_or_rows: object, /) -> object:
    """Build a SQLite insert from a single pending model or a sequence of them.

    A single model compiles to one ``INSERT ... VALUES (...)``; a sequence
    compiles to one multi-row ``INSERT`` and is a no-op when empty. Executed
    plain, the insert returns ``None``. Call ``.returning()`` to get the Fetched
    model(s) SQLite produced -- generated ``INTEGER PRIMARY KEY`` rowids and
    server defaults -- read back through ``RETURNING``. Call ``.on_conflict``
    with ``DoUpdate`` or ``DoNothing`` for SQLite's atomic conflict handling.
    """

    query = build_insert(row_or_rows)
    _require_sqlite_model(cast("Any", query).state.model())
    return query


def update[ModelT: Model[Any, Any], ReadT: Table[Any]](
    model: _SelectableModelClass[Literal["sqlite"], ModelT, ReadT], /
) -> UpdateQuery[Literal["sqlite"], ModelT, ReadT]:
    """Build a SQLite ``UPDATE`` for a table model.

    Executed, it returns the affected-row count. SQLite's ``rowcount`` counts
    every row the ``WHERE`` clause matched, so updating a row to its current
    value still increments the count. Chain ``.set(...)`` with assignments and
    ``.where(...)`` / ``.all()`` to scope the statement.
    """

    _require_sqlite_model(cast("type[Table[Any]]", model))
    return build_update(model)


def delete[ModelT: Model[Any, Any], ReadT: Table[Any]](
    model: _SelectableModelClass[Literal["sqlite"], ModelT, ReadT], /
) -> DeleteQuery[Literal["sqlite"], ModelT, ReadT]:
    """Build a SQLite ``DELETE`` for a table model.

    Executed, it returns the number of rows deleted (SQLite's ``rowcount``).
    Chain ``.where(...)`` to scope the statement or ``.all()`` to delete every
    row.
    """

    _require_sqlite_model(cast("type[Table[Any]]", model))
    return build_delete(model)
