"""MariaDB write verbs whose docstrings describe MariaDB write semantics.

The Query Builder in ``snekql.query`` is dialect-blind, so the neutral
``insert`` / ``update`` / ``delete`` carry only a backend-agnostic description.
These thin wrappers delegate to that builder unchanged but document what MariaDB
actually does on execution -- most notably how aiomysql reports affected rows --
so the ``snekql.mariadb`` namespace surfaces MariaDB-specific guidance.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Literal, Never, cast, overload

from pydantic import BaseModel

from snekql._aliases import TableAlias, _AliasOwner, build_alias
from snekql._cte import _Cte, _CteOwner, build_cte_alias
from snekql._dialect_expr import DialectSelectable
from snekql._query_readiness import _IncompleteQuery
from snekql._query_state import selectable_owner_model
from snekql.errors import QueryConstructionError
from snekql.expressions import Aggregate, ColumnRef, Scalar, _Scalar
from snekql.mariadb.model import Model
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
from snekql.query import (
    update as build_update,
)
from snekql.storage import Attr

type ReadQuery[Scope, Result] = _ExecutableSelect[
    Literal["mariadb"], Scope, Scope, Result
]
"""An executable read retaining the tables its expressions reference."""
type OptionalRead[Scope, Result] = _ExecutableOptionalSelect[
    Literal["mariadb"], Scope, Scope, Result
]
"""A read whose missing row is distinct from every possible row value."""
type ClosedRead[Result] = ReadQuery[Never, Result]
"""An execution/inspection view checked by ready, without fluent composition."""
type ClosedOptional[Result] = OptionalRead[Never, Result]
"""A checked read that still permits fetch_one_or_none."""
type PendingInput[Owner: Model[Pending], Result: Table[Row]] = InsertableModel[
    Literal["mariadb"], Owner, Result
]
"""Pending insertion input retaining its exact model owner and Row result."""


def _require_mariadb_model(model: type[Table[Any]] | None) -> None:
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
    if received != "mariadb":
        msg = (
            "backend mismatch: expected mariadb model, "
            f"received {received} model {model.__name__}"
        )
        raise QueryConstructionError(msg)


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
    _check_read_query(query, backend="mariadb")
    # Native compilation checked the references; Never records their closure.
    # This annotation exposes execution and inspection, not more composition.
    return cast("ClosedRead[Result]", query)


@overload
def select[SourceT: Table[Any], ResultT: BaseModel, RoleT, NonNullableOwnerT](
    source: _Cte[Literal["mariadb"], SourceT, ResultT, RoleT, NonNullableOwnerT],
    /,
) -> SelectModelQuery[
    Literal["mariadb"], _CteOwner[Literal["mariadb"], SourceT, RoleT], ResultT
]: ...


# BEGIN GENERATED BACKEND SELECT OVERLOADS
@overload
def select[
    OwnerT: Model[Any]
    | _AliasOwner[Literal["mariadb"], Any, Any]
    | _CteOwner[Literal["mariadb"], Any, Any],
    ReadT: Table[Any],
](
    model: _SelectableModelClass[Literal["mariadb"], OwnerT, ReadT],
    /,
) -> SelectModelQuery[Literal["mariadb"], OwnerT, ReadT]: ...


@overload
def select[
    OwnerT: Model[Any]
    | _AliasOwner[Literal["mariadb"], Any, Any]
    | _CteOwner[Literal["mariadb"], Any, Any],
    ValueT,
    CompareT,
](
    field: Attr[Any, Any, OwnerT, Any, ValueT, Any, CompareT]
    | Aggregate[OwnerT, ValueT, CompareT]
    | DialectSelectable[OwnerT, ValueT, CompareT],
    /,
) -> SelectValueQuery[Literal["mariadb"], OwnerT, OwnerT, ValueT, CompareT]: ...


@overload
def select[
    OwnerT: Model[Any]
    | _AliasOwner[Literal["mariadb"], Any, Any]
    | _CteOwner[Literal["mariadb"], Any, Any],
    ValueT,
](
    field: ColumnRef[OwnerT, ValueT],
    /,
) -> SelectValueQuery[Literal["mariadb"], OwnerT, OwnerT, ValueT, Any]: ...


@overload
def select[
    Owner1T: Model[Any]
    | _AliasOwner[Literal["mariadb"], Any, Any]
    | _CteOwner[Literal["mariadb"], Any, Any],
    T1,
    Owner2T: Model[Any]
    | _AliasOwner[Literal["mariadb"], Any, Any]
    | _CteOwner[Literal["mariadb"], Any, Any],
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
) -> SelectTupleQuery[
    Literal["mariadb"], Owner1T, Owner1T | Owner2T, _IncompleteQuery, T1, T2
]: ...


@overload
def select[
    Owner1T: Model[Any]
    | _AliasOwner[Literal["mariadb"], Any, Any]
    | _CteOwner[Literal["mariadb"], Any, Any],
    T1,
    Owner2T: Model[Any]
    | _AliasOwner[Literal["mariadb"], Any, Any]
    | _CteOwner[Literal["mariadb"], Any, Any],
    T2,
    Owner3T: Model[Any]
    | _AliasOwner[Literal["mariadb"], Any, Any]
    | _CteOwner[Literal["mariadb"], Any, Any],
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
    Literal["mariadb"],
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
    | _AliasOwner[Literal["mariadb"], Any, Any]
    | _CteOwner[Literal["mariadb"], Any, Any],
    T1,
    Owner2T: Model[Any]
    | _AliasOwner[Literal["mariadb"], Any, Any]
    | _CteOwner[Literal["mariadb"], Any, Any],
    T2,
    Owner3T: Model[Any]
    | _AliasOwner[Literal["mariadb"], Any, Any]
    | _CteOwner[Literal["mariadb"], Any, Any],
    T3,
    Owner4T: Model[Any]
    | _AliasOwner[Literal["mariadb"], Any, Any]
    | _CteOwner[Literal["mariadb"], Any, Any],
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
    Literal["mariadb"],
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
    | _AliasOwner[Literal["mariadb"], Any, Any]
    | _CteOwner[Literal["mariadb"], Any, Any],
    T1,
    Owner2T: Model[Any]
    | _AliasOwner[Literal["mariadb"], Any, Any]
    | _CteOwner[Literal["mariadb"], Any, Any],
    T2,
    Owner3T: Model[Any]
    | _AliasOwner[Literal["mariadb"], Any, Any]
    | _CteOwner[Literal["mariadb"], Any, Any],
    T3,
    Owner4T: Model[Any]
    | _AliasOwner[Literal["mariadb"], Any, Any]
    | _CteOwner[Literal["mariadb"], Any, Any],
    T4,
    Owner5T: Model[Any]
    | _AliasOwner[Literal["mariadb"], Any, Any]
    | _CteOwner[Literal["mariadb"], Any, Any],
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
    Literal["mariadb"],
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
    | _AliasOwner[Literal["mariadb"], Any, Any]
    | _CteOwner[Literal["mariadb"], Any, Any],
    T1,
    Owner2T: Model[Any]
    | _AliasOwner[Literal["mariadb"], Any, Any]
    | _CteOwner[Literal["mariadb"], Any, Any],
    T2,
    Owner3T: Model[Any]
    | _AliasOwner[Literal["mariadb"], Any, Any]
    | _CteOwner[Literal["mariadb"], Any, Any],
    T3,
    Owner4T: Model[Any]
    | _AliasOwner[Literal["mariadb"], Any, Any]
    | _CteOwner[Literal["mariadb"], Any, Any],
    T4,
    Owner5T: Model[Any]
    | _AliasOwner[Literal["mariadb"], Any, Any]
    | _CteOwner[Literal["mariadb"], Any, Any],
    T5,
    Owner6T: Model[Any]
    | _AliasOwner[Literal["mariadb"], Any, Any]
    | _CteOwner[Literal["mariadb"], Any, Any],
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
    Literal["mariadb"],
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
    | _AliasOwner[Literal["mariadb"], Any, Any]
    | _CteOwner[Literal["mariadb"], Any, Any],
    T1,
    Owner2T: Model[Any]
    | _AliasOwner[Literal["mariadb"], Any, Any]
    | _CteOwner[Literal["mariadb"], Any, Any],
    T2,
    Owner3T: Model[Any]
    | _AliasOwner[Literal["mariadb"], Any, Any]
    | _CteOwner[Literal["mariadb"], Any, Any],
    T3,
    Owner4T: Model[Any]
    | _AliasOwner[Literal["mariadb"], Any, Any]
    | _CteOwner[Literal["mariadb"], Any, Any],
    T4,
    Owner5T: Model[Any]
    | _AliasOwner[Literal["mariadb"], Any, Any]
    | _CteOwner[Literal["mariadb"], Any, Any],
    T5,
    Owner6T: Model[Any]
    | _AliasOwner[Literal["mariadb"], Any, Any]
    | _CteOwner[Literal["mariadb"], Any, Any],
    T6,
    Owner7T: Model[Any]
    | _AliasOwner[Literal["mariadb"], Any, Any]
    | _CteOwner[Literal["mariadb"], Any, Any],
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
    Literal["mariadb"],
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
    | _AliasOwner[Literal["mariadb"], Any, Any]
    | _CteOwner[Literal["mariadb"], Any, Any],
    T1,
    Owner2T: Model[Any]
    | _AliasOwner[Literal["mariadb"], Any, Any]
    | _CteOwner[Literal["mariadb"], Any, Any],
    T2,
    Owner3T: Model[Any]
    | _AliasOwner[Literal["mariadb"], Any, Any]
    | _CteOwner[Literal["mariadb"], Any, Any],
    T3,
    Owner4T: Model[Any]
    | _AliasOwner[Literal["mariadb"], Any, Any]
    | _CteOwner[Literal["mariadb"], Any, Any],
    T4,
    Owner5T: Model[Any]
    | _AliasOwner[Literal["mariadb"], Any, Any]
    | _CteOwner[Literal["mariadb"], Any, Any],
    T5,
    Owner6T: Model[Any]
    | _AliasOwner[Literal["mariadb"], Any, Any]
    | _CteOwner[Literal["mariadb"], Any, Any],
    T6,
    Owner7T: Model[Any]
    | _AliasOwner[Literal["mariadb"], Any, Any]
    | _CteOwner[Literal["mariadb"], Any, Any],
    T7,
    Owner8T: Model[Any]
    | _AliasOwner[Literal["mariadb"], Any, Any]
    | _CteOwner[Literal["mariadb"], Any, Any],
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
    Literal["mariadb"],
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
    """Build a MariaDB select whose private carrier retains MariaDB identity."""

    query = build_select(*args)
    state = cast("Any", query).state
    _require_mariadb_model(state.model)
    for field in state.fields:
        if isinstance(field, _Scalar):
            _require_mariadb_model(field.subquery.state.model)
        else:
            _require_mariadb_model(selectable_owner_model(field))
    return query


def insert[OwnerT: Model[Any], ReadT: Table[Any]](
    row: InsertableModel[Literal["mariadb"], OwnerT, ReadT], /
) -> InsertQuery[Literal["mariadb"], OwnerT, ReadT]:
    """Insert one MariaDB Pending value; use insert_many(Model, rows) for batches.

    `insert(user)` executes to `None`. `insert(user).returning()` returns the
    Row produced by the database, including generated values. Conflict handling
    remains available through `on_conflict` with `DoUpdate` or `DoNothing`.
    RETURNING includes generated AUTO_INCREMENT keys and server defaults.
    Conflict actions use MariaDB ON DUPLICATE KEY UPDATE handling.
    """
    query = build_insert(row)
    _require_mariadb_model(query.state.model())
    return query


def insert_many[OwnerT: Model[Pending], ReadT: Table[Row]](
    model: _DeclarationSource[Literal["mariadb"], OwnerT, ReadT],
    rows: Sequence[OwnerT],
    /,
) -> InsertManyQuery[Literal["mariadb"], OwnerT, ReadT]:
    """Insert Pending values into one declared model, including an empty batch.

    `await transaction.execute(insert_many(User, users))` returns `None`.
    `.returning()` uses MariaDB's existing INSERT RETURNING support and yields
    a list of declared Row values. Empty batches execute no SQL. Conflict
    handling and codecs use the same path as single-row `insert(user)`.
    """
    query = build_insert_many(model, rows)
    # The builder has checked that this is a bare model declaration.
    _require_mariadb_model(cast("type[Table[Any]]", model))
    return query


def update[ModelT: Model[Any], ReadT: Table[Any]](
    model: _DeclarationSource[Literal["mariadb"], ModelT, ReadT], /
) -> UpdateQuery[Literal["mariadb"], ModelT, ReadT]:
    """Build a MariaDB ``UPDATE`` for a table model.

    Executed, it returns the affected-row count. aiomysql uses MariaDB's default
    row count mode (without ``CLIENT_FOUND_ROWS``), so ``UPDATE`` counts only
    rows whose values actually changed; setting a column to its current value
    does not increment the count. Chain ``.set(...)`` with assignments and
    ``.where(...)`` / ``.all()`` to scope the statement.
    """

    _require_mariadb_model(cast("type[Table[Any]]", model))
    return build_update(model)


def delete[ModelT: Model[Any], ReadT: Table[Any]](
    model: _DeclarationSource[Literal["mariadb"], ModelT, ReadT], /
) -> DeleteQuery[Literal["mariadb"], ModelT, ReadT]:
    """Build a MariaDB ``DELETE`` for a table model.

    Executed, it returns the number of rows deleted (MariaDB's ``rowcount``).
    Chain ``.where(...)`` to scope the statement or ``.all()`` to delete every
    row.
    """

    _require_mariadb_model(cast("type[Table[Any]]", model))
    return build_delete(model)


@overload
def alias[
    SourceT: Table[Any],
    ResultT: BaseModel,
    RoleT,
    NonNullableOwnerT,
    AliasRoleT,
](
    model: _Cte[Literal["mariadb"], SourceT, ResultT, RoleT, NonNullableOwnerT],
    role: type[AliasRoleT],
    *,
    name: str,
) -> _Cte[Literal["mariadb"], SourceT, ResultT, AliasRoleT, NonNullableOwnerT]: ...


@overload
def alias[OwnerT: Model[Any], ReadT: Table[Any], RoleT](
    model: _DeclarationSource[Literal["mariadb"], OwnerT, ReadT],
    role: type[RoleT],
    *,
    name: str,
) -> TableAlias[Literal["mariadb"], OwnerT, ReadT, RoleT]: ...


def alias(
    model: object, role: type[object], *, name: str
) -> TableAlias[Any, Any, Any, Any] | _Cte[Any, Any, Any, Any, Any]:
    """Give a table or CTE a typed role without changing its fetched result type."""
    if isinstance(model, _Cte):
        return build_cte_alias(model, role, name=name, backend="mariadb")
    return build_alias(model, role, name=name, backend="mariadb")
