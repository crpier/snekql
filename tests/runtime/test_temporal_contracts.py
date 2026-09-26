"""Temporal values survive native storage without changing their meaning."""

from collections.abc import AsyncGenerator
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any, ClassVar

from pydantic import BaseModel, Json
from snektest import Param, assert_eq, assert_raises, fixture, load_fixture, test

from snekql import mariadb, sqlite
from snekql.model import BackendFamily
from snekql.runtime import Database
from tests.helpers import initialized_database, provide_mariadb_server


class SQLiteInstant[S = sqlite.Pending](sqlite.Model[S]):
    __tablename__ = "temporal_instant"
    __row_type__: ClassVar[sqlite.ReadType[SQLiteInstant[sqlite.Row]]]
    at: sqlite.Col[sqlite.UtcDatetime] = sqlite.Text()


class MariaInstant[S = mariadb.Pending](mariadb.Model[S]):
    __row_type__: ClassVar[mariadb.ReadType[MariaInstant[mariadb.Row]]]
    at: mariadb.Col[mariadb.UtcDatetime] = mariadb.DateTime()


class SQLiteCivil[S = sqlite.Pending](sqlite.Model[S]):
    __tablename__ = "temporal_civil"
    __row_type__: ClassVar[sqlite.ReadType[SQLiteCivil[sqlite.Row]]]
    at: sqlite.Col[sqlite.LocalDatetime] = sqlite.Text()


class MariaCivil[S = mariadb.Pending](mariadb.Model[S]):
    __row_type__: ClassVar[mariadb.ReadType[MariaCivil[mariadb.Row]]]
    at: mariadb.Col[mariadb.LocalDatetime] = mariadb.DateTime()


@dataclass(frozen=True)
class TemporalCase:
    """Keep runtime backend selection local to the native test fixture."""

    database: Database[Any]
    model: Any
    namespace: Any


@fixture
async def provide_instant_case(
    backend: BackendFamily, *, civil: bool = False
) -> AsyncGenerator[TemporalCase]:
    if backend == "mariadb":
        server = await load_fixture(provide_mariadb_server())
        async with await initialized_database(
            server.config(), models=[MariaCivil if civil else MariaInstant]
        ) as database:
            yield TemporalCase(database, MariaCivil if civil else MariaInstant, mariadb)
    else:
        async with await initialized_database(
            database=":memory:", models=[SQLiteCivil if civil else SQLiteInstant]
        ) as database:
            yield TemporalCase(
                database, SQLiteCivil if civil else SQLiteInstant, sqlite
            )


@test(
    [
        Param[BackendFamily]("sqlite", name="sqlite"),
        Param[BackendFamily]("mariadb", name="mariadb"),
    ],
    mark="slow",
)
async def instant_round_trip_preserves_microseconds(backend: BackendFamily) -> None:
    """The fetched value is the same concrete instant supplied by the application."""
    case = await load_fixture(provide_instant_case(backend))
    instant = sqlite.UtcDatetime(datetime(2026, 1, 2, 3, 4, 5, 123456, tzinfo=UTC))
    async with case.database.transaction() as transaction:
        await transaction.execute(case.namespace.insert(case.model(at=instant)))

    async with case.database.transaction() as transaction:
        actual = await transaction.fetch_one(case.namespace.select(case.model.at))

    assert_eq(actual, instant)


@test(
    [
        Param[BackendFamily]("sqlite", name="sqlite"),
        Param[BackendFamily]("mariadb", name="mariadb"),
    ],
    mark="slow",
)
async def civil_round_trip_never_attaches_a_timezone(backend: BackendFamily) -> None:
    """Native DATETIME can retain civil meaning rather than silently adding UTC."""
    case = await load_fixture(provide_instant_case(backend, civil=True))
    civil = sqlite.LocalDatetime(datetime(2026, 1, 2, 3, 4, 5, 123456))  # noqa: DTZ001
    async with case.database.transaction() as transaction:
        await transaction.execute(case.namespace.insert(case.model(at=civil)))

    async with case.database.transaction() as transaction:
        actual = await transaction.fetch_one(case.namespace.select(case.model.at))

    assert_eq(actual, civil)


@fixture
async def provide_date_case(backend: BackendFamily) -> AsyncGenerator[TemporalCase]:
    if backend == "mariadb":
        server = await load_fixture(provide_mariadb_server())

        class Calendar[S = mariadb.Pending](mariadb.Model[S]):
            __row_type__: ClassVar[mariadb.ReadType[Calendar[mariadb.Row]]]
            day: mariadb.Col[date] = mariadb.Date()

        async with await initialized_database(
            server.config(), models=[Calendar], verify=True
        ) as database:
            yield TemporalCase(database, Calendar, mariadb)
    else:

        class CalendarText[S = sqlite.Pending](sqlite.Model[S]):
            __row_type__: ClassVar[sqlite.ReadType[CalendarText[sqlite.Row]]]
            day: sqlite.Col[date] = sqlite.Text()

        async with await initialized_database(
            database=":memory:", models=[CalendarText], verify=True
        ) as database:
            yield TemporalCase(database, CalendarText, sqlite)


@test(
    [
        Param[BackendFamily]("sqlite", name="sqlite"),
        Param[BackendFamily]("mariadb", name="mariadb"),
    ],
    mark="slow",
)
async def calendar_date_round_trips_without_a_clock(backend: BackendFamily) -> None:
    """A leap date remains a date under verified text and native DATE storage."""
    case = await load_fixture(provide_date_case(backend))
    async with case.database.transaction() as transaction:
        await transaction.execute(
            case.namespace.insert(case.model(day=date(2024, 2, 29)))
        )

    async with case.database.transaction() as transaction:
        actual = await transaction.fetch_one(case.namespace.select(case.model.day))

    assert_eq(actual, date(2024, 2, 29))


@fixture
async def provide_coarse_case() -> AsyncGenerator[TemporalCase]:
    server = await load_fixture(provide_mariadb_server())

    class Coarse[S = mariadb.Pending](mariadb.Model[S]):
        __row_type__: ClassVar[mariadb.ReadType[Coarse[mariadb.Row]]]
        at: mariadb.Col[mariadb.UtcDatetime] = mariadb.DateTime(precision=3)

    async with await initialized_database(
        server.config(), models=[Coarse], verify=True
    ) as database:
        async with database.transaction() as transaction:
            await transaction.execute(
                mariadb.insert(
                    Coarse(
                        at=mariadb.UtcDatetime(
                            datetime(2026, 1, 1, 12, 0, 0, 123000, tzinfo=UTC)
                        )
                    )
                )
            )
        yield TemporalCase(database, Coarse, mariadb)


@test(
    [
        Param(shape, name=shape)
        for shape in ("direct", "alias", "cte", "compound", "aggregate")
    ],
    mark="slow",
)
async def coarse_storage_keeps_full_precision_query_bounds(shape: str) -> None:
    """DATETIME(3) does not round a comparison bound down into a false match."""
    case = await load_fixture(provide_coarse_case())
    cutoff = mariadb.UtcDatetime(datetime(2026, 1, 1, 12, 0, 0, 123456, tzinfo=UTC))

    class Role:
        pass

    class Snapshot(BaseModel):
        at: mariadb.UtcDatetime

    column = case.model.at
    if shape == "alias":
        column = mariadb.alias(case.model, Role, name="aliased").column(column)
    elif shape in ("cte", "compound"):
        token = column.label("at")
        named = mariadb.select(case.model).project(Snapshot, at=token)
        if shape == "compound":
            named = named.union_all(named)
        column = named.cte(Role, name="derived").column(token)
    if shape == "aggregate":
        query = mariadb.select(column.min()).having(column.min().gte(cutoff))
    else:
        query = mariadb.select(column).where(column.gte(cutoff))

    async with case.database.transaction() as transaction:
        actual = await transaction.fetch_all(query)

    assert_eq(actual, [])


@test(mark="slow")
async def coarse_storage_rejects_lossy_writes_before_execution() -> None:
    """The driver never gets a value that would lose digits under its SQL mode."""
    case = await load_fixture(provide_coarse_case())
    instant = mariadb.UtcDatetime(datetime(2026, 1, 1, 12, 0, 0, 123456, tzinfo=UTC))

    with assert_raises(mariadb.ModelValidationError):
        mariadb.insert(case.model(at=instant)).compile()


@fixture
async def provide_clock_case(kind: str) -> AsyncGenerator[TemporalCase]:
    if kind == "sqlite-text":

        class ClockText[S = sqlite.Pending](sqlite.Model[S]):
            __row_type__: ClassVar[sqlite.ReadType[ClockText[sqlite.Row]]]
            at: sqlite.GenCol[sqlite.UtcDatetime] = sqlite.Text(
                default=sqlite.CurrentTimestamp
            )

        async with await initialized_database(
            database=":memory:", models=[ClockText], verify=True
        ) as database:
            yield TemporalCase(database, ClockText, sqlite)
    else:
        server = await load_fixture(provide_mariadb_server())

        class Clock[S = mariadb.Pending](mariadb.Model[S]):
            __row_type__: ClassVar[mariadb.ReadType[Clock[mariadb.Row]]]
            at: mariadb.GenCol[mariadb.UtcDatetime] = (
                mariadb.Text(default=mariadb.CurrentTimestamp)
                if kind == "mariadb-text"
                else mariadb.DateTime(
                    precision=int(kind[-1]), default=mariadb.CurrentTimestamp
                )
            )

        async with await initialized_database(
            server.config(), models=[Clock], verify=True
        ) as database:
            yield TemporalCase(database, Clock, mariadb)


@test(
    [
        Param("sqlite-text", name="sqlite-text"),
        Param("mariadb-text", name="mariadb-text"),
        *[
            Param(f"mariadb-native-{precision}", name=f"native-{precision}")
            for precision in range(7)
        ],
    ],
    mark="slow",
)
async def database_clock_returns_a_canonical_utc_value(kind: str) -> None:
    """Defaults use the declared wire form and native precision, including zero."""
    case = await load_fixture(provide_clock_case(kind))
    async with case.database.transaction() as transaction:
        await transaction.execute(case.namespace.insert(case.model()))

    async with case.database.transaction() as transaction:
        actual = await transaction.fetch_one(case.namespace.select(case.model.at))

    assert isinstance(actual, sqlite.UtcDatetime)
    assert_eq(actual.datetime.tzinfo, UTC)
    if "native" in kind:
        assert_eq(actual.datetime.microsecond % 10 ** (6 - int(kind[-1])), 0)


@test(mark="medium")
async def date_text_rejects_a_noncanonical_stored_datetime() -> None:
    """A permissive reader cannot repair SQL equality over noncanonical date text."""
    case = await load_fixture(provide_date_case("sqlite"))
    async with case.database.transaction() as transaction:
        await transaction.execute(
            sqlite.raw("INSERT INTO calendar_text VALUES ('2024-02-29T00:00:00')")
        )

    async with case.database.transaction() as transaction:
        with assert_raises(sqlite.ModelValidationError):
            await transaction.fetch_one(sqlite.select(case.model.day))


@test(
    [
        Param[BackendFamily]("sqlite", name="sqlite"),
        Param[BackendFamily]("mariadb", name="mariadb"),
    ],
    mark="slow",
)
async def one_microsecond_distinguishes_ordered_instants(
    backend: BackendFamily,
) -> None:
    """Ordering and equality retain digits that exceed SQLite's clock resolution."""
    case = await load_fixture(provide_instant_case(backend))
    early = sqlite.UtcDatetime(datetime(2026, 1, 1, 0, 0, 0, 123456, tzinfo=UTC))
    late = sqlite.UtcDatetime(datetime(2026, 1, 1, 0, 0, 0, 123457, tzinfo=UTC))
    async with case.database.transaction() as transaction:
        await transaction.execute(
            case.namespace.insert_many(
                case.model, [case.model(at=late), case.model(at=early)]
            )
        )

    async with case.database.transaction() as transaction:
        ordered = await transaction.fetch_all(
            case.namespace.select(case.model.at).order_by(case.model.at.asc())
        )
        matched = await transaction.fetch_all(
            case.namespace.select(case.model.at).where(case.model.at.eq(late))
        )

    assert_eq(ordered, [early, late])
    assert_eq(matched, [late])


@test([Param(kind, name=kind) for kind in ("utc", "civil", "zoned")], mark="medium")
async def json_payloads_do_not_acquire_temporal_column_restrictions(kind: str) -> None:
    """JSON can distinguish UTC and civil members using their own canonical forms."""

    class Payload[S = sqlite.Pending](sqlite.Model[S]):
        __row_type__: ClassVar[sqlite.ReadType[Payload[sqlite.Row]]]
        value: sqlite.Col[
            Json[sqlite.UtcDatetime | sqlite.LocalDatetime | sqlite.ZonedDatetime]
        ] = sqlite.Text()

    value = {
        "utc": sqlite.UtcDatetime(datetime(2026, 1, 1, 9, tzinfo=UTC)),
        "civil": sqlite.LocalDatetime(datetime(2026, 1, 1, 9)),  # noqa: DTZ001
        "zoned": sqlite.ZonedDatetime(datetime(2026, 1, 1, 9, tzinfo=UTC)),
    }[kind]
    async with await initialized_database(
        database=":memory:", models=[Payload]
    ) as database:
        async with database.transaction() as transaction:
            await transaction.execute(sqlite.insert(Payload(value=value)))
        async with database.transaction() as transaction:
            actual = await transaction.fetch_one(sqlite.select(Payload.value))

    assert_eq(actual, value)
