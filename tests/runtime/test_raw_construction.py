"""Backend-owned raw declarations and their public inspection boundary."""

from typing import Any

from snektest import Param, assert_eq, assert_not_in, assert_raises, test

from snekql import sqlite

dynamic_raw: Any = sqlite.raw


@test(mark="fast")
def sql_inspection_preserves_literal_text() -> None:
    """Construction leaves whitespace, comments, and delimiters untouched."""

    statement = sqlite.raw("  SELECT '100%'; -- untouched\n")

    assert_eq(statement.sql, "  SELECT '100%'; -- untouched\n")


@test(mark="fast")
def sql_rejects_non_string_without_rendering() -> None:
    """Dynamic declarations receive package-owned construction errors."""

    with assert_raises(sqlite.QueryConstructionError):
        dynamic_raw(object())


@test(
    [Param(value="mapping", name="mapping"), Param(value="tuple", name="tuple")],
    mark="fast",
)
def statement_rendering_omits_secrets(mode: str) -> None:
    """Neither diagnostic representation is an accidental SQL inspection API."""

    statement = dynamic_raw(
        "SELECT 'sql_secret'", params={"key_secret": "value_secret"}, row_mode=mode
    )

    for marker in ("sql_secret", "key_secret", "value_secret"):
        assert_not_in(marker, repr(statement))
        assert_not_in(marker, str(statement))


@test(
    [
        Param[object](value=value, name=str(index))
        for index, value in enumerate(("bad", 0, None, [], b"tuple"))
    ],
    mark="fast",
)
def row_mode_rejects_invalid_declaration(mode: object) -> None:
    """Only the two literal string modes are valid, regardless of consumption."""

    with assert_raises(sqlite.QueryConstructionError):
        dynamic_raw("SELECT 1", row_mode=mode)


@test(
    [
        Param[object](value=value, name=str(index))
        for index, value in enumerate(
            (
                "secret",
                b"secret",
                bytearray(b"secret"),
                memoryview(b"secret"),
                {1},
                iter([1]),
                {1: "secret"},
            )
        )
    ],
    mark="fast",
)
def parameters_reject_unsupported_containers(params: object) -> None:
    """Raw accepts only string-keyed mappings and non-string sequences."""

    with assert_raises(sqlite.QueryConstructionError):
        dynamic_raw("SELECT 1", params=params)


@test(mark="fast")
def validation_contract_is_explicitly_unavailable() -> None:
    """An intermediate unvalidated factory never silently ignores a contract."""

    with assert_raises(sqlite.QueryConstructionError):
        dynamic_raw("SELECT 1", validate=int)


@test(
    [Param(value=name, name=name) for name in ("sql", "backend", "row_mode")],
    mark="fast",
)
def statement_fields_cannot_be_reassigned(name: str) -> None:
    """Execution policy and parameter membership are frozen after construction."""

    statement = sqlite.raw("SELECT 1", params={})

    with assert_raises(AttributeError):
        setattr(statement, name, "replacement")


@test(mark="fast")
def rejected_parameter_keys_are_never_rendered() -> None:
    """A malformed key cannot leak through its user-defined representation."""

    class SecretKey:
        def __repr__(self) -> str:
            msg = "key representation must not be evaluated"
            raise AssertionError(msg)

    with assert_raises(sqlite.QueryConstructionError):
        dynamic_raw("SELECT 1", params={SecretKey(): 1})
