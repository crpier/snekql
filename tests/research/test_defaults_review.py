"""The agreed review sheet exercised at declaration/consumer typing seams."""

from anyio import Path
from snektest import Param, test

from tests.research.test_default_declarations import assert_paired_typing


async def review_source(backend: str, candidate: str, consumer: str) -> str:
    declarations = await Path(
        "research/defaults_473/review_declarations.py.txt"
    ).read_text()
    if candidate == "split":
        expressions = (
            "TwinText()",
            "TwinText()",
            "TwinInteger(default=7)",
            "TwinText(default=None)",
            'TwinText(default="guest")',
            "TwinText(default_factory=uuid4)",
            "TwinInteger(default=database.PENDING_GENERATION, server_default=False)",
            "TwinText(default=database.PENDING_GENERATION, server_default=database.CurrentTimestamp)",
            'TwinText(default=database.PENDING_GENERATION, server_default="fallback")',
            "TwinText(default=database.PENDING_GENERATION, server_default=None)",
            "TwinInteger(default=database.PENDING_GENERATION, primary_key=True, auto_increment=True)",
        )
    elif candidate == "selector":
        expressions = (
            "ChoiceText()",
            "ChoiceText()",
            "ChoiceInteger(default=7)",
            "ChoiceText(default=None)",
            'ChoiceText(default="guest")',
            "ChoiceText(default_factory=uuid4)",
            'ChoiceInteger(default=False, default_on="server")',
            'ChoiceText(default=database.CurrentTimestamp, default_on="server")',
            'ChoiceText(default="fallback", default_on="server")',
            'ChoiceText(default=None, default_on="server")',
            "ChoiceInteger(default=database.PENDING_GENERATION, primary_key=True, auto_increment=True)",
        )
    elif candidate == "prefix":
        expressions = (
            "database.Text()",
            "database.Text()",
            "database.Integer(default=7)",
            "database.Text(default=None)",
            'database.Text(default="guest")',
            "database.Text(default_factory=uuid4)",
            "ServerInteger(False)",
            "ServerText(database.CurrentTimestamp)",
            'ServerText("fallback")',
            "ServerText(None)",
            "ServerInteger(primary_key=True, auto_increment=True)",
        )
    elif candidate == "explicit_prefix":
        expressions = (
            "database.Text()",
            "database.Text()",
            "PythonInteger(7)",
            "PythonText(None)",
            'PythonText("guest")',
            "PythonText(factory=uuid4)",
            "ServerInteger(False)",
            "ServerText(database.CurrentTimestamp)",
            'ServerText("fallback")',
            "ServerText(None)",
            "ServerInteger(primary_key=True, auto_increment=True)",
        )
    elif candidate == "policies":
        declarations = await Path(
            "research/defaults_473/policy_declarations.py.txt"
        ).read_text()
        declarations = declarations.replace(
            "class PolicyModel[S]", "class ReviewModel[S]"
        )
        expressions = (
            "PolicyText()",
            "PolicyText()",
            "PolicyInteger(default=PythonDefault(7))",
            "PolicyText(default=PythonDefault(None))",
            'PolicyText(default=PythonDefault("guest"))',
            "PolicyText(default=PythonDefault(factory=uuid4))",
            "PolicyInteger(default=ServerDefault(False))",
            "PolicyText(default=ServerDefault(database.CurrentTimestamp))",
            'PolicyText(default=ServerDefault("fallback"))',
            "PolicyText(default=ServerDefault(None))",
            "database.Integer(default=database.PENDING_GENERATION, primary_key=True, auto_increment=True)",
        )
    else:
        raise ValueError(candidate)
    for name, expression in zip(
        (
            "REQUIRED",
            "REQUIRED_NULLABLE",
            "PYTHON_VALUE",
            "PYTHON_NONE",
            "PYTHON_NULLABLE",
            "PYTHON_FACTORY",
            "SERVER_VALUE",
            "SERVER_CLOCK",
            "SERVER_NULLABLE",
            "SERVER_NULL",
            "IDENTITY",
        ),
        expressions,
        strict=True,
    ):
        consumer = consumer.replace(f"__{name}__", expression)
    return (
        (declarations + "\n" + consumer)
        .replace("__BACKEND__", backend)
        .replace("__META_MODULE__", f"snekql.{backend}.model")
    )


@test(
    [Param(backend, name=backend) for backend in ("sqlite", "mariadb")],
    [
        Param(candidate, name=candidate)
        for candidate in ("split", "selector", "prefix", "explicit_prefix", "policies")
    ],
    mark="slow",
)
async def candidates_cover_the_eleven_core_scenarios(
    backend: str, candidate: str
) -> None:
    consumer = await Path("research/defaults_473/review_baseline.py.txt").read_text()
    await assert_paired_typing(await review_source(backend, candidate, consumer))


@test(
    [Param(backend, name=backend) for backend in ("sqlite", "mariadb")],
    mark="slow",
)
async def tightened_prefix_requires_a_declared_generation_source(backend: str) -> None:
    consumer = """
from typing import ClassVar

class Source[S = database.Pending](ReviewModel[S]):
    __row_type__: ClassVar[database.ReadType[Source[database.Row]]]
    id: database.GenCol[int] = ServerInteger(primary_key=True, auto_increment=True)
    absent: database.GenCol[int] = ServerInteger()  # error: no-matching-overload
    disabled: database.GenCol[int] = ServerInteger(auto_increment=False)  # error: no-matching-overload
    wrong_type: database.GenCol[str] = ServerInteger(primary_key=True, auto_increment=True)  # error: invalid-assignment
"""
    await assert_paired_typing(await review_source(backend, "prefix", consumer))


@test(
    [Param(backend, name=backend) for backend in ("sqlite", "mariadb")],
    [
        Param(candidate, name=candidate)
        for candidate in ("split", "selector", "prefix", "explicit_prefix", "policies")
    ],
    mark="slow",
)
async def declaration_mistakes_do_not_hide_behind_precise_constructor_types(
    backend: str, candidate: str
) -> None:
    consumer = await Path("research/defaults_473/review_misuse.py.txt").read_text()
    await assert_paired_typing(await review_source(backend, candidate, consumer))


@test(
    [Param(backend, name=backend) for backend in ("sqlite", "mariadb")],
    mark="slow",
)
async def split_contrasts_keep_required_inputs_but_expose_server_only_validation_gaps(
    backend: str,
) -> None:
    consumer = await Path(
        "research/defaults_473/review_split_contrasts.py.txt"
    ).read_text()
    await assert_paired_typing(await review_source(backend, "split", consumer))


@test(
    [Param(backend, name=backend) for backend in ("sqlite", "mariadb")],
    [
        Param(candidate, name=candidate)
        for candidate in ("split", "selector", "prefix", "explicit_prefix", "policies")
    ],
    mark="slow",
)
async def nullable_clock_defaults_keep_explicit_none_without_claiming_null_only_rows(
    backend: str, candidate: str
) -> None:
    consumer = """
from typing import ClassVar, assert_type

class Clock[S = database.Pending](ReviewModel[S]):
    __row_type__: ClassVar[database.ReadType[Clock[database.Row]]]
    value: database.GenCol[database.UtcDatetime | None] = __SERVER_CLOCK__

assert_type(Clock().value, database.UtcDatetime | None | database.PENDING_GENERATION)
Clock(value=None)
Clock(value="wrong")  # error: invalid-argument-type

class BadClock[S = database.Pending](ReviewModel[S]):
    __row_type__: ClassVar[database.ReadType[BadClock[database.Row]]]
    value: database.GenCol[None] = __SERVER_CLOCK__  # error: invalid-assignment
"""
    await assert_paired_typing(await review_source(backend, candidate, consumer))


@test(
    [Param(backend, name=backend) for backend in ("sqlite", "mariadb")],
    [
        Param(candidate, name=candidate)
        for candidate in ("split", "selector", "prefix", "explicit_prefix", "policies")
    ],
    mark="slow",
)
async def importing_consumers_keep_required_arguments_and_pending_row_types(
    backend: str, candidate: str
) -> None:
    baseline = await Path("research/defaults_473/review_baseline.py.txt").read_text()
    declarations = await review_source(
        backend, candidate, baseline.split("pending =", 1)[0]
    )
    consumer = """
from typing import assert_type
from reviewed_model import Review, database

pending = Review(required="Ada", required_nullable=None)
assert_type(pending, Review[database.Pending])
assert_type(pending.server_value, bool | database.PENDING_GENERATION)
assert_type(pending.python_value, int)
Review(required="Ada", required_nullable=None, server_nullable=None)

def fetched(row: Review[database.Row]) -> None:
    assert_type(row.server_value, bool)
    assert_type(row.server_nullable, str | None)

Review(required="Ada")  # error: missing-argument
Review(required="Ada", required_nullable=None, server_value="wrong")  # error: invalid-argument-type
"""
    await assert_paired_typing(consumer, modules={"reviewed_model": declarations})


@test(
    [Param(backend, name=backend) for backend in ("sqlite", "mariadb")],
    [
        Param(candidate, name=candidate)
        for candidate in ("split", "selector", "prefix", "explicit_prefix", "policies")
    ],
    mark="slow",
)
async def factories_requiring_arguments_are_rejected(
    backend: str, candidate: str
) -> None:
    consumer = """
from typing import ClassVar

def needs_argument(value: str) -> str:
    return value

class BadFactory[S = database.Pending](ReviewModel[S]):
    __row_type__: ClassVar[database.ReadType[BadFactory[database.Row]]]
    value: database.Col[str] = __PYTHON_FACTORY__  # error: invalid-argument-type
"""
    if candidate == "prefix":
        consumer = consumer.replace(
            "# error: invalid-argument-type", "# error: no-matching-overload"
        )
    source = (await review_source(backend, candidate, consumer)).replace(
        "factory=uuid4", "factory=needs_argument"
    )
    await assert_paired_typing(source)


@test(
    [Param(backend, name=backend) for backend in ("sqlite", "mariadb")],
    [
        Param(candidate, name=candidate)
        for candidate in ("split", "selector", "prefix", "explicit_prefix", "policies")
    ],
    mark="slow",
)
async def required_generated_inputs_stay_required_without_an_omission_default(
    backend: str, candidate: str
) -> None:
    consumer = """
from typing import ClassVar, assert_type

class RequiredGenerated[S = database.Pending](ReviewModel[S]):
    __row_type__: ClassVar[database.ReadType[RequiredGenerated[database.Row]]]
    value: database.GenCol[str] = __REQUIRED__

assert_type(RequiredGenerated(value="concrete").value, str | database.PENDING_GENERATION)
RequiredGenerated(value=database.PENDING_GENERATION)
RequiredGenerated()  # error: missing-argument
RequiredGenerated(value=42)  # error: invalid-argument-type
"""
    await assert_paired_typing(await review_source(backend, candidate, consumer))


@test(
    [Param(backend, name=backend) for backend in ("sqlite", "mariadb")],
    mark="slow",
)
async def contradictory_modes_and_missing_defaults_are_rejected_by_signatures(
    backend: str,
) -> None:
    consumer = """
ChoiceInteger(default=False, default_on="server")
PythonInteger(7)
PythonText(factory=lambda: "value")
ChoiceInteger(default=7, default_on="typo")  # error: no-matching-overload
ChoiceInteger(default_on="server")  # error: invalid-argument-type
ChoiceText(default_factory=lambda: "value", default_on="server")  # error: invalid-argument-type
ChoiceText(default="value", default_factory=lambda: "value")  # error: no-matching-overload
TwinText(default="value", default_factory=lambda: "value")  # error: no-matching-overload
PythonInteger()  # error: missing-argument
PythonText()  # error: no-matching-overload
PythonText("value", factory=lambda: "value")  # error: no-matching-overload
"""
    await assert_paired_typing(await review_source(backend, "selector", consumer))
