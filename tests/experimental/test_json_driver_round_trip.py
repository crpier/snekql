"""Issue #603: actual Pydantic Json output bound directly by both async drivers.

No snekql value conversion, model, storage constructor or query builder is tested.
The MariaDB helper owns only a private disposable server used by aiomysql.
"""

from collections.abc import AsyncGenerator
from pathlib import Path
from tempfile import TemporaryDirectory

import aiomysql
import aiosqlite
from pydantic import BaseModel, Json, JsonValue, TypeAdapter, ValidationError
from snektest import assert_eq, assert_raises, fixture, load_fixture, test

from snekql.testing.mariadb import TemporaryMariaDBServer, temporary_mariadb_server

OBJECT = TypeAdapter[dict[str, int]](Json[dict[str, int]])
JSON_VALUE = TypeAdapter[JsonValue](Json[JsonValue])
VALUES: tuple[tuple[str, JsonValue], ...] = (
    ('{"x":1}', {"x": 1}),
    ("[1,2]", [1, 2]),
    ('"hello"', "hello"),
    ("42", 42),
    ("true", True),
    ("null", None),
    ('{"nested":[{"text":"☃"},false,null]}', {"nested": [{"text": "☃"}, False, None]}),
)


class Envelope(BaseModel):
    """An actual public Pydantic model, not a replacement snekql model."""

    payload: Json[dict[str, int]]


@fixture(scope="session")
async def json_server() -> AsyncGenerator[TemporaryMariaDBServer]:
    with TemporaryDirectory(prefix="j603-") as directory:
        async with temporary_mariadb_server(
            runtime_base_directory=Path(directory)
        ) as server:
            yield server


@test(mark="fast")
async def sqlite_json_annotation_round_trips() -> None:
    async with aiosqlite.connect(":memory:") as connection:
        async with connection.execute(
            "CREATE TABLE sample (payload TEXT CHECK(json_valid(payload)))"
        ):
            pass
        for encoded, expected in VALUES:
            value = JSON_VALUE.validate_python(encoded)
            assert_eq(value, expected)
            parameter: object = JSON_VALUE.dump_python(value, round_trip=True)
            assert isinstance(parameter, str)
            async with connection.execute("DELETE FROM sample"):
                pass
            async with connection.execute(
                "INSERT INTO sample (payload) VALUES (?)", (parameter,)
            ):
                pass
            async with connection.execute("SELECT payload FROM sample") as cursor:
                row = await cursor.fetchone()
            assert row is not None
            assert isinstance(row[0], str)  # JSON null is text, not SQL NULL.
            parsed = JSON_VALUE.validate_python(row[0])
            assert type(parsed) is type(expected)
            assert_eq(parsed, expected)


@test(mark="medium")
async def mysql_json_annotation_round_trips() -> None:
    server = await load_fixture(json_server())
    config = server.config()
    async with (
        aiomysql.connect(
            unix_socket=str(config.unix_socket),
            user=config.user,
            password=config.password,
            db=config.database,
            charset="utf8mb4",
            autocommit=True,
        ) as connection,
        connection.cursor() as cursor,
    ):
        await cursor.execute(
            "CREATE TEMPORARY TABLE sample (payload JSON, payload_text LONGTEXT)"
        )
        for encoded, expected in VALUES:
            value = JSON_VALUE.validate_python(encoded)
            assert_eq(value, expected)
            parameter: object = JSON_VALUE.dump_python(value, round_trip=True)
            assert isinstance(parameter, str)
            await cursor.execute("DELETE FROM sample")
            await cursor.execute(
                "INSERT INTO sample (payload, payload_text) VALUES (%s, %s)",
                (parameter, parameter),
            )
            await cursor.execute("SELECT payload, payload_text FROM sample")
            row = await cursor.fetchone()
            assert row is not None
            for raw in row:
                assert isinstance(raw, str)
                parsed = JSON_VALUE.validate_python(raw)
                assert type(parsed) is type(expected)
                assert_eq(parsed, expected)


@test(mark="fast")
async def sqlite_default_dump_dictionary_is_rejected_by_driver() -> None:
    value = OBJECT.validate_python('{"x":1}')
    parameter: object = OBJECT.dump_python(value)
    assert_eq(parameter, {"x": 1})
    async with aiosqlite.connect(":memory:") as connection:
        async with connection.execute("CREATE TABLE sample (payload TEXT)"):
            pass
        with assert_raises(aiosqlite.ProgrammingError):
            async with connection.execute(
                "INSERT INTO sample (payload) VALUES (?)", (parameter,)
            ):
                pass


@test(mark="medium")
async def mysql_default_dump_dictionary_is_rejected_by_driver() -> None:
    server = await load_fixture(json_server())
    config = server.config()
    value = OBJECT.validate_python('{"x":1}')
    parameter: object = OBJECT.dump_python(value)
    assert_eq(parameter, {"x": 1})
    async with (
        aiomysql.connect(
            unix_socket=str(config.unix_socket),
            user=config.user,
            password=config.password,
            db=config.database,
            charset="utf8mb4",
            autocommit=True,
        ) as connection,
        connection.cursor() as cursor,
    ):
        await cursor.execute("CREATE TEMPORARY TABLE sample (payload JSON)")
        with assert_raises(TypeError):
            await cursor.execute(
                "INSERT INTO sample (payload) VALUES (%s)", (parameter,)
            )


@test(mark="fast")
def json_annotation_requires_encoded_input_not_an_ordinary_dictionary() -> None:
    assert_eq(OBJECT.validate_python('{"x":1}'), {"x": 1})
    with assert_raises(ValidationError) as error:
        OBJECT.validate_python({"x": 1})
    assert_eq([detail["type"] for detail in error.exception.errors()], ["json_type"])
    with assert_raises(ValidationError):
        Envelope.model_validate({"payload": {"x": 1}})


@test(mark="fast")
def model_dump_and_type_adapter_both_honor_json_round_trip() -> None:
    envelope = Envelope.model_validate({"payload": '{"x":1}'})
    assert_eq(envelope.payload, {"x": 1})
    assert_eq(envelope.model_dump(mode="python"), {"payload": {"x": 1}})
    assert_eq(
        envelope.model_dump(mode="python", round_trip=True),
        {"payload": '{"x":1}'},
    )
    model_adapter = TypeAdapter[Envelope](Envelope)
    assert_eq(
        model_adapter.dump_python(envelope, round_trip=True),
        {"payload": '{"x":1}'},
    )


@test(mark="fast")
def round_trip_does_not_turn_an_ordinary_dictionary_annotation_into_json_text() -> None:
    ordinary = TypeAdapter[dict[str, int]](dict[str, int])
    assert_eq(ordinary.dump_python({"x": 1}, round_trip=True), {"x": 1})
