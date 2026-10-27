"""Bounded native id-generation agreement, not counter or session certification."""

from snekql.errors import SchemaError
from snekql.experimental._migration_mariadb import mariadb_declared_auto_increment
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


def validate_column_identity(column: ColumnState, backend: Backend) -> None:
    """Admit native standalone terms independently of final ownership/operation permission."""
    if backend == "mariadb":
        mariadb_declared_auto_increment(column.definition)


def validate_identity_claims(table: TableState, backend: Backend) -> None:
    """Bind managed native presence/absence; extra SQL does not create generator claims."""
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
            if mariadb_declared_auto_increment(
                column.definition
            ) != mariadb_declared_auto_increment(
                declarations[ascii_lower(column.name)]
            ):
                msg = f"construction AUTO_INCREMENT differs for {table.name!r}.{column.name!r}"
                raise PackageError(msg)
    except SchemaError as error:
        msg = f"cannot verify construction AUTO_INCREMENT: {error}"
        raise PackageError(msg) from error
