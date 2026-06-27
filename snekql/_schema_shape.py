"""Backend-neutral semantic schema shapes and drift diffing.

Schema verification compares the *shape* a model expects against the *shape* a
live table actually has, rather than comparing rendered DDL strings. Each
backend reads its own catalog (SQLite ``PRAGMA``, MariaDB ``INFORMATION_SCHEMA``)
into the same :class:`TableShape`, so a table legitimately produced or evolved
by migrations is recognized as matching whenever it is semantically equal,
regardless of cosmetic DDL differences (identifier quoting, whitespace, column
or index ordering).

When shapes differ, :func:`diff_table_shapes` reports each divergence naming the
specific table, column, index, or foreign key so a migration author can act on
it.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ColumnShape:
    """Semantic column shape compared name-for-name, independent of position."""

    name: str
    storage_type: str
    nullable: bool
    primary_key: bool
    auto_increment: bool
    has_server_default: bool
    collation: str | None


@dataclass(frozen=True)
class IndexShape:
    """Semantic index shape compared by name, columns, and uniqueness."""

    name: str
    column_names: tuple[str, ...]
    unique: bool


@dataclass(frozen=True)
class ForeignKeyShape:
    """Semantic foreign-key shape compared by local column, target, and actions.

    ``on_delete``/``on_update`` hold the normalized referential action; an FK with
    no declared action carries ``"NO ACTION"``, matching what the catalog reports,
    so a missing action and an explicit ``NO ACTION`` compare equal.
    """

    column_name: str
    target_table: str
    target_column: str
    on_delete: str = "NO ACTION"
    on_update: str = "NO ACTION"


@dataclass(frozen=True)
class TableShape:
    """A table's full semantic shape, as expected by a model or read live.

    ``storage_options`` carries backend-specific table-level facts compared as a
    set of tokens (SQLite ``STRICT``; MariaDB ``ENGINE=InnoDB``), so each backend
    keeps its own integrity requirements without a bespoke comparison path.
    """

    table_name: str
    columns: tuple[ColumnShape, ...]
    indexes: tuple[IndexShape, ...]
    foreign_keys: tuple[ForeignKeyShape, ...]
    storage_options: tuple[str, ...]


def _diff_storage_options(
    expected: TableShape,
    actual: TableShape,
    issues: list[str],
) -> None:
    if expected.storage_options != actual.storage_options:
        message = (
            "table storage options differ: "
            f"expected {list(expected.storage_options)}, "
            f"found {list(actual.storage_options)}"
        )
        issues.append(message)


def _column_differences(expected: ColumnShape, actual: ColumnShape) -> list[str]:
    differences: list[str] = []
    if expected.storage_type != actual.storage_type:
        differences.append(
            f"type expected {expected.storage_type!r}, found {actual.storage_type!r}"
        )
    if expected.nullable != actual.nullable:
        differences.append(
            f"nullable expected {expected.nullable}, found {actual.nullable}"
        )
    if expected.primary_key != actual.primary_key:
        differences.append(
            f"primary key expected {expected.primary_key}, found {actual.primary_key}"
        )
    if expected.auto_increment != actual.auto_increment:
        auto_increment_message = (
            "auto-increment expected "
            f"{expected.auto_increment}, found {actual.auto_increment}"
        )
        differences.append(auto_increment_message)
    if expected.has_server_default != actual.has_server_default:
        default_message = (
            "server default expected "
            f"{expected.has_server_default}, found {actual.has_server_default}"
        )
        differences.append(default_message)
    if expected.collation != actual.collation:
        differences.append(
            f"collation expected {expected.collation!r}, found {actual.collation!r}"
        )
    return differences


def _diff_columns(
    expected: TableShape,
    actual: TableShape,
    issues: list[str],
) -> None:
    expected_by_name = {column.name: column for column in expected.columns}
    actual_by_name = {column.name: column for column in actual.columns}
    issues.extend(
        f"column {name!r} is missing from the database table"
        for name in expected_by_name
        if name not in actual_by_name
    )
    issues.extend(
        f"column {name!r} exists in the database but not in the model"
        for name in actual_by_name
        if name not in expected_by_name
    )
    for name, expected_column in expected_by_name.items():
        actual_column = actual_by_name.get(name)
        if actual_column is None:
            continue
        differences = _column_differences(expected_column, actual_column)
        if differences:
            issues.append(f"column {name!r} differs: {', '.join(differences)}")


def _index_differences(expected: IndexShape, actual: IndexShape) -> list[str]:
    differences: list[str] = []
    if expected.column_names != actual.column_names:
        columns_message = (
            f"columns expected {list(expected.column_names)}, "
            f"found {list(actual.column_names)}"
        )
        differences.append(columns_message)
    if expected.unique != actual.unique:
        differences.append(
            f"uniqueness expected {expected.unique}, found {actual.unique}"
        )
    return differences


def _diff_indexes(
    expected: TableShape,
    actual: TableShape,
    issues: list[str],
) -> None:
    expected_by_name = {index.name: index for index in expected.indexes}
    actual_by_name = {index.name: index for index in actual.indexes}
    issues.extend(
        f"index {name!r} is missing from the database table"
        for name in expected_by_name
        if name not in actual_by_name
    )
    issues.extend(
        f"index {name!r} exists in the database but not in the model"
        for name in actual_by_name
        if name not in expected_by_name
    )
    for name, expected_index in expected_by_name.items():
        actual_index = actual_by_name.get(name)
        if actual_index is None:
            continue
        differences = _index_differences(expected_index, actual_index)
        if differences:
            issues.append(f"index {name!r} differs: {', '.join(differences)}")


def _describe_foreign_key(foreign_key: ForeignKeyShape) -> str:
    description = f"{foreign_key.target_table}.{foreign_key.target_column}"
    if foreign_key.on_delete != "NO ACTION":
        description += f" ON DELETE {foreign_key.on_delete}"
    if foreign_key.on_update != "NO ACTION":
        description += f" ON UPDATE {foreign_key.on_update}"
    return description


def _foreign_key_facts(foreign_key: ForeignKeyShape) -> tuple[str, str, str, str]:
    return (
        foreign_key.target_table,
        foreign_key.target_column,
        foreign_key.on_delete,
        foreign_key.on_update,
    )


def _diff_foreign_keys(
    expected: TableShape,
    actual: TableShape,
    issues: list[str],
) -> None:
    expected_by_column = {fk.column_name: fk for fk in expected.foreign_keys}
    actual_by_column = {fk.column_name: fk for fk in actual.foreign_keys}
    for column_name, expected_fk in expected_by_column.items():
        actual_fk = actual_by_column.get(column_name)
        if actual_fk is None:
            missing_message = (
                f"foreign key on column {column_name!r} -> "
                f"{_describe_foreign_key(expected_fk)} is missing from the "
                "database table"
            )
            issues.append(missing_message)
        elif _foreign_key_facts(actual_fk) != _foreign_key_facts(expected_fk):
            differs_message = (
                f"foreign key on column {column_name!r} differs: "
                f"expected -> {_describe_foreign_key(expected_fk)}, "
                f"found -> {_describe_foreign_key(actual_fk)}"
            )
            issues.append(differs_message)
    for column_name, actual_fk in actual_by_column.items():
        if column_name not in expected_by_column:
            unexpected_message = (
                f"foreign key on column {column_name!r} -> "
                f"{_describe_foreign_key(actual_fk)} exists in the database but "
                "not in the model"
            )
            issues.append(unexpected_message)


def diff_table_shapes(expected: TableShape, actual: TableShape) -> tuple[str, ...]:
    """Report each way ``actual`` diverges from ``expected``, or ``()`` if equal.

    Comparison is semantic: columns and indexes match by name regardless of
    declaration order, and only the facts snekql controls are compared.
    """

    issues: list[str] = []
    _diff_storage_options(expected, actual, issues)
    _diff_columns(expected, actual, issues)
    _diff_indexes(expected, actual, issues)
    _diff_foreign_keys(expected, actual, issues)
    return tuple(issues)
