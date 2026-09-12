"""Statement-owned result contracts through real backend Transactions."""

from dataclasses import dataclass
from traceback import format_exception
from typing import Annotated, ForwardRef

from pydantic import (
    BaseModel,
    BeforeValidator,
    Field,
    GetCoreSchemaHandler,
    PlainValidator,
    StrictBool,
)
from pydantic_core import CoreSchema
from snektest import Param, assert_eq, assert_raises, load_fixture, test
from typing_extensions import TypedDict

from snekql.model import BackendFamily
from tests.runtime.test_raw_execution import provide_raw_case


@test(
    [
        Param[BackendFamily](value="sqlite", name="sqlite"),
        Param[BackendFamily](value="mariadb", name="mariadb"),
    ],
    [
        Param(value=method, name=method)
        for method in ("fetch_all", "fetch_one", "fetch_one_or_none", "fetch_chunks")
    ],
    mark="slow",
)
async def dataclass_rows_use_pydantic_coercion(
    backend: BackendFamily, method: str
) -> None:
    """The declared dataclass receives mapped columns with normal coercion."""

    case = await load_fixture(provide_raw_case(backend))

    @dataclass
    class Total:
        amount: int

    statement = case.namespace.raw("SELECT '42' AS amount", validate=Total)
    async with case.database.transaction() as transaction:
        if method == "fetch_chunks":
            async with transaction.fetch_chunks(statement, size=1) as stream:
                rows = [row async for chunk in stream for row in chunk]
        else:
            rows = await getattr(transaction, method)(statement)

    assert_eq(
        rows,
        [Total(amount=42)]
        if method in ("fetch_all", "fetch_chunks")
        else Total(amount=42),
    )


@test(
    [
        Param[BackendFamily](value="sqlite", name="sqlite"),
        Param[BackendFamily](value="mariadb", name="mariadb"),
    ],
    [
        Param(value=method, name=method)
        for method in ("fetch_all", "fetch_one", "fetch_one_or_none", "fetch_chunks")
    ],
    mark="slow",
)
async def invalid_rows_expose_only_redacted_details(
    backend: BackendFamily, method: str
) -> None:
    """Built-in failures report a fixed code without the alias or bad input."""

    case = await load_fixture(provide_raw_case(backend))

    @dataclass
    class Total:
        amount: int

    statement = case.namespace.raw("SELECT 'value_secret' AS amount", validate=Total)
    async with case.database.transaction() as transaction:
        with assert_raises(case.namespace.RawResultValidationError) as raised:
            if method == "fetch_chunks":
                async with transaction.fetch_chunks(statement, size=1) as stream:
                    await anext(stream)
            else:
                await getattr(transaction, method)(statement)

    error = raised.exception
    assert_eq(error.operation, method)
    assert_eq(error.row_index, 0)
    assert_eq("value_secret" in "".join(format_exception(error)), False)
    assert_eq(
        [(detail.location, detail.code) for detail in error.details],
        [(("<redacted>",), "int_parsing")],
    )


@test(
    [
        Param[BackendFamily](value="sqlite", name="sqlite"),
        Param[BackendFamily](value="mariadb", name="mariadb"),
    ],
    [
        Param(value=method, name=method)
        for method in ("fetch_all", "fetch_one", "fetch_one_or_none", "fetch_chunks")
    ],
    mark="slow",
)
async def adapter_none_obeys_consumption(backend: BackendFamily, method: str) -> None:
    """Only optional-one reserves None exclusively for an absent row."""

    case = await load_fixture(provide_raw_case(backend))

    def discard_row(row: object) -> None:
        del row

    statement = case.namespace.raw(
        "SELECT 1 AS amount", validate=Annotated[object, PlainValidator(discard_row)]
    )
    async with case.database.transaction() as transaction:
        if method == "fetch_one_or_none":
            with assert_raises(case.namespace.RawResultValidationError) as raised:
                await transaction.fetch_one_or_none(statement)
            assert_eq(
                [(item.location, item.code) for item in raised.exception.details],
                [((), "none_result")],
            )
            return
        if method == "fetch_chunks":
            async with transaction.fetch_chunks(statement, size=1) as stream:
                observed = [row async for chunk in stream for row in chunk]
        else:
            observed = await getattr(transaction, method)(statement)

    assert_eq(observed, None if method == "fetch_one" else [None])


@test(
    [
        Param[BackendFamily](value="sqlite", name="sqlite"),
        Param[BackendFamily](value="mariadb", name="mariadb"),
    ],
    mark="slow",
)
async def model_policy_controls_mapping(backend: BackendFamily) -> None:
    """Aliases, defaults and ignored extras follow the model's own policy."""

    case = await load_fixture(provide_raw_case(backend))

    class Total(BaseModel):
        amount: int = Field(alias="wire_amount")
        label: str = "default"

    statement = case.namespace.raw(
        "SELECT '42' AS wire_amount, 7 AS unused", validate=Total
    )
    async with case.database.transaction() as transaction:
        row = await transaction.fetch_one(statement)

    assert_eq(row, Total(wire_amount=42))


@test(
    [
        Param[BackendFamily](value="sqlite", name="sqlite"),
        Param[BackendFamily](value="mariadb", name="mariadb"),
    ],
    mark="slow",
)
async def typed_dict_rows_preserve_nullability(backend: BackendFamily) -> None:
    """TypedDict declarations coerce values without losing nullable fields."""

    case = await load_fixture(provide_raw_case(backend))

    class Total(TypedDict):
        amount: int
        label: str | None

    statement = case.namespace.raw(
        "SELECT NULL AS label, '42' AS amount", validate=Total
    )
    async with case.database.transaction() as transaction:
        row = await transaction.fetch_one(statement)

    assert_eq(row, {"amount": 42, "label": None})


@test(
    [
        Param[BackendFamily](value="sqlite", name="sqlite"),
        Param[BackendFamily](value="mariadb", name="mariadb"),
    ],
    mark="slow",
)
async def tuple_contract_uses_column_order(backend: BackendFamily) -> None:
    """Duplicate aliases have no role in positional result validation."""

    case = await load_fixture(provide_raw_case(backend))
    statement = case.namespace.raw(
        "SELECT '42' AS repeated, NULL AS repeated",
        validate=tuple[int, str | None],
        row_mode="tuple",
    )
    async with case.database.transaction() as transaction:
        row = await transaction.fetch_one(statement)

    assert_eq(row, (42, None))


@test(
    [
        Param[BackendFamily](value="sqlite", name="sqlite"),
        Param[BackendFamily](value="mariadb", name="mariadb"),
    ],
    mark="slow",
)
async def tuple_contract_does_not_select_tuple_mode(backend: BackendFamily) -> None:
    """The default mapping stays a mapping even when the contract wants a tuple."""

    case = await load_fixture(provide_raw_case(backend))
    statement = case.namespace.raw("SELECT 42 AS amount", validate=tuple[int])
    async with case.database.transaction() as transaction:
        with assert_raises(case.namespace.RawResultValidationError) as raised:
            await transaction.fetch_one(statement)

    assert_eq(raised.exception.details[0].code, "tuple_type")


@test(
    [
        Param[BackendFamily](value="sqlite", name="sqlite"),
        Param[BackendFamily](value="mariadb", name="mariadb"),
    ],
    mark="slow",
)
async def adapter_schema_is_built_once(backend: BackendFamily) -> None:
    """A public schema hook observes construction once across repeated execution."""

    case = await load_fixture(provide_raw_case(backend))
    constructions: list[object] = []

    class Contract:
        @classmethod
        def __get_pydantic_core_schema__(
            cls, source: object, handler: GetCoreSchemaHandler
        ) -> CoreSchema:
            constructions.append(source)
            return handler.generate_schema(dict[str, int])

    statement = case.namespace.raw("SELECT '42' AS amount", validate=Contract)
    assert_eq(len(constructions), 1)
    for _ in range(2):
        async with case.database.transaction() as transaction:
            await transaction.fetch_all(statement)
            async with transaction.fetch_chunks(statement, size=1) as stream:
                await anext(stream)

    assert_eq(len(constructions), 1)


@test(
    [
        Param[BackendFamily](value="sqlite", name="sqlite"),
        Param[BackendFamily](value="mariadb", name="mariadb"),
    ],
    mark="slow",
)
async def execute_never_calls_row_validator(backend: BackendFamily) -> None:
    """A valid result declaration is unused for a no-column response."""

    case = await load_fixture(provide_raw_case(backend))
    calls: list[object] = []

    def observe(row: object) -> object:
        calls.append(row)
        return row

    statement = case.namespace.raw(
        "CREATE TEMPORARY TABLE raw_validated_command (amount INT)",
        validate=Annotated[object, PlainValidator(observe)],
    )
    async with case.database.transaction() as transaction:
        affected = await transaction.execute(statement)

    assert_eq(affected, -1 if backend == "sqlite" else 0)
    assert_eq(calls, [])


@test(
    [
        Param[BackendFamily](value="sqlite", name="sqlite"),
        Param[BackendFamily](value="mariadb", name="mariadb"),
    ],
    [
        Param(value=method, name=method)
        for method in ("fetch_all", "fetch_one", "fetch_one_or_none", "fetch_chunks")
    ],
    mark="slow",
)
async def empty_rows_do_not_call_validator(backend: BackendFamily, method: str) -> None:
    """An empty rowset cannot prove compatibility with a result contract."""

    case = await load_fixture(provide_raw_case(backend))
    calls: list[object] = []

    def observe(row: object) -> object:
        calls.append(row)
        return row

    statement = case.namespace.raw(
        "SELECT 1 AS amount WHERE 1=0",
        validate=Annotated[int, BeforeValidator(observe)],
    )
    async with case.database.transaction() as transaction:
        if method == "fetch_one":
            with assert_raises(case.namespace.NoResultError):
                await transaction.fetch_one(statement)
        elif method == "fetch_chunks":
            async with transaction.fetch_chunks(statement, size=1) as stream:
                assert_eq([chunk async for chunk in stream], [])
        else:
            rows = await getattr(transaction, method)(statement)
            assert_eq(rows, [] if method == "fetch_all" else None)

    assert_eq(calls, [])


@test(
    [
        Param[BackendFamily](value="sqlite", name="sqlite"),
        Param[BackendFamily](value="mariadb", name="mariadb"),
    ],
    [Param(value=method, name=method) for method in ("fetch_all", "fetch_chunks")],
    mark="slow",
)
async def late_validation_failure_resets_per_execution(
    backend: BackendFamily, method: str
) -> None:
    """Global row indices survive chunk boundaries, but not statement reuse."""

    case = await load_fixture(provide_raw_case(backend))

    @dataclass
    class Total:
        amount: int

    statement = case.namespace.raw(
        "SELECT amount FROM (SELECT 1 AS ordinal, '1' AS amount UNION ALL SELECT 2, '2' UNION ALL SELECT 3, '3' UNION ALL SELECT 4, 'bad' UNION ALL SELECT 5, '5') AS ordered_rows ORDER BY ordinal",
        validate=Total,
    )
    for _ in range(2):
        async with case.database.transaction() as transaction:
            if method == "fetch_chunks":
                async with transaction.fetch_chunks(statement, size=2) as stream:
                    assert_eq(await anext(stream), [Total(amount=1), Total(amount=2)])
                    with assert_raises(
                        case.namespace.RawResultValidationError
                    ) as raised:
                        await anext(stream)
                    with assert_raises(StopAsyncIteration):
                        await anext(stream)
            else:
                with assert_raises(case.namespace.RawResultValidationError) as raised:
                    await transaction.fetch_all(statement)
            assert_eq(
                (raised.exception.operation, raised.exception.row_index), (method, 3)
            )
            assert_eq(
                await transaction.fetch_one(case.namespace.raw("SELECT 42 AS amount")),
                {"amount": 42},
            )


@test(
    [
        Param[BackendFamily](value="sqlite", name="sqlite"),
        Param[BackendFamily](value="mariadb", name="mariadb"),
    ],
    [
        Param(value=scenario, name=scenario)
        for scenario in ("duplicates", "multiple", "execute_rows", "missing_metadata")
    ],
    mark="slow",
)
async def rejected_results_never_call_validator(
    backend: BackendFamily, scenario: str
) -> None:
    """Metadata and cardinality are decided before invoking user validators."""

    case = await load_fixture(provide_raw_case(backend))
    calls: list[object] = []

    def observe(row: object) -> object:
        calls.append(row)
        return row

    sql = {
        "duplicates": "SELECT 1 AS amount, 2 AS amount UNION ALL SELECT 3, 4",
        "multiple": "SELECT 1 AS amount UNION ALL SELECT 2",
        "execute_rows": "SELECT 1 AS amount",
        "missing_metadata": "CREATE TEMPORARY TABLE raw_validated_shape (amount INT)",
    }[scenario]
    statement = case.namespace.raw(
        sql, validate=Annotated[object, PlainValidator(observe)]
    )
    error = (
        case.namespace.MultipleResultsError
        if scenario == "multiple"
        else case.namespace.RawResultShapeError
    )
    async with case.database.transaction() as transaction:
        with assert_raises(error):
            if scenario == "execute_rows":
                await transaction.execute(statement)
            else:
                await transaction.fetch_one(statement)

    assert_eq(calls, [])


@test(
    [
        Param[BackendFamily](value="sqlite", name="sqlite"),
        Param[BackendFamily](value="mariadb", name="mariadb"),
    ],
    [
        Param(value=scenario, name=scenario)
        for scenario in ("missing", "extra", "null", "strict_bool")
    ],
    mark="slow",
)
async def declared_field_policy_rejects_invalid_values(
    backend: BackendFamily, scenario: str
) -> None:
    """Required fields, extra policy and strictness are owned by Pydantic."""

    case = await load_fixture(provide_raw_case(backend))

    class Total(BaseModel):
        amount: int

    class ForbidExtra(BaseModel):
        amount: int
        model_config = {"extra": "forbid"}

    class BooleanTotal(BaseModel):
        amount: StrictBool

    contract, sql, code = {
        "missing": (Total, "SELECT 1 AS other", "missing"),
        "extra": (ForbidExtra, "SELECT 1 AS amount, 2 AS other", "extra_forbidden"),
        "null": (Total, "SELECT NULL AS amount", "int_type"),
        "strict_bool": (BooleanTotal, "SELECT 1 AS amount", "bool_type"),
    }[scenario]
    statement = case.namespace.raw(sql, validate=contract)
    async with case.database.transaction() as transaction:
        with assert_raises(case.namespace.RawResultValidationError) as raised:
            await transaction.fetch_one(statement)

    assert_eq([detail.code for detail in raised.exception.details], [code])


@test(
    [
        Param[BackendFamily](value="sqlite", name="sqlite"),
        Param[BackendFamily](value="mariadb", name="mariadb"),
    ],
    mark="slow",
)
async def forward_annotation_uses_factory_callers_namespace(
    backend: BackendFamily,
) -> None:
    """Factory wrappers must not replace Pydantic's declaration namespace."""

    case = await load_fixture(provide_raw_case(backend))

    class LocalTotal(TypedDict):
        amount: int

    statement = case.namespace.raw(
        "SELECT '42' AS amount", validate=ForwardRef("LocalTotal")
    )
    async with case.database.transaction() as transaction:
        row = await transaction.fetch_one(statement)

    assert_eq(row, {"amount": 42})


@test(
    [
        Param[BackendFamily](value="sqlite", name="sqlite"),
        Param[BackendFamily](value="mariadb", name="mariadb"),
    ],
    [Param(value=mode, name=mode) for mode in ("mapping", "tuple")],
    mark="slow",
)
async def scalar_contract_does_not_extract_a_column(
    backend: BackendFamily, mode: str
) -> None:
    """Even a one-column result is passed to the adapter as a complete row."""

    case = await load_fixture(provide_raw_case(backend))
    statement = case.namespace.raw("SELECT 42 AS amount", validate=int, row_mode=mode)
    async with case.database.transaction() as transaction:
        with assert_raises(case.namespace.RawResultValidationError) as raised:
            await transaction.fetch_one(statement)

    assert_eq(raised.exception.details[0].code, "int_type")
