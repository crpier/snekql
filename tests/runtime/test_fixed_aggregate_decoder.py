"""COUNT/AVG normalize SQL results independently of source-column policies."""

from typing import Annotated, Any, ClassVar, cast

from annotated_types import Ge
from snektest import Param, assert_eq, assert_is, load_fixture, test

from snekql import mariadb, sqlite
from snekql.storage import Attr
from tests.helpers import initialized_database, provide_mariadb_server


def source_policies(column: Attr[Any, Any, Any, Any, Any]) -> Any:
    column.__decode_with_policy__ = lambda _raw, **_kwargs: 999
    column.__decode_sum__ = lambda _raw: 999
    column.__encode_sum_comparison__ = lambda value: value
    return column


class SqlStatistics[S = sqlite.Pending](sqlite.Model[S]):
    __row_type__: ClassVar[sqlite.ReadType[SqlStatistics[sqlite.Row]]]
    id: SqlStatistics.Col[int] = sqlite.Integer(primary_key=True)
    units: SqlStatistics.Col[Annotated[int, Ge(0)] | None] = sqlite.Integer(
        nullable=True
    )
    custom: SqlStatistics.Col[Annotated[int, Ge(0)] | None] = source_policies(
        sqlite.Integer(nullable=True)
    )


class NativeStatistics[S = mariadb.Pending](mariadb.Model[S]):
    __row_type__: ClassVar[mariadb.ReadType[NativeStatistics[mariadb.Row]]]
    id: NativeStatistics.Col[int] = mariadb.Integer(primary_key=True)
    units: NativeStatistics.Col[Annotated[int, Ge(0)] | None] = mariadb.Integer(
        nullable=True
    )
    custom: NativeStatistics.Col[Annotated[int, Ge(0)] | None] = source_policies(
        mariadb.Integer(nullable=True)
    )


@test(
    [Param(backend, name=backend) for backend in ("sqlite", "mariadb")],
    [Param(mode, name=mode) for mode in ("buffered", "streamed")],
    mark="medium",
)
async def fixed_aggregates_preserve_numeric_types_nulls_and_policy_independence(
    backend: str, mode: str
) -> None:
    api: Any = sqlite if backend == "sqlite" else mariadb
    model: Any = SqlStatistics if backend == "sqlite" else NativeStatistics
    if backend == "sqlite":
        database = await initialized_database(
            database=":memory:", models=[SqlStatistics]
        )
        table = "sql_statistics"
    else:
        server = await load_fixture(provide_mariadb_server())
        database = await initialized_database(
            server.config(), models=[NativeStatistics]
        )
        table = "native_statistics"
    async with database as db, db.transaction() as tx:
        await tx.execute(
            api.raw(
                f"INSERT INTO {table} (id, units, custom) VALUES (1,-5,-5),(2,2,2),(3,NULL,NULL)"
            )
        )
        query = api.select(
            model.count_all(),
            model.units.count(),
            model.units.avg(),
            model.custom.count(),
            model.custom.avg(),
        )
        for validate in (False, True, False):
            for selected, expected in (
                (query, (3, 2, -1.5, 2, -1.5)),
                (query.where(model.units.gt(99)), (0, 0, None, 0, None)),
                (query.where(model.units.is_null()), (1, 0, None, 0, None)),
            ):
                if mode == "buffered":
                    rows = await tx.fetch_all(selected, validate=validate)
                else:
                    async with tx.fetch_chunks(
                        selected, size=1, validate=validate
                    ) as chunks:
                        rows = [row async for chunk in chunks for row in chunk]
                assert_eq(rows, [expected])
                row = cast("tuple[object, ...]", rows[0])
                for index in (0, 1, 3):
                    assert_is(type(row[index]), int)
                for index in (2, 4):
                    if expected[index] is not None:
                        assert_is(type(row[index]), float)
        scalar_query = api.select(
            model.id,
            api.scalar(api.select(model.count_all()).limit(0)),
            api.scalar(api.select(model.units.avg()).limit(0)),
        ).order_by(model.id.asc())
        assert_eq(
            await tx.fetch_all(scalar_query),
            [(1, None, None), (2, None, None), (3, None, None)],
        )
