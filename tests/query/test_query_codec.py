"""Dialect query codec seam tests.

``DialectQueryCodec`` bundles compile and materialize behind one object built
from the dialect registry, so the Backend Runtime Adapters carry a codec
attribute instead of four pass-through methods.
"""

from __future__ import annotations

from typing import ClassVar

from snektest import assert_eq, assert_raises, test

from snekql import mariadb, sqlite
from snekql._query_codec import DialectQueryCodec
from snekql._query_dialect import query_dialect_for_backend
from snekql.errors import QueryCompilationError
from snekql.sqlite import Pending, Row


@test(mark="fast")
def sqlite_codec_compiles_select_with_sqlite_dialect() -> None:
    """The SQLite codec renders `?` placeholders and double-quoted names."""

    class Widget[S = Pending](sqlite.Model[S]):
        """Model compiled through the SQLite codec."""

        __row_type__: ClassVar[sqlite.ReadType[Widget[Row]]]

        label: Widget.Col[str] = sqlite.Text(nullable=False)

    codec = DialectQueryCodec.for_backend("sqlite")

    select_sql, select_params = codec.compile_select_sql(
        sqlite.select(Widget.label).where(Widget.label.eq("a")),
    )

    assert_eq(select_sql, 'SELECT "label" FROM "widget" WHERE ("label" = ?)')
    assert_eq(select_params, ("a",))


@test(mark="fast")
def mariadb_codec_compiles_select_with_mariadb_dialect() -> None:
    """The MariaDB codec renders `%s` placeholders and backtick-quoted names."""

    class Widget[S = Pending](mariadb.Model[S]):
        """Model compiled through the MariaDB codec."""

        __row_type__: ClassVar[mariadb.ReadType[Widget[Row]]]

        label: Widget.Col[str] = mariadb.Text(nullable=False)

    codec = DialectQueryCodec.for_backend("mariadb")

    select_sql, select_params = codec.compile_select_sql(
        mariadb.select(Widget.label).where(Widget.label.eq("a")),
    )

    assert_eq(select_sql, "SELECT `label` FROM `widget` WHERE (`label` = %s)")
    assert_eq(select_params, ("a",))


@test(mark="fast")
def sqlite_codec_compiles_write_with_sqlite_dialect() -> None:
    """The SQLite codec compiles writes with the SQLite dialect."""

    class Widget[S = Pending](sqlite.Model[S]):
        """Model inserted through the SQLite codec."""

        __row_type__: ClassVar[sqlite.ReadType[Widget[Row]]]

        label: Widget.Col[str] = sqlite.Text(nullable=False)

    codec = DialectQueryCodec.for_backend("sqlite")

    insert_sql, insert_params = codec.compile_write_sql(
        sqlite.insert(Widget(label="a")),
    )

    assert_eq(insert_sql, 'INSERT INTO "widget" ("label") VALUES (?)')
    assert_eq(insert_params, ("a",))


@test(mark="fast")
def mariadb_codec_compiles_write_with_mariadb_dialect() -> None:
    """The MariaDB codec compiles writes with MariaDB value encoding."""

    class Flag[S = Pending](mariadb.Model[S]):
        """Model whose boolean encoding differs from Python's."""

        __row_type__: ClassVar[mariadb.ReadType[Flag[Row]]]

        enabled: Flag.Col[bool] = mariadb.Boolean(nullable=False)

    codec = DialectQueryCodec.for_backend("mariadb")

    insert_sql, insert_params = codec.compile_write_sql(
        mariadb.insert(Flag(enabled=True)),
    )

    assert_eq(insert_sql, "INSERT INTO `flag` (`enabled`) VALUES (%s)")
    assert_eq(insert_params, (1,))


@test(mark="fast")
def sqlite_codec_materializes_select_rows_with_backend_decoding() -> None:
    """The SQLite codec decodes select rows with SQLite column codecs."""

    class Widget[S = Pending](sqlite.Model[S]):
        """Model materialized through the SQLite codec."""

        __row_type__: ClassVar[sqlite.ReadType[Widget[Row]]]

        label: Widget.Col[str] = sqlite.Text(nullable=False)

    codec = DialectQueryCodec.for_backend("sqlite")

    value = codec.materialize_select_row(
        sqlite.select(Widget.label).all(),
        ("a",),
    )

    assert_eq(value, "a")


@test(mark="fast")
def mariadb_codec_materializes_write_rows_with_backend_decoding() -> None:
    """The MariaDB codec decodes RETURNING rows with MariaDB column codecs."""

    class Flag[S = Pending](mariadb.Model[S]):
        """Model whose boolean decodes from MariaDB's integer wire value."""

        __row_type__: ClassVar[mariadb.ReadType[Flag[Row]]]

        enabled: Flag.Col[bool] = mariadb.Boolean(nullable=False)

    codec = DialectQueryCodec.for_backend("mariadb")

    values = codec.materialize_write_rows(
        mariadb.insert(Flag(enabled=True)).returning(Flag.enabled),
        [(1,)],
    )

    assert_eq(values, [True])


@test(mark="fast")
def codec_for_unregistered_backend_raises_compilation_error() -> None:
    """Resolving a codec for a family with no registered dialect fails."""

    with assert_raises(QueryCompilationError):
        _ = DialectQueryCodec.for_backend("postgres")  # ty: ignore[invalid-argument-type] - exercise dynamic backend rejection


@test(mark="fast")
def importing_a_backend_namespace_registers_its_query_dialect() -> None:
    """Namespace import is the registration side effect the codec relies on."""

    assert_eq(query_dialect_for_backend("sqlite").placeholder, "?")
    assert_eq(query_dialect_for_backend("mariadb").placeholder, "%s")
