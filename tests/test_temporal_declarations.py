"""Temporal declarations must state a meaning compatible with their storage."""

from datetime import datetime
from typing import Any, ClassVar

from pydantic import Json
from snektest import assert_raises, test

from snekql import mariadb, sqlite


@test(mark="fast")
def bare_datetime_text_requires_an_explicit_meaning() -> None:
    """A warning is insufficient when SQL comparisons can disagree with values."""
    with assert_raises(sqlite.ModelDeclarationError):

        class Ambiguous[S = sqlite.Pending](sqlite.Model[S]):
            __row_type__: ClassVar[sqlite.ReadType[Ambiguous[sqlite.Row]]]
            at: sqlite.Col[datetime] = sqlite.Text()

        sqlite.scaffold([Ambiguous])


@test(mark="fast")
def native_datetime_requires_an_explicit_meaning() -> None:
    """DATETIME storage does not implicitly choose UTC for ordinary datetimes."""
    with assert_raises(mariadb.ModelDeclarationError):

        class Ambiguous[S = mariadb.Pending](mariadb.Model[S]):
            __row_type__: ClassVar[mariadb.ReadType[Ambiguous[mariadb.Row]]]
            at: mariadb.Col[datetime] = mariadb.DateTime()

        mariadb.scaffold([Ambiguous])


@test(mark="fast")
def native_date_rejects_an_incompatible_logical_type() -> None:
    """DATE cannot silently strip time fields or reinterpret arbitrary strings."""
    with assert_raises(mariadb.ModelDeclarationError):

        class Wrong[S = mariadb.Pending](mariadb.Model[S]):
            __row_type__: ClassVar[mariadb.ReadType[Wrong[mariadb.Row]]]
            day: mariadb.Col[str] = mariadb.Date()

        mariadb.scaffold([Wrong])


@test(mark="fast")
def a_server_clock_cannot_supply_a_local_civil_value() -> None:
    """A UTC server instant is not a declaration of local timezone policy."""
    with assert_raises(sqlite.ModelDeclarationError):

        class Wrong[S = sqlite.Pending](sqlite.Model[S]):
            __row_type__: ClassVar[sqlite.ReadType[Wrong[sqlite.Row]]]
            at: sqlite.GenCol[sqlite.LocalDatetime] = sqlite.Text(
                default=sqlite.CurrentTimestamp
            )

        sqlite.scaffold([Wrong])


@test(mark="fast")
def utc_and_civil_columns_cannot_be_compared_after_type_erasure() -> None:
    """Native field compatibility cannot substitute for compatible meanings."""

    class Event[S = sqlite.Pending](sqlite.Model[S]):
        __row_type__: ClassVar[sqlite.ReadType[Event[sqlite.Row]]]
        instant: sqlite.Col[sqlite.UtcDatetime] = sqlite.Text()
        civil: sqlite.Col[sqlite.LocalDatetime] = sqlite.Text()

    erased: Any = Event.civil

    with assert_raises(sqlite.QueryCompilationError):
        sqlite.select(Event).where(Event.instant.eq_col(erased)).compile()


@test(mark="fast")
def temporal_membership_rejects_an_erased_civil_subquery() -> None:
    """IN cannot compare an instant against timezone-free civil output."""

    class Event[S = sqlite.Pending](sqlite.Model[S]):
        __row_type__: ClassVar[sqlite.ReadType[Event[sqlite.Row]]]
        instant: sqlite.Col[sqlite.UtcDatetime] = sqlite.Text()
        civil: sqlite.Col[sqlite.LocalDatetime] = sqlite.Text()

    erased: Any = sqlite.select(Event.civil)

    with assert_raises(sqlite.QueryCompilationError):
        sqlite.select(Event).where(Event.instant.in_subquery(erased)).compile()


@test(mark="fast")
def temporal_predicate_rejects_an_erased_civil_value() -> None:
    """Serialization must not turn a civil bound into UTC-shaped text."""

    class Event[S = sqlite.Pending](sqlite.Model[S]):
        __row_type__: ClassVar[sqlite.ReadType[Event[sqlite.Row]]]
        instant: sqlite.Col[sqlite.UtcDatetime] = sqlite.Text()

    erased: Any = sqlite.LocalDatetime(datetime(2026, 1, 1))  # noqa: DTZ001

    with assert_raises(sqlite.ModelValidationError):
        sqlite.select(Event).where(Event.instant.gte(erased)).compile()


@test(mark="fast")
def sqlite_cannot_borrow_a_native_datetime_declaration() -> None:
    """SQLite text storage must not acquire MariaDB's native wire decoder."""
    with assert_raises(sqlite.ModelDeclarationError):

        class Wrong[S = sqlite.Pending](sqlite.Model[S]):
            __row_type__: ClassVar[sqlite.ReadType[Wrong[sqlite.Row]]]
            at: sqlite.Col[sqlite.UtcDatetime] = mariadb.DateTime()

        sqlite.scaffold([Wrong])


@test(mark="fast")
def a_json_marker_cannot_override_native_datetime_storage() -> None:
    """JSON payload support does not turn DATETIME into a JSON column."""
    with assert_raises(mariadb.ModelDeclarationError):

        class Wrong[S = mariadb.Pending](mariadb.Model[S]):
            __row_type__: ClassVar[mariadb.ReadType[Wrong[mariadb.Row]]]
            at: mariadb.Col[Json[mariadb.UtcDatetime]] = mariadb.DateTime()

        mariadb.scaffold([Wrong])


@test(mark="fast")
def a_column_cannot_mix_utc_and_civil_meanings() -> None:
    """One native decoder cannot infer which meaning a row's fields intended."""
    with assert_raises(mariadb.ModelDeclarationError):

        class Wrong[S = mariadb.Pending](mariadb.Model[S]):
            __row_type__: ClassVar[mariadb.ReadType[Wrong[mariadb.Row]]]
            at: mariadb.Col[mariadb.UtcDatetime | mariadb.LocalDatetime] = (
                mariadb.DateTime()
            )

        mariadb.scaffold([Wrong])
