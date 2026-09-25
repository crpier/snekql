"""Throwaway SQLite native-query reuse, with explicit phantom-owner translations.

The public dual models remain authoritative. A private native counterpart already
exists in the storage adapter. This experiment types that counterpart's query
owner and translates native model results back into the declared dual rows.
The `table`/`column` calls expose the translation for inspection, not as a proposed
replacement for ordinary Row.field syntax.
"""

from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from typing import Any, Generic, Literal, TypeVar, cast, overload

from snekql import sqlite
from snekql.model import Table
from snekql.query import (
    InsertManyQuery,
    InsertQuery,
    _ExecutableOptionalSelect,
    _ExecutableSelect,
)
from snekql.storage import Attr, FKAttr

from scratchpad.dual_backends.core import Column, ForeignColumn
from scratchpad.dual_backends.core import Table as TableSource
from scratchpad.dual_finalization.interface import Record, Schema
from scratchpad.dual_pairing.sqlite import Paired
from scratchpad.dual_pairing.sqlite import insert as paired_insert
from scratchpad.paired_situations.dual_sqlite import Row as OriginalRow


class Row(Table[sqlite.Fetched], OriginalRow, Record):
    """Satisfy native result bounds without adopting native model construction."""


Result = TypeVar("Result", bound=Row)


class Owner(sqlite.Model[sqlite.Pending, Result], Generic[Result]):  # noqa: UP046 - Explicit invariance; PEP 695 infers covariance here.
    """Typing-only native owner, invariant in the corresponding public row."""


_rows: dict[type[object], type[Row]] = {}
"""Study-local mapping from finalized native model identities to public rows."""


def _materialize(value: object) -> object:
    row = _rows.get(type(value))
    if row is not None:
        return row(**{name: getattr(value, name) for name in row.fields})
    if isinstance(value, list):
        return [_materialize(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_materialize(item) for item in value)
    return value


def table[Result: Row](
    row: type[TableSource[Literal["sqlite"], Result]],
) -> type[Owner[Result]]:
    """Bind one declaration; preserve public row identity through native queries."""
    if not isinstance(row, type) or not issubclass(row, Row):
        raise sqlite.ModelDeclarationError("Query a complete dual row class")
    native = Schema(row).native(row)
    _rows[native] = row
    # Owner is a phantom for this exact bound native class, never instantiated.
    # Transaction below replaces its materialized values with the public row.
    return cast("type[Owner[Result]]", native)


@overload
def column[Result: Row, Target: Row, Value](
    source: ForeignColumn[Literal["sqlite"], Result, Target, Value | None],
) -> FKAttr[
    Table[sqlite.Pending],
    Table[sqlite.Fetched],
    Owner[Result],
    Value | None,
    Value | None,
    Owner[Target],
    Value | None,
    Value,
]: ...
@overload
def column[Result: Row, Target: Row, Value](
    source: ForeignColumn[Literal["sqlite"], Result, Target, Value],
) -> FKAttr[
    Table[sqlite.Pending],
    Table[sqlite.Fetched],
    Owner[Result],
    Value,
    Value,
    Owner[Target],
    Value,
    Value,
]: ...
@overload
def column[Result: Row, Value](
    source: Column[Literal["sqlite"], Result, Value | None],
) -> Attr[
    Table[sqlite.Pending],
    Table[sqlite.Fetched],
    Owner[Result],
    Value | None,
    Value | None,
    Value | None,
    Value,
]: ...
@overload
def column[Result: Row, Value](
    source: Column[Literal["sqlite"], Result, Value],
) -> Attr[
    Table[sqlite.Pending],
    Table[sqlite.Fetched],
    Owner[Result],
    Value,
    Value,
    Value,
    Value,
]: ...
def column(source: Any) -> Any:
    """Translate field ownership only; native expressions retain their full contract."""
    if not isinstance(source, Column) or source.family != "sqlite":
        raise sqlite.QueryConstructionError("Column belongs to another Backend Family")
    return getattr(table(source.owner), source.name)


def insert[Result: Row](
    pending: Paired[Result],
) -> InsertQuery[Literal["sqlite"], Owner[Result], Result]:
    """Reuse implicit pairing and insertion validation before translating ownership."""
    insertion = paired_insert(pending)
    table(insertion.source.model)
    # The validated pair fixes both native table and the dual result decoder.
    return cast(
        "InsertQuery[Literal['sqlite'], Owner[Result], Result]", insertion._query()
    )


def insert_many[Result: Row](
    rows: Sequence[Paired[Result]],
) -> InsertManyQuery[Literal["sqlite"], Owner[Result], Result]:
    """Native batching keeps homogeneous-table validation and result cardinality."""
    values: list[Any] = []
    for row in rows:
        insertion = paired_insert(row)
        model = table(insertion.source.model)
        # The native storage class validates prepared input; public callers keep Row.
        values.append(model(**insertion.values))
    return cast(
        "InsertManyQuery[Literal['sqlite'], Owner[Result], Result]",
        sqlite.insert(values),
    )


class Transaction:
    """Reuse native execution; decode declared row objects at this explicit seam."""

    def __init__(self, transaction: sqlite.Transaction) -> None:
        self.native: sqlite.Transaction = transaction

    @overload
    async def fetch_all[Scope, Result](
        self,
        query: _ExecutableSelect[Literal["sqlite"], Scope, Scope, Result],
        *,
        validate: Literal[True] = True,
    ) -> list[Result]: ...
    @overload
    async def fetch_all[Scope, Result](
        self,
        query: _ExecutableSelect[Literal["sqlite"], Scope, Scope, Result],
        *,
        validate: bool,
    ) -> list[object]: ...
    async def fetch_all[Scope](
        self,
        query: _ExecutableSelect[Literal["sqlite"], Scope, Scope, Any],
        *,
        validate: bool = True,
    ) -> list[Any]:
        values = await self.native.fetch_all(query, validate=validate)
        # Unchecked native results must not regain typed-row validation here.
        return cast("list[Any]", _materialize(values)) if validate else values

    @overload
    async def execute[Result](
        self, command: sqlite.Write[Result], *, validate: Literal[True] = True
    ) -> Result: ...
    @overload
    async def execute[Result](
        self, command: sqlite.Write[Result], *, validate: bool
    ) -> object: ...
    async def execute(
        self, command: sqlite.Write[Any], *, validate: bool = True
    ) -> object:
        values = await self.native.execute(command, validate=validate)
        return _materialize(values) if validate else values

    @overload
    async def fetch_one[Scope, Result](
        self,
        query: _ExecutableSelect[Literal["sqlite"], Scope, Scope, Result],
        *,
        validate: Literal[True] = True,
    ) -> Result: ...
    @overload
    async def fetch_one[Scope, Result](
        self,
        query: _ExecutableSelect[Literal["sqlite"], Scope, Scope, Result],
        *,
        validate: bool,
    ) -> object: ...
    async def fetch_one[Scope](
        self,
        query: _ExecutableSelect[Literal["sqlite"], Scope, Scope, Any],
        *,
        validate: bool = True,
    ) -> object:
        value = await self.native.fetch_one(query, validate=validate)
        return _materialize(value) if validate else value

    @overload
    async def fetch_one_or_none[Scope, Result](
        self,
        query: _ExecutableOptionalSelect[Literal["sqlite"], Scope, Scope, Result],
        *,
        validate: Literal[True] = True,
    ) -> Result | None: ...
    @overload
    async def fetch_one_or_none[Scope, Result](
        self,
        query: _ExecutableOptionalSelect[Literal["sqlite"], Scope, Scope, Result],
        *,
        validate: bool,
    ) -> object: ...
    async def fetch_one_or_none[Scope](
        self,
        query: _ExecutableOptionalSelect[Literal["sqlite"], Scope, Scope, Any],
        *,
        validate: bool = True,
    ) -> object:
        value = await self.native.fetch_one_or_none(query, validate=validate)
        return _materialize(value) if validate else value

    @asynccontextmanager
    async def fetch_chunks[Scope, Result](
        self,
        query: _ExecutableSelect[Literal["sqlite"], Scope, Scope, Result],
        *,
        size: int,
    ) -> AsyncIterator[AsyncIterator[list[Result]]]:
        async with self.native.fetch_chunks(query, size=size) as chunks:

            async def decoded() -> AsyncIterator[list[Result]]:
                async for batch in chunks:
                    yield cast("list[Result]", _materialize(batch))

            yield decoded()
