"""MariaDB write verbs whose docstrings describe MariaDB write semantics.

The Query Builder in ``snekql.query`` is dialect-blind, so the neutral
``insert`` / ``update`` / ``delete`` carry only a backend-agnostic description.
These thin wrappers delegate to that builder unchanged but document what MariaDB
actually does on execution -- most notably how aiomysql reports affected rows --
so the ``snekql.mariadb`` namespace surfaces MariaDB-specific guidance.
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
    """Build a MariaDB insert from a single pending model or a sequence of them.

    A single model compiles to one ``INSERT ... VALUES (...)``; a sequence
    compiles to one multi-row ``INSERT`` and is a no-op when empty. Executed
    plain, the insert returns ``None``. Call ``.returning()`` to get the Fetched
    model(s) MariaDB produced -- generated ``AUTO_INCREMENT`` keys and server
    defaults -- read back through ``RETURNING``.
    """

    return build_insert(row_or_rows)


def update[ModelT: Table[Any]](model: type[ModelT], /) -> UpdateQuery[ModelT]:
    """Build a MariaDB ``UPDATE`` for a table model.

    Executed, it returns the affected-row count. aiomysql uses MariaDB's default
    row count mode (without ``CLIENT_FOUND_ROWS``), so ``UPDATE`` counts only
    rows whose values actually changed; setting a column to its current value
    does not increment the count. Chain ``.set(...)`` with assignments and
    ``.where(...)`` / ``.all()`` to scope the statement.
    """

    return build_update(model)


def delete[ModelT: Table[Any]](model: type[ModelT], /) -> DeleteQuery[ModelT]:
    """Build a MariaDB ``DELETE`` for a table model.

    Executed, it returns the number of rows deleted (MariaDB's ``rowcount``).
    Chain ``.where(...)`` to scope the statement or ``.all()`` to delete every
    row.
    """

    return build_delete(model)
