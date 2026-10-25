"""Static-only prototypes for Python-left / SQL-right declarations in #473."""

from anyio import Path
from snektest import Param, assert_eq, assert_in, assert_raises, test

from research.defaults_473.annotation_signatures import typing_overlay
from tests.research.test_default_declarations import assert_paired_typing


@test(
    [Param(backend, name=backend) for backend in ("sqlite", "mariadb")],
    [
        Param(metadata, name=name)
        for name, metadata in (
            ("custom-metadata", "Default(False)"),
            ("stdlib-field", "field(default=False)"),
            ("pydantic-field", "Field(default=False)"),
        )
    ],
    mark="slow",
)
async def native_left_metadata_does_not_make_fields_omittable(
    backend: str, metadata: str
) -> None:
    """Custom, stdlib and Pydantic metadata all leave the field required."""
    declarations = await Path(
        "research/defaults_473/left_declarations.py.txt"
    ).read_text()
    consumer = await Path("research/defaults_473/left_basic.py.txt").read_text()
    source = (
        (declarations + "\n" + consumer)
        .replace("__BACKEND__", backend)
        .replace("__META_MODULE__", f"snekql.{backend}.model")
        .replace("__DEFAULT_METADATA__", metadata)
        .replace("# required-probe", "# error: missing-argument")
        .replace("# omission-probe", "# error: missing-argument")
    )
    await assert_paired_typing(source)


@test(
    [Param(backend, name=backend) for backend in ("sqlite", "mariadb")],
    mark="slow",
)
async def unregistering_sql_declarations_also_makes_required_fields_optional(
    backend: str,
) -> None:
    """Treating every RHS as a default loses required-field checking."""
    declarations = await Path(
        "research/defaults_473/left_declarations.py.txt"
    ).read_text()
    declarations = declarations.replace(
        "field_specifiers=(Integer, Text, field, Field)",
        "field_specifiers=(field, Field)",
    )
    consumer = await Path("research/defaults_473/left_basic.py.txt").read_text()
    source = (
        (declarations + "\n" + consumer)
        .replace("__BACKEND__", backend)
        .replace("__META_MODULE__", f"snekql.{backend}.model")
        .replace("__DEFAULT_METADATA__", "Default(False)")
    )
    await assert_paired_typing(source)


@test(
    [Param(backend, name=backend) for backend in ("sqlite", "mariadb")],
    [
        Param("", name="plain"),
        Param("from __future__ import annotations\n", name="future-annotations"),
    ],
    mark="slow",
)
async def generated_left_metadata_preserves_default_omission_and_required_inputs(
    backend: str, preamble: str
) -> None:
    """Generated constructor evidence should distinguish the two Python contracts."""

    declarations = await Path(
        "research/defaults_473/left_declarations.py.txt"
    ).read_text()
    consumer = await Path("research/defaults_473/left_basic.py.txt").read_text()
    source = (
        (declarations + "\n" + consumer)
        .replace("__BACKEND__", backend)
        .replace("__META_MODULE__", f"snekql.{backend}.model")
        .replace("__DEFAULT_METADATA__", "Default(False)")
        .replace("# required-probe", "# error: missing-argument")
    )
    await assert_paired_typing(typing_overlay(preamble + source))


@test(
    [Param(backend, name=backend) for backend in ("sqlite", "mariadb")],
    mark="slow",
)
async def generated_annotations_keep_requiredness_and_lifecycle_types_independent(
    backend: str,
) -> None:
    """GenCol alone stays required; a left-side pending default permits omission."""

    declarations = await Path(
        "research/defaults_473/left_declarations.py.txt"
    ).read_text()
    consumer = await Path("research/defaults_473/left_generated.py.txt").read_text()
    source = (
        (declarations + "\n" + consumer)
        .replace("__BACKEND__", backend)
        .replace("__META_MODULE__", f"snekql.{backend}.model")
    )
    await assert_paired_typing(typing_overlay(source))


@test(
    [Param(backend, name=backend) for backend in ("sqlite", "mariadb")],
    mark="slow",
)
async def python_factories_and_nullable_defaults_keep_concrete_field_types(
    backend: str,
) -> None:
    """Factories and constructed values need no Python-default arguments on SQL declarations."""

    declarations = await Path(
        "research/defaults_473/left_declarations.py.txt"
    ).read_text()
    consumer = await Path("research/defaults_473/left_factories.py.txt").read_text()
    source = (
        (declarations + "\n" + consumer)
        .replace("__BACKEND__", backend)
        .replace("__META_MODULE__", f"snekql.{backend}.model")
    )
    await assert_paired_typing(typing_overlay(source))


@test(
    [Param(backend, name=backend) for backend in ("sqlite", "mariadb")],
    mark="slow",
)
async def generated_typing_rejects_incompatible_metadata_and_sql_defaults(
    backend: str,
) -> None:
    """Metadata defaults must not bypass value, NULL, factory or sentinel checks."""

    declarations = await Path(
        "research/defaults_473/left_declarations.py.txt"
    ).read_text()
    consumer = await Path(
        "research/defaults_473/left_invalid_defaults.py.txt"
    ).read_text()
    source = (
        (declarations + "\n" + consumer)
        .replace("__BACKEND__", backend)
        .replace("__META_MODULE__", f"snekql.{backend}.model")
    )
    generated = typing_overlay(source)
    assert_eq(generated.count("# error:"), 6)
    corrected = source
    for invalid, valid in (
        ('Default("wrong")', "Default(False)"),
        ("Default(None)", "Default(0)"),
        ("Factory(bad_token)", "Factory(good_token)"),
        ("Default(database.PENDING_GENERATION)", "Default(0)"),
        ('Integer(server_default="wrong")', "Integer(server_default=7)"),
        (
            "Text(server_default=database.CurrentTimestamp)",
            'Text(server_default="valid")',
        ),
    ):
        assert_in(invalid, corrected)
        corrected = corrected.replace(invalid, valid)
    corrected = "\n".join(
        line.split("# default-error:")[0].split("# sql-error:")[0]
        for line in corrected.splitlines()
    )
    await assert_paired_typing(generated, positive_source=typing_overlay(corrected))


@test(
    [Param(backend, name=backend) for backend in ("sqlite", "mariadb")],
    [Param(name, name=name) for name in ("server_default", "default")],
    mark="slow",
)
async def sql_defaults_do_not_determine_python_omission_or_pending_shape(
    backend: str,
    sql_keyword: str,
) -> None:
    """All combinations arise from independent Python behavior and SQL facts."""

    declarations = await Path(
        "research/defaults_473/left_declarations.py.txt"
    ).read_text()
    consumer = await Path(
        "research/defaults_473/left_sql_independence.py.txt"
    ).read_text()
    source = (
        (declarations + "\n" + consumer)
        .replace("__BACKEND__", backend)
        .replace("__META_MODULE__", f"snekql.{backend}.model")
    )
    await assert_paired_typing(
        typing_overlay(source.replace("server_default", sql_keyword))
    )


@test(
    [
        Param(source, name=name)
        for name, source in (
            ("no-model", "x = 1\n"),
            (
                "custom-init",
                "class Example[S](LeftModel[S]):\n    value: db.Col[int] = Integer()\n    def __init__(self) -> None: ...\n",
            ),
            (
                "inheritance",
                "class Parent[S](LeftModel[S]):\n    value: db.Col[int] = Integer()\nclass Child[S](Parent[S]):\n    other: db.Col[int] = Integer()\n",
            ),
            (
                "conditional-field",
                "class Example[S](LeftModel[S]):\n    value: db.Col[int] = Integer()\n    if True:\n        other: db.Col[int] = Integer()\n",
            ),
            (
                "local-model",
                "def f():\n    class Example[S](LeftModel[S]):\n        value: db.Col[int] = Integer()\n",
            ),
            (
                "annotation-alias",
                "class Example[S](LeftModel[S]):\n    value: DefaultedBoolean = Integer()\n",
            ),
            (
                "two-python-defaults",
                "class Example[S](LeftModel[S]):\n    value: Annotated[db.Col[int], Default(1), Factory(make_number)] = Integer()\n",
            ),
            (
                "missing-sql",
                "class Example[S](LeftModel[S]):\n    value: db.Col[int]\n",
            ),
            (
                "extra-type-parameter",
                "class Example[S, T](LeftModel[S]):\n    value: db.Col[T] = Integer()\n",
            ),
            (
                "self-field",
                "class Example[S](LeftModel[S]):\n    self: db.Col[int] = Integer()\n",
            ),
        )
    ],
    mark="fast",
)
def unsupported_source_is_rejected_instead_of_getting_partial_typing(
    source: str,
) -> None:
    """This research tool must not silently claim support for unhandled models."""
    with assert_raises(ValueError):
        typing_overlay(source)


@test(
    [Param(backend, name=backend) for backend in ("sqlite", "mariadb")],
    mark="slow",
)
async def generated_model_module_keeps_external_consumer_types(backend: str) -> None:
    """Generated typing must work for imported models, not just inline examples."""
    declarations = await Path(
        "research/defaults_473/left_declarations.py.txt"
    ).read_text()
    model = """
class Entry[S = database.Pending](LeftModel[S]):
    __row_type__: ClassVar[database.ReadType[Entry[database.Row]]]
    value: database.Col[str] = Text()
    required_generated: database.GenCol[int] = Integer()
    done: Annotated[database.Col[bool], Default(False)] = Integer()
    id: Annotated[database.GenCol[int], Default(database.PENDING_GENERATION)] = Integer(primary_key=True, auto_increment=True)
"""
    module = (
        (declarations + "\n" + model)
        .replace("__BACKEND__", backend)
        .replace("__META_MODULE__", f"snekql.{backend}.model")
    )
    consumer = """
from typing import assert_type
from snekql import __BACKEND__ as database
from model473 import Entry

pending = Entry(value="Ada", required_generated=database.PENDING_GENERATION)
assert_type(pending, Entry[database.Pending])
assert_type(pending.done, bool)
assert_type(pending.id, int | database.PENDING_GENERATION)
write: database.Write[Entry[database.Row]] = database.insert(pending).returning()

def row_types(row: Entry[database.Row]) -> None:
    assert_type(row.done, bool)
    assert_type(row.id, int)

Entry(required_generated=3)  # error: missing-argument
Entry(value="Ada")  # error: missing-argument
Entry(value="Ada", required_generated=3, done="wrong")  # error: invalid-argument-type
Entry[database.Row](value="Ada", required_generated=3)  # error: invalid-argument-type
""".replace("__BACKEND__", backend)
    await assert_paired_typing(consumer, modules={"model473": typing_overlay(module)})


@test(
    [Param(backend, name=backend) for backend in ("sqlite", "mariadb")],
    [Param(mode, name=mode) for mode in ("native", "overlay")],
    mark="slow",
)
async def sql_default_spelling_must_not_imply_a_python_default(
    backend: str, mode: str
) -> None:
    """A RHS SQL default= is a false Python optionality signal without an overlay."""
    declarations = await Path(
        "research/defaults_473/left_declarations.py.txt"
    ).read_text()
    declarations = declarations.replace("server_default", "default")
    consumer = """
class Required[S = database.Pending](LeftModel[S]):
    __row_type__: ClassVar[database.ReadType[Required[database.Row]]]
    value: database.Col[bool] = Integer(default=False)

assert_type(Required(value=True).value, bool)
Required()  # omission-probe
Required(value="wrong")  # error: invalid-argument-type
"""
    source = (
        (declarations + "\n" + consumer)
        .replace("__BACKEND__", backend)
        .replace("__META_MODULE__", f"snekql.{backend}.model")
    )
    if mode == "overlay":
        source = source.replace("# omission-probe", "# error: missing-argument")
        source = typing_overlay(source)
    await assert_paired_typing(source)
