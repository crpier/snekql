"""SUM keeps numeric policies distinct from projection codecs and validation."""

from typing import Annotated, Any, ClassVar, cast

from annotated_types import Ge
from snektest import Param, assert_eq, assert_is, load_fixture, test

from snekql import mariadb, sqlite
from snekql.storage import Attr
from tests.helpers import initialized_database, provide_mariadb_server
from tests.query.test_column_protocol_dispatch import PolicySqlReading


def numeric_policy(column: Attr[Any, Any, Any, Any, Any], *, complete: bool) -> Any:
    column.__decode_sum__ = lambda raw: cast("int", raw) + 1000
    if complete:
        column.__encode_sum_comparison__ = lambda value: value
    return column


class NumericReading[S = sqlite.Pending](sqlite.Model[S]):
    __row_type__: ClassVar[sqlite.ReadType[NumericReading[sqlite.Row]]]
    value: NumericReading.Col[int] = numeric_policy(sqlite.Integer(), complete=True)


class IncompleteReading[S = sqlite.Pending](sqlite.Model[S]):
    __row_type__: ClassVar[sqlite.ReadType[IncompleteReading[sqlite.Row]]]
    value: IncompleteReading.Col[int] = numeric_policy(sqlite.Integer(), complete=False)


class OrdinaryReading[S = sqlite.Pending](sqlite.Model[S]):
    __row_type__: ClassVar[sqlite.ReadType[OrdinaryReading[sqlite.Row]]]
    value: OrdinaryReading.Col[int] = sqlite.Integer()


@test(
    [
        Param(kind, name=kind)
        for kind in ("ordinary", "projection_policy", "numeric", "incomplete")
    ],
    [Param(mode, name=mode) for mode in ("buffered", "streamed")],
    mark="medium",
)
async def sum_honors_only_complete_numeric_policies(kind: str, mode: str) -> None:
    model: Any = {
        "ordinary": OrdinaryReading,
        "projection_policy": PolicySqlReading,
        "numeric": NumericReading,
        "incomplete": IncompleteReading,
    }[kind]
    async with (
        await initialized_database(database=":memory:", models=[model]) as db,
        db.transaction() as tx,
    ):
        values = (
            [model(key=1, value=7), model(key=2, value=8)]
            if kind == "projection_policy"
            else [model(value=7), model(value=8)]
        )
        await tx.execute(sqlite.insert_many(model, values))
        query = sqlite.select(model.value.sum(), model.value.avg(), model.value.count())
        for validate in (False, True, False):
            for empty in (False, True):
                selected = query.where(model.value.gt(99)) if empty else query
                if mode == "buffered":
                    rows = await tx.fetch_all(selected, validate=validate)
                else:
                    async with tx.fetch_chunks(
                        selected, size=1, validate=validate
                    ) as chunks:
                        rows = [row async for chunk in chunks for row in chunk]
                expected = (
                    (None, None, 0)
                    if empty
                    else (1015 if kind == "numeric" else 15, 7.5, 2)
                )
                assert_eq(rows, [expected])
                if not empty:
                    assert_is(type(cast("tuple[object, ...]", rows[0])[0]), int)
                    assert_is(type(cast("tuple[object, ...]", rows[0])[1]), float)


class SqlTotals[S = sqlite.Pending](sqlite.Model[S]):
    __row_type__: ClassVar[sqlite.ReadType[SqlTotals[sqlite.Row]]]
    units: SqlTotals.Col[Annotated[int, Ge(0)]] = sqlite.Integer()
    amount: SqlTotals.Col[float] = sqlite.Real()


class NativeTotals[S = mariadb.Pending](mariadb.Model[S]):
    __row_type__: ClassVar[mariadb.ReadType[NativeTotals[mariadb.Row]]]
    units: NativeTotals.Col[Annotated[int, Ge(0)]] = mariadb.Integer()
    amount: NativeTotals.Col[float] = mariadb.Real()


@test(
    [Param(backend, name=backend) for backend in ("sqlite", "mariadb")], mark="medium"
)
async def sums_normalize_storage_numbers_without_validating_column_domain(
    backend: str,
) -> None:
    api: Any = sqlite if backend == "sqlite" else mariadb
    model: Any = SqlTotals if backend == "sqlite" else NativeTotals
    if backend == "sqlite":
        database = await initialized_database(database=":memory:", models=[SqlTotals])
        table = "sql_totals"
    else:
        server = await load_fixture(provide_mariadb_server())
        database = await initialized_database(server.config(), models=[NativeTotals])
        table = "native_totals"
    async with database as db, db.transaction() as tx:
        await tx.execute(
            api.raw(f"INSERT INTO {table} (units, amount) VALUES (-5, 1.25), (2, 2.5)")
        )
        query = api.select(model.units.sum(), model.amount.sum())
        for validate in (False, True, False):
            rows = await tx.fetch_all(query, validate=validate)
            assert_eq(rows, [(-3, 3.75)])
            assert_is(type(cast("Any", rows[0])[0]), int)
            assert_is(type(cast("Any", rows[0])[1]), float)
            assert_eq(
                await tx.fetch_all(query.where(model.amount.gt(99)), validate=validate),
                [(None, None)],
            )
