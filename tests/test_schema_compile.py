"""Tests for the backend-neutral schema DDL/shape compiler seam."""

from __future__ import annotations

from snektest import assert_eq, test

from snekql._schema_compile import (
    compile_create_index_sql,
    compile_create_table_sql,
    compile_foreign_key_constraint,
    expected_table_shape,
)
from snekql._schema_dialect import SchemaDialect
from snekql._schema_plan import PlannedColumn, PlannedModel, build_schema_plan
from snekql._schema_shape import ColumnShape, ForeignKeyShape, IndexShape, TableShape
from snekql.sqlite import (
    PENDING_GENERATION,
    Fetched,
    ForeignKey,
    Integer,
    Model,
    Pending,
    Text,
)


class _Author[S = Pending](Model[S, "_Author[Fetched]"]):
    """Referenced table anchoring the foreign-key constraint."""

    __tablename__ = "author"

    id: _Author.GenCol[int] = Integer(
        primary_key=True, auto_increment=True, default=PENDING_GENERATION
    )
    email: _Author.Col[str] = Text(nullable=False, unique=True)


class _Book[S = Pending](Model[S, "_Book[Fetched]"]):
    """Table with a unique column index and an enforced foreign key."""

    __tablename__ = "book"

    id: _Book.GenCol[int] = Integer(
        primary_key=True, auto_increment=True, default=PENDING_GENERATION
    )
    isbn: _Book.Col[str] = Text(nullable=False, unique=True)
    author_id: _Book.FKCol[_Author, int] = ForeignKey(_Author.id)


def _planned(model_cls: type) -> PlannedModel:
    plan = build_schema_plan([_Author, _Book])
    return next(p for p in plan.models if p.model is model_cls)


def _fake_column_definition(planned_column: PlannedColumn) -> str:
    return f"<col:{planned_column.name}>"


def _fake_column_shape(planned_column: PlannedColumn) -> ColumnShape:
    return ColumnShape(
        name=planned_column.name,
        storage_type="FAKE",
        nullable=True,
        primary_key=False,
        auto_increment=False,
        has_server_default=False,
        collation=None,
    )


def _dialect(*, verifies_foreign_keys: bool) -> SchemaDialect:
    return SchemaDialect(
        quote_identifier=lambda name: f'"{name}"',
        compile_column_definition=_fake_column_definition,
        expected_column_shape=_fake_column_shape,
        table_suffix="MYSUFFIX",
        verifies_foreign_keys=verifies_foreign_keys,
    )


@test()
def create_table_delegates_columns_appends_fks_and_suffix() -> None:
    """CREATE TABLE delegates columns, appends FK constraints, ends with suffix."""

    sql = compile_create_table_sql(
        _planned(_Book), _dialect(verifies_foreign_keys=True)
    )

    expected_sql = (
        'CREATE TABLE "book" (<col:id>, <col:isbn>, <col:author_id>, '
        'FOREIGN KEY ("author_id") REFERENCES "author" ("id")) MYSUFFIX'
    )
    assert_eq(sql, expected_sql)


@test()
def foreign_key_constraint_is_rendered_with_quoting() -> None:
    """A planned foreign key renders a quoted REFERENCES constraint."""

    planned = _planned(_Book)
    constraint = compile_foreign_key_constraint(
        planned.foreign_keys[0], _dialect(verifies_foreign_keys=True)
    )

    assert_eq(constraint, 'FOREIGN KEY ("author_id") REFERENCES "author" ("id")')


@test()
def create_index_renders_unique_columns_and_quoting() -> None:
    """A unique column index renders quoted UNIQUE INDEX SQL."""

    planned = _planned(_Book)
    index = next(index for index in planned.indexes if index.name == "ux_book_isbn")

    sql = compile_create_index_sql("book", index, _dialect(verifies_foreign_keys=True))

    assert_eq(sql, 'CREATE UNIQUE INDEX "ux_book_isbn" ON "book" ("isbn")')


@test()
def expected_shape_includes_foreign_keys_when_verified() -> None:
    """The expected shape carries FK shapes only when the dialect verifies them."""

    shape = expected_table_shape(_planned(_Book), _dialect(verifies_foreign_keys=True))

    assert_eq(
        shape,
        TableShape(
            table_name="book",
            columns=(
                _fake_column_shape(PlannedColumn(column=Integer(), name="id")),
                _fake_column_shape(PlannedColumn(column=Text(), name="isbn")),
                _fake_column_shape(PlannedColumn(column=Integer(), name="author_id")),
            ),
            indexes=(
                IndexShape(name="ux_book_isbn", column_names=("isbn",), unique=True),
            ),
            foreign_keys=(
                ForeignKeyShape(
                    column_name="author_id",
                    target_table="author",
                    target_column="id",
                ),
            ),
            storage_options=("MYSUFFIX",),
        ),
    )


@test()
def expected_shape_omits_foreign_keys_when_not_verified() -> None:
    """A dialect that does not verify foreign keys yields an empty FK tuple."""

    shape = expected_table_shape(_planned(_Book), _dialect(verifies_foreign_keys=False))

    assert_eq(shape.foreign_keys, ())
