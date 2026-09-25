"""Named UNION behavior through real backend transactions."""

from collections.abc import AsyncGenerator
from typing import ClassVar, assert_type
from uuid import UUID

from pydantic import BaseModel, Field, field_validator
from snektest import Param, assert_eq, assert_raises, fixture, load_fixture, test

from snekql import mariadb, sqlite
from tests.helpers import provide_mariadb_server
from tests.query.test_unions import (
    CombinedRole,
    Event,
    MariaEvent,
    NullableEvent,
    OptionalRow,
    Pair,
    Row,
)
from tests.runtime.test_named_codecs import (
    DocumentResult,
    LocalDocument,
    MariaDocument,
    provide_mariadb_documents,
    provide_sqlite_documents,
)


class MariaNullable[S = mariadb.Pending](mariadb.Model[S]):
    """Nullable native outputs for database set equality."""

    __row_type__: ClassVar[mariadb.ReadType[MariaNullable[mariadb.Row]]]

    event_id: mariadb.Col[int | None] = mariadb.Integer()


class LocalText[S = sqlite.Pending](sqlite.Model[S]):
    __row_type__: ClassVar[sqlite.ReadType[LocalText[sqlite.Row]]]
    value: sqlite.Col[str] = sqlite.Text(collation="NOCASE")


class NativeText[S = mariadb.Pending](mariadb.Model[S]):
    __row_type__: ClassVar[mariadb.ReadType[NativeText[mariadb.Row]]]
    value: mariadb.Col[str] = mariadb.Text(length=80, collation="utf8mb4_unicode_ci")


class TextRow(BaseModel):
    value: str


@fixture
async def provide_sqlite_events() -> AsyncGenerator[sqlite.Database]:
    """Seed duplicates and SQL NULLs before compound-query execution."""
    async with await sqlite.Database.initialize(database=":memory:") as database:
        await database.migrate(
            {"001_events": sqlite.scaffold([Event, NullableEvent, LocalText])}
        )
        async with database.transaction() as transaction:
            await transaction.execute(
                sqlite.insert_many(
                    Event, [Event(event_id=number) for number in (1, 2, 3)]
                )
            )
            await transaction.execute(
                sqlite.insert_many(
                    NullableEvent,
                    [NullableEvent(event_id=number) for number in (None, None, 1)],
                )
            )
            await transaction.execute(
                sqlite.insert_many(
                    LocalText, [LocalText(value=value) for value in ("a", "A")]
                )
            )
        yield database


@fixture
async def provide_mariadb_events() -> AsyncGenerator[mariadb.Database]:
    """Use the managed native server, never an in-memory SQL stand-in."""
    server = await load_fixture(provide_mariadb_server())
    async with await mariadb.Database.initialize(server.config()) as database:
        await database.migrate(
            {"001_events": mariadb.scaffold([MariaEvent, MariaNullable, NativeText])}
        )
        async with database.transaction() as transaction:
            await transaction.execute(
                mariadb.insert_many(
                    MariaEvent, [MariaEvent(event_id=number) for number in (1, 2, 3)]
                )
            )
            await transaction.execute(
                mariadb.insert_many(
                    MariaNullable,
                    [MariaNullable(event_id=number) for number in (None, None, 1)],
                )
            )
            await transaction.execute(
                mariadb.insert_many(
                    NativeText, [NativeText(value=value) for value in ("a", "A")]
                )
            )
        yield database


@test([Param("all", name="all"), Param("distinct", name="distinct")], mark="medium")
async def sqlite_union_obeys_database_multiplicity(
    operator: str,
) -> None:
    """UNION ALL retains the common row; UNION removes it in SQL."""
    database = await load_fixture(provide_sqlite_events())
    token = Event.event_id.label("event_id")
    left = sqlite.select(Event).where(Event.event_id.lt(3)).project(Row, event_id=token)
    right = (
        sqlite.select(Event).where(Event.event_id.gt(1)).project(Row, event_id=token)
    )
    combined = left.union_all(right) if operator == "all" else left.union(right)

    async with database.transaction() as transaction:
        rows = await transaction.fetch_all(
            combined.order_by(combined.column(token).asc())
        )

    assert_type(rows, list[Row])
    assert_eq(
        [row.event_id for row in rows], [1, 2, 2, 3] if operator == "all" else [1, 2, 3]
    )


@test([Param("all", name="all"), Param("distinct", name="distinct")], mark="slow")
async def mariadb_union_obeys_database_multiplicity(
    operator: str,
) -> None:
    """The native dialect applies the same explicit set operator."""
    database = await load_fixture(provide_mariadb_events())
    token = MariaEvent.event_id.label("event_id")
    left = (
        mariadb.select(MariaEvent)
        .where(MariaEvent.event_id.lt(3))
        .project(Row, event_id=token)
    )
    right = (
        mariadb.select(MariaEvent)
        .where(MariaEvent.event_id.gt(1))
        .project(Row, event_id=token)
    )
    combined = left.union_all(right) if operator == "all" else left.union(right)

    async with database.transaction() as transaction:
        rows = await transaction.fetch_all(
            combined.order_by(combined.column(token).asc())
        )

    assert_type(rows, list[Row])
    assert_eq(
        [row.event_id for row in rows], [1, 2, 2, 3] if operator == "all" else [1, 2, 3]
    )


@test(
    [Param("left", name="left_grouped"), Param("right", name="right_grouped")],
    mark="medium",
)
async def sqlite_mixed_operations_preserve_grouping(
    grouping: str,
) -> None:
    """Parenthesizing the right branch changes duplicate removal."""
    database = await load_fixture(provide_sqlite_events())
    token = Event.event_id.label("event_id")
    operand = (
        sqlite.select(Event).where(Event.event_id.eq(1)).project(Row, event_id=token)
    )
    combined = (
        operand.union(operand).union_all(operand)
        if grouping == "left"
        else operand.union(operand.union_all(operand))
    )

    async with database.transaction() as transaction:
        rows = await transaction.fetch_all(combined)

    assert_eq(
        rows,
        [Row(event_id=1), Row(event_id=1)] if grouping == "left" else [Row(event_id=1)],
    )


@test(
    [Param("left", name="left_grouped"), Param("right", name="right_grouped")],
    mark="slow",
)
async def mariadb_mixed_operations_preserve_grouping(
    grouping: str,
) -> None:
    """Derived operands preserve grouping on the native engine too."""
    database = await load_fixture(provide_mariadb_events())
    token = MariaEvent.event_id.label("event_id")
    operand = (
        mariadb.select(MariaEvent)
        .where(MariaEvent.event_id.eq(1))
        .project(Row, event_id=token)
    )
    combined = (
        operand.union(operand).union_all(operand)
        if grouping == "left"
        else operand.union(operand.union_all(operand))
    )

    async with database.transaction() as transaction:
        rows = await transaction.fetch_all(combined)

    assert_eq(
        rows,
        [Row(event_id=1), Row(event_id=1)] if grouping == "left" else [Row(event_id=1)],
    )


@test(mark="medium")
async def nullable_union_uses_sql_null_equality() -> None:
    """Two NULL rows collapse under UNION without Python set equality."""
    database = await load_fixture(provide_sqlite_events())
    token = NullableEvent.event_id.label("event_id")
    optional = sqlite.select(NullableEvent).all().project(OptionalRow, event_id=token)
    required = (
        sqlite.select(Event)
        .all()
        .project(OptionalRow, event_id=Event.event_id.label("event_id"))
    )
    combined = optional.union(required)

    async with database.transaction() as transaction:
        rows = await transaction.fetch_all(
            combined.order_by(combined.column(token).asc())
        )

    assert_eq(rows, [OptionalRow(event_id=number) for number in (None, 1, 2, 3)])


@test(mark="medium")
async def reordered_operand_values_materialize_by_name() -> None:
    """Different binding orders cannot silently swap compatible integer fields."""
    database = await load_fixture(provide_sqlite_events())
    left = (
        sqlite.select(Event)
        .where(Event.event_id.eq(1))
        .project(Pair, second=Event.event_id.add(10), first=Event.event_id.add(1))
    )
    right = (
        sqlite.select(Event)
        .where(Event.event_id.eq(1))
        .project(Pair, first=Event.event_id.add(2), second=Event.event_id.add(20))
    )

    async with database.transaction() as transaction:
        rows = await transaction.fetch_all(left.union_all(right))

    assert_eq(rows, [Pair(first=2, second=11), Pair(first=3, second=21)])


@test(mark="medium")
async def compound_cte_filters_the_complete_result() -> None:
    """CTE consumption keeps the compound operation inside its definition."""
    database = await load_fixture(provide_sqlite_events())
    token = Event.event_id.label("event_id")
    operand = sqlite.select(Event).all().project(Row, event_id=token)
    combined = operand.union_all(operand).cte(CombinedRole, name="combined")
    query = sqlite.select(combined).where(combined.column(token).eq(2))

    async with database.transaction() as transaction:
        rows = await transaction.fetch_all(query)

    assert_eq(rows, [Row(event_id=2), Row(event_id=2)])


@test(mark="medium")
async def compound_page_applies_after_duplicate_elimination() -> None:
    """The final limit/offset operates on ordered combined rows."""
    database = await load_fixture(provide_sqlite_events())
    token = Event.event_id.label("event_id")
    operand = sqlite.select(Event).all().project(Row, event_id=token)
    combined = operand.union(operand)

    async with database.transaction() as transaction:
        rows = await transaction.fetch_all(
            combined.order_by(combined.column(token).desc()).limit(1).offset(1)
        )

    assert_eq(rows, [Row(event_id=2)])


@test(mark="medium")
async def empty_compound_has_no_optional_row() -> None:
    """Both empty operands remain an empty named result, not a NULL row."""
    database = await load_fixture(provide_sqlite_events())
    operand = (
        sqlite.select(Event)
        .where(Event.event_id.lt(0))
        .project(Row, event_id=Event.event_id)
    )

    async with database.transaction() as transaction:
        row = await transaction.fetch_one_or_none(operand.union_all(operand))

    assert_eq(row, None)


@test(mark="medium")
async def bounded_cte_inputs_keep_their_explicit_limits() -> None:
    """An explicit relational boundary makes a bounded SELECT a valid operand."""
    database = await load_fixture(provide_sqlite_events())
    token = Event.event_id.label("event_id")
    bounded = (
        sqlite.select(Event)
        .all()
        .project(Row, event_id=token)
        .order_by(Event.event_id.asc())
        .limit(1)
        .cte(CombinedRole, name="bounded")
    )
    operand = sqlite.select(bounded).all().project(Row, event_id=bounded.column(token))

    async with database.transaction() as transaction:
        rows = await transaction.fetch_all(operand.union_all(operand))

    assert_eq(rows, [Row(event_id=1), Row(event_id=1)])


@test(mark="medium")
async def union_runs_only_final_result_validation() -> None:
    """The input SELECT contracts are SQL boundaries, not Python model passes."""
    database = await load_fixture(provide_sqlite_events())

    class AdjustedResult(BaseModel):
        event_id: int

        @field_validator("event_id")
        @classmethod
        def increment(cls, value: int) -> int:
            return value + 10

    token = Event.event_id.label("event_id")
    operand = (
        sqlite.select(Event)
        .where(Event.event_id.eq(1))
        .project(AdjustedResult, event_id=token)
    )
    compound = operand.union(operand).cte(CombinedRole, name="validated")

    async with database.transaction() as transaction:
        row = await transaction.fetch_one(sqlite.select(compound).all())

    assert_eq(row.event_id, 11)


@test(mark="medium")
async def union_preserves_rich_logical_codecs() -> None:
    """A compound decodes UUID/JSON outputs before validating its result model."""
    database = await load_fixture(provide_sqlite_documents())
    operand = (
        sqlite.select(LocalDocument)
        .all()
        .project(DocumentResult, key=LocalDocument.id, values=LocalDocument.payload)
    )

    async with database.transaction() as transaction:
        rows = await transaction.fetch_all(operand.union_all(operand))

    assert_eq(rows, [DocumentResult(key=UUID(int=1), values=[2, 3])] * 2)


@test(mark="slow")
async def mariadb_compound_cte_preserves_rich_codecs() -> None:
    """Native UUID/JSON policies survive the combined definition boundary."""
    database = await load_fixture(provide_mariadb_documents())
    operand = (
        mariadb.select(MariaDocument)
        .all()
        .project(DocumentResult, key=MariaDocument.id, values=MariaDocument.payload)
    )
    combined = operand.union_all(operand).cte(CombinedRole, name="documents")

    async with database.transaction() as transaction:
        rows = await transaction.fetch_all(mariadb.select(combined).all())

    assert_eq(rows, [DocumentResult(key=UUID(int=1), values=[2, 3])] * 2)


@test(mark="medium")
async def compound_cte_presence_distinguishes_a_matched_null_row() -> None:
    """The private presence column is not part of set equality or visible results."""
    database = await load_fixture(provide_sqlite_events())
    token = NullableEvent.event_id.label("event_id")
    operand = (
        sqlite.select(NullableEvent)
        .where(NullableEvent.event_id.is_null())
        .project(OptionalRow, event_id=token)
    )
    combined = operand.union(operand).cte(CombinedRole, name="null_rows")
    query = (
        sqlite.select(Event)
        .left_join(combined, on=Event.event_id.eq(1))
        .all()
        .order_by(Event.event_id.asc())
    )

    async with database.transaction() as transaction:
        rows = await transaction.fetch_all(query)

    assert_eq([row[1] for row in rows], [OptionalRow(event_id=None), None, None])


@test(mark="slow")
async def mariadb_nullable_union_uses_sql_null_equality() -> None:
    """The native set operator collapses NULLs without widening left references."""
    database = await load_fixture(provide_mariadb_events())
    token = MariaNullable.event_id.label("event_id")
    optional = mariadb.select(MariaNullable).all().project(OptionalRow, event_id=token)
    required = (
        mariadb.select(MariaEvent)
        .all()
        .project(OptionalRow, event_id=MariaEvent.event_id)
    )
    combined = optional.union(required)

    async with database.transaction() as transaction:
        rows = await transaction.fetch_all(
            combined.order_by(combined.column(token).asc())
        )

    assert_eq(rows, [OptionalRow(event_id=number) for number in (None, 1, 2, 3)])


@test(mark="medium")
async def sqlite_union_uses_source_collation() -> None:
    """Database equality, not Python string equality, removes duplicate rows."""
    database = await load_fixture(provide_sqlite_events())
    operand = sqlite.select(LocalText).all().project(TextRow, value=LocalText.value)

    async with database.transaction() as transaction:
        rows = await transaction.fetch_all(operand.union(operand))

    assert_eq([row.value.lower() for row in rows], ["a"])


@test(mark="slow")
async def mariadb_union_uses_source_collation() -> None:
    """Unicode collation semantics remain the database's responsibility."""
    database = await load_fixture(provide_mariadb_events())
    operand = mariadb.select(NativeText).all().project(TextRow, value=NativeText.value)

    async with database.transaction() as transaction:
        rows = await transaction.fetch_all(operand.union(operand))

    assert_eq([row.value.lower() for row in rows], ["a"])


@test(mark="slow")
async def mariadb_compound_page_applies_after_duplicate_elimination() -> None:
    """Native final pagination sees the distinct combined set."""
    database = await load_fixture(provide_mariadb_events())
    token = MariaEvent.event_id.label("event_id")
    operand = mariadb.select(MariaEvent).all().project(Row, event_id=token)
    combined = operand.union(operand)

    async with database.transaction() as transaction:
        rows = await transaction.fetch_all(
            combined.order_by(combined.column(token).desc()).limit(1).offset(1)
        )

    assert_eq(rows, [Row(event_id=2)])


@test(mark="medium")
async def compound_result_validation_is_strict_when_source_validation_is_disabled() -> (
    None
):
    """The source-validation escape hatch does not bypass the final row model."""
    database = await load_fixture(provide_sqlite_events())

    class ConstrainedRow(BaseModel):
        event_id: int = Field(gt=10)

    operand = (
        sqlite.select(Event).all().project(ConstrainedRow, event_id=Event.event_id)
    )

    async with database.transaction() as transaction:
        with assert_raises(sqlite.ModelValidationError):
            await transaction.fetch_all(operand.union(operand), validate=False)


@test(mark="medium")
async def sqlite_extrema_union_decodes_the_original_column_domain() -> None:
    """MIN/MAX share the column wire format without requiring identical provenance."""
    database = await load_fixture(provide_sqlite_events())
    left = (
        sqlite.select(Event).all().project(OptionalRow, event_id=Event.event_id.min())
    )
    right = (
        sqlite.select(Event).all().project(OptionalRow, event_id=Event.event_id.max())
    )

    async with database.transaction() as transaction:
        rows = await transaction.fetch_all(left.union_all(right))

    assert_eq(rows, [OptionalRow(event_id=1), OptionalRow(event_id=3)])


@test(mark="slow")
async def mariadb_extrema_union_decodes_the_original_column_domain() -> None:
    """Native extrema retain their compatible source decoder across the set boundary."""
    database = await load_fixture(provide_mariadb_events())
    left = (
        mariadb.select(MariaEvent)
        .all()
        .project(OptionalRow, event_id=MariaEvent.event_id.min())
    )
    right = (
        mariadb.select(MariaEvent)
        .all()
        .project(OptionalRow, event_id=MariaEvent.event_id.max())
    )

    async with database.transaction() as transaction:
        rows = await transaction.fetch_all(left.union_all(right))

    assert_eq(rows, [OptionalRow(event_id=1), OptionalRow(event_id=3)])
