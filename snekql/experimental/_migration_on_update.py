"""Bounded native ON UPDATE construction agreement, not clock or session proof."""

from snekql.errors import SchemaError
from snekql.experimental._migration_mariadb import mariadb_declared_on_update
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


def validate_column_on_update(column: ColumnState, backend: Backend) -> None:
    """Admit native standalone terms independently of final ownership/operation permission."""
    if backend == "mariadb":
        mariadb_declared_on_update(column.definition)


def validate_on_update_claims(table: TableState, backend: Backend) -> None:
    """Bind automatic update presence/precision without granting ownership to extra SQL."""
    if backend != "mariadb":
        return
    try:
        declarations = {
            ascii_lower(name): part
            for part in split_table(table.sql, mysql=True)[1]
            if tokens(part, mysql=True)
            and (name := column_name(part, mysql=True)) is not None
        }
        for column in table.columns:
            if mariadb_declared_on_update(
                column.definition
            ) != mariadb_declared_on_update(declarations[ascii_lower(column.name)]):
                msg = (
                    f"construction ON UPDATE differs for {table.name!r}.{column.name!r}"
                )
                raise PackageError(msg)
    except SchemaError as error:
        msg = f"cannot verify construction ON UPDATE: {error}"
        raise PackageError(msg) from error
