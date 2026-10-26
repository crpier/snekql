"""The agreed review sheet exercised at declaration/consumer typing seams."""

from ast import AnnAssign, ClassDef, FunctionDef, If, parse, unparse

from anyio import Path
from snektest import Param, test

from tests.research.test_default_declarations import assert_paired_typing


async def review_source(backend: str, candidate: str, consumer: str) -> str:
    declarations = await Path(
        "research/defaults_473/review_declarations.py.txt"
    ).read_text()
    if candidate == "current":
        declarations = (
            "from snekql import __BACKEND__ as database\nReviewModel = database.Model\n"
        )
        expressions = (
            "database.Text()",
            "database.Text()",
            "database.Integer(default=7)",
            "database.Text(default=None)",
            'database.Text(default="guest")',
            "database.Text(default_factory=uuid4)",
            "database.Integer(default=database.LiteralDefault(False))",
            "database.Text(default=database.CurrentTimestamp)",
            'database.Text(default=database.LiteralDefault("fallback"))',
            "database.Text(default=database.LiteralDefault(None))",
            "database.Integer(default=database.PENDING_GENERATION, primary_key=True, auto_increment=True)",
        )
    elif candidate == "split":
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
        for candidate in (
            "current",
            "split",
            "selector",
            "prefix",
            "explicit_prefix",
            "policies",
        )
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
        for candidate in (
            "current",
            "split",
            "selector",
            "prefix",
            "explicit_prefix",
            "policies",
        )
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
        for candidate in (
            "current",
            "split",
            "selector",
            "prefix",
            "explicit_prefix",
            "policies",
        )
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
    if candidate in ("current", "prefix"):
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
        for candidate in (
            "current",
            "split",
            "selector",
            "prefix",
            "explicit_prefix",
            "policies",
        )
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


@test(
    [Param(backend, name=backend) for backend in ("sqlite", "mariadb")],
    mark="slow",
)
async def current_declarations_reject_mistakes_but_accept_a_wrong_clock_type(
    backend: str,
) -> None:
    consumer = await Path("research/defaults_473/review_misuse.py.txt").read_text()
    consumer = consumer.replace(
        "__SERVER_CLOCK__  # error: invalid-assignment",
        "__SERVER_CLOCK__  # accepted gap: logical str with SQL clock",
    )
    await assert_paired_typing(await review_source(backend, "current", consumer))


@test(
    [Param(backend, name=backend) for backend in ("sqlite", "mariadb")],
    mark="slow",
)
async def current_nullable_clocks_keep_input_types_but_do_not_validate_sql_clock_results(
    backend: str,
) -> None:
    consumer = """
from typing import ClassVar, assert_type

class Clock[S = database.Pending](ReviewModel[S]):
    __row_type__: ClassVar[database.ReadType[Clock[database.Row]]]
    value: database.GenCol[database.UtcDatetime | None] = __SERVER_CLOCK__

class WrongClock[S = database.Pending](ReviewModel[S]):
    __row_type__: ClassVar[database.ReadType[WrongClock[database.Row]]]
    value: database.GenCol[str] = __SERVER_CLOCK__

class NullOnlyClock[S = database.Pending](ReviewModel[S]):
    __row_type__: ClassVar[database.ReadType[NullOnlyClock[database.Row]]]
    value: database.GenCol[None] = __SERVER_CLOCK__

assert_type(Clock().value, database.UtcDatetime | None | database.PENDING_GENERATION)
Clock(value=None)
WrongClock(value="not a timestamp")
NullOnlyClock(value=None)

def rows(wrong: WrongClock[database.Row], null_only: NullOnlyClock[database.Row]) -> None:
    assert_type(wrong.value, str)
    assert_type(null_only.value, None)

Clock(value="wrong")  # error: invalid-argument-type
WrongClock(value=42)  # error: invalid-argument-type
NullOnlyClock(value="timestamp")  # error: invalid-argument-type
"""
    await assert_paired_typing(await review_source(backend, "current", consumer))


@test(
    [Param(backend, name=backend) for backend in ("sqlite", "mariadb")],
    mark="slow",
)
async def current_source_less_generation_is_accepted_but_value_factory_mixes_are_rejected(
    backend: str,
) -> None:
    consumer = """
from typing import ClassVar, assert_type

class Source[S = database.Pending](ReviewModel[S]):
    __row_type__: ClassVar[database.ReadType[Source[database.Row]]]
    absent: database.GenCol[int] = database.Integer(default=database.PENDING_GENERATION)
    disabled: database.GenCol[int] = database.Integer(default=database.PENDING_GENERATION, auto_increment=False)

assert_type(Source().absent, int | database.PENDING_GENERATION)
Source(absent=42, disabled=43)
Source(absent="wrong")  # error: invalid-argument-type

database.Text(default="value", default_factory=lambda: "value")  # error: no-matching-overload
database.Integer(default=database.LiteralDefault(False), default_factory=lambda: False)  # error: no-matching-overload
database.Integer(server_default=False)  # error: no-matching-overload
"""
    await assert_paired_typing(await review_source(backend, "current", consumer))


@test(
    [Param(backend, name=backend) for backend in ("sqlite", "mariadb")],
    [
        Param(candidate, name=candidate)
        for candidate in ("current", "split", "selector", "prefix")
    ],
    mark="slow",
)
async def plain_python_bool_defaults_keep_concrete_pending_types_in_every_shortlisted_option(
    backend: str, candidate: str
) -> None:
    consumer = """
from typing import ClassVar, assert_type

class Boolean[S = database.Pending](ReviewModel[S]):
    __row_type__: ClassVar[database.ReadType[Boolean[database.Row]]]
    value: database.Col[bool] = __PYTHON_VALUE__

assert_type(Boolean().value, bool)
Boolean(value=True)
Boolean(value=None)  # error: invalid-argument-type
Boolean(value=database.PENDING_GENERATION)  # error: invalid-argument-type
"""
    source = (await review_source(backend, candidate, consumer)).replace(
        "default=7", "default=False"
    )
    await assert_paired_typing(source)


@test(
    [Param(backend, name=backend) for backend in ("sqlite", "mariadb")],
    [
        Param(candidate, name=candidate)
        for candidate in ("current", "split", "selector")
    ],
    mark="slow",
)
async def visual_examples_keep_the_review_sheet_constructor_and_consumer_contracts(
    backend: str, candidate: str
) -> None:
    """Check the displayed declarations, never import or execute the examples."""
    examples = parse(await Path("research/defaults_473/scenarios.py").read_text())
    guarded = next(node for node in examples.body if isinstance(node, If))
    scenarios = [node for node in guarded.body if isinstance(node, FunctionDef)]
    consumer = await Path("research/defaults_473/review_baseline.py.txt").read_text()
    model = next(node for node in parse(consumer).body if isinstance(node, ClassDef))
    fields = [
        node
        for node in model.body
        if isinstance(node, AnnAssign) and node.value is not None
    ]
    approach = ("current", "split", "selector").index(candidate)
    for index, field in enumerate(fields, 1):
        scenario = next(
            node for node in scenarios if node.name.startswith(f"scenario_{index:02}_")
        )
        declarations = [node for node in scenario.body if isinstance(node, AnnAssign)]
        declaration = declarations[approach]
        assert declaration.value is not None
        displayed = f"    {unparse(field.target)}: {unparse(declaration.annotation)} = {unparse(declaration.value)}"
        consumer = consumer.replace(consumer.splitlines()[field.lineno - 1], displayed)
    consumer = consumer.replace("db.", "database.")
    for namespace, prefix in (("separate", "Twin"), ("selector", "Choice")):
        for storage in ("Integer", "Text"):
            consumer = consumer.replace(f"{namespace}.{storage}", f"{prefix}{storage}")
    await assert_paired_typing(await review_source(backend, candidate, consumer))
