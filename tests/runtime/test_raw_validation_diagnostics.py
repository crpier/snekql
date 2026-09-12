"""Raw validation failures expose fixed diagnostics, not user data."""

import asyncio
import logging
from dataclasses import make_dataclass
from io import StringIO
from threading import Event
from traceback import format_exception
from typing import Annotated
from warnings import catch_warnings, simplefilter, warn

from pydantic import BeforeValidator, GetCoreSchemaHandler, PlainValidator, with_config
from pydantic_core import CoreSchema, PydanticCustomError
from snektest import Param, assert_eq, assert_raises, load_fixture, test

from snekql import sqlite
from snekql.model import BackendFamily
from tests.runtime.test_raw_execution import provide_raw_case


@test(
    [
        Param[BackendFamily](value="sqlite", name="sqlite"),
        Param[BackendFamily](value="mariadb", name="mariadb"),
    ],
    [Param(value=kind, name=kind) for kind in ("ordinary", "custom")],
    mark="slow",
)
async def validator_exceptions_have_safe_rendering(
    backend: BackendFamily, kind: str
) -> None:
    """Ordinary exceptions and custom codes share the same diagnostic boundary."""

    case = await load_fixture(provide_raw_case(backend, visibility="values"))

    def reject(row: object) -> object:
        del row
        if kind == "ordinary":
            error = sqlite.DatabaseRuntimeError("exception_secret")
            error.add_note("note_secret")
            raise error
        code = "code_secret"
        raise PydanticCustomError(
            code, "message_secret {context}", {"context": "context_secret"}
        )

    statement = case.namespace.raw(
        "SELECT 'input_secret' AS column_secret",
        validate=Annotated[object, PlainValidator(reject)],
    )
    captured = StringIO()
    handler = logging.StreamHandler(captured)
    logger = logging.getLogger("snekql")
    logger.addHandler(handler)
    try:
        async with case.database.transaction() as transaction:
            with assert_raises(case.namespace.RawResultValidationError) as raised:
                await transaction.fetch_one(statement)
        error = raised.exception
        rendered = (
            captured.getvalue()
            + "".join(format_exception(error))
            + repr(error.details)
            + repr(statement)
        )
    finally:
        logger.removeHandler(handler)

    assert_eq(
        [(item.location, item.code) for item in error.details],
        [((), "custom_validation_error")],
    )
    for marker in (
        "exception_secret",
        "note_secret",
        "code_secret",
        "message_secret",
        "context_secret",
        "input_secret",
        "column_secret",
    ):
        assert_eq(marker in rendered, False)


@test(
    [
        Param[BackendFamily](value="sqlite", name="sqlite"),
        Param[BackendFamily](value="mariadb", name="mariadb"),
    ],
    [
        Param[object](value="key_secret", name="string"),
        Param[object](value=987654321, name="integer"),
    ],
    mark="slow",
)
async def input_derived_location_segments_are_redacted(
    backend: BackendFamily, key: object
) -> None:
    """Integer dictionary keys are no safer to expose than string keys."""

    case = await load_fixture(provide_raw_case(backend))

    def nested_input(row: object) -> dict[object, object]:
        del row
        return {key: "value_secret"}

    statement = case.namespace.raw(
        "SELECT 1 AS amount",
        validate=Annotated[dict[object, int], BeforeValidator(nested_input)],
    )
    async with case.database.transaction() as transaction:
        with assert_raises(case.namespace.RawResultValidationError) as raised:
            await transaction.fetch_one(statement)

    assert_eq(
        [(item.location, item.code) for item in raised.exception.details],
        [(("<redacted>",), "int_parsing")],
    )


@test(mark="fast")
def construction_failure_hides_contract_exception() -> None:
    """Schema hooks can fail without publishing their exceptions or notes."""

    class Contract:
        @classmethod
        def __get_pydantic_core_schema__(
            cls, source: object, handler: GetCoreSchemaHandler
        ) -> CoreSchema:
            del source, handler
            error = sqlite.DatabaseRuntimeError("construction_secret")
            error.add_note("note_secret")
            raise error

    with assert_raises(sqlite.QueryConstructionError) as raised:
        sqlite.raw("SQL", validate=Contract)

    rendered = "".join(format_exception(raised.exception))
    assert_eq("construction_secret" in rendered, False)
    assert_eq("note_secret" in rendered, False)


@test(
    [Param(value=kind, name=kind) for kind in ("cancel", "interrupt", "exit")],
    [Param(value=method, name=method) for method in ("fetch_one", "fetch_chunks")],
    mark="medium",
)
async def validator_control_flow_is_not_wrapped(kind: str, method: str) -> None:
    """Cancellation and process control must not become validation errors."""

    case = await load_fixture(provide_raw_case("sqlite"))
    exception = {
        "cancel": asyncio.CancelledError,
        "interrupt": KeyboardInterrupt,
        "exit": SystemExit,
    }[kind]

    def interrupt(row: object) -> object:
        del row
        raise exception

    statement = sqlite.raw(
        "SELECT 1 AS amount", validate=Annotated[object, PlainValidator(interrupt)]
    )
    with assert_raises(exception):
        async with case.database.transaction() as transaction:
            if method == "fetch_chunks":
                async with transaction.fetch_chunks(statement, size=1) as stream:
                    await anext(stream)
            else:
                await transaction.fetch_one(statement)


@test(mark="fast")
def schema_warnings_do_not_render_contract_objects() -> None:
    """Pydantic's permissive schema generation can warn with a contract repr."""

    class Annotation:
        def __repr__(self) -> str:
            return "contract_secret"

    contract = with_config(arbitrary_types_allowed=True)(
        make_dataclass("WarningContract", [("amount", Annotation())])
    )
    with catch_warnings(record=True) as captured:
        simplefilter("always")
        sqlite.raw("SELECT 1 AS amount", validate=contract)

    assert_eq(any("contract_secret" in str(event.message) for event in captured), False)


@test(mark="medium")
async def schema_warning_capture_does_not_affect_another_context() -> None:
    """A concurrently compiling contract cannot suppress another task's warning."""

    entered = Event()
    release = Event()

    class Contract:
        @classmethod
        def __get_pydantic_core_schema__(
            cls, source: object, handler: GetCoreSchemaHandler
        ) -> CoreSchema:
            del source
            entered.set()
            if not release.wait(timeout=5):
                msg = "schema coordination timed out"
                raise sqlite.DatabaseRuntimeError(msg)
            warn("contract_secret", UserWarning, stacklevel=1)
            return handler.generate_schema(dict[str, int])

    with catch_warnings(record=True) as captured:
        simplefilter("always")
        construction = asyncio.create_task(
            asyncio.to_thread(sqlite.raw, "SELECT 1", validate=Contract)
        )
        try:
            assert_eq(await asyncio.to_thread(entered.wait, 5), True)
            warn("unrelated_warning", UserWarning, stacklevel=1)
        finally:
            release.set()
            await construction

    assert_eq([str(event.message) for event in captured], ["unrelated_warning"])


@test(mark="medium")
async def validation_detail_formatting_cannot_emit_warnings() -> None:
    """Pydantic message formatting remains inside the diagnostic warning scope."""

    case = await load_fixture(provide_raw_case("sqlite"))

    class ContextValue:
        def __str__(self) -> str:
            warn("context_secret", UserWarning, stacklevel=1)
            return "context_secret"

    def reject(row: object) -> object:
        del row
        code = "custom_code"
        raise PydanticCustomError(
            code, "invalid {context}", {"context": ContextValue()}
        )

    statement = sqlite.raw(
        "SELECT 1", validate=Annotated[object, PlainValidator(reject)]
    )
    with catch_warnings(record=True) as captured:
        simplefilter("always")
        async with case.database.transaction() as transaction:
            with assert_raises(sqlite.RawResultValidationError):
                await transaction.fetch_one(statement)

    assert_eq(captured, [])
