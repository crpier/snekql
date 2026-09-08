"""HAVING validates both direct operands without entering nested query scopes."""

from __future__ import annotations

from snektest import assert_eq, load_fixture, test

from snekql import mariadb
from tests.helpers import initialized_database, provide_mariadb_server


class Sale[S = mariadb.Pending](mariadb.Model[S, "Sale[mariadb.Fetched]"]):
    """A grouped key and a separate ungrouped amount."""

    category: Sale.Col[int] = mariadb.Integer(nullable=False)
    amount: Sale.Col[int] = mariadb.Integer(nullable=False)


@test(mark="medium")
async def grouped_column_comparison_filters_groups() -> None:
    """MariaDB executes a valid comparison between two grouping keys."""

    server = await load_fixture(provide_mariadb_server())
    async with await initialized_database(server.config(), models=[Sale]) as database:
        async with database.transaction() as setup:
            await setup.execute(mariadb.insert(Sale(category=1, amount=2)))
            await setup.execute(mariadb.insert(Sale(category=1, amount=2)))
            await setup.execute(mariadb.insert(Sale(category=2, amount=1)))

        query = (
            mariadb.select(Sale.category, Sale.amount)
            .all()
            .group_by(Sale.category, Sale.amount)
            .having(Sale.category.lt_col(Sale.amount))
        )
        async with database.transaction() as tx:
            rows = await tx.fetch_all(query)

    assert_eq(rows, [(1, 2)])


@test(mark="medium")
async def having_scalar_subquery_keeps_its_own_column_scope() -> None:
    """Inner ungrouped columns do not become outer HAVING grouping operands."""

    server = await load_fixture(provide_mariadb_server())

    class Detail[S = mariadb.Pending](mariadb.Model[S, "Detail[mariadb.Fetched]"]):
        """A correlated inner source with its own non-grouped columns."""

        category: Detail.Col[int] = mariadb.Integer(nullable=False)
        amount: Detail.Col[int] = mariadb.Integer(nullable=False)

    async with await initialized_database(
        server.config(), models=[Sale, Detail]
    ) as database:
        async with database.transaction() as setup:
            await setup.execute(mariadb.insert(Sale(category=1, amount=10)))
            await setup.execute(mariadb.insert(Sale(category=2, amount=10)))
            await setup.execute(mariadb.insert(Detail(category=1, amount=2)))
            await setup.execute(mariadb.insert(Detail(category=2, amount=1)))

        inner = mariadb.scalar(
            mariadb.select(Detail.amount.max()).where(
                Detail.category.eq_col(Sale.category)
            )
        )
        query = (
            mariadb.select(Sale.category)
            .all()
            .group_by(Sale.category)
            .having(Sale.category.lt_col(inner))
        )
        async with database.transaction() as tx:
            rows = await tx.fetch_all(query)

    assert_eq(rows, [1])
