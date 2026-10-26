"""Follow #473 through native field metadata, not more public design families."""

from re import sub
from textwrap import indent

from snektest import Param, test

from tests.research.test_default_declarations import assert_paired_typing
from tests.research.test_defaults_review import review_source
from tests.research.test_split_omission import CONSUMER

OPTIONS = """
from typing import NotRequired, TypedDict, Unpack

class _OmissionOptions(TypedDict):
    default: NotRequired[database.PENDING_GENERATION]

class _ExplicitGeneration(TypedDict):
    default: database.PENDING_GENERATION

_generation: _ExplicitGeneration = {"default": database.PENDING_GENERATION}

"""


@test(
    [Param(backend, name=backend) for backend in ("sqlite", "mariadb")],
    [
        Param(mechanism, name=mechanism)
        for mechanism in (
            "exported-staticmethod",
            "registered-callable-instance",
            "registered-new",
            "optional-typed-kwargs",
            "explicit-typed-unpack-control",
        )
    ],
    mark="slow",
)
async def native_field_metadata_distinguishes_implicit_hooks_from_bound_defaults(
    backend: str, mechanism: str
) -> None:
    """A working explicit pack is a control, not a zero-duplication solution."""
    consumer = CONSUMER
    if mechanism != "registered-callable-instance":
        consumer = consumer.replace("# required-probe", "# error: missing-argument")
        consumer = consumer.replace(
            "# schema-required-probe", "# error: missing-argument"
        )
    if mechanism not in (
        "registered-callable-instance",
        "explicit-typed-unpack-control",
    ):
        consumer = consumer.replace("# omission-probe", "# error: missing-argument")
    source = await review_source(backend, "split", consumer)
    start = source.index("@overload\ndef TwinInteger")
    end = source.index("@overload\ndef TwinText")
    block = source[start:end]
    if mechanism == "exported-staticmethod":
        block = block.replace("@overload", "@staticmethod\n@overload")
        block = block.replace(
            "\ndef TwinInteger(*,", "\n@staticmethod\ndef TwinInteger(*,"
        )
        block = "class _IntegerFactory:\n" + indent(block, "    ")
        block += "\nTwinInteger = _IntegerFactory.TwinInteger\n\n"
    if mechanism in ("registered-callable-instance", "registered-new"):
        method, receiver = (
            ("__call__", "self")
            if mechanism == "registered-callable-instance"
            else ("__new__", "cls")
        )
        block = sub(
            r"def TwinInteger(\[[^\]]+\])?\(",
            lambda match: f"def {method}{match[1] or ''}({receiver}, ",
            block,
        )
        block = "class _IntegerFactory:\n" + indent(block, "    ")
        block += (
            "\nTwinInteger = _IntegerFactory()\n\n"
            if mechanism == "registered-callable-instance"
            else "\nTwinInteger = _IntegerFactory\n\n"
        )
        source = source.replace(
            "ChoiceText, TwinInteger,",
            f"ChoiceText, _IntegerFactory.{method}, TwinInteger,",
        )
    source = source[:start] + block + source[end:]
    if mechanism in ("optional-typed-kwargs", "explicit-typed-unpack-control"):
        source = source.replace(
            "\ntype RequiredColumn", OPTIONS + "\ntype RequiredColumn", 1
        )
    if mechanism == "optional-typed-kwargs":
        source = source.replace(
            "def TwinInteger[Write, Read](*, server_default: Read)",
            "def TwinInteger[Write, Read](*, server_default: Read, **options: Unpack[_OmissionOptions])",
        )
        source = source.replace(
            "auto_increment: bool = False) -> Any:",
            "auto_increment: bool = False, **options: object) -> Any:",
            1,
        )
    if mechanism == "explicit-typed-unpack-control":
        source = source.replace(
            "value: database.GenCol[bool] = TwinInteger(server_default=False)",
            "value: database.GenCol[bool] = TwinInteger(server_default=False, **_generation)",
        )
    await assert_paired_typing(source)


@test(
    [Param(backend, name=backend) for backend in ("sqlite", "mariadb")],
    [Param(mode, name=mode) for mode in ("no-default", "explicit-pack")],
    mark="slow",
)
async def identity_generation_also_needs_native_constructor_default_metadata(
    backend: str,
    mode: str,
) -> None:
    packed = mode == "explicit-pack"
    consumer = """
from typing import ClassVar, assert_type

class Identity[S = database.Pending](ReviewModel[S]):
    __row_type__: ClassVar[database.ReadType[Identity[database.Row]]]
    value: database.GenCol[int] = TwinInteger(primary_key=True, auto_increment=True)

assert_type(Identity().value, int | database.PENDING_GENERATION)  # omission-probe
assert_type(Identity(value=42).value, int | database.PENDING_GENERATION)
Identity(value=database.PENDING_GENERATION)
write: database.Write[Identity[database.Row]] = database.insert(Identity(value=42)).returning()

def row(value: Identity[database.Row]) -> None:
    assert_type(value.value, int)

Identity(value=None)  # error: invalid-argument-type
Identity(value="wrong")  # error: invalid-argument-type
Identity[database.Row](value=42)  # error: invalid-argument-type
"""
    if not packed:
        consumer = consumer.replace("# omission-probe", "# error: missing-argument")
    source = await review_source(backend, "split", consumer)
    if packed:
        source = source.replace(
            "\ntype RequiredColumn", OPTIONS + "\ntype RequiredColumn", 1
        )
        source = source.replace(
            "TwinInteger(primary_key=True, auto_increment=True)",
            "TwinInteger(primary_key=True, auto_increment=True, **_generation)",
        )
    await assert_paired_typing(source)
