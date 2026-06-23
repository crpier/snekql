"""SQLite write verbs whose docstrings describe SQLite's own write semantics.

The Query Builder in ``snekql.query`` is dialect-blind, so the neutral
``insert`` / ``update`` / ``delete`` carry only a backend-agnostic description.
These thin wrappers delegate to that builder unchanged but document what SQLite
actually does on execution -- most notably how SQLite reports affected rows --
so the ``snekql.sqlite`` namespace surfaces SQLite-specific guidance.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, overload

from snekql.model import Table
from snekql.query import (
    DeleteQuery,
    InsertableModel,
    InsertManyQuery,
    InsertQuery,
    UpdateQuery,
    build_insert,
)
from snekql.query import (
    delete as build_delete,
)
from snekql.query import (
    update as build_update,
)


@overload
def insert[OwnerT: Table[Any], ReadT: Table[Any]](
    row: InsertableModel[OwnerT, ReadT],
    /,
) -> InsertQuery[OwnerT, ReadT]: ...
@overload
def insert[OwnerT: Table[Any], ReadT: Table[Any]](
    rows: Sequence[InsertableModel[OwnerT, ReadT]],
    /,
) -> InsertManyQuery[OwnerT, ReadT]: ...
def insert(row_or_rows: object, /) -> object:
    """Build a SQLite insert from a single pending model or a sequence of them.

    A single model compiles to one ``INSERT ... VALUES (...)``; a sequence
    compiles to one multi-row ``INSERT`` and is a no-op when empty. Executed
    plain, the insert returns ``None``. Call ``.returning()`` to get the Fetched
    model(s) SQLite produced -- generated ``INTEGER PRIMARY KEY`` rowids and
    server defaults -- read back through ``RETURNING``.
    """

    return build_insert(row_or_rows)


def update[ModelT: Table[Any]](model: type[ModelT], /) -> UpdateQuery[ModelT]:
    """Build a SQLite ``UPDATE`` for a table model.

    Executed, it returns the affected-row count. SQLite's ``rowcount`` counts
    every row the ``WHERE`` clause matched, so updating a row to its current
    value still increments the count. Chain ``.set(...)`` with assignments and
    ``.where(...)`` / ``.all()`` to scope the statement.
    """

    return build_update(model)


def delete[ModelT: Table[Any]](model: type[ModelT], /) -> DeleteQuery[ModelT]:
    """Build a SQLite ``DELETE`` for a table model.

    Executed, it returns the number of rows deleted (SQLite's ``rowcount``).
    Chain ``.where(...)`` to scope the statement or ``.all()`` to delete every
    row.
    """

    return build_delete(model)
