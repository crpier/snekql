"""Structured API inputs retain their declared meaning at runtime."""

from traceback import format_exception
from typing import Any, ClassVar
from warnings import catch_warnings, simplefilter

from pydantic import Json
from snektest import Param, assert_not_in, assert_raises, test

from snekql import mariadb, sqlite


@test(
    [
        Param[object](value=True, name="boolean"),
        Param[object](value=8.0, name="float"),
        Param[object](value="8); DROP TABLE entries; --", name="sql-text"),
    ],
    mark="fast",
)
def decimal_precision_requires_native_integer(precision: object) -> None:
    """DDL dimensions reject noninteger inputs with a declaration error."""
    with assert_raises(mariadb.ModelDeclarationError):
        mariadb.Decimal(precision, 0)  # ty: ignore[invalid-argument-type]


@test(
    [
        Param[object](value=True, name="boolean"),
        Param[object](value=0.0, name="float"),
        Param[object](value="0); DROP TABLE entries; --", name="sql-text"),
    ],
    mark="fast",
)
def decimal_scale_requires_native_integer(scale: object) -> None:
    """The second DDL dimension has the same integer-only boundary."""
    with assert_raises(mariadb.ModelDeclarationError):
        mariadb.Decimal(8, scale)  # ty: ignore[invalid-argument-type]


@test(mark="fast")
def config_validation_traceback_omits_input() -> None:
    """Invalid policy values do not appear in ordinary exception rendering."""
    private_input = "configuration_secret"
    with assert_raises(sqlite.DatabaseRuntimeError) as caught:
        sqlite.Config(
            database=":memory:",
            parameter_visibility=private_input,  # ty: ignore[invalid-argument-type]
        )

    assert_not_in(private_input, "".join(format_exception(caught.exception)))


@test(mark="fast")
def invalid_comparison_encoding_omits_values() -> None:
    """A mistyped bound value cannot escape through serializer warnings or errors."""

    class Entry[S = sqlite.Pending](sqlite.Model[S]):
        __row_type__: ClassVar[sqlite.ReadType[Entry[sqlite.Row]]]
        number: sqlite.Col[int] = sqlite.Integer()

    private_input = "comparison_value_secret"
    query = sqlite.select(Entry).where(
        Entry.number.eq(private_input)  # ty: ignore[invalid-argument-type]
    )
    with catch_warnings(record=True) as captured:
        simplefilter("always")
        with assert_raises(sqlite.ModelValidationError) as caught:
            query.compile()

    rendered = "".join(format_exception(caught.exception))
    rendered += "".join(str(warning.message) for warning in captured)
    assert_not_in(private_input, rendered)


@test(mark="fast")
def invalid_json_comparison_encoding_omits_values() -> None:
    """JSON serialization rejects mismatched payloads without forwarding values."""

    class Entry[S = sqlite.Pending](sqlite.Model[S]):
        __row_type__: ClassVar[sqlite.ReadType[Entry[sqlite.Row]]]
        payload: sqlite.Col[Json[list[int]]] = sqlite.Text()

    private_input = "json_comparison_secret"
    query = sqlite.select(Entry).where(
        Entry.payload.eq([private_input])  # ty: ignore[invalid-argument-type]
    )
    with catch_warnings(record=True) as captured:
        simplefilter("always")
        with assert_raises(sqlite.ModelValidationError) as caught:
            query.compile()

    rendered = "".join(format_exception(caught.exception))
    rendered += "".join(str(warning.message) for warning in captured)
    assert_not_in(private_input, rendered)


@test(
    [Param("sqlite", name="sqlite"), Param("mariadb", name="mariadb")],
    [Param("on_delete", name="delete"), Param("on_update", name="update")],
    [Param("direct", name="direct"), Param("deferred", name="deferred")],
    mark="fast",
)
def scalar_foreign_key_rejects_sql_action(
    backend: str,
    option: str,
    target_kind: str,
) -> None:
    """Referential actions are bounded selectors, never caller-provided DDL."""
    namespace: Any = sqlite if backend == "sqlite" else mariadb

    class Parent[S = namespace.Pending](namespace.Model[S]):
        __row_type__: ClassVar[namespace.ReadType[Parent[namespace.Row]]]
        number: namespace.Col[int] = namespace.Integer(primary_key=True)

    target = (lambda: Parent.number) if target_kind == "deferred" else Parent.number
    with assert_raises(sqlite.ModelDeclarationError):
        namespace.ForeignKey(
            target, default=0, **{option: "CASCADE); DROP TABLE parent; --"}
        )


@test(mark="fast")
def pending_validation_traceback_omits_input() -> None:
    """A mistyped model value stays out of package validation diagnostics."""

    class Entry[S = sqlite.Pending](sqlite.Model[S]):
        __row_type__: ClassVar[sqlite.ReadType[Entry[sqlite.Row]]]
        number: sqlite.Col[int] = sqlite.Integer()

    private_input = "pending_value_secret"
    with assert_raises(sqlite.ModelValidationError) as caught:
        Entry(number=private_input)  # ty: ignore[invalid-argument-type]

    assert_not_in(private_input, "".join(format_exception(caught.exception)))
