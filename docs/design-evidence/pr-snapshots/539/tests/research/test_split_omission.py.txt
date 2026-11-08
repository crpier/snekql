"""Static-only follow-up for #473: can server_default imply Python omission?"""

from snektest import Param, test

from tests.research.test_default_declarations import assert_paired_typing
from tests.research.test_defaults_review import review_source

CONSUMER = """
from typing import ClassVar, assert_type

class Required[S = database.Pending](ReviewModel[S]):
    __row_type__: ClassVar[database.ReadType[Required[database.Row]]]
    required: database.Col[bool] = TwinInteger()
    nullable: database.Col[bool | None] = TwinInteger()
    generated: database.GenCol[bool] = TwinInteger()

class Server[S = database.Pending](ReviewModel[S]):
    __row_type__: ClassVar[database.ReadType[Server[database.Row]]]
    value: database.GenCol[bool] = TwinInteger(server_default=False)

class SchemaOnly[S = database.Pending](ReviewModel[S]):
    __row_type__: ClassVar[database.ReadType[SchemaOnly[database.Row]]]
    value: database.Col[bool] = TwinInteger(server_default=False)

class Python[S = database.Pending](ReviewModel[S]):
    __row_type__: ClassVar[database.ReadType[Python[database.Row]]]
    value: database.Col[bool] = TwinInteger(default=False)

class Both[S = database.Pending](ReviewModel[S]):
    __row_type__: ClassVar[database.ReadType[Both[database.Row]]]
    value: database.Col[bool] = TwinInteger(default=False, server_default=True)

required = Required(required=True, nullable=None, generated=database.PENDING_GENERATION)
assert_type(required.required, bool)
assert_type(required.nullable, bool | None)
assert_type(required.generated, bool | database.PENDING_GENERATION)
assert_type(Server().value, bool | database.PENDING_GENERATION)  # omission-probe
assert_type(Server(value=True).value, bool | database.PENDING_GENERATION)  # override-probe
Server(value=database.PENDING_GENERATION)  # override-probe
assert_type(SchemaOnly(value=True).value, bool)  # override-probe
assert_type(Python().value, bool)
assert_type(Both().value, bool)
write: database.Write[Server[database.Row]] = database.insert(Server(value=False)).returning()  # insert-probe

def row(value: Server[database.Row]) -> None:
    assert_type(value.value, bool)

SchemaOnly()  # schema-required-probe
Required(nullable=None, generated=True)  # required-probe
Required(required=True, generated=True)  # required-probe
Required(required=True, nullable=None)  # required-probe
Required(required=None, nullable=None, generated=True)  # error: invalid-argument-type
Required(required=True, nullable="wrong", generated=True)  # error: invalid-argument-type
Required(required=True, nullable=None, generated="wrong")  # error: invalid-argument-type
Server(value=None)  # error: invalid-argument-type
Server(value="wrong")  # error: invalid-argument-type
Python(value=database.PENDING_GENERATION)  # error: invalid-argument-type
Both(value=database.PENDING_GENERATION)  # error: invalid-argument-type
Server[database.Row](value=True)  # error: invalid-argument-type
"""


CLASS_DECLARATION = """
class TwinInteger[Write, Read](
    Attr[Table[database.Pending], Table[database.Row], _UnboundOwner,
         Write, Read, Write, Any, Literal["__BACKEND__"]]
):
    @overload
    def __init__(self) -> None: ...

    @overload
    def __init__(self, *, server_default: Read, default: database.PENDING_GENERATION = database.PENDING_GENERATION) -> None: ...

    @overload
    def __init__(self, *, default: Write) -> None: ...

    @overload
    def __init__(self, *, default: Write, server_default: Read) -> None: ...

    def __init__(self, *, default: object = ..., server_default: object = ...) -> None:
        raise NotImplementedError
"""


@test(
    [Param(backend, name=backend) for backend in ("sqlite", "mariadb")],
    [
        Param(mechanism, name=mechanism)
        for mechanism in (
            "signature-default",
            "typed-signature-default",
            "signature-factory",
            "class-specifier",
            "unregistered",
            "init-false",
        )
    ],
    mark="slow",
)
async def shorter_split_spelling_exposes_native_omission_tradeoffs(
    backend: str, mechanism: str
) -> None:
    """Record failed mechanisms, not a working omission-inference implementation."""
    consumer = CONSUMER
    if mechanism not in ("unregistered", "class-specifier"):
        consumer = consumer.replace("# required-probe", "# error: missing-argument")
    if mechanism not in ("unregistered", "class-specifier", "init-false"):
        consumer = consumer.replace("# omission-probe", "# error: missing-argument")
        consumer = consumer.replace(
            "# schema-required-probe", "# error: missing-argument"
        )
    if mechanism == "init-false":
        consumer = consumer.replace("# override-probe", "# error: unknown-argument")
        consumer = consumer.replace(
            "Server[database.Row](value=True)", "Server[database.Row]()"
        )
        consumer = consumer.replace(
            "database.insert(Server(value=False))", "database.insert(Server())"
        )
        consumer = consumer.replace(
            "Server(value=None)  # error: invalid-argument-type",
            "Server(value=None)  # error: unknown-argument",
        )
        consumer = consumer.replace(
            'Server(value="wrong")  # error: invalid-argument-type',
            'Server(value="wrong")  # error: unknown-argument',
        )
    source = await review_source(backend, "split", consumer)
    original = "def TwinInteger[Write, Read](*, server_default: Read)"
    parameters = {
        "signature-default": "server_default: Read, default: object = database.PENDING_GENERATION",
        "typed-signature-default": "server_default: Read, default: database.PENDING_GENERATION = database.PENDING_GENERATION",
        "signature-factory": "server_default: Read, default_factory: Callable[[], database.PENDING_GENERATION] = _pending",
        "init-false": "server_default: Read, init: Literal[False] = False",
    }
    if mechanism in parameters:
        source = source.replace(
            original, f"def TwinInteger[Write, Read](*, {parameters[mechanism]})"
        )
    if mechanism == "signature-factory":
        source = source.replace(
            "@overload\ndef TwinInteger",
            "def _pending() -> database.PENDING_GENERATION:\n    raise NotImplementedError\n\n\n@overload\ndef TwinInteger",
            1,
        )
        source = source.replace(
            "def TwinInteger(*, default:",
            "def TwinInteger(*, default_factory: object = ..., default:",
        )
    if mechanism == "init-false":
        source = source.replace(
            "def TwinInteger(*, default:",
            "def TwinInteger(*, init: bool = True, default:",
        )
    if mechanism == "unregistered":
        source = source.replace(
            "ChoiceText, TwinInteger, TwinText", "ChoiceText, TwinText"
        )
    if mechanism == "class-specifier":
        start = source.index("@overload\ndef TwinInteger")
        end = source.index("@overload\ndef TwinText")
        source = (
            source[:start]
            + CLASS_DECLARATION.replace("__BACKEND__", backend)
            + "\n\n"
            + source[end:]
        )
    await assert_paired_typing(source)
