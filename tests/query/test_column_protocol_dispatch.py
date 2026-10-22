"""Column extensions keep their public compilation and decoding contracts."""

from typing import Any, ClassVar, cast

from snektest import Param, assert_eq, assert_in, test

from snekql import mariadb, sqlite
from snekql._dialect_expr import CompileCtx
from snekql.storage import Attr, StorageBackend
from tests.helpers import initialized_database


def extended(column: Attr[Any, Any, Any, Any, Any]) -> Any:
    """Install the open-AST interface on a descriptor before declaration binding."""

    def operand(ctx: CompileCtx) -> tuple[str, tuple[object, ...]]:
        return f"({ctx.render_column(column)} + {ctx.placeholder})", (10,)

    def projection(ctx: CompileCtx) -> tuple[str, tuple[object, ...]]:
        return f"({ctx.render_column(column)} + {ctx.placeholder})", (20,)

    column.__owner_model__ = lambda: column.owner
    column.__compile_sql__ = operand
    column.__compile_select_sql__ = projection
    column.__decode__ = lambda raw: cast("int", raw) + 300
    return column


class SqlReading[S = sqlite.Pending](sqlite.Model[S]):
    __row_type__: ClassVar[sqlite.ReadType[SqlReading[sqlite.Row]]]
    key: SqlReading.Col[int] = sqlite.Integer(primary_key=True)
    value: SqlReading.Col[int] = extended(sqlite.Integer())


class MariaReading[S = mariadb.Pending](mariadb.Model[S]):
    __row_type__: ClassVar[mariadb.ReadType[MariaReading[mariadb.Row]]]
    key: MariaReading.Col[int] = mariadb.Integer(primary_key=True)
    value: MariaReading.Col[int] = extended(mariadb.Integer())


@test(
    [Param(value="sqlite", name="sqlite"), Param(value="mariadb", name="mariadb")],
    mark="fast",
)
def instance_column_hooks_keep_projection_and_operand_bindings(backend: str) -> None:
    api: Any = sqlite if backend == "sqlite" else mariadb
    model: Any = SqlReading if backend == "sqlite" else MariaReading
    query = api.select(model.value).where(model.value.eq(17))
    compiled = query.compile()
    assert_eq(compiled.params, (20, 10, 17))
    marker = "?" if backend == "sqlite" else "%s"
    quote = '"' if backend == "sqlite" else "`"
    assert_in(f"({quote}value{quote} + {marker})", compiled.sql)


def policy_extended(column: Attr[Any, Any, Any, Any, Any]) -> Any:
    column = extended(column)

    def decode(raw: object, *, backend: StorageBackend, validate: bool) -> object:
        value = cast("int", column.decode(raw, backend=backend, validate=validate))
        return value + (100 if validate else 200)

    column.__decode_with_policy__ = decode
    return column


class PolicySqlReading[S = sqlite.Pending](sqlite.Model[S]):
    __row_type__: ClassVar[sqlite.ReadType[PolicySqlReading[sqlite.Row]]]
    key: PolicySqlReading.Col[int] = sqlite.Integer(primary_key=True)
    value: PolicySqlReading.Col[int] = policy_extended(sqlite.Integer())


@test(
    [Param(value="dialect", name="dialect"), Param(value="policy", name="policy")],
    [
        Param(value="buffered", name="buffered"),
        Param(value="streamed", name="streamed"),
    ],
    mark="medium",
)
async def instance_column_hooks_keep_each_executions_decode_policy(
    kind: str, consumption: str
) -> None:
    model: Any = SqlReading if kind == "dialect" else PolicySqlReading
    async with (
        await initialized_database(database=":memory:", models=[model]) as db,
        db.transaction() as tx,
    ):
        await tx.execute(sqlite.insert(model(key=1, value=7)))
        whole = await tx.fetch_one(sqlite.select(model))
        assert_eq(whole.value, 27)
        query = sqlite.select(model.value)
        for validate in (False, True, False):
            if consumption == "buffered":
                values = await tx.fetch_all(query, validate=validate)
            else:
                async with tx.fetch_chunks(query, size=1, validate=validate) as chunks:
                    values = [value async for batch in chunks for value in batch]
            expected = 327 if kind == "dialect" else 127 if validate else 227
            assert_eq(values, [expected])
