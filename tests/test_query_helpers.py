"""Checked helper annotations retain native query execution behavior."""

from __future__ import annotations

from typing import Any, ClassVar, assert_type

from snektest import Param, assert_eq, assert_is, assert_raises, load_fixture, test

from snekql import mariadb, sqlite
from tests.helpers import initialized_database, provide_mariadb_server


@test(mark="medium")
async def closed_scalar_helper_executes_native_query() -> None:
    """Closing a query keeps its identity and exact scalar result type."""

    class Account[State = sqlite.Pending](sqlite.Model[State]):
        __row_type__: ClassVar[sqlite.ReadType[Account[sqlite.Row]]]
        email: sqlite.Col[str] = sqlite.Text()

    query = sqlite.select(Account.email).all()
    closed: sqlite.ClosedRead[str] = sqlite.ready(query)
    assert_is(closed, query)

    async with await initialized_database(
        database=":memory:", models=[Account]
    ) as database:
        async with database.transaction() as setup:
            await setup.execute(sqlite.insert(Account(email="Ada")))
        async with database.transaction() as transaction:
            emails = await transaction.fetch_all(closed)

    assert_type(emails, list[str])
    assert_eq(emails, ["Ada"])


@test(mark="medium")
async def closed_optional_keeps_null_distinct_from_absence() -> None:
    """A tuple containing SQL NULL is a row, not the absent-row result."""

    class Account[State = sqlite.Pending](sqlite.Model[State]):
        __row_type__: ClassVar[sqlite.ReadType[Account[sqlite.Row]]]
        account_id: sqlite.Col[int] = sqlite.Integer(primary_key=True)
        nickname: sqlite.Col[str | None] = sqlite.Text(default=None)

    def lookup(account_id: int) -> sqlite.ClosedOptional[tuple[int, str | None]]:
        return sqlite.ready(
            sqlite.select(Account.account_id, Account.nickname).where(
                Account.account_id.eq(account_id)
            )
        )

    async with await initialized_database(
        database=":memory:", models=[Account]
    ) as database:
        async with database.transaction() as setup:
            await setup.execute(sqlite.insert(Account(account_id=1)))
        async with database.transaction() as transaction:
            present = await transaction.fetch_one_or_none(lookup(1))
            absent = await transaction.fetch_one_or_none(lookup(2))

    assert_type(present, tuple[int, str | None] | None)
    assert_eq(present, (1, None))
    assert_eq(absent, None)


@test(mark="fast")
def ready_does_not_require_a_database() -> None:
    """Compiling a helper neither requires a connection nor creates its table."""

    class Account[State = sqlite.Pending](sqlite.Model[State]):
        __row_type__: ClassVar[sqlite.ReadType[Account[sqlite.Row]]]
        __tablename__ = "helper_accounts"
        email: sqlite.Col[str] = sqlite.Text()

    query = sqlite.ready(sqlite.select(Account.email).where(Account.email.eq("Ada")))

    assert_eq(
        query.compile().sql, 'SELECT "email" FROM "helper_accounts" WHERE ("email" = ?)'
    )
    assert_eq(query.compile().params, ("Ada",))


@test(
    [
        Param(kind, name=kind)
        for kind in ("unfinished", "missing-source", "write", "foreign", "pretender")
    ],
    mark="fast",
)
def ready_rejects_invalid_queries_after_erasure(kind: str) -> None:
    """Dynamic inputs still go through native read compilation and family checks."""

    class Account[State = sqlite.Pending](sqlite.Model[State]):
        __row_type__: ClassVar[sqlite.ReadType[Account[sqlite.Row]]]
        email: sqlite.Col[str] = sqlite.Text()

    class Post[State = sqlite.Pending](sqlite.Model[State]):
        __row_type__: ClassVar[sqlite.ReadType[Post[sqlite.Row]]]
        title: sqlite.Col[str] = sqlite.Text()

    class Foreign[State = mariadb.Pending](mariadb.Model[State]):
        __row_type__: ClassVar[mariadb.ReadType[Foreign[mariadb.Row]]]
        email: mariadb.Col[str] = mariadb.Text()

    queries: dict[str, Any] = {
        "unfinished": sqlite.select(Account),
        "missing-source": sqlite.select(Account.email, Post.title).all(),
        "write": sqlite.insert(Account(email="Ada")),
        "foreign": mariadb.select(Foreign).all(),
        "pretender": object(),
    }

    with assert_raises(sqlite.QueryCompilationError, sqlite.QueryConstructionError):
        sqlite.ready(queries[kind])


@test(mark="slow")
async def mariadb_closed_helper_materializes_rows() -> None:
    """Closing a MariaDB read leaves native model materialization intact."""
    server = await load_fixture(provide_mariadb_server())

    class Account[State = mariadb.Pending](mariadb.Model[State]):
        __row_type__: ClassVar[mariadb.ReadType[Account[mariadb.Row]]]
        email: mariadb.Col[str] = mariadb.Text()

    def accounts() -> mariadb.ClosedOptional[Account[mariadb.Row]]:
        return mariadb.ready(mariadb.select(Account).all())

    async with await initialized_database(
        server.config(), models=[Account]
    ) as database:
        async with database.transaction() as setup:
            await setup.execute(mariadb.insert(Account(email="Ada")))
        async with database.transaction() as transaction:
            account = await transaction.fetch_one_or_none(accounts())

    assert_type(account, Account[mariadb.Row] | None)
    assert account is not None
    assert_is(type(account), Account)
    assert_eq(account.email, "Ada")


@test(mark="medium")
async def scoped_helper_streams_without_closing() -> None:
    """Generic helpers keep source information and need no ready call."""

    class Account[State = sqlite.Pending](sqlite.Model[State]):
        __row_type__: ClassVar[sqlite.ReadType[Account[sqlite.Row]]]
        email: sqlite.Col[str] = sqlite.Text()

    def stream[Scope, Result](
        transaction: sqlite.Transaction, query: sqlite.ReadQuery[Scope, Result]
    ) -> sqlite.ChunkStream[Result]:
        return transaction.fetch_chunks(query, size=1)

    async with await initialized_database(
        database=":memory:", models=[Account]
    ) as database:
        async with database.transaction() as setup:
            await setup.execute(
                sqlite.insert_many(
                    Account, [Account(email="Ada"), Account(email="Grace")]
                )
            )
        async with database.transaction() as transaction:
            batches: list[list[str]] = []
            async with stream(
                transaction,
                sqlite.select(Account.email).all().order_by(Account.email.asc()),
            ) as chunks:
                assert_type(chunks, sqlite.ChunkStream[str])
                batches.extend([batch async for batch in chunks])

    assert_eq(batches, [["Ada"], ["Grace"]])
