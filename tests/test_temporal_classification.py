"""Temporal classification follows resolved declarations, not an early guess."""

from datetime import UTC, datetime
from typing import ClassVar

from snektest import assert_eq, assert_in, assert_raises, test

from snekql import mariadb, sqlite


class LateInstantRow[S = sqlite.Pending](sqlite.Model[S]):
    __row_type__: ClassVar[sqlite.ReadType[LateInstantRow[sqlite.Row]]]
    at: sqlite.Col[LaterInstant] = sqlite.Text()


# Deliberately resolved only after the model's initial declaration checks.
LaterInstant = sqlite.UtcDatetime


@test(mark="fast")
def later_temporal_annotation_can_receive_the_server_clock() -> None:
    """An unresolved annotation must not become a permanent non-temporal decision."""
    query = (
        sqlite.update(LateInstantRow)
        .set(LateInstantRow.at.to(sqlite.CurrentTimestamp))
        .all()
    )
    compiled = query.compile()
    assert_in("strftime", compiled.sql)
    assert_eq(compiled.params, ())


@test(mark="fast")
def deferred_temporal_foreign_key_keeps_exact_write_precision() -> None:
    """Lazy storage binding retains the inherited native precision and meaning."""

    class Event[S = mariadb.Pending](mariadb.Model[S]):
        __row_type__: ClassVar[mariadb.ReadType[Event[mariadb.Row]]]
        at: mariadb.Col[mariadb.UtcDatetime] = mariadb.DateTime(
            precision=3, unique=True
        )
        parent: mariadb.FKCol[Event, mariadb.UtcDatetime | None] = mariadb.ForeignKey(
            lambda: Event.at, default=None
        )

    exact = mariadb.UtcDatetime(datetime(2026, 1, 2, 3, 4, 5, 123000, tzinfo=UTC))
    inexact = mariadb.UtcDatetime(datetime(2026, 1, 2, 3, 4, 5, 123456, tzinfo=UTC))
    compiled = mariadb.insert(Event(at=exact, parent=exact)).compile()
    assert_eq(compiled.params, ("2026-01-02 03:04:05.123000",) * 2)
    with assert_raises(mariadb.ModelValidationError):
        mariadb.insert(Event(at=exact, parent=inexact)).compile()
    predicate = mariadb.select(Event.parent).where(Event.parent.gte(inexact)).compile()
    assert_eq(predicate.params, ("2026-01-02 03:04:05.123456",))


@test(mark="fast")
def aliased_temporal_column_retains_its_source_meaning() -> None:
    """A query alias cannot discard a resolved instant's comparison contract."""
    instant = sqlite.UtcDatetime(datetime(2026, 1, 2, tzinfo=UTC))
    sqlite.select(LateInstantRow.at).where(LateInstantRow.at.eq(instant)).compile()

    class Role:
        pass

    alias = sqlite.alias(LateInstantRow, Role, name="event")
    column = alias.column(LateInstantRow.at)
    compiled = sqlite.select(column).where(column.eq(instant)).compile()
    assert_eq(compiled.params, ("2026-01-02T00:00:00.000000Z",))
    civil = sqlite.LocalDatetime(datetime(2026, 1, 2))  # noqa: DTZ001
    with assert_raises(sqlite.ModelValidationError):
        # Type erasure must not bypass the column's runtime meaning check.
        sqlite.select(column).where(column.eq(civil)).compile()  # ty: ignore[invalid-argument-type]


@test(mark="fast")
def ordinary_and_temporal_columns_keep_independent_wire_values() -> None:
    """Same descriptor classes do not imply the same annotation or wire policy."""

    class Mixed[S = sqlite.Pending](sqlite.Model[S]):
        __row_type__: ClassVar[sqlite.ReadType[Mixed[sqlite.Row]]]
        count: sqlite.Col[int] = sqlite.Integer()
        title: sqlite.Col[str] = sqlite.Text()
        at: sqlite.Col[sqlite.UtcDatetime | None] = sqlite.Text(default=None)

    instant = sqlite.UtcDatetime(datetime(2026, 1, 2, tzinfo=UTC))
    for at in (None, instant, None):
        compiled = sqlite.insert(Mixed(count=7, title="plain", at=at)).compile()
        assert_eq(
            compiled.params,
            (7, "plain", None if at is None else "2026-01-02T00:00:00.000000Z"),
        )
