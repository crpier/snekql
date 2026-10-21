"""Pagination retains its strict public call contract on every SELECT shape."""

from enum import IntEnum
from typing import Any, ClassVar

from pydantic import BaseModel, ValidationError
from snektest import (
    Param,
    assert_eq,
    assert_isinstance,
    assert_not_in,
    assert_raises,
    test,
)

from snekql import mariadb, sqlite


class SqlMember[S = sqlite.Pending](sqlite.Model[S]):
    """SQLite source for model and compound selections."""

    __row_type__: ClassVar[sqlite.ReadType[SqlMember[sqlite.Row]]]
    member_id: sqlite.Col[int] = sqlite.Integer(primary_key=True)


class MariaMember[S = mariadb.Pending](mariadb.Model[S]):
    """MariaDB source sharing the result contract."""

    __row_type__: ClassVar[mariadb.ReadType[MariaMember[mariadb.Row]]]
    member_id: mariadb.Col[int] = mariadb.Integer(primary_key=True)


class MemberId(BaseModel):
    """Named result required by compound selections."""

    member_id: int


def query_for(backend: str, shape: str) -> Any:
    """Deliberately exercise the public interface as an untyped caller."""
    if backend == "sqlite":
        query = sqlite.select(SqlMember)
        named = query.project(
            MemberId, member_id=SqlMember.member_id.label("member_id")
        )
        return named.union_all(named) if shape == "compound" else query
    maria_query = mariadb.select(MariaMember)
    maria_named = maria_query.project(
        MemberId, member_id=MariaMember.member_id.label("member_id")
    )
    return maria_named.union_all(maria_named) if shape == "compound" else maria_query


BACKENDS = [Param("sqlite", name="sqlite"), Param("mariadb", name="mariadb")]
SHAPES = [Param("model", name="model"), Param("compound", name="compound")]


@test(BACKENDS, SHAPES, mark="fast")
def pagination_rejects_invalid_values_and_call_shapes(backend: str, shape: str) -> None:
    """Bad calls keep domain errors, Pydantic causes and redacted messages."""
    query = query_for(backend, shape)
    calls = [
        ((True,), {}),
        ((-1,), {}),
        ((1.0,), {}),
        (("private-pagination-input",), {}),
        ((None,), {}),
        ((), {}),
        ((1, 2), {}),
        ((1,), {"value": 2}),
        ((1,), {"unexpected": 2}),
    ]
    for name in ("limit", "offset"):
        method = getattr(query, name)
        for args, kwargs in calls:
            with assert_raises(sqlite.QueryConstructionError) as error:
                method(*args, **kwargs)
            assert_isinstance(error.exception.__cause__, ValidationError)
            assert_not_in("private-pagination-input", str(error.exception))


class PageSize(IntEnum):
    """Integer subtypes still use the existing normalizing validator."""

    TWO = 2


@test(BACKENDS, SHAPES, mark="fast")
def valid_pagination_keeps_values_and_independent_branches(
    backend: str, shape: str
) -> None:
    """Zero, large ints, keywords and integer subtypes keep their SQL meaning."""
    base = query_for(backend, shape)
    empty = base.limit(0).offset(0)
    keyword = base.limit(value=PageSize.TWO).offset(value=1)
    subtype = base.limit(PageSize.TWO).offset(1)
    large = base.limit(2**70)
    assert_eq(base.compile().params, ())
    assert_eq(empty.compile().params, (0, 0))
    assert_eq(empty.compile().sql.count("LIMIT"), 1)
    assert_eq(keyword.compile().params, (2, 1))
    assert_eq(subtype.compile().params, (2, 1))
    assert_eq(type(subtype.compile().params[0]), int)
    assert_eq(large.compile().params, (2**70,))


@test(SHAPES, mark="medium")
async def pagination_applies_to_rows_without_changing_the_base(shape: str) -> None:
    """Zero and independent slices apply to ordinary and whole compound results."""
    async with await sqlite.Database.initialize(database=":memory:") as database:
        await database.migrate({"001_members": sqlite.scaffold([SqlMember])})
        async with database.transaction() as transaction:
            await transaction.execute(
                sqlite.insert_many(
                    SqlMember, [SqlMember(member_id=number) for number in (1, 2, 3)]
                )
            )
            base: Any = sqlite.select(SqlMember).order_by(SqlMember.member_id.asc())
            expected = [1, 2, 3]
            page = [2, 3]
            if shape == "compound":
                token = SqlMember.member_id.label("member_id")
                left = sqlite.select(SqlMember).project(MemberId, member_id=token)
                combined = left.union_all(left)
                base = combined.order_by(combined.column(token).asc())
                expected = [1, 1, 2, 2, 3, 3]
                page = [1, 2]
            empty = base.limit(0)
            sliced = base.limit(2).offset(1)
            assert_eq(await transaction.fetch_all(empty), [])
            assert_eq(
                [row.member_id for row in await transaction.fetch_all(sliced)], page
            )
            assert_eq(
                [row.member_id for row in await transaction.fetch_all(base)], expected
            )
