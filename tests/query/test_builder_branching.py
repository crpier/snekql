"""Derived builders retain their source query and sibling branches (#481)."""

from typing import Any, ClassVar

from pydantic import BaseModel
from snektest import assert_eq, assert_raises, test

from snekql import mariadb, sqlite
from tests.helpers import initialized_database


class Entry[S = sqlite.Pending](sqlite.Model[S]):
    __row_type__: ClassVar[sqlite.ReadType[Entry[sqlite.Row]]]
    id: sqlite.Col[int] = sqlite.Integer(primary_key=True)
    label: sqlite.Col[str] = sqlite.Text()


@test(mark="fast")
def pagination_branches_keep_every_earlier_clause() -> None:
    base = (
        sqlite.select(Entry.id)
        .where(Entry.id.gt(0))
        .distinct()
        .order_by(Entry.id.asc())
    )
    first = base.limit(1)
    later = base.offset(1).limit(2)

    expected = 'SELECT DISTINCT "id" FROM "entry" WHERE ("id" > ?) ORDER BY "id" ASC'
    assert_eq(base.compile().sql, expected)
    assert_eq(base.compile().params, (0,))
    assert_eq(first.compile().sql, expected + " LIMIT ?")
    assert_eq(first.compile().params, (0, 1))
    assert_eq(later.compile().sql, expected + " LIMIT ? OFFSET ?")
    assert_eq(later.compile().params, (0, 2, 1))


@test(mark="medium")
async def write_and_read_branches_execute_independently() -> None:
    """Assignments, row scope and RETURNING belong to each derived write."""
    async with await initialized_database(
        database=":memory:", models=[Entry]
    ) as database:
        async with database.transaction() as tx:
            await tx.execute(
                sqlite.insert_many(
                    Entry,
                    [Entry(id=1, label="one"), Entry(id=2, label="two")],
                )
            )
        pending = sqlite.update(Entry).set(Entry.label.to("changed"))
        one = pending.where(Entry.id.eq(1)).returning(Entry.label)
        two = pending.where(Entry.id.eq(2)).returning(Entry.id)
        with assert_raises(sqlite.QueryCompilationError):
            pending.compile()
        base = sqlite.select(Entry.id).order_by(Entry.id.asc())
        first = base.limit(1)
        second = base.offset(1).limit(1)
        async with database.transaction() as tx:
            assert_eq(await tx.execute(one), ["changed"])
            assert_eq(await tx.execute(two), [2])
            assert_eq(await tx.fetch_all(first), [1])
            assert_eq(await tx.fetch_all(second), [2])
            assert_eq(await tx.fetch_all(base), [1, 2])
            assert_eq(
                await tx.fetch_all(sqlite.select(Entry.label).order_by(Entry.id.asc())),
                ["changed", "changed"],
            )


@test(mark="medium")
async def conflict_and_delete_branches_keep_their_own_result_shapes() -> None:
    async with (
        await initialized_database(database=":memory:", models=[Entry]) as database,
        database.transaction() as tx,
    ):
        await tx.execute(sqlite.insert(Entry(id=1, label="original")))
        pending = sqlite.insert(Entry(id=1, label="attempt"))
        ignore = pending.on_conflict(Entry.id, action=sqlite.DoNothing)
        change = pending.on_conflict(
            Entry.id, action=sqlite.DoUpdate(Entry.label.to("updated"))
        ).returning(Entry.label)
        assert_eq(
            pending.compile().sql,
            'INSERT INTO "entry" ("id", "label") VALUES (?, ?)',
        )
        assert_eq(pending.compile().params, (1, "attempt"))
        await tx.execute(ignore)
        assert_eq(await tx.fetch_all(sqlite.select(Entry.label)), ["original"])
        assert_eq(await tx.execute(change), "updated")

        remove = sqlite.delete(Entry).where(Entry.id.eq(1))
        labels = remove.returning(Entry.label)
        identifiers = remove.returning(Entry.id)
        assert_eq(remove.compile().sql, 'DELETE FROM "entry" WHERE ("id" = ?)')
        assert_eq(
            identifiers.compile().sql,
            'DELETE FROM "entry" WHERE ("id" = ?) RETURNING "id"',
        )
        assert_eq(await tx.execute(labels), ["updated"])
        assert_eq(await tx.fetch_all(sqlite.select(Entry.id)), [])


class Summary(BaseModel):
    label: str
    count: int


@test(mark="medium")
async def grouped_named_branches_preserve_having_and_materialization() -> None:
    async with (
        await initialized_database(database=":memory:", models=[Entry]) as database,
        database.transaction() as tx,
    ):
        await tx.execute(
            sqlite.insert_many(
                Entry,
                [
                    Entry(id=1, label="shared"),
                    Entry(id=2, label="shared"),
                    Entry(id=3, label="single"),
                ],
            )
        )
        base = (
            sqlite.select(Entry)
            .project(Summary, label=Entry.label, count=Entry.id.count())
            .group_by(Entry.label)
            .having(Entry.id.count().gt(1))
            .order_by(Entry.label.asc())
        )
        first = base.limit(1)
        later = base.limit(1).offset(1)
        assert_eq(await tx.fetch_all(later), [])
        assert_eq(await tx.fetch_all(first), [Summary(label="shared", count=2)])
        assert_eq(await tx.fetch_all(base), [Summary(label="shared", count=2)])


class RemoteEntry[S = mariadb.Pending](mariadb.Model[S]):
    __row_type__: ClassVar[mariadb.ReadType[RemoteEntry[mariadb.Row]]]
    id: mariadb.Col[int] = mariadb.Integer(primary_key=True)


@test(mark="fast")
def derived_queries_still_reject_foreign_owners_and_backends() -> None:
    class Other[S = sqlite.Pending](sqlite.Model[S]):
        __row_type__: ClassVar[sqlite.ReadType[Other[sqlite.Row]]]
        id: sqlite.Col[int] = sqlite.Integer(primary_key=True)

    base = sqlite.select(Entry.id)
    branch = base.limit(2)
    for foreign in (Other.id, RemoteEntry.id):
        # Dynamic input must not evade construction-time ownership checks.
        erased: Any = foreign
        with assert_raises(sqlite.QueryConstructionError):
            branch.where(erased.eq(1))
    assert_eq(base.compile().params, ())
    assert_eq(branch.compile().params, (2,))
