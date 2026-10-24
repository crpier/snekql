"""Single RETURNING fields preserve logical values and named contracts."""

from typing import Any, cast
from uuid import UUID

from pydantic import BaseModel, field_validator
from snektest import Param, assert_eq, assert_is, assert_raises, load_fixture, test

from snekql import mariadb, sqlite
from snekql.errors import ModelValidationError
from tests.helpers import initialized_database, provide_mariadb_server
from tests.runtime.test_model_returning_materialization import (
    NativeTextNumber,
    TextNumber,
)
from tests.runtime.test_named_codecs import (
    LocalDocument,
    MariaDocument,
    provide_mariadb_documents,
    provide_sqlite_documents,
)
from tests.runtime.test_projection_decoder import PolicyReading
from tests.runtime.test_single_field_materialization import (
    OneCollection,
    OnePolicy,
    RejectPolicy,
)


@test(
    [Param(backend, name=backend) for backend in ("sqlite", "mariadb")], mark="medium"
)
async def returning_one_collection_keeps_scalar_and_named_shapes(backend: str) -> None:
    api: Any = sqlite if backend == "sqlite" else mariadb
    model: Any = LocalDocument if backend == "sqlite" else MariaDocument
    db = await load_fixture(
        provide_sqlite_documents()
        if backend == "sqlite"
        else provide_mariadb_documents()
    )
    async with db.transaction() as tx:
        scalar = await tx.execute(
            api.insert(model(id=UUID(int=2), payload=[4, 5])).returning(model.payload)
        )
        assert_eq(scalar, [4, 5])
        assert_is(type(scalar), list)
        named = await tx.execute(
            api.insert(model(id=UUID(int=3), payload=[6, 7])).returning_as(
                OneCollection, values=model.payload
            )
        )
        assert_is(type(named), OneCollection)
        assert_eq(named.values, [6, 7, 99])
        rows = await tx.execute(
            api.insert_many(
                model,
                [
                    model(id=UUID(int=4), payload=[8]),
                    model(id=UUID(int=5), payload=[9, 10]),
                ],
            ).returning(model.payload)
        )
        assert_eq(rows, [[8], [9, 10]])
        assert_eq(
            await tx.execute(api.insert_many(model, []).returning(model.payload)), []
        )
        assert_eq(
            await tx.execute(
                api.insert_many(model, []).returning_as(
                    OneCollection, values=model.payload
                )
            ),
            [],
        )


class OneNote(BaseModel):
    value: str | None

    @field_validator("value")
    @classmethod
    def transform_once(cls, value: str | None) -> str | None:
        return None if value is None else value + "!"


@test(
    [Param(backend, name=backend) for backend in ("sqlite", "mariadb")], mark="medium"
)
async def bulk_single_returning_retains_nulls_and_execution_policy(
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
        )
        scalar = query.returning(model.number)
        named = query.returning_as(OneNote, value=model.note)
        for validate in (False, True, False):
            values = cast("list[Any]", await tx.execute(scalar, validate=validate))
            assert_eq(values, [7, 9] if validate else ["7", "9"])
            assert_is(type(values[0]), int if validate else str)
            rows = cast("list[Any]", await tx.execute(named, validate=validate))
            assert_eq([row.value for row in rows], [None, "tail!"])


@test([Param(op, name=op) for op in ("update", "delete")], mark="medium")
async def single_returning_hooks_and_named_failure_retain_write_effects(
    op: str,
) -> None:
    async with (
        await initialized_database(database=":memory:", models=[PolicyReading]) as db,
        db.transaction() as tx,
    ):
        await tx.execute(
            sqlite.insert_many(
                PolicyReading, [PolicyReading(value=7), PolicyReading(value=8)]
            )
        )
        update = (
            sqlite.update(PolicyReading)
            .set(PolicyReading.value.to_expr(PolicyReading.value.add(0)))
            .all()
        )
        for validate in (False, True, False):
            assert_eq(
                await tx.execute(
                    update.returning(PolicyReading.value), validate=validate
                ),
                [107, 108] if validate else [207, 208],
            )
            rows = cast(
                "list[Any]",
                await tx.execute(
                    update.returning_as(OnePolicy, value=PolicyReading.value),
                    validate=validate,
                ),
            )
            assert_eq(
                [row.value for row in rows], [1107, 1108] if validate else [1207, 1208]
            )
        query = (
            sqlite.update(PolicyReading)
            .set(PolicyReading.value.to_expr(PolicyReading.value.add(1)))
            .all()
            if op == "update"
            else sqlite.delete(PolicyReading).all()
        )
        with assert_raises(ModelValidationError):
            await tx.execute(
                query.returning_as(RejectPolicy, value=PolicyReading.value),
                validate=False,
            )
        assert_eq(
            await tx.fetch_all(
                sqlite.select(PolicyReading.value).order_by(PolicyReading.value.asc()),
                validate=False,
            ),
            [208, 209] if op == "update" else [],
        )
        deleted = await tx.execute(
            sqlite.delete(PolicyReading).all().returning(PolicyReading.value)
        )
        assert_eq(deleted, [108, 109] if op == "update" else [])
        assert_eq(
            await tx.execute(
                update.returning_as(RejectPolicy, value=PolicyReading.value)
            ),
            [],
        )
