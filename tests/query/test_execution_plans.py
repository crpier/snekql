"""Vertical tracer tests for typed compiled execution plans (#250)."""

from __future__ import annotations

from pathlib import Path
from sqlite3 import connect
from tempfile import TemporaryDirectory
from typing import Any, assert_type
from uuid import UUID, uuid4

from snektest import assert_eq, assert_isinstance, assert_raises, test

from snekql._query_codec import DialectQueryCodec
from snekql._query_plan import SelectPlan, WritePlan
from snekql.errors import ResultCardinalityError
from snekql.query import _QueryShape, _WriteShape
from snekql.sqlite import (
    PENDING_GENERATION,
    Fetched,
    Integer,
    Model,
    Pending,
    Text,
    insert,
    select,
)
from tests.helpers import initialized_database


class Token[S = Pending](Model[S, "Token[Fetched]"]):
    """Model whose logical UUID differs from its SQLite wire value."""

    id: Token.GenCol[int] = Integer(
        primary_key=True,
        auto_increment=True,
        default=PENDING_GENERATION,
    )
    value: Token.Col[UUID] = Text(nullable=False)


class _UnlistedSelect[ResultT](_QueryShape[Any, Any, ResultT]):
    """Internal query shape proving runtime does not enumerate select builders."""

    def __init__(self, state: object) -> None:
        self.state = state


class _UnlistedWrite[ResultT](_WriteShape[ResultT]):
    """Internal query shape proving runtime does not enumerate write builders."""

    def __init__(self, state: object) -> None:
        self.state = state


@test(mark="fast")
def select_plan_carries_sql_backend_cardinality_and_validation() -> None:
    """A select plan owns compilation and validated row materialization."""

    source = uuid4()
    codec = DialectQueryCodec.for_backend("sqlite")
    query = select(Token.value).where(Token.value.eq(source))

    plan = assert_type(
        codec.compile_select_plan(query, cardinality="one", validate=True),
        SelectPlan[UUID],
    )

    assert_eq(plan.sql, 'SELECT "value" FROM "token" WHERE ("value" = ?)')
    assert_eq(plan.params, (str(source),))
    assert_eq(plan.backend, "sqlite")
    assert_eq(plan.cardinality, "one")
    assert_eq(plan.materialize([(str(source),)]), source)


@test(mark="fast")
def select_plan_preserves_raw_materialization_policy() -> None:
    """The plan fixes validate=False before Query Runtime executes it."""

    source = uuid4()
    plan = assert_type(
        DialectQueryCodec.for_backend("sqlite").compile_select_plan(
            select(Token.value).all(),
            cardinality="one",
            validate=False,
        ),
        SelectPlan[object],
    )

    result = plan.materialize([(str(source),)])

    assert_isinstance(result, str)
    assert_eq(result, str(source))


@test(mark="fast")
def write_plan_carries_single_returning_execution_policy() -> None:
    """A single insert RETURNING plan owns its one-row result contract."""

    source = uuid4()
    codec = DialectQueryCodec.for_backend("sqlite")
    query = insert(Token(value=source)).returning(Token.value)

    plan = assert_type(
        codec.compile_write_plan(query, validate=True),
        WritePlan[UUID],
    )

    assert_eq(
        plan.sql,
        'INSERT INTO "token" ("value") VALUES (?) RETURNING "value"',
    )
    assert_eq(plan.params, (str(source),))
    assert_eq(plan.backend, "sqlite")
    assert_eq(plan.cardinality, "one")
    assert_eq(plan.materialize(rowcount=1, rows=[(str(source),)]), source)


@test(mark="fast")
def write_plan_preserves_raw_materialization_policy() -> None:
    """A literal false policy gives the plan an object result and raw wire value."""

    source = uuid4()
    plan = assert_type(
        DialectQueryCodec.for_backend("sqlite").compile_write_plan(
            insert(Token(value=source)).returning(Token.value),
            validate=False,
        ),
        WritePlan[object],
    )

    result = plan.materialize(rowcount=1, rows=[(str(source),)])

    assert_isinstance(result, str)
    assert_eq(result, str(source))


@test(mark="fast")
def missing_single_returning_row_raises_package_cardinality_error() -> None:
    """Single-row RETURNING absence never leaks list IndexError."""

    plan = DialectQueryCodec.for_backend("sqlite").compile_write_plan(
        insert(Token(value=uuid4())).returning(Token.value),
    )

    with assert_raises(ResultCardinalityError):
        _ = plan.materialize(rowcount=0, rows=[])


@test(mark="medium")
async def runtime_executes_unlisted_select_and_write_shapes_through_plans() -> None:
    """Adding equivalent query shapes requires no Transaction class dispatch."""

    source = uuid4()
    database = await initialized_database(database=":memory:", models=[Token])
    try:
        async with database.transaction() as transaction:
            base_write = insert(Token(value=source)).returning(Token.value)
            written = assert_type(
                await transaction.execute(_UnlistedWrite[UUID](base_write.state)),
                UUID,
            )
            base_select = select(Token.value).where(Token.value.eq(source))
            fetched = assert_type(
                await transaction.fetch_one(_UnlistedSelect[UUID](base_select.state)),
                UUID,
            )
    finally:
        await database.close()

    assert_eq(written, source)
    assert_eq(fetched, source)


@test(mark="medium")
async def ignored_insert_returning_raises_package_cardinality_error() -> None:
    """A trigger-suppressed insert exercises the former models[0] failure."""

    class Message[S = Pending](Model[S, "Message[Fetched]"]):
        """Rows whose blocked body is ignored by a trigger."""

        id: Message.GenCol[int] = Integer(
            primary_key=True,
            auto_increment=True,
            default=PENDING_GENERATION,
        )
        body: Message.Col[str] = Text(nullable=False)

    with TemporaryDirectory() as directory:
        database_path = Path(directory) / "plans.db"
        database = await initialized_database(database=database_path, models=[Message])
        raw_connection = connect(database_path)
        try:
            raw_connection.execute(
                """
                CREATE TRIGGER ignore_blocked_message
                BEFORE INSERT ON message
                WHEN NEW.body = 'blocked'
                BEGIN
                    SELECT RAISE(IGNORE);
                END
                """
            )
            raw_connection.commit()
        finally:
            raw_connection.close()
        try:
            async with database.transaction() as transaction:
                with assert_raises(ResultCardinalityError):
                    _ = await transaction.execute(
                        insert(Message(body="blocked")).returning(Message.id),
                    )
        finally:
            await database.close()
