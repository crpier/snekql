"""Projection resets must not enable unsupported MariaDB RETURNING operations."""

from __future__ import annotations

from snektest import Param, assert_eq, assert_in, assert_raises, load_fixture, test

from snekql import mariadb
from snekql.errors import QueryCompilationError
from tests.helpers import initialized_database, provide_mariadb_server


class Item[S = mariadb.Pending](mariadb.Model[S, "Item[mariadb.Fetched]"]):
    """A row that must survive rejected returning writes unchanged."""

    id: Item.Col[int] = mariadb.Integer(primary_key=True)
    score: Item.Col[int] = mariadb.Integer(nullable=False)
    label: Item.Col[str] = mariadb.Text(nullable=False)


@test(
    [
        Param(value=(operation, shape), name=f"{operation}_{shape}")
        for operation in ("update", "delete")
        for shape in ("scalar", "tuple", "model")
    ],
    mark="medium",
)
async def returning_reset_keeps_backend_restrictions(case: tuple[str, str]) -> None:
    """The current adapter rejects both operations before mutating any row."""

    server = await load_fixture(provide_mariadb_server())
    async with await initialized_database(server.config(), models=[Item]) as database:
        async with database.transaction() as setup:
            await setup.execute(mariadb.insert(Item(id=1, score=10, label="one")))

        base = (
            mariadb.update(Item).set(Item.score.to(20)).all()
            if case[0] == "update"
            else mariadb.delete(Item).all()
        )
        if case[1] == "scalar":
            query = base.returning(Item.id).returning()
        elif case[1] == "tuple":
            query = base.returning(Item.label, Item.id).returning()
        else:
            query = base.returning().returning()

        async with database.transaction() as tx:
            with assert_raises(QueryCompilationError) as caught:
                await tx.execute(query)

        async with database.transaction() as tx:
            rows = await tx.fetch_all(
                mariadb.select(Item.id, Item.score, Item.label).all()
            )

    assert_in(f"does not support {case[0].upper()} RETURNING", str(caught.exception))
    assert_eq(rows, [(1, 10, "one")])
