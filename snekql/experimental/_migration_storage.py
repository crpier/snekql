"""Bounded definition/construction storage agreement, not codec certification."""

from snekql.errors import SchemaError
from snekql.experimental._migration_mariadb import mariadb_construction_storage_matches
from snekql.experimental._migration_sql import (
    ascii_lower,
    column_name,
    split_table,
    tokens,
)
from snekql.experimental.migrations import (
    Backend,
    ColumnState,
    PackageError,
    TableState,
)

_SQLITE_TYPES = frozenset({"integer", "int", "real", "text", "blob", "any"})
_SQLITE_TYPE_TOKENS = 2
_SQLITE_CLAUSES = frozenset(
    {
        "constraint",
        "primary",
        "not",
        "null",
        "unique",
        "check",
        "default",
        "collate",
        "references",
        "generated",
        "as",
    }
)


def _sqlite_storage(definition: str) -> str:
    """Keep INTEGER distinct from INT; affinity cannot prove rowid/STRICT identity."""
    stream = tokens(definition)
    if (
        len(stream) < _SQLITE_TYPE_TOKENS
        or stream[1].kind != "word"
        or ascii_lower(stream[1].value) not in _SQLITE_TYPES
        or (
            len(stream) > _SQLITE_TYPE_TOKENS
            and (
                stream[2].kind != "word"
                or ascii_lower(stream[2].value) not in _SQLITE_CLAUSES
            )
        )
    ):
        msg = "unsupported SQLite construction storage; explicit adapter required"
        raise PackageError(msg)
    return ascii_lower(stream[1].value)


def validate_column_storage(column: ColumnState, backend: Backend) -> None:
    """Admit standalone ADD/default type declarations before intermediate projection."""
    if backend == "sqlite":
        _sqlite_storage(column.definition)
    else:
        mariadb_construction_storage_matches(column.definition, column.definition)


def validate_storage_claims(table: TableState, backend: Backend) -> None:
    """Compare positive managed declarations without inferring claims from extras."""
    mysql = backend == "mariadb"
    try:
        definitions = {
            ascii_lower(name): part
            for part in split_table(table.sql, mysql=mysql)[1]
            if tokens(part, mysql=mysql)
            and (name := column_name(part, mysql=mysql)) is not None
        }
        for column in table.columns:
            actual = definitions[ascii_lower(column.name)]
            matches = (
                mariadb_construction_storage_matches(column.definition, actual)
                if mysql
                else _sqlite_storage(column.definition) == _sqlite_storage(actual)
            )
            if not matches:
                msg = f"construction storage differs for {table.name!r}.{column.name!r}"
                raise PackageError(msg)
    except SchemaError as error:
        msg = f"cannot verify construction storage: {error}"
        raise PackageError(msg) from error
