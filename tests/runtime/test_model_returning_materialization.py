"""Whole-model write results retain assignment and per-execution policies."""

from typing import Any, ClassVar, cast

from snektest import Param, assert_eq, assert_is, assert_raises, load_fixture, test

from snekql import mariadb, sqlite
from snekql.errors import FrozenModelError, ModelValidationError
from tests.helpers import initialized_database, provide_mariadb_server
from tests.runtime.test_model_row_materialization import SetterReading, ValidatedReading


@test(
    [Param(op, name=op) for op in ("insert", "bulk", "update", "delete")],
    mark="medium",
)
async def whole_model_returning_preserves_descriptors_and_row_freezing(op: str) -> None:
    async with (
        await initialized_database(database=":memory:", models=[SetterReading]) as db,
        db.transaction() as tx,
    ):
        if op == "insert":
            rows = [await tx.execute(sqlite.insert(SetterReading(value=3)).returning())]
            expected = [12]
        elif op == "bulk":
            rows = await tx.execute(
                sqlite.insert_many(
                    SetterReading, [SetterReading(value=3), SetterReading(value=4)]
                ).returning()
            )
            expected = [12, 16]
        else:
            await tx.execute(
                sqlite.raw("INSERT INTO setter_reading (value) VALUES (7), (8)")
            )
            query = (
                sqlite.update(SetterReading)
                .set(SetterReading.value.to(9))
                .all()
                .returning()
                if op == "update"
                else sqlite.delete(SetterReading).all().returning()
            )
            rows = await tx.execute(query)
            expected = [18, 18] if op == "update" else [14, 16]
        assert_eq([row.value for row in rows], expected)
        with assert_raises(FrozenModelError):
            cast("Any", rows[0]).value = 0
        stored = await tx.fetch_all(
            sqlite.select(SetterReading.value).order_by(SetterReading.value.asc())
        )
        assert_eq(
            stored, {"insert": [6], "bulk": [6, 8], "update": [9, 9], "delete": []}[op]
        )


class TextNumber[S = sqlite.Pending](sqlite.Model[S]):
    __row_type__: ClassVar[sqlite.ReadType[TextNumber[sqlite.Row]]]
    note: TextNumber.Col[str | None] = sqlite.Text()
    number: TextNumber.Col[int] = sqlite.Text()
    amount: TextNumber.Col[float] = sqlite.Real()


class NativeTextNumber[S = mariadb.Pending](mariadb.Model[S]):
    __row_type__: ClassVar[mariadb.ReadType[NativeTextNumber[mariadb.Row]]]
    note: NativeTextNumber.Col[str | None] = mariadb.Text()
    number: NativeTextNumber.Col[int] = mariadb.Text()
    amount: NativeTextNumber.Col[float] = mariadb.Real()


@test(
    [Param(backend, name=backend) for backend in ("sqlite", "mariadb")], mark="medium"
)
async def bulk_returning_keeps_column_order_nulls_and_each_validation_policy(
    backend: str,
) -> None:
    api: Any = sqlite if backend == "sqlite" else mariadb
    model: Any = TextNumber if backend == "sqlite" else NativeTextNumber
    config = (
        sqlite.Config(database=":memory:")
        if backend == "sqlite"
        else (await load_fixture(provide_mariadb_server())).config()
    )
    async with (
        await initialized_database(config, models=[model]) as db,
        db.transaction() as tx,
    ):
        query = api.insert_many(
            model,
            [
                model(note=None, number=7, amount=2.5),
                model(note="tail", number=9, amount=-0.5),
            ],
        ).returning()
        for validate in (False, True, False):
            rows = cast("list[Any]", await tx.execute(query, validate=validate))
            assert_eq(
                [(row.note, row.number, row.amount) for row in rows],
                [
                    (None, 7 if validate else "7", 2.5),
                    ("tail", 9 if validate else "9", -0.5),
                ],
            )
            assert_is(type(rows[0].number), int if validate else str)
            with assert_raises(FrozenModelError):
                rows[0].number = 10
        assert_eq(await tx.execute(api.insert_many(model, []).returning()), [])


@test(mark="medium")
async def returning_validation_failure_keeps_written_state_and_transaction_usable() -> (
    None
):
    async with (
        await initialized_database(
            database=":memory:", models=[ValidatedReading]
        ) as db,
        db.transaction() as tx,
    ):
        await tx.execute(
            sqlite.raw("INSERT INTO validated_reading (value) VALUES (-5)")
        )
        query = (
            sqlite.update(ValidatedReading)
            .set(ValidatedReading.value.to_expr(ValidatedReading.value.add(0)))
            .all()
            .returning()
        )
        for validate in (False, True, False):
            if validate:
                with assert_raises(ModelValidationError):
                    await tx.execute(query, validate=validate)
            else:
                rows = cast("list[Any]", await tx.execute(query, validate=validate))
                assert_eq([row.value for row in rows], [-5])
        assert_eq(
            await tx.fetch_all(sqlite.select(ValidatedReading.value), validate=False),
            [-5],
        )
