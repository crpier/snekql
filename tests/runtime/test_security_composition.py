"""Adversarial names and bindings retain meaning across derived query sources."""

from collections.abc import AsyncGenerator
from typing import Any, ClassVar

from pydantic import create_model
from snektest import Param, assert_eq, fixture, load_fixture, test

from snekql import mariadb, sqlite
from snekql.model import BackendFamily
from tests.runtime.test_raw_execution import RawCase, provide_raw_case


class LocalValue[S = sqlite.Pending](sqlite.Model[S]):
    __row_type__: ClassVar[sqlite.ReadType[LocalValue[sqlite.Row]]]
    value: sqlite.Col[str] = sqlite.Text()


class NativeValue[S = mariadb.Pending](mariadb.Model[S]):
    __row_type__: ClassVar[mariadb.ReadType[NativeValue[mariadb.Row]]]
    value: mariadb.Col[str] = mariadb.Text(length=255)


class DerivedRole:
    """Identity of an adversarially named query source."""


@fixture
async def values(backend: BackendFamily, value: str) -> AsyncGenerator[RawCase]:
    """Seed both the selected value and an independently excluded sentinel."""
    case = await load_fixture(provide_raw_case(backend))
    model = LocalValue if backend == "sqlite" else NativeValue
    await case.database.migrate({"001": case.namespace.scaffold([model])})
    async with case.database.transaction() as transaction:
        await transaction.execute(case.namespace.insert(model(value=value)))
        await transaction.execute(case.namespace.insert(model(value="excluded")))
    yield case


@test(
    [
        Param[BackendFamily]("sqlite", name="sqlite"),
        Param[BackendFamily]("mariadb", name="mariadb"),
    ],
    [
        Param('odd`".name#--%s', name="quotes-comments-positional"),
        Param("odd%(value)s", name="named-placeholder"),
        Param("odd%%s", name="doubled-percent"),
        Param("odd\n\x1fname", name="control-characters"),
        Param("odd/*comment*/;name", name="block-comment-semicolon"),
        Param("oddé雪", name="unicode"),
    ],
    mark="slow",
)
async def derived_names_preserve_bound_filtering(
    backend: BackendFamily, name: str
) -> None:
    """UNION, CTE output, filtering and ordering never reinterpret a quoted name."""
    private_value = "bound'`\";--#/*value*/%s%(value)s"
    case = await load_fixture(values(backend, private_value))
    model = LocalValue if backend == "sqlite" else NativeValue
    fields: dict[str, Any] = {name: (str, ...)}
    result_type = create_model("DerivedValue", **fields)
    label = model.value.label(name)
    branch = case.namespace.select(model).project(result_type, **{name: label})
    relation = branch.union_all(branch).cte(DerivedRole, name="derived_values")
    column = relation.column(label)
    query = (
        case.namespace.select(column)
        .where(column.eq(private_value))
        .order_by(column.asc())
    )

    async with case.database.transaction() as transaction:
        rows = await transaction.fetch_all(query)

    assert_eq(rows, [private_value, private_value])
