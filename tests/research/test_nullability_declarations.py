"""Native type observations for #473; never execute the rendered model source."""

from anyio import Path
from snektest import Param, test

from tests.research.typing_support import assert_paired_typing

BACKENDS = [Param(backend, name=backend) for backend in ("sqlite", "mariadb")]


@test(BACKENDS, mark="slow")
async def non_null_input_can_have_a_nullable_row_without_optionalizing_input(
    backend: str,
) -> None:
    declarations = await Path(
        "research/nullability_473/declarations.py.txt"
    ).read_text()
    source = (
        declarations.replace("__BACKEND__", backend)
        + """
from typing import ClassVar, assert_type

class Entry[S = database.Pending](database.Model[S]):
    __row_type__: ClassVar[database.ReadType[Entry[database.Row]]]
    value: Col[str, str | None] = database.Text(nullable=True)

pending = Entry(value="client")
assert_type(pending.value, str)
Entry()  # error: missing-argument
Entry(value=None)  # error: invalid-argument-type
Entry(value=1)  # error: invalid-argument-type

def consumer(pending: Entry[database.Pending], row: Entry[database.Row]) -> None:
    assert_type(pending.value, str)
    assert_type(row.value, str | None)
    pending.value = "other"  # error: invalid-assignment
    row.value = None  # error: invalid-assignment
"""
    )
    await assert_paired_typing(source)


@test(BACKENDS, mark="slow")
async def separate_input_and_row_domains_also_keep_generated_overrides_precise(
    backend: str,
) -> None:
    declarations = await Path(
        "research/nullability_473/declarations.py.txt"
    ).read_text()
    source = (
        declarations.replace("__BACKEND__", backend)
        + """
from typing import ClassVar, assert_type

class Entry[S = database.Pending](ResearchModel[S]):
    __row_type__: ClassVar[database.ReadType[Entry[database.Row]]]
    value: GenCol[str, str | None] = Text(
        nullable=True, default=database.PENDING_GENERATION, server_default="server"
    )

assert_type(Entry().value, str | database.PENDING_GENERATION)
Entry(value="client")
Entry(value=database.PENDING_GENERATION)
Entry(value=None)  # error: invalid-argument-type
Entry(value=1)  # error: invalid-argument-type
Entry[database.Row](value="client")  # error: invalid-argument-type

def consumer(row: Entry[database.Row]) -> None:
    assert_type(row.value, str | None)
    row.value = None  # error: invalid-assignment
"""
    )
    await assert_paired_typing(source)


@test(BACKENDS, mark="slow")
async def current_nullability_does_not_supply_a_constructor_default(
    backend: str,
) -> None:
    source = """
from typing import ClassVar, assert_type
from snekql import __BACKEND__ as database

type MaybeText = str | None

class Entry[S = database.Pending](database.Model[S]):
    __row_type__: ClassVar[database.ReadType[Entry[database.Row]]]
    required: database.Col[str] = database.Text()
    nullable: database.Col[MaybeText] = database.Text()
    python_none: database.Col[str | None] = database.Text(default=None)
    python_value: database.Col[str] = database.Text(default="client")
    factory: database.Col[str] = database.Text(default_factory=lambda: "client")
    sql_value: database.GenCol[str | None] = database.Text(default=database.LiteralDefault("server"))
    sql_null: database.GenCol[str | None] = database.Text(default=database.LiteralDefault(None))
    generated_required: database.GenCol[int] = database.Integer()

pending = Entry(required="x", nullable=None, generated_required=1)
Entry(required="x", nullable="x", generated_required=database.PENDING_GENERATION)
Entry(nullable=None, generated_required=1)  # error: missing-argument
Entry(required="x", generated_required=1)  # error: missing-argument
Entry(required="x", nullable=None)  # error: missing-argument
Entry(required=None, nullable=None, generated_required=1)  # error: invalid-argument-type
Entry(required="x", nullable=1, generated_required=1)  # error: invalid-argument-type

assert_type(pending.required, str)
assert_type(pending.nullable, str | None)
assert_type(pending.python_none, str | None)
assert_type(pending.python_value, str)
assert_type(pending.factory, str)
assert_type(pending.sql_value, str | None | database.PENDING_GENERATION)
assert_type(pending.sql_null, str | None | database.PENDING_GENERATION)
assert_type(pending.generated_required, int | database.PENDING_GENERATION)

def consumer(row: Entry[database.Row]) -> None:
    assert_type(row.nullable, str | None)
    assert_type(row.sql_value, str | None)
    assert_type(row.sql_null, str | None)
    assert_type(row.generated_required, int)
""".replace("__BACKEND__", backend)
    await assert_paired_typing(source)


@test(BACKENDS, mark="slow")
async def current_schema_flags_are_not_native_input_or_row_type_operators(
    backend: str,
) -> None:
    # These classes pass ty but current runtime declaration guards reject them.
    # They are deliberately never executed; green is an accepted-gap observation.
    source = """
from typing import ClassVar, assert_type
from snekql import __BACKEND__ as database

class Narrow[S = database.Pending](database.Model[S]):
    __row_type__: ClassVar[database.ReadType[Narrow[database.Row]]]
    value: database.Col[str] = database.Text(nullable=True)

class Wide[S = database.Pending](database.Model[S]):
    __row_type__: ClassVar[database.ReadType[Wide[database.Row]]]
    value: database.Col[str | None] = database.Text(nullable=False)

Narrow(value="client")
Wide(value=None)
Wide(value="client")
Narrow(value=None)  # error: invalid-argument-type
Wide()  # error: missing-argument

def consumer(narrow: Narrow[database.Row], wide: Wide[database.Row]) -> None:
    assert_type(narrow.value, str)
    assert_type(wide.value, str | None)
""".replace("__BACKEND__", backend)
    await assert_paired_typing(source)


@test(BACKENDS, mark="slow")
async def separate_domains_keep_python_defaults_and_sql_null_in_their_own_domains(
    backend: str,
) -> None:
    declarations = await Path(
        "research/nullability_473/declarations.py.txt"
    ).read_text()
    source = (
        declarations.replace("__BACKEND__", backend)
        + """
from typing import ClassVar, assert_type

class Entry[S = database.Pending](ResearchModel[S]):
    __row_type__: ClassVar[database.ReadType[Entry[database.Row]]]
    required: Col[str, str | None] = Text(server_default="server", nullable=True)
    python: Col[str, str | None] = Text(default="client", server_default="server", nullable=True)
    factory: Col[str, str | None] = Text(default_factory=lambda: "client", server_default="server", nullable=True)
    sql_null: GenCol[str, str | None] = Text(default=database.PENDING_GENERATION, server_default=None, nullable=True)

assert_type(Entry(required="client").python, str)
assert_type(Entry(required="client").factory, str)
assert_type(Entry(required="client").sql_null, str | database.PENDING_GENERATION)
Entry()  # error: missing-argument
Entry(required=None)  # error: invalid-argument-type
Entry(required="client", python=None)  # error: invalid-argument-type
Entry(required="client", sql_null=None)  # error: invalid-argument-type

class BadPython[S = database.Pending](ResearchModel[S]):
    __row_type__: ClassVar[database.ReadType[BadPython[database.Row]]]
    value: Col[str, str | None] = Text(default=None, server_default="server", nullable=True)  # error: invalid-assignment

class BadSql[S = database.Pending](ResearchModel[S]):
    __row_type__: ClassVar[database.ReadType[BadSql[database.Row]]]
    value: GenCol[str, str | None] = Text(default=database.PENDING_GENERATION, server_default=1, nullable=True)  # error: invalid-assignment

def consumer(row: Entry[database.Row]) -> None:
    assert_type(row.required, str | None)
    assert_type(row.python, str | None)
    assert_type(row.factory, str | None)
    assert_type(row.sql_null, str | None)
"""
    )
    await assert_paired_typing(source)


@test(BACKENDS, mark="slow")
async def imported_two_domain_models_keep_query_results_and_join_nullability(
    backend: str,
) -> None:
    declarations = (
        await Path("research/nullability_473/declarations.py.txt").read_text()
    ).replace("__BACKEND__", backend)
    model = """
from typing import ClassVar
from nullability_factory import Col, GenCol, ResearchModel, Text, database

class Entry[S = database.Pending](ResearchModel[S]):
    __row_type__: ClassVar[database.ReadType[Entry[database.Row]]]
    value: Col[str, str | None] = database.Text(nullable=True)
    generated: GenCol[str, str | None] = Text(default=database.PENDING_GENERATION, server_default=None, nullable=True)

class Other[S = database.Pending](database.Model[S]):
    __row_type__: ClassVar[database.ReadType[Other[database.Row]]]
    name: database.Col[str] = database.Text()
"""
    consumer = """
from typing import assert_type
from snekql import __BACKEND__ as database
from nullability_model import Entry, Other

pending = Entry(value="client")
assert_type(pending.value, str)
assert_type(pending.generated, str | database.PENDING_GENERATION)
Entry(value=None)  # error: invalid-argument-type
Entry()  # error: missing-argument
Entry[database.Row](value="client")  # error: invalid-argument-type
write: database.Write[Entry[database.Row]] = database.insert(pending).returning()

async def reads(tx: database.Transaction) -> None:
    row = await tx.fetch_one(database.select(Entry))
    assert_type(row, Entry[database.Row])
    assert_type(row.value, str | None)
    assert_type(row.generated, str | None)
    assert_type(await tx.fetch_one(database.select(Entry.value)), str | None)
    assert_type(await tx.fetch_one(database.select(Entry.value), validate=False), object)
    assert_type(
        await tx.fetch_one(database.select(Entry).left_join(Other, on=Other.name.eq("match"))),
        tuple[Entry[database.Row], Other[database.Row] | None],
    )
    too_narrow: str = row.value  # error: invalid-assignment
    row.value = None  # error: invalid-assignment
""".replace("__BACKEND__", backend)
    await assert_paired_typing(
        consumer,
        modules={"nullability_factory": declarations, "nullability_model": model},
    )


@test(BACKENDS, mark="slow")
async def ordinary_default_helpers_do_not_implement_separate_domains(
    backend: str,
) -> None:
    declarations = await Path(
        "research/nullability_473/declarations.py.txt"
    ).read_text()
    source = (
        declarations.replace("__BACKEND__", backend)
        + """
from typing import ClassVar, assert_type

class Ordinary[S = database.Pending](database.Model[S]):
    __row_type__: ClassVar[database.ReadType[Ordinary[database.Row]]]
    value: Col[str] = database.Text()
    generated: GenCol[str] = database.Text()

assert_type(Ordinary(value="client", generated="x").value, str)
Ordinary(value="client", generated=database.PENDING_GENERATION)
Ordinary(value="client")  # error: missing-argument
Ordinary(value=None, generated="x")  # error: invalid-argument-type

def consumer(row: Ordinary[database.Row]) -> None:
    assert_type(row.value, str)
    assert_type(row.generated, str)

# Current marker helpers tie the input/Pending domain to the Row domain.
# Changing aliases alone did not make these valid; custom typed producers above
# are a research contract, not proof of current runtime implementation.
class CurrentMarker[S = database.Pending](database.Model[S]):
    __row_type__: ClassVar[database.ReadType[CurrentMarker[database.Row]]]
    value: GenCol[str, str | None] = database.Text(nullable=True, default=database.LiteralDefault("server"))  # error: invalid-assignment

class CurrentNullMarker[S = database.Pending](database.Model[S]):
    __row_type__: ClassVar[database.ReadType[CurrentNullMarker[database.Row]]]
    value: GenCol[str, str | None] = database.Text(nullable=True, default=database.LiteralDefault(None))  # error: invalid-assignment
"""
    )
    await assert_paired_typing(source)


@test(BACKENDS, mark="slow")
async def required_prototype_calls_still_need_runtime_schema_validation(
    backend: str,
) -> None:
    declarations = await Path(
        "research/nullability_473/declarations.py.txt"
    ).read_text()
    source = (
        declarations.replace("__BACKEND__", backend)
        + """
from typing import ClassVar, assert_type

# Accepted gaps: the registered no-Python-default path does not check its
# descriptor result against the annotated read domain. Not producer conformance.
class RequiredGap[S = database.Pending](ResearchModel[S]):
    __row_type__: ClassVar[database.ReadType[RequiredGap[database.Row]]]
    wrong_sql: Col[str, str | None] = Text(server_default=1, nullable=True)
    incompatible_read: Col[str, int] = Text(server_default="server", nullable=True)

RequiredGap(wrong_sql="client", incompatible_read="client")
RequiredGap(wrong_sql=None, incompatible_read="client")  # error: invalid-argument-type
RequiredGap(incompatible_read="client")  # error: missing-argument

def consumer(row: RequiredGap[database.Row]) -> None:
    assert_type(row.wrong_sql, str | None)
    assert_type(row.incompatible_read, int)

# None is a valid Python default only when the INPUT domain admits it.
class NullableInput[S = database.Pending](ResearchModel[S]):
    __row_type__: ClassVar[database.ReadType[NullableInput[database.Row]]]
    value: Col[str | None] = Text(default=None, server_default="server", nullable=True)

assert_type(NullableInput().value, str | None)
NullableInput(value=None)
NullableInput(value=1)  # error: invalid-argument-type

def needs_argument(value: str) -> str:
    return value

class BadFactory[S = database.Pending](ResearchModel[S]):
    __row_type__: ClassVar[database.ReadType[BadFactory[database.Row]]]
    value: Col[str, str | None] = Text(default_factory=needs_argument, server_default="server", nullable=True)  # error: invalid-argument-type
"""
    )
    await assert_paired_typing(source)


@test(BACKENDS, mark="slow")
async def schema_nullable_need_not_force_nullable_application_reads(
    backend: str,
) -> None:
    declarations = await Path(
        "research/nullability_473/declarations.py.txt"
    ).read_text()
    source = (
        declarations.replace("__BACKEND__", backend)
        + """
from typing import ClassVar, assert_type

# This policy requires validated SQL NULL reads to RAISE, not to return None.
# Only static consumer behavior is witnessed; no decoder is implemented here.
class StrictSubset[S = database.Pending](ResearchModel[S]):
    __row_type__: ClassVar[database.ReadType[StrictSubset[database.Row]]]
    value: Col[str] = Text(default="client", server_default="server", nullable=True)
    generated: GenCol[str] = Text(default=database.PENDING_GENERATION, server_default="server", nullable=True)

assert_type(StrictSubset().value, str)
assert_type(StrictSubset().generated, str | database.PENDING_GENERATION)
StrictSubset(value=None)  # error: invalid-argument-type
StrictSubset(generated=None)  # error: invalid-argument-type

def consumer(row: StrictSubset[database.Row]) -> None:
    assert_type(row.value, str)
    assert_type(row.generated, str)

# A valid intended strict-subset policy that this narrow producer OVER-REJECTS:
# Python always binds a non-null default; only other writers use SQL DEFAULT NULL.
class UnsupportedSchemaOnlyNull[S = database.Pending](ResearchModel[S]):
    __row_type__: ClassVar[database.ReadType[UnsupportedSchemaOnlyNull[database.Row]]]
    value: Col[str] = Text(default="client", server_default=None, nullable=True)  # error: invalid-assignment

class NullGeneration[S = database.Pending](ResearchModel[S]):
    __row_type__: ClassVar[database.ReadType[NullGeneration[database.Row]]]
    value: GenCol[str] = Text(default=database.PENDING_GENERATION, server_default=None, nullable=True)  # error: invalid-assignment
"""
    )
    await assert_paired_typing(source)
