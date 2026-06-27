"""Semantic schema shape diffing tests independent of any backend."""

from __future__ import annotations

from snektest import assert_eq, assert_true, test

from snekql._schema_shape import (
    ColumnShape,
    ForeignKeyShape,
    IndexShape,
    TableShape,
    diff_table_shapes,
)


def _column(  # noqa: PLR0913
    name: str,
    *,
    storage_type: str = "TEXT",
    nullable: bool = True,
    primary_key: bool = False,
    auto_increment: bool = False,
    has_server_default: bool = False,
    collation: str | None = None,
) -> ColumnShape:
    return ColumnShape(
        name=name,
        storage_type=storage_type,
        nullable=nullable,
        primary_key=primary_key,
        auto_increment=auto_increment,
        has_server_default=has_server_default,
        collation=collation,
    )


def _table(
    *,
    columns: tuple[ColumnShape, ...] = (),
    indexes: tuple[IndexShape, ...] = (),
    foreign_keys: tuple[ForeignKeyShape, ...] = (),
    storage_options: tuple[str, ...] = ("STRICT",),
) -> TableShape:
    return TableShape(
        table_name="user",
        columns=columns,
        indexes=indexes,
        foreign_keys=foreign_keys,
        storage_options=storage_options,
    )


@test(mark="fast")
async def identical_shapes_report_no_drift() -> None:
    """A live shape equal to the expected shape produces no drift issues."""

    shape = _table(
        columns=(_column("id", primary_key=True), _column("email", nullable=False)),
        indexes=(
            IndexShape(name="ux_user_email", column_names=("email",), unique=True),
        ),
    )

    assert_eq(diff_table_shapes(shape, shape), ())


@test(mark="fast")
async def column_order_is_not_drift() -> None:
    """Columns match by name, so a different declaration order is not drift."""

    expected = _table(columns=(_column("id"), _column("email")))
    actual = _table(columns=(_column("email"), _column("id")))

    assert_eq(diff_table_shapes(expected, actual), ())


@test(mark="fast")
async def missing_column_is_named() -> None:
    """A column expected by the model but absent in the table is named precisely."""

    expected = _table(columns=(_column("id"), _column("email")))
    actual = _table(columns=(_column("id"),))

    issues = diff_table_shapes(expected, actual)

    assert_eq(issues, ("column 'email' is missing from the database table",))


@test(mark="fast")
async def unexpected_column_is_named() -> None:
    """A column present in the table but not the model is named precisely."""

    expected = _table(columns=(_column("id"),))
    actual = _table(columns=(_column("id"), _column("legacy")))

    issues = diff_table_shapes(expected, actual)

    assert_eq(
        issues,
        ("column 'legacy' exists in the database but not in the model",),
    )


@test(mark="fast")
async def mismatched_column_attribute_is_named() -> None:
    """A column whose nullability diverges reports the column and the attribute."""

    expected = _table(columns=(_column("email", nullable=False),))
    actual = _table(columns=(_column("email", nullable=True),))

    issues = diff_table_shapes(expected, actual)

    assert_eq(
        issues,
        ("column 'email' differs: nullable expected False, found True",),
    )


@test(mark="fast")
async def index_drift_is_named() -> None:
    """A missing index and a uniqueness change each name the index."""

    expected = _table(
        indexes=(
            IndexShape(name="ix_user_status", column_names=("status",), unique=True),
            IndexShape(name="ix_user_tenant", column_names=("tenant",), unique=False),
        ),
    )
    actual = _table(
        indexes=(
            IndexShape(name="ix_user_status", column_names=("status",), unique=False),
        ),
    )

    issues = diff_table_shapes(expected, actual)

    assert_true("index 'ix_user_tenant' is missing from the database table" in issues)
    assert_true(
        "index 'ix_user_status' differs: uniqueness expected True, found False"
        in issues
    )


@test(mark="fast")
async def missing_foreign_key_is_named() -> None:
    """A foreign key the model expects but the table lacks names the column."""

    expected = _table(
        foreign_keys=(
            ForeignKeyShape(
                column_name="user_id", target_table="user", target_column="id"
            ),
        ),
    )
    actual = _table(foreign_keys=())

    issues = diff_table_shapes(expected, actual)

    expected_message = (
        "foreign key on column 'user_id' -> user.id is missing from the database table"
    )
    assert_eq(issues, (expected_message,))


@test(mark="fast")
async def foreign_key_referential_action_drift_is_reported() -> None:
    """A live FK whose ON DELETE action differs from the model is named as drift."""

    expected = _table(
        foreign_keys=(
            ForeignKeyShape(
                column_name="user_id",
                target_table="user",
                target_column="id",
                on_delete="CASCADE",
            ),
        ),
    )
    actual = _table(
        foreign_keys=(
            ForeignKeyShape(
                column_name="user_id",
                target_table="user",
                target_column="id",
                on_delete="NO ACTION",
            ),
        ),
    )

    issues = diff_table_shapes(expected, actual)

    assert_true(
        any("user_id" in issue and "CASCADE" in issue for issue in issues),
    )


@test(mark="fast")
async def matching_foreign_key_actions_report_no_drift() -> None:
    """Equal actions on both sides (default NO ACTION) produce no FK drift."""

    shape = _table(
        foreign_keys=(
            ForeignKeyShape(
                column_name="user_id", target_table="user", target_column="id"
            ),
        ),
    )

    assert_eq(diff_table_shapes(shape, shape), ())


@test(mark="fast")
async def storage_option_drift_is_reported() -> None:
    """A live table missing a required storage option (e.g. STRICT) is drift."""

    expected = _table(storage_options=("STRICT",))
    actual = _table(storage_options=())

    issues = diff_table_shapes(expected, actual)

    assert_eq(
        issues,
        ("table storage options differ: expected ['STRICT'], found []",),
    )
