"""Fetch contracts apply to the final SQL result without SELECT acknowledgment."""

from collections.abc import AsyncGenerator
from dataclasses import dataclass
from typing import ClassVar, Literal

from snektest import Param, assert_eq, assert_raises, fixture, load_fixture, test

from snekql import mariadb, sqlite
from tests.helpers import initialized_database, provide_mariadb_server
from tests.query.test_select_readiness import EntryRole, EntrySummary


class LocalEntry[S = sqlite.Pending](sqlite.Model[S]):
    __row_type__: ClassVar[sqlite.ReadType[LocalEntry[sqlite.Row]]]
    id: sqlite.Col[int] = sqlite.Integer(primary_key=True)
    nickname: sqlite.Col[str | None] = sqlite.Text(default=None)


class MariaEntry[S = mariadb.Pending](mariadb.Model[S]):
    __row_type__: ClassVar[mariadb.ReadType[MariaEntry[mariadb.Row]]]
    id: mariadb.Col[int] = mariadb.Integer(primary_key=True)
    nickname: mariadb.Col[str | None] = mariadb.Text(default=None)


@dataclass(frozen=True)
class FetchCase:
    """Expected consumption of a known dataset after SQL pagination."""

    expected: object
    method: Literal["all", "one", "optional", "chunks"]
    rows: int
    error: type[sqlite.ResultCardinalityError] | None = None
    limit: int | None = None
    offset: int = 0


CASES = [
    Param(FetchCase([], "all", 0), name="all-empty"),
    Param(FetchCase([(1, None)], "all", 1), name="all-one"),
    Param(FetchCase([(1, None), (2, None)], "all", 2), name="all-many"),
    Param(FetchCase(None, "one", 0, sqlite.NoResultError), name="one-empty"),
    Param(FetchCase((1, None), "one", 1), name="one-present-null"),
    Param(FetchCase(None, "one", 2, sqlite.MultipleResultsError), name="one-many"),
    Param(FetchCase(None, "optional", 0), name="optional-empty"),
    Param(FetchCase((1, None), "optional", 1), name="optional-present-null"),
    Param(
        FetchCase(None, "optional", 2, sqlite.MultipleResultsError),
        name="optional-many",
    ),
    Param(FetchCase((1, None), "one", 2, limit=1), name="limit-chooses-first"),
    Param(
        FetchCase((2, None), "one", 2, limit=1, offset=1), name="offset-chooses-second"
    ),
    Param(FetchCase(None, "optional", 2, limit=0), name="limit-zero"),
    Param(
        FetchCase(None, "one", 0, sqlite.NoResultError, limit=1),
        name="limit-does-not-create-row",
    ),
    Param(
        FetchCase(None, "one", 2, sqlite.NoResultError, offset=2),
        name="offset-removes-rows",
    ),
    Param(FetchCase([(1, None)], "all", 2, limit=1), name="limit-retains-list"),
    Param(FetchCase([(1, None), (2, None)], "chunks", 2), name="stream-batches"),
]


@fixture
async def local_entries(rows: int) -> AsyncGenerator[sqlite.Database]:
    """Seed nullable rows before the read transaction."""
    async with await initialized_database(
        database=":memory:", models=[LocalEntry]
    ) as database:
        async with database.transaction() as transaction:
            await transaction.execute(
                sqlite.insert_many(
                    LocalEntry, [LocalEntry(id=index + 1) for index in range(rows)]
                )
            )
        yield database


@fixture
async def maria_entries(rows: int) -> AsyncGenerator[mariadb.Database]:
    """Use an actual MariaDB database with the same logical row contract."""
    server = await load_fixture(provide_mariadb_server())
    async with await initialized_database(
        server.config(), models=[MariaEntry]
    ) as database:
        async with database.transaction() as transaction:
            await transaction.execute(
                mariadb.insert_many(
                    MariaEntry, [MariaEntry(id=index + 1) for index in range(rows)]
                )
            )
        yield database


@test(CASES, mark="medium")
async def sqlite_fetch_checks_final_result(case: FetchCase) -> None:
    """Zero, one, and multiple rows keep their meaning after SQL pagination."""
    database = await load_fixture(local_entries(case.rows))
    query = (
        sqlite.select(LocalEntry.id, LocalEntry.nickname)
        .order_by(LocalEntry.id.asc())
        .offset(case.offset)
    )
    if case.limit is not None:
        query = query.limit(case.limit)

    async with database.transaction() as transaction:
        if case.error is not None:
            with assert_raises(case.error):
                if case.method == "one":
                    await transaction.fetch_one(query)
                else:
                    await transaction.fetch_one_or_none(query)
            return
        if case.method == "all":
            observed = await transaction.fetch_all(query)
        elif case.method == "one":
            observed = await transaction.fetch_one(query)
        elif case.method == "optional":
            observed = await transaction.fetch_one_or_none(query)
        else:
            observed = []
            async with transaction.fetch_chunks(query, size=1) as stream:
                async for batch in stream:
                    observed.extend(batch)

    assert_eq(observed, case.expected)


@test(CASES, mark="slow")
async def mariadb_fetch_checks_final_result(case: FetchCase) -> None:
    """MariaDB enforces the same consumption contracts as SQLite."""
    database = await load_fixture(maria_entries(case.rows))
    query = (
        mariadb.select(MariaEntry.id, MariaEntry.nickname)
        .order_by(MariaEntry.id.asc())
        .offset(case.offset)
    )
    if case.limit is not None:
        query = query.limit(case.limit)

    async with database.transaction() as transaction:
        if case.error is not None:
            with assert_raises(case.error):
                if case.method == "one":
                    await transaction.fetch_one(query)
                else:
                    await transaction.fetch_one_or_none(query)
            return
        if case.method == "all":
            observed = await transaction.fetch_all(query)
        elif case.method == "one":
            observed = await transaction.fetch_one(query)
        elif case.method == "optional":
            observed = await transaction.fetch_one_or_none(query)
        else:
            observed = []
            async with transaction.fetch_chunks(query, size=1) as stream:
                async for batch in stream:
                    observed.extend(batch)

    assert_eq(observed, case.expected)


@test(
    [
        Param(kind, name=kind)
        for kind in (
            "model",
            "count",
            "group",
            "cte",
            "union",
            "exists",
            "membership",
            "scalar",
            "explain",
        )
    ],
    mark="medium",
)
async def sqlite_unfiltered_composition_executes(kind: str) -> None:
    """Ordinary result shapes compose without an acknowledgment at any level."""
    database = await load_fixture(local_entries(2))

    async with database.transaction() as transaction:
        if kind == "model":
            rows = await transaction.fetch_all(
                sqlite.select(LocalEntry).order_by(LocalEntry.id.asc())
            )
            observed = [row.id for row in rows]
            expected = [1, 2]
        elif kind == "count":
            observed = await transaction.fetch_one(
                sqlite.select(LocalEntry.count_all())
            )
            expected = 2
        elif kind == "group":
            query = (
                sqlite.select(LocalEntry.nickname, LocalEntry.id.count())
                .group_by(LocalEntry.nickname)
                .having(LocalEntry.id.count().gt(1))
            )
            observed = await transaction.fetch_one(query)
            expected = (None, 2)
        elif kind in ("cte", "union"):
            token = LocalEntry.id.label("id")
            named = sqlite.select(LocalEntry).project(EntrySummary, id=token)
            if kind == "cte":
                relation = named.cte(EntryRole, name="entry_summary")
                named_rows = await transaction.fetch_all(
                    sqlite.select(relation).order_by(relation.column(token).asc())
                )
                expected = [1, 2]
            else:
                combined = named.union_all(named)
                named_rows = await transaction.fetch_all(
                    combined.order_by(combined.column(token).asc())
                )
                expected = [1, 1, 2, 2]
            observed = [row.id for row in named_rows]
        elif kind == "exists":
            observed = await transaction.fetch_all(
                sqlite.select(LocalEntry.id)
                .where(sqlite.exists(sqlite.select(LocalEntry.id)))
                .order_by(LocalEntry.id.asc())
            )
            expected = [1, 2]
        elif kind == "membership":
            observed = await transaction.fetch_all(
                sqlite.select(LocalEntry.id)
                .where(LocalEntry.id.in_subquery(sqlite.select(LocalEntry.id)))
                .order_by(LocalEntry.id.asc())
            )
            expected = [1, 2]
        elif kind == "scalar":
            query = sqlite.select(
                LocalEntry.id,
                sqlite.scalar(
                    sqlite.select(LocalEntry.id).order_by(LocalEntry.id.asc()).limit(1)
                ),
            ).order_by(LocalEntry.id.asc())
            observed = await transaction.fetch_all(query)
            expected = [(1, 1), (2, 1)]
        else:
            plan = await transaction.explain(sqlite.select(LocalEntry))
            observed = plan.backend
            expected = "sqlite"

    assert_eq(observed, expected)


@test(
    [
        Param(kind, name=kind)
        for kind in (
            "model",
            "count",
            "group",
            "cte",
            "union",
            "exists",
            "membership",
            "scalar",
            "explain",
        )
    ],
    mark="slow",
)
async def mariadb_unfiltered_composition_executes(kind: str) -> None:
    """Ordinary result shapes compose without an acknowledgment at any level."""
    database = await load_fixture(maria_entries(2))

    async with database.transaction() as transaction:
        if kind == "model":
            rows = await transaction.fetch_all(
                mariadb.select(MariaEntry).order_by(MariaEntry.id.asc())
            )
            observed = [row.id for row in rows]
            expected = [1, 2]
        elif kind == "count":
            observed = await transaction.fetch_one(
                mariadb.select(MariaEntry.count_all())
            )
            expected = 2
        elif kind == "group":
            query = (
                mariadb.select(MariaEntry.nickname, MariaEntry.id.count())
                .group_by(MariaEntry.nickname)
                .having(MariaEntry.id.count().gt(1))
            )
            observed = await transaction.fetch_one(query)
            expected = (None, 2)
        elif kind in ("cte", "union"):
            token = MariaEntry.id.label("id")
            named = mariadb.select(MariaEntry).project(EntrySummary, id=token)
            if kind == "cte":
                relation = named.cte(EntryRole, name="entry_summary")
                named_rows = await transaction.fetch_all(
                    mariadb.select(relation).order_by(relation.column(token).asc())
                )
                expected = [1, 2]
            else:
                combined = named.union_all(named)
                named_rows = await transaction.fetch_all(
                    combined.order_by(combined.column(token).asc())
                )
                expected = [1, 1, 2, 2]
            observed = [row.id for row in named_rows]
        elif kind == "exists":
            observed = await transaction.fetch_all(
                mariadb.select(MariaEntry.id)
                .where(mariadb.exists(mariadb.select(MariaEntry.id)))
                .order_by(MariaEntry.id.asc())
            )
            expected = [1, 2]
        elif kind == "membership":
            observed = await transaction.fetch_all(
                mariadb.select(MariaEntry.id)
                .where(MariaEntry.id.in_subquery(mariadb.select(MariaEntry.id)))
                .order_by(MariaEntry.id.asc())
            )
            expected = [1, 2]
        elif kind == "scalar":
            query = mariadb.select(
                MariaEntry.id,
                mariadb.scalar(
                    mariadb.select(MariaEntry.id).order_by(MariaEntry.id.asc()).limit(1)
                ),
            ).order_by(MariaEntry.id.asc())
            observed = await transaction.fetch_all(query)
            expected = [(1, 1), (2, 1)]
        else:
            plan = await transaction.explain(mariadb.select(MariaEntry))
            observed = plan.backend
            expected = "mariadb"

    assert_eq(observed, expected)


@test(mark="slow")
async def unfiltered_locking_read_executes_in_write_transaction() -> None:
    """Locking reads retain transaction policy without a row-scope marker."""
    database = await load_fixture(maria_entries(2))

    async with database.transaction(read_only=False) as transaction:
        rows = await transaction.fetch_all(
            mariadb.select(MariaEntry).order_by(MariaEntry.id.asc()).for_update()
        )

    assert_eq([row.id for row in rows], [1, 2])
