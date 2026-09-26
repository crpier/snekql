"""Self-join result shapes on real SQLite and MariaDB databases."""

from collections.abc import AsyncGenerator
from typing import ClassVar, assert_type
from uuid import UUID

from snektest import assert_eq, fixture, load_fixture, test

from snekql import mariadb, sqlite
from tests.query.test_table_aliases import ManagerRole, ReviewerRole
from tests.runtime.test_join_predicates import (
    LocalParent,
    MariaParent,
    provide_mariadb_join_rows,
    provide_sqlite_join_rows,
)


@test(mark="medium")
async def sqlite_repeated_left_joins_materialize_original_models() -> None:
    """Each alias has its own nullable slot, with no synthetic model instances."""
    database = await load_fixture(provide_sqlite_join_rows())
    manager = sqlite.alias(LocalParent, ManagerRole, name="manager")
    reviewer = sqlite.alias(LocalParent, ReviewerRole, name="reviewer")
    query = (
        sqlite.select(LocalParent)
        .left_join(
            manager,
            on=LocalParent.id.eq_col(manager.column(LocalParent.id))
            & manager.column(LocalParent.id).lt(3),
        )
        .left_join(
            reviewer,
            on=LocalParent.id.eq_col(reviewer.column(LocalParent.id))
            & reviewer.column(LocalParent.id).gt(1),
        )
        .order_by(LocalParent.id.asc())
    )

    async with database.transaction() as transaction:
        rows = await transaction.fetch_all(query)

    assert_type(
        rows,
        list[
            tuple[
                LocalParent[sqlite.Row],
                LocalParent[sqlite.Row] | None,
                LocalParent[sqlite.Row] | None,
            ]
        ],
    )
    assert_eq(
        [
            (
                parent.id,
                manager.id if manager is not None else None,
                reviewer.id if reviewer is not None else None,
            )
            for parent, manager, reviewer in rows
        ],
        [(1, 1, None), (2, 2, 2), (3, None, 3)],
    )
    assert_eq(type(rows[0][1]), LocalParent)


@test(mark="slow")
async def mariadb_repeated_left_joins_materialize_original_models() -> None:
    """MariaDB keeps independently nullable roles and original fetched models."""
    database = await load_fixture(provide_mariadb_join_rows())
    manager = mariadb.alias(MariaParent, ManagerRole, name="manager")
    reviewer = mariadb.alias(MariaParent, ReviewerRole, name="reviewer")
    query = (
        mariadb.select(MariaParent)
        .left_join(
            manager,
            on=MariaParent.id.eq_col(manager.column(MariaParent.id))
            & manager.column(MariaParent.id).lt(3),
        )
        .left_join(
            reviewer,
            on=MariaParent.id.eq_col(reviewer.column(MariaParent.id))
            & reviewer.column(MariaParent.id).gt(1),
        )
        .order_by(MariaParent.id.asc())
    )

    async with database.transaction() as transaction:
        rows = await transaction.fetch_all(query)

    assert_type(
        rows,
        list[
            tuple[
                MariaParent[mariadb.Row],
                MariaParent[mariadb.Row] | None,
                MariaParent[mariadb.Row] | None,
            ]
        ],
    )
    assert_eq(
        [
            (
                parent.id,
                manager.id if manager is not None else None,
                reviewer.id if reviewer is not None else None,
            )
            for parent, manager, reviewer in rows
        ],
        [(1, 1, None), (2, 2, 2), (3, None, 3)],
    )
    assert_eq(type(rows[0][1]), MariaParent)


@test(mark="medium")
async def alias_as_from_source_returns_original_fetched_models() -> None:
    """A standalone alias select decodes through the underlying Table Model."""
    database = await load_fixture(provide_sqlite_join_rows())
    manager = sqlite.alias(LocalParent, ManagerRole, name="manager")

    async with database.transaction() as transaction:
        rows = await transaction.fetch_all(
            sqlite.select(manager).order_by(manager.column(LocalParent.id).asc())
        )

    assert_type(rows, list[LocalParent[sqlite.Row]])
    assert_eq([row.id for row in rows], [1, 2, 3])
    assert_eq(type(rows[0]), LocalParent)


@test(mark="medium")
async def alias_projection_keeps_scalar_types() -> None:
    """Role-bound columns participate in scalar selects and aggregates."""
    database = await load_fixture(provide_sqlite_join_rows())
    manager = sqlite.alias(LocalParent, ManagerRole, name="manager")

    async with database.transaction() as transaction:
        count = await transaction.fetch_one(
            sqlite.select(manager.column(LocalParent.id).count())
        )

    assert_type(count, int)
    assert_eq(count, 3)


@test(mark="medium")
async def correlated_alias_subquery_preserves_outer_role() -> None:
    """Two roles of one physical table remain distinct across nested SELECTs."""
    database = await load_fixture(provide_sqlite_join_rows())
    manager = sqlite.alias(LocalParent, ManagerRole, name="manager")
    reviewer = sqlite.alias(LocalParent, ReviewerRole, name="reviewer")
    query = (
        sqlite.select(manager.column(LocalParent.id))
        .where(
            sqlite.exists(
                sqlite.select(reviewer.column(LocalParent.id)).where(
                    reviewer.column(LocalParent.id).gt_col(
                        manager.column(LocalParent.id)
                    )
                )
            )
        )
        .order_by(manager.column(LocalParent.id).asc())
    )

    async with database.transaction() as transaction:
        rows = await transaction.fetch_all(query)

    assert_eq(rows, [1, 2])


class Document[S = sqlite.Pending](sqlite.Model[S]):
    """A logical value whose wire type differs from its Python type."""

    __row_type__: ClassVar[sqlite.ReadType[Document[sqlite.Row]]]

    token: Document.Col[UUID] = sqlite.Text(primary_key=True)


@fixture
async def provide_documents() -> AsyncGenerator[sqlite.Database]:
    """Seed a UUID before binding it through an alias."""
    async with await sqlite.Database.initialize(database=":memory:") as database:
        await database.migrate({"001_document": sqlite.scaffold([Document])})
        async with database.transaction() as transaction:
            await transaction.execute(
                sqlite.insert(
                    Document(token=UUID("12345678-1234-5678-1234-567812345678"))
                )
            )
        yield database


@test(mark="medium")
async def alias_columns_preserve_logical_codecs() -> None:
    """The role changes SQL ownership, not UUID binding or row decoding."""
    database = await load_fixture(provide_documents())
    document = sqlite.alias(Document, ManagerRole, name="document_role")
    token = UUID("12345678-1234-5678-1234-567812345678")
    query = sqlite.select(document.column(Document.token)).where(
        document.column(Document.token).eq(token)
    )

    async with database.transaction() as transaction:
        rows = await transaction.fetch_all(query)

    assert_type(rows, list[UUID])
    assert_eq(rows, [token])
