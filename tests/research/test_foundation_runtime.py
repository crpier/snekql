"""Runtime feasibility checks, not SQL or database execution coverage."""

from dataclasses import dataclass

from anyio import Path, run_process
from snektest import assert_eq, assert_raises, test

from typing_probes.foundations.core import Column, columns
from typing_probes.foundations.generate import render_facade
from typing_probes.foundations.schema import Account as DeclaredAccount
from typing_probes.foundations.selectors import SelectorError, column_name


@dataclass
class Account:
    age: int
    name: str


@dataclass
class Summary:
    name: str
    total: int


@test(mark="slow")
async def generated_facade_matches_schema() -> None:
    """Checked-in generated typing must match the actual generator output."""
    checked_in = await (
        Path(__file__).parents[2] / "typing_probes/foundations/generated.pyi"
    ).read_bytes()

    generated = await run_process(
        ["ruff", "format", "--stdin-filename", "generated.pyi", "-"],
        input=render_facade(DeclaredAccount).encode(),
    )

    assert_eq(generated.stdout, checked_in)


@test(mark="fast")
def projection_keeps_sql_column_order() -> None:
    """Incremental typing has a direct ordered SQL-expression representation."""
    name = Column[Account, str](Account, "name")
    age = Column[Account, int](Account, "age")

    projected = columns(name).add(age.count()).map(Summary)

    assert_eq(projected.selections, ("name", "COUNT(age)"))


@test(mark="fast")
def projection_calls_result_constructor() -> None:
    """The same callable checked by ty actually builds the named result."""
    name = Column[Account, str](Account, "name")
    age = Column[Account, int](Account, "age")
    projected = columns(name).add(age.count()).map(Summary)

    summary = projected.materialize_raw("Ada", 3)

    assert_eq(summary, Summary(name="Ada", total=3))


@test(mark="fast")
def selector_captures_attribute() -> None:
    """A selector can recover a column without source parsing or a real row."""
    selected = column_name(Account, lambda row: row.name)

    assert_eq(selected, "name")


@test(mark="fast")
def selector_rejects_constant() -> None:
    """A callback accepted by ty still needs runtime validation."""
    with assert_raises(SelectorError):
        column_name(Account, lambda _row: 42)


@test(mark="fast")
def selector_rejects_transformation() -> None:
    """A string computation is not silently mistaken for a column reference."""
    with assert_raises(SelectorError):
        column_name(Account, lambda row: row.name.upper())


@test(mark="fast")
def selector_rejects_boolean_shortcut() -> None:
    """Python boolean evaluation must not silently discard a selected field."""
    with assert_raises(SelectorError):
        column_name(Account, lambda row: row.name or row.age)
