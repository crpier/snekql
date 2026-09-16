"""General join predicates executed against SQLite and MariaDB."""

from collections.abc import AsyncGenerator
from typing import assert_type

from snektest import assert_eq, fixture, load_fixture, test

from snekql import mariadb, sqlite
from tests.helpers import provide_mariadb_server


class LocalParent[S = sqlite.Pending](sqlite.Model[S, "LocalParent[sqlite.Fetched]"]):
    """A tenant-owned row without a declared foreign-key relationship."""

    id: LocalParent.Col[int] = sqlite.Integer(primary_key=True)
    tenant: LocalParent.Col[int] = sqlite.Integer()


class LocalChild[S = sqlite.Pending](sqlite.Model[S, "LocalChild[sqlite.Fetched]"]):
    """A child matched by compound ON, not FK metadata."""

    id: LocalChild.Col[int] = sqlite.Integer(primary_key=True)
    parent_id: LocalChild.Col[int] = sqlite.Integer()
    tenant: LocalChild.Col[int] = sqlite.Integer()
    label: LocalChild.Col[str] = sqlite.Text()


@fixture
async def provide_sqlite_join_rows() -> AsyncGenerator[sqlite.Database]:
    """Seed tenant mismatches and right-side rows excluded by ON."""
    async with await sqlite.Database.initialize(database=":memory:") as database:
        await database.migrate(
            {
                "001_parent": sqlite.scaffold([LocalParent]),
                "002_child": sqlite.scaffold([LocalChild]),
            }
        )
        async with database.transaction() as transaction:
            await transaction.execute(
                sqlite.insert(
                    [
                        LocalParent(id=1, tenant=1),
                        LocalParent(id=2, tenant=2),
                        LocalParent(id=3, tenant=3),
                    ]
                )
            )
            await transaction.execute(
                sqlite.insert(
                    [
                        LocalChild(id=10, parent_id=1, tenant=1, label="visible"),
                        LocalChild(id=11, parent_id=1, tenant=2, label="visible"),
                        LocalChild(id=12, parent_id=2, tenant=2, label="hidden"),
                    ]
                )
            )
        yield database


@test(mark="medium")
async def sqlite_compound_on_matches_without_foreign_keys() -> None:
    """Both key comparisons and the bound filter constrain matching rows."""
    database = await load_fixture(provide_sqlite_join_rows())
    query = (
        sqlite.select(LocalParent.id, LocalChild.id)
        .join(
            LocalChild,
            on=(
                LocalChild.parent_id.eq_col(LocalParent.id)
                & LocalChild.tenant.eq_col(LocalParent.tenant)
                & LocalChild.label.ne("hidden")
            ),
        )
        .all()
        .order_by(LocalChild.id.asc())
    )

    async with database.transaction() as transaction:
        rows = await transaction.fetch_all(query)

    assert_type(rows, list[tuple[int, int]])
    assert_eq(rows, [(1, 10)])


@test(mark="medium")
async def sqlite_left_on_filter_preserves_unmatched_parents() -> None:
    """Moving the right-side filter into WHERE would incorrectly drop parents."""
    database = await load_fixture(provide_sqlite_join_rows())
    query = (
        sqlite.select(LocalParent)
        .left_join(
            LocalChild,
            on=(
                LocalChild.parent_id.eq_col(LocalParent.id)
                & LocalChild.tenant.eq_col(LocalParent.tenant)
                & LocalChild.label.ne("hidden")
            ),
        )
        .all()
        .order_by(LocalParent.id.asc())
    )

    async with database.transaction() as transaction:
        rows = await transaction.fetch_all(query)

    assert_type(
        rows,
        list[tuple[LocalParent[sqlite.Fetched], LocalChild[sqlite.Fetched] | None]],
    )
    assert_eq(
        [
            (parent.id, child.id if child is not None else None)
            for parent, child in rows
        ],
        [(1, 10), (2, None), (3, None)],
    )


class MariaParent[S = mariadb.Pending](
    mariadb.Model[S, "MariaParent[mariadb.Fetched]"]
):
    """A tenant-owned row without a declared foreign-key relationship."""

    id: MariaParent.Col[int] = mariadb.Integer(primary_key=True)
    tenant: MariaParent.Col[int] = mariadb.Integer()


class MariaChild[S = mariadb.Pending](mariadb.Model[S, "MariaChild[mariadb.Fetched]"]):
    """A child matched by compound ON, not FK metadata."""

    id: MariaChild.Col[int] = mariadb.Integer(primary_key=True)
    parent_id: MariaChild.Col[int] = mariadb.Integer()
    tenant: MariaChild.Col[int] = mariadb.Integer()
    label: MariaChild.Col[str] = mariadb.Text()


@fixture
async def provide_mariadb_join_rows() -> AsyncGenerator[mariadb.Database]:
    """Seed tenant mismatches and right-side rows excluded by ON."""
    server = await load_fixture(provide_mariadb_server())
    async with await mariadb.Database.initialize(server.config()) as database:
        await database.migrate(
            {
                "001_parent": mariadb.scaffold([MariaParent]),
                "002_child": mariadb.scaffold([MariaChild]),
            }
        )
        async with database.transaction() as transaction:
            await transaction.execute(
                mariadb.insert(
                    [
                        MariaParent(id=1, tenant=1),
                        MariaParent(id=2, tenant=2),
                        MariaParent(id=3, tenant=3),
                    ]
                )
            )
            await transaction.execute(
                mariadb.insert(
                    [
                        MariaChild(id=10, parent_id=1, tenant=1, label="visible"),
                        MariaChild(id=11, parent_id=1, tenant=2, label="visible"),
                        MariaChild(id=12, parent_id=2, tenant=2, label="hidden"),
                    ]
                )
            )
        yield database


@test(mark="slow")
async def mariadb_compound_on_matches_without_foreign_keys() -> None:
    """Both key comparisons and the bound filter constrain matching rows."""
    database = await load_fixture(provide_mariadb_join_rows())
    query = (
        mariadb.select(MariaParent.id, MariaChild.id)
        .join(
            MariaChild,
            on=(
                MariaChild.parent_id.eq_col(MariaParent.id)
                & MariaChild.tenant.eq_col(MariaParent.tenant)
                & MariaChild.label.ne("hidden")
            ),
        )
        .all()
        .order_by(MariaChild.id.asc())
    )

    async with database.transaction() as transaction:
        rows = await transaction.fetch_all(query)

    assert_type(rows, list[tuple[int, int]])
    assert_eq(rows, [(1, 10)])


@test(mark="slow")
async def mariadb_left_on_filter_preserves_unmatched_parents() -> None:
    """Moving the right-side filter into WHERE would incorrectly drop parents."""
    database = await load_fixture(provide_mariadb_join_rows())
    query = (
        mariadb.select(MariaParent)
        .left_join(
            MariaChild,
            on=(
                MariaChild.parent_id.eq_col(MariaParent.id)
                & MariaChild.tenant.eq_col(MariaParent.tenant)
                & MariaChild.label.ne("hidden")
            ),
        )
        .all()
        .order_by(MariaParent.id.asc())
    )

    async with database.transaction() as transaction:
        rows = await transaction.fetch_all(query)

    assert_type(
        rows,
        list[tuple[MariaParent[mariadb.Fetched], MariaChild[mariadb.Fetched] | None]],
    )
    assert_eq(
        [
            (parent.id, child.id if child is not None else None)
            for parent, child in rows
        ],
        [(1, 10), (2, None), (3, None)],
    )


@test(mark="medium")
async def sqlite_on_supports_non_equality_boolean_predicates() -> None:
    """OR and NOT combine with a non-equality column comparison in ON."""
    database = await load_fixture(provide_sqlite_join_rows())
    query = (
        sqlite.select(LocalParent.id, LocalChild.id)
        .join(
            LocalChild,
            on=LocalChild.parent_id.eq_col(LocalParent.id)
            & (
                LocalChild.tenant.gt_col(LocalParent.tenant)
                | ~LocalChild.label.eq("hidden")
            ),
        )
        .all()
        .order_by(LocalChild.id.asc())
    )

    async with database.transaction() as transaction:
        rows = await transaction.fetch_all(query)

    assert_eq(rows, [(1, 10), (1, 11)])
