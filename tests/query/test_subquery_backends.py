"""Nested reads must retain their declared backend during compilation."""

from typing import ClassVar

from snektest import assert_raises, test

from snekql import mariadb, sqlite


class LocalAccount[State = sqlite.Pending](sqlite.Model[State]):
    """SQLite account used as the enclosing query source."""

    __row_type__: ClassVar[sqlite.ReadType[LocalAccount[sqlite.Row]]]
    id: sqlite.Col[int] = sqlite.Integer(primary_key=True)


class RemoteAccount[State = mariadb.Pending](mariadb.Model[State]):
    """MariaDB account that must not be read on a SQLite connection."""

    __row_type__: ClassVar[mariadb.ReadType[RemoteAccount[mariadb.Row]]]
    id: mariadb.Col[int] = mariadb.Integer(primary_key=True)


@test()
def exists_cannot_read_another_backend() -> None:
    """EXISTS must not silently compile a foreign model in the outer dialect."""
    query = sqlite.select(LocalAccount).where(
        mariadb.exists(mariadb.select(RemoteAccount).all())
    )

    with assert_raises(sqlite.QueryCompilationError):
        query.compile()


@test()
def mariadb_exists_cannot_read_sqlite() -> None:
    """The backend check applies in both directions."""
    query = mariadb.select(RemoteAccount).where(
        sqlite.exists(sqlite.select(LocalAccount).all())
    )

    with assert_raises(mariadb.QueryCompilationError):
        query.compile()


@test()
def scalar_comparison_cannot_read_another_backend() -> None:
    """Scalar comparisons cannot bypass the nested SELECT backend check."""
    query = sqlite.select(LocalAccount).where(
        LocalAccount.id.eq_col(mariadb.scalar(mariadb.select(RemoteAccount.id).all()))
    )

    with assert_raises(sqlite.QueryCompilationError):
        query.compile()


@test()
def membership_cannot_read_another_backend() -> None:
    """IN subqueries must not read a foreign model in the outer dialect."""
    query = sqlite.select(LocalAccount).where(
        LocalAccount.id.in_subquery(mariadb.select(RemoteAccount.id).all())
    )

    with assert_raises(sqlite.QueryCompilationError):
        query.compile()


@test()
def delete_cannot_read_another_backend() -> None:
    """A foreign EXISTS predicate must fail before any rows can be deleted."""
    query = sqlite.delete(LocalAccount).where(
        mariadb.exists(mariadb.select(RemoteAccount).all())
    )

    with assert_raises(sqlite.QueryCompilationError):
        query.compile()


@test()
def update_cannot_read_another_backend() -> None:
    """A foreign EXISTS predicate must fail before any rows can be changed."""
    query = (
        sqlite.update(LocalAccount)
        .set(LocalAccount.id.to(2))
        .where(mariadb.exists(mariadb.select(RemoteAccount).all()))
    )

    with assert_raises(sqlite.QueryCompilationError):
        query.compile()
