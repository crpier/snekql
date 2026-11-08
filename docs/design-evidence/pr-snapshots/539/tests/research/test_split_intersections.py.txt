"""Native callable intersections for #473; no declaration is ever executed."""

from anyio import Path
from snektest import Param, test

from tests.research.test_default_declarations import assert_paired_typing
from tests.research.test_defaults_review import review_source
from tests.research.test_split_omission import CONSUMER


async def intersection_source(backend: str, consumer: str) -> str:
    declarations = await Path(
        "research/defaults_473/intersection_declarations.py.txt"
    ).read_text()
    consumer = await review_source(
        backend, "split", "# intersection-consumer\n" + consumer
    )
    consumer = consumer.split("# intersection-consumer\n", 1)[1]
    consumer = consumer.replace("TwinInteger", "Integer").replace("TwinText", "Text")
    consumer = consumer.replace(
        "default=database.PENDING_GENERATION, server_default=", "server_default="
    )
    consumer = consumer.replace(
        "default=database.PENDING_GENERATION, primary_key=", "primary_key="
    )
    return (
        (declarations + "\n" + consumer)
        .replace("__BACKEND__", backend)
        .replace("__META_MODULE__", f"snekql.{backend}.model")
    )


@test([Param(backend, name=backend) for backend in ("sqlite", "mariadb")], mark="slow")
async def intersection_calls_cover_the_core_sheet_without_pending_arguments(
    backend: str,
) -> None:
    consumer = await Path("research/defaults_473/review_baseline.py.txt").read_text()
    await assert_paired_typing(await intersection_source(backend, consumer))


@test([Param(backend, name=backend) for backend in ("sqlite", "mariadb")], mark="slow")
async def imported_intersection_factories_keep_their_native_constructor_behavior(
    backend: str,
) -> None:
    declarations = await intersection_source(backend, "")
    consumer = """
from typing import ClassVar, assert_type
from native_factories import Integer, Text, ReviewModel, database

class Entry[S = database.Pending](ReviewModel[S]):
    __row_type__: ClassVar[database.ReadType[Entry[database.Row]]]
    required: database.Col[bool] = Integer()
    server: database.GenCol[bool] = Integer(server_default=False)

assert_type(Entry(required=True).server, bool | database.PENDING_GENERATION)
Entry(server=True)  # error: missing-argument
Entry(required=True, server=None)  # error: invalid-argument-type
"""
    await assert_paired_typing(consumer, modules={"native_factories": declarations})


@test([Param(backend, name=backend) for backend in ("sqlite", "mariadb")], mark="slow")
async def intersection_required_override_and_independent_defaults_keep_brownfield_flexibility(
    backend: str,
) -> None:
    consumer = CONSUMER.replace(
        "# required-probe", "# error: missing-argument"
    ).replace("# schema-required-probe", "# error: missing-argument")
    consumer = consumer.replace(
        "value: database.Col[bool] = TwinInteger(server_default=False)",
        "value: database.Col[bool] = TwinInteger(server_default=False, required=True)",
    )
    consumer += """
class BothFactory[S = database.Pending](ReviewModel[S]):
    __row_type__: ClassVar[database.ReadType[BothFactory[database.Row]]]
    value: database.Col[str] = Text(default_factory=lambda: "client", server_default="server")

assert_type(BothFactory().value, str)
BothFactory(value=None)  # error: invalid-argument-type

class RequiredServerGenerated[S = database.Pending](ReviewModel[S]):
    __row_type__: ClassVar[database.ReadType[RequiredServerGenerated[database.Row]]]
    value: database.GenCol[bool] = Integer(server_default=False, required=True)

assert_type(RequiredServerGenerated(value=False).value, bool | database.PENDING_GENERATION)
RequiredServerGenerated(value=database.PENDING_GENERATION)
RequiredServerGenerated()  # error: missing-argument

class BareSchemaOnly[S = database.Pending](ReviewModel[S]):
    __row_type__: ClassVar[database.ReadType[BareSchemaOnly[database.Row]]]
    value: database.Col[bool] = Integer(server_default=False)  # error: invalid-assignment
"""
    await assert_paired_typing(await intersection_source(backend, consumer))


@test([Param(backend, name=backend) for backend in ("sqlite", "mariadb")], mark="slow")
async def intersection_declaration_errors_do_not_get_erased_by_callable_narrowing(
    backend: str,
) -> None:
    consumer = await Path("research/defaults_473/review_misuse.py.txt").read_text()
    await assert_paired_typing(await intersection_source(backend, consumer))


@test([Param(backend, name=backend) for backend in ("sqlite", "mariadb")], mark="slow")
async def intersection_nullable_clocks_factories_and_required_generated_inputs_stay_precise(
    backend: str,
) -> None:
    consumer = """
from typing import ClassVar, assert_type

class RequiredGenerated[S = database.Pending](ReviewModel[S]):
    __row_type__: ClassVar[database.ReadType[RequiredGenerated[database.Row]]]
    value: database.GenCol[str] = Text()

assert_type(RequiredGenerated(value="given").value, str | database.PENDING_GENERATION)
RequiredGenerated(value=database.PENDING_GENERATION)
RequiredGenerated()  # error: missing-argument
RequiredGenerated(value=42)  # error: invalid-argument-type

class Clock[S = database.Pending](ReviewModel[S]):
    __row_type__: ClassVar[database.ReadType[Clock[database.Row]]]
    value: database.GenCol[database.UtcDatetime | None] = Text(server_default=database.CurrentTimestamp)

assert_type(Clock().value, database.UtcDatetime | None | database.PENDING_GENERATION)
Clock(value=None)
Clock(value="wrong")  # error: invalid-argument-type

class NullOnlyClock[S = database.Pending](ReviewModel[S]):
    __row_type__: ClassVar[database.ReadType[NullOnlyClock[database.Row]]]
    value: database.GenCol[None] = Text(server_default=database.CurrentTimestamp)  # error: invalid-assignment

def needs_argument(value: str) -> str:
    return value

class BadFactory[S = database.Pending](ReviewModel[S]):
    __row_type__: ClassVar[database.ReadType[BadFactory[database.Row]]]
    value: database.Col[str] = Text(default_factory=needs_argument)  # error: no-matching-overload, invalid-argument-type
"""
    await assert_paired_typing(await intersection_source(backend, consumer))


@test([Param(backend, name=backend) for backend in ("sqlite", "mariadb")], mark="slow")
async def importing_intersection_models_preserves_postponed_annotations_and_row_results(
    backend: str,
) -> None:
    baseline = await Path("research/defaults_473/review_baseline.py.txt").read_text()
    declarations = "from __future__ import annotations\n" + await intersection_source(
        backend, baseline.split("pending =", 1)[0]
    )
    consumer = """
from typing import assert_type
from intersected_model import Review, database

pending = Review(required="Ada", required_nullable=None)
assert_type(pending, Review[database.Pending])
assert_type(pending.server_value, bool | database.PENDING_GENERATION)
assert_type(pending.server_null, str | None | database.PENDING_GENERATION)
assert_type(pending.identity, int | database.PENDING_GENERATION)
write: database.Write[Review[database.Row]] = database.insert(pending).returning()

def row(value: Review[database.Row]) -> None:
    assert_type(value.server_value, bool)
    assert_type(value.server_clock, database.UtcDatetime)
    assert_type(value.server_null, str | None)
    assert_type(value.identity, int)

Review(required="Ada")  # error: missing-argument
Review(required="Ada", required_nullable=None, server_value=None)  # error: invalid-argument-type
pending.server_value = True  # error: invalid-assignment
Review[database.Row](required="Ada", required_nullable=None)  # error: invalid-argument-type
"""
    await assert_paired_typing(consumer, modules={"intersected_model": declarations})


@test([Param(backend, name=backend) for backend in ("sqlite", "mariadb")], mark="slow")
async def intersection_required_escape_keeps_accepted_sql_validation_gaps_visible(
    backend: str,
) -> None:
    consumer = """
from typing import ClassVar, assert_type

class AcceptedGaps[S = database.Pending](ReviewModel[S]):
    __row_type__: ClassVar[database.ReadType[AcceptedGaps[database.Row]]]
    literal: database.Col[int] = Integer(server_default="wrong", required=True)
    null: database.Col[str] = Text(server_default=None, required=True)
    clock: database.Col[str] = Text(server_default=database.CurrentTimestamp, required=True)

value = AcceptedGaps(literal=3, null="value", clock="value")
assert_type(value.literal, int)
assert_type(value.null, str)
AcceptedGaps(null="value", clock="value")  # error: missing-argument
AcceptedGaps(literal="wrong", null="value", clock="value")  # error: invalid-argument-type
Integer(default=False, server_default=True, required=True)  # error: no-matching-overload, no-matching-overload
"""
    await assert_paired_typing(await intersection_source(backend, consumer))
