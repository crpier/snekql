"""Correlated scalar outputs can read explicit grouping keys on real backends."""

from snektest import assert_eq, load_fixture, test

from snekql import mariadb, sqlite
from tests.runtime.test_join_predicates import (
    LocalChild,
    LocalParent,
    MariaChild,
    MariaParent,
    provide_mariadb_join_rows,
    provide_sqlite_join_rows,
)


@test(mark="medium")
async def grouped_scalar_keeps_outer_key_correlation() -> None:
    """A grouped parent keeps its own first child, including no matching child."""
    database = await load_fixture(provide_sqlite_join_rows())
    first_child = sqlite.scalar(
        sqlite.select(LocalChild.id)
        .where(LocalChild.parent_id.eq_col(LocalParent.id))
        .order_by(LocalChild.id.asc())
        .limit(1)
    )
    query = (
        sqlite.select(LocalParent.tenant, first_child, LocalParent.count_all())
        .group_by(LocalParent.id, LocalParent.tenant)
        .order_by(LocalParent.id.asc())
    )

    async with database.transaction() as transaction:
        rows = await transaction.fetch_all(query)

    assert_eq(rows, [(1, 10, 1), (2, 12, 1), (3, None, 1)])


@test(mark="slow")
async def native_grouped_scalar_keeps_outer_key_correlation() -> None:
    """MariaDB preserves per-group correlation through scalar SQL NULL decoding."""
    database = await load_fixture(provide_mariadb_join_rows())
    first_child = mariadb.scalar(
        mariadb.select(MariaChild.id)
        .where(MariaChild.parent_id.eq_col(MariaParent.id))
        .order_by(MariaChild.id.asc())
        .limit(1)
    )
    query = (
        mariadb.select(MariaParent.tenant, first_child, MariaParent.count_all())
        .group_by(MariaParent.id, MariaParent.tenant)
        .order_by(MariaParent.id.asc())
    )

    async with database.transaction() as transaction:
        rows = await transaction.fetch_all(query)

    assert_eq(rows, [(1, 10, 1), (2, 12, 1), (3, None, 1)])
