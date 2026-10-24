"""Numeric gates retry unknown annotations and preserve each column's domain."""

from typing import Annotated, ClassVar

from annotated_types import Ge
from snektest import assert_eq, assert_raises, test

from snekql import sqlite


class LateNumber[S = sqlite.Pending](sqlite.Model[S]):
    __row_type__: ClassVar[sqlite.ReadType[LateNumber[sqlite.Row]]]
    value: sqlite.Col[LaterNumber] = sqlite.Integer()


with assert_raises(sqlite.QueryConstructionError):
    LateNumber.value.sum()
LaterNumber = int


@test(mark="fast")
def unresolved_numeric_gate_is_retried_after_binding() -> None:
    for _ in range(2):
        assert_eq(
            sqlite.select(LateNumber.value.sum(), LateNumber.value.avg())
            .compile()
            .params,
            (),
        )


@test(mark="fast")
def unbound_numeric_gate_does_not_override_bound_text_domain() -> None:
    declaration = sqlite.Text()
    declaration.sum()

    class TextRow[S = sqlite.Pending](sqlite.Model[S]):
        __row_type__: ClassVar[sqlite.ReadType[TextRow[sqlite.Row]]]
        value: sqlite.Col[str] = declaration

    for _ in range(2):
        with assert_raises(sqlite.QueryConstructionError):
            TextRow.value.sum()
        with assert_raises(sqlite.QueryConstructionError):
            TextRow.value.avg()


@test(mark="fast")
def warmed_alias_and_deferred_foreign_key_keep_separate_numeric_domains() -> None:
    class Reading[S = sqlite.Pending](sqlite.Model[S]):
        __row_type__: ClassVar[sqlite.ReadType[Reading[sqlite.Row]]]
        value: sqlite.Col[Annotated[int, Ge(0)]] = sqlite.Integer(unique=True)
        flag: sqlite.Col[bool] = sqlite.Integer()
        parent: sqlite.FKCol[Reading, int | None] = sqlite.ForeignKey(
            lambda: Reading.value, default=None
        )

    class Role:
        pass

    for _ in range(2):
        assert_eq(
            sqlite.select(Reading.value.sum(), Reading.parent.avg()).compile().params,
            (),
        )
        with assert_raises(sqlite.QueryConstructionError):
            Reading.flag.sum()
        alias = sqlite.alias(Reading, Role, name="reading_peer")
        assert_eq(
            sqlite.select(alias.column(Reading.parent).sum()).compile().params, ()
        )
        with assert_raises(sqlite.QueryConstructionError):
            alias.column(Reading.flag).avg()
        with assert_raises(sqlite.ModelValidationError):
            sqlite.update(Reading).set(Reading.value.to(-1)).all().compile()
