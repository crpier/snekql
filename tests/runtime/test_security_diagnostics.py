"""Default database diagnostics omit values even in formatted tracebacks."""

from collections.abc import Iterable
from traceback import format_exception
from typing import Any, ClassVar, Literal
from unittest.mock import patch
from uuid import UUID
from warnings import catch_warnings, simplefilter, warn

from aiosqlite import Connection, Cursor
from pydantic import Json, create_model
from snektest import Param, assert_eq, assert_not_in, assert_raises, load_fixture, test

from snekql import mariadb, sqlite
from snekql.model import BackendFamily
from tests.runtime.test_raw_execution import provide_raw_case


class SQLiteDocument[S = sqlite.Pending](sqlite.Model[S]):
    """Text wire storage exercises JSON validation after a native fetch."""

    __row_type__: ClassVar[sqlite.ReadType[SQLiteDocument[sqlite.Row]]]
    __tablename__ = "security_documents"
    payload: sqlite.Col[Json[list[int]]] = sqlite.Text()


class MariaDocument[S = mariadb.Pending](mariadb.Model[S]):
    """Native JSON has the same payload-validation confidentiality contract."""

    __row_type__: ClassVar[mariadb.ReadType[MariaDocument[mariadb.Row]]]
    __tablename__ = "security_documents"
    payload: mariadb.JsonCol[list[int]] = mariadb.Json()


@test(
    [
        Param[BackendFamily]("sqlite", name="sqlite"),
        Param[BackendFamily]("mariadb", name="mariadb"),
    ],
    mark="slow",
)
async def json_validation_traceback_omits_input(backend: BackendFamily) -> None:
    """Bad stored JSON is reported without rendering its payload."""
    case = await load_fixture(provide_raw_case(backend))
    model = SQLiteDocument if backend == "sqlite" else MariaDocument
    private_input = "stored_json_secret"
    await case.database.migrate({"001": case.namespace.scaffold([model])})
    placeholder = "?" if backend == "sqlite" else "%s"
    async with case.database.transaction() as setup:
        await setup.execute(
            case.namespace.raw(
                f"INSERT INTO {model.__tablename__} VALUES ({placeholder})",
                params=(f'["{private_input}"]',),
            )
        )

    with assert_raises(sqlite.ModelValidationError) as caught:
        async with case.database.transaction() as transaction:
            await transaction.fetch_all(case.namespace.select(model.payload))

    assert_not_in(private_input, "".join(format_exception(caught.exception)))


@test(
    [
        Param[Literal["redacted", "values"]]("redacted", name="redacted"),
        Param[Literal["redacted", "values"]]("values", name="values"),
    ],
    mark="slow",
)
async def builder_error_traceback_honors_visibility(
    visibility: Literal["redacted", "values"],
) -> None:
    """Driver messages are exposed only under the explicit unsafe values policy."""
    case = await load_fixture(provide_raw_case("mariadb", visibility=visibility))

    class Account[S = mariadb.Pending](mariadb.Model[S]):
        __row_type__: ClassVar[mariadb.ReadType[Account[mariadb.Row]]]
        token: mariadb.Col[str] = mariadb.Text(unique=True)

    private_input = "duplicate_value_secret"
    await case.database.migrate({"001": mariadb.scaffold([Account])})
    async with case.database.transaction() as setup:
        await setup.execute(mariadb.insert(Account(token=private_input)))

    with assert_raises(mariadb.ExecutionError) as caught:
        async with case.database.transaction() as transaction:
            await transaction.execute(mariadb.insert(Account(token=private_input)))

    rendered = "".join(format_exception(caught.exception))
    assert_eq(private_input in rendered, visibility == "values")
    assert_eq(caught.exception.params, (private_input,))
    assert caught.exception.failure is not None
    assert_eq(caught.exception.failure.category, "unique_violation")


@test(mark="medium")
async def primitive_validation_traceback_omits_input() -> None:
    """Lax wire decoding does not include malformed stored text in errors."""
    case = await load_fixture(provide_raw_case("sqlite"))

    class Identifier[S = sqlite.Pending](sqlite.Model[S]):
        __row_type__: ClassVar[sqlite.ReadType[Identifier[sqlite.Row]]]
        token: sqlite.Col[UUID] = sqlite.Text()

    private_input = "invalid_identifier_secret"
    await case.database.migrate({"001": sqlite.scaffold([Identifier])})
    async with case.database.transaction() as setup:
        await setup.execute(
            sqlite.raw("INSERT INTO identifier VALUES (?)", params=(private_input,))
        )

    with assert_raises(sqlite.ModelValidationError) as caught:
        async with case.database.transaction() as transaction:
            await transaction.fetch_all(sqlite.select(Identifier.token))

    assert_not_in(private_input, "".join(format_exception(caught.exception)))


@test(mark="slow")
async def json_extraction_traceback_omits_values() -> None:
    """A typed extraction mismatch hides both its bound path and stored value."""
    case = await load_fixture(provide_raw_case("mariadb"))

    class Document[S = mariadb.Pending](mariadb.Model[S]):
        __row_type__: ClassVar[mariadb.ReadType[Document[mariadb.Row]]]
        payload: mariadb.JsonCol[dict[str, str]] = mariadb.Json()

    private_key = "path_secret"
    private_value = "extracted_value_secret"
    await case.database.migrate({"001": mariadb.scaffold([Document])})
    async with case.database.transaction() as setup:
        await setup.execute(
            mariadb.insert(Document(payload={private_key: private_value}))
        )

    query = mariadb.select(Document.payload.json_extract_int(f"$.{private_key}"))
    with assert_raises(mariadb.ModelValidationError) as caught:
        async with case.database.transaction() as transaction:
            await transaction.fetch_all(query)

    rendered = "".join(format_exception(caught.exception))
    assert_not_in(private_key, rendered)
    assert_not_in(private_value, rendered)


@test(
    [
        Param[BackendFamily]("sqlite", name="sqlite"),
        Param[BackendFamily]("mariadb", name="mariadb"),
    ],
    mark="slow",
)
async def quoted_projection_name_retains_parameter_binding(
    backend: BackendFamily,
) -> None:
    """Quoted output names cannot consume driver placeholders or alter row selection."""
    case = await load_fixture(provide_raw_case(backend))
    model = SQLiteDocument if backend == "sqlite" else MariaDocument
    output_name = 'quoted`".name#--%s'
    # Dynamically supplied Pydantic field names cannot be expressed as keywords.
    fields: dict[str, Any] = {output_name: (list[int], ...)}
    result_type = create_model("QuotedResult", **fields)
    await case.database.migrate({"001": case.namespace.scaffold([model])})
    async with case.database.transaction() as setup:
        await setup.execute(case.namespace.insert(model(payload=[7])))
        await setup.execute(case.namespace.insert(model(payload=[8])))

    query = (
        case.namespace.select(model)
        .where(model.payload.eq([7]))
        .project(result_type, **{output_name: model.payload.label(output_name)})
    )
    async with case.database.transaction() as transaction:
        rows = await transaction.fetch_all(query)

    assert_eq([row.model_dump() for row in rows], [{output_name: [7]}])


@test(
    [Param("buffered", name="buffered"), Param("stream", name="stream")],
    mark="slow",
)
async def builder_server_warnings_are_not_forwarded(consumption: str) -> None:
    """Server warning text is private; unrelated Python warnings remain visible."""
    case = await load_fixture(provide_raw_case("mariadb"))
    await case.database.migrate({"001": mariadb.scaffold([MariaDocument])})
    async with case.database.transaction() as setup:
        await setup.execute(mariadb.insert(MariaDocument(payload=[7])))

    query = mariadb.select(MariaDocument.payload.json_extract_int("invalid_path"))
    with catch_warnings(record=True) as captured:
        simplefilter("always")
        async with case.database.transaction() as transaction:
            if consumption == "stream":
                async with transaction.fetch_chunks(query, size=1) as stream:
                    await anext(stream)
            else:
                await transaction.fetch_all(query)
        warn("unrelated_warning", stacklevel=1)

    assert_eq([str(warning.message) for warning in captured], ["unrelated_warning"])


@test(
    [
        Param[Literal["redacted", "values"]]("redacted", name="redacted"),
        Param[Literal["redacted", "values"]]("values", name="values"),
    ],
    mark="medium",
)
async def builder_timeout_traceback_honors_visibility(
    visibility: Literal["redacted", "values"],
) -> None:
    """Driver-originated timeouts must not bypass default query-error redaction."""
    case = await load_fixture(provide_raw_case("sqlite", visibility=visibility))

    class Entry[S = sqlite.Pending](sqlite.Model[S]):
        __row_type__: ClassVar[sqlite.ReadType[Entry[sqlite.Row]]]
        token: sqlite.Col[str] = sqlite.Text()

    private_input = "driver_timeout_secret"
    await case.database.migrate({"001": sqlite.scaffold([Entry])})
    native_execute = Connection.execute

    async def timeout_execute(
        connection: Connection,
        sql: str,
        parameters: Iterable[object] | None = None,
    ) -> Cursor:
        if sql.startswith("SELECT "):
            # A native driver can time out independently of the package deadline.
            raise TimeoutError(private_input)
        return await native_execute(connection, sql, parameters)

    with (
        patch.object(Connection, "execute", timeout_execute),
        assert_raises(sqlite.DatabaseOperationTimeoutError) as caught,
    ):
        async with case.database.transaction() as transaction:
            await transaction.fetch_all(sqlite.select(Entry.token))

    rendered = "".join(format_exception(caught.exception))
    assert_eq(private_input in rendered, visibility == "values")
