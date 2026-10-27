"""Derived totals use retained numeric domains, not intermediate codecs."""

from typing import Annotated, Any, ClassVar, cast

from annotated_types import Ge
from pydantic import BaseModel, field_validator
from snektest import Param, assert_eq, assert_is, load_fixture, test

from snekql import mariadb, sqlite
from tests.helpers import initialized_database, provide_mariadb_server
from tests.runtime.test_fixed_aggregate_decoder import source_policies


class SqlAmounts[S = sqlite.Pending](sqlite.Model[S]):
    __row_type__: ClassVar[sqlite.ReadType[SqlAmounts[sqlite.Row]]]
    id: SqlAmounts.Col[int] = sqlite.Integer(primary_key=True)
    units: SqlAmounts.Col[Annotated[int, Ge(0)] | None] = source_policies(
        sqlite.Integer(nullable=True)
    )
    amount: SqlAmounts.Col[float | None] = sqlite.Real(nullable=True)


class NativeAmounts[S = mariadb.Pending](mariadb.Model[S]):
    __row_type__: ClassVar[mariadb.ReadType[NativeAmounts[mariadb.Row]]]
    id: NativeAmounts.Col[int] = mariadb.Integer(primary_key=True)
    units: NativeAmounts.Col[Annotated[int, Ge(0)] | None] = source_policies(
        mariadb.Integer(nullable=True)
    )
    amount: NativeAmounts.Col[float | None] = mariadb.Real(nullable=True)


class Intermediate(BaseModel):
    key: int
    total: int | None
    mean: float | None
    quantity: int | None

    @field_validator("total")
    @classmethod
    def reject_intermediate_materialization(cls, _value: int | None) -> int | None:
        msg = "intermediate result validation must not run"
        raise ValueError(msg)


class Final(BaseModel):
    total: int | None
    mean: float | None
    quantity: int | None

    @field_validator("total")
    @classmethod
    def transform_final_result(cls, value: int | None) -> int | None:
        return None if value is None else value + 1000


class InnerRole:
    pass


class OuterRole:
    pass


class AliasRole:
    pass


@test(
    [Param(backend, name=backend) for backend in ("sqlite", "mariadb")],
    [Param(mode, name=mode) for mode in ("buffered", "streamed")],
    [Param(kind, name=kind) for kind in ("columns", "aggregates")],
    mark="medium",
)
async def nested_aliased_sums_keep_numeric_provenance(
    backend: str, mode: str, kind: str
) -> None:
    api: Any = sqlite if backend == "sqlite" else mariadb
    model: Any = SqlAmounts if backend == "sqlite" else NativeAmounts
    if backend == "sqlite":
        database = await initialized_database(database=":memory:", models=[SqlAmounts])
        table = "sql_amounts"
    else:
        server = await load_fixture(provide_mariadb_server())
        database = await initialized_database(server.config(), models=[NativeAmounts])
        table = "native_amounts"
    async with database as db, db.transaction() as tx:
        await tx.execute(
            api.raw(
                f"INSERT INTO {table} (id, units, amount) VALUES (1,-5,1.25),(2,2,2.5),(3,NULL,NULL)"
            )
        )
        assert_eq(await tx.fetch_all(api.select(model.units.sum())), [999])
        for subset in ("all", "null", "empty"):
            base = api.select(model)
            if subset == "null":
                base = base.where(model.id.eq(3))
            if subset == "empty":
                base = base.where(model.id.gt(99))
            expressions = (
                (model.id, model.units, model.amount, model.id)
                if kind == "columns"
                else (
                    model.count_all(),
                    model.units.sum(),
                    model.units.avg(),
                    model.units.count(),
                )
            )
            labels = tuple(
                expression.label(name)
                for expression, name in zip(
                    expressions, ("key", "total", "mean", "quantity"), strict=True
                )
            )
            inner = base.project(
                Intermediate,
                **dict(zip(("key", "total", "mean", "quantity"), labels, strict=True)),
            ).cte(InnerRole, name="inner_amounts")
            outputs = tuple(
                inner.column(token).label(name)
                for token, name in zip(
                    labels, ("key", "total", "mean", "quantity"), strict=True
                )
            )
            outer = (
                api.select(inner)
                .project(
                    Intermediate,
                    **dict(
                        zip(("key", "total", "mean", "quantity"), outputs, strict=True)
                    ),
                )
                .cte(OuterRole, name="outer_amounts")
            )
            source = api.alias(outer, AliasRole, name="amounts")
            key, total, mean, quantity = (source.column(token) for token in outputs)
            query = api.select(source).project(
                Final, total=total.sum(), mean=mean.sum(), quantity=quantity.sum()
            )
            expected = {
                ("columns", "all"): (997, 3.75, 6),
                ("columns", "null"): (None, None, 3),
                ("columns", "empty"): (None, None, None),
                ("aggregates", "all"): (997, -1.5, 2),
                ("aggregates", "null"): (None, None, 0),
                ("aggregates", "empty"): (None, None, 0),
            }[kind, subset]
            for validate in (False, True, False):
                for selected, wanted in (
                    (query, expected),
                    (query.where(key.gt(99)), (None, None, None)),
                ):
                    if mode == "buffered":
                        rows = await tx.fetch_all(selected, validate=validate)
                    else:
                        async with tx.fetch_chunks(
                            selected, size=1, validate=validate
                        ) as chunks:
                            rows = [row async for chunk in chunks for row in chunk]
                    result = cast("Final", rows[0])
                    assert_eq(len(rows), 1)
                    assert_eq((result.total, result.mean, result.quantity), wanted)
                    for value, typ in (
                        (result.total, int),
                        (result.mean, float),
                        (result.quantity, int),
                    ):
                        if value is not None:
                            assert_is(type(value), typ)
