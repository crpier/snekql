"""Named results consume decoded logical values, not database wire values."""

from collections.abc import AsyncGenerator
from typing import ClassVar, assert_type
from uuid import UUID

from pydantic import BaseModel, Json
from snektest import assert_eq, assert_raises, fixture, load_fixture, test

from snekql import mariadb, sqlite
from tests.helpers import provide_mariadb_server


class LocalDocument[S = sqlite.Pending](sqlite.Model[S]):
    """Text storage retaining UUID and JSON logical codecs."""

    __row_type__: ClassVar[sqlite.ReadType[LocalDocument[sqlite.Row]]]

    id: LocalDocument.Col[UUID] = sqlite.Text(primary_key=True)
    payload: LocalDocument.Col[Json[list[int]]] = sqlite.Text()


class MariaDocument[S = mariadb.Pending](mariadb.Model[S]):
    """Native UUID and JSON storage with the same logical values."""

    __row_type__: ClassVar[mariadb.ReadType[MariaDocument[mariadb.Row]]]

    id: MariaDocument.Col[UUID] = mariadb.Uuid(primary_key=True)
    payload: MariaDocument.JsonCol[list[int]] = mariadb.Json()


class DocumentResult(BaseModel):
    """Decoded fields may be renamed without changing codecs."""

    key: UUID
    values: list[int]


class FirstValue(BaseModel):
    """A nullable dialect expression projected under a named field."""

    value: int | None


@fixture
async def provide_sqlite_documents() -> AsyncGenerator[sqlite.Database]:
    """Seed values whose logical types differ from their wire representation."""
    async with await sqlite.Database.initialize(database=":memory:") as database:
        await database.migrate({"001_documents": sqlite.scaffold([LocalDocument])})
        async with database.transaction() as transaction:
            await transaction.execute(
                sqlite.insert(LocalDocument(id=UUID(int=1), payload=[2, 3]))
            )
        yield database


@test(mark="medium")
async def sqlite_named_results_retain_logical_codecs() -> None:
    """Contract validation follows column decoding rather than replacing it."""
    database = await load_fixture(provide_sqlite_documents())
    query = sqlite.select(LocalDocument).project(
        DocumentResult, values=LocalDocument.payload, key=LocalDocument.id
    )

    async with database.transaction() as transaction:
        row = await transaction.fetch_one(query)

    assert_type(row, DocumentResult)
    assert_eq(row, DocumentResult(key=UUID(int=1), values=[2, 3]))


@test(mark="medium")
async def sqlite_named_returning_retains_logical_codecs() -> None:
    """Named RETURNING decodes logical values before checking the row contract."""
    database = await load_fixture(provide_sqlite_documents())
    query = sqlite.insert(LocalDocument(id=UUID(int=2), payload=[4, 5])).returning_as(
        DocumentResult, key=LocalDocument.id, values=LocalDocument.payload
    )

    async with database.transaction() as transaction:
        row = await transaction.execute(query)

    assert_type(row, DocumentResult)
    assert_eq(row, DocumentResult(key=UUID(int=2), values=[4, 5]))


@fixture
async def provide_mariadb_documents() -> AsyncGenerator[mariadb.Database]:
    """Seed values whose logical types differ from their wire representation."""
    server = await load_fixture(provide_mariadb_server())
    async with await mariadb.Database.initialize(server.config()) as database:
        await database.migrate({"001_documents": mariadb.scaffold([MariaDocument])})
        async with database.transaction() as transaction:
            await transaction.execute(
                mariadb.insert(MariaDocument(id=UUID(int=1), payload=[2, 3]))
            )
        yield database


@test(mark="slow")
async def mariadb_named_results_retain_logical_codecs() -> None:
    """Contract validation follows column decoding rather than replacing it."""
    database = await load_fixture(provide_mariadb_documents())
    query = mariadb.select(MariaDocument).project(
        DocumentResult, values=MariaDocument.payload, key=MariaDocument.id
    )

    async with database.transaction() as transaction:
        row = await transaction.fetch_one(query)

    assert_type(row, DocumentResult)
    assert_eq(row, DocumentResult(key=UUID(int=1), values=[2, 3]))


@test(mark="slow")
async def mariadb_named_returning_retains_logical_codecs() -> None:
    """Named RETURNING decodes logical values before checking the row contract."""
    database = await load_fixture(provide_mariadb_documents())
    query = mariadb.insert(MariaDocument(id=UUID(int=2), payload=[4, 5])).returning_as(
        DocumentResult, key=MariaDocument.id, values=MariaDocument.payload
    )

    async with database.transaction() as transaction:
        row = await transaction.execute(query)

    assert_type(row, DocumentResult)
    assert_eq(row, DocumentResult(key=UUID(int=2), values=[4, 5]))


@test(mark="slow")
async def named_projection_accepts_dialect_expression() -> None:
    """A backend expression keeps its decoder and ordered parameter bindings."""
    database = await load_fixture(provide_mariadb_documents())
    query = mariadb.select(MariaDocument).project(
        FirstValue, value=MariaDocument.payload.json_extract_int("$[0]")
    )

    async with database.transaction() as transaction:
        row = await transaction.fetch_one(query)

    assert_type(row, FirstValue)
    assert_eq(row, FirstValue(value=2))


type Values[T] = list[T]


@test(mark="medium")
async def named_contract_supports_parameterized_type_aliases() -> None:
    """Pydantic validates specialized aliases after the JSON codec has decoded."""
    database = await load_fixture(provide_sqlite_documents())

    class AliasedResult(BaseModel):
        values: Values[int]

    query = sqlite.select(LocalDocument).project(
        AliasedResult, values=LocalDocument.payload
    )

    async with database.transaction() as transaction:
        row = await transaction.fetch_one(query)

    assert_eq(row, AliasedResult(values=[2, 3]))


@test(mark="slow")
async def opaque_expression_still_checks_named_result_type() -> None:
    """An expression with no inspectable domain cannot bypass result validation."""
    database = await load_fixture(provide_mariadb_documents())

    class TextResult(BaseModel):
        value: str

    query = mariadb.select(MariaDocument).project(
        TextResult, value=MariaDocument.payload.json_extract_int("$[0]")
    )

    async with database.transaction() as transaction:
        with assert_raises(mariadb.ModelValidationError):
            await transaction.fetch_all(query, validate=False)
