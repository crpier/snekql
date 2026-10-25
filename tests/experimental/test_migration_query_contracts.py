"""Historical query declarations refuse reconstruction they cannot preserve."""

import asyncio
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Annotated, ClassVar, Literal

from snektest import Param, assert_eq, assert_raises, load_fixture, test

from snekql import mariadb, sqlite
from snekql.experimental import migrations as m
from tests.experimental.test_migration_nullability import NativeRequired, Required
from tests.experimental.test_migration_targets import provide_package_server


class WideText[S = mariadb.Pending](mariadb.Model[S]):
    """A builtin logical scalar does not imply the default VARCHAR codec policy."""

    __tablename__ = "entries"
    __row_type__: ClassVar[mariadb.ReadType[WideText[mariadb.Row]]]
    id: mariadb.Col[int] = mariadb.Integer(primary_key=True)
    label: mariadb.Col[str] = mariadb.Text(length=512)


@test(mark="fast")
def historical_source_cannot_silently_narrow_a_native_text_codec() -> None:
    """Deployment supports wide text without promising automatic codec reconstruction."""
    draft = m.generate("001", [WideText], backend="mariadb")
    package = m.Package.load(m.compile(draft).dump())
    assert_eq(package.target.tables[0].columns[1].query_type, "str")
    draft = draft.then(m.Checkpoint(name="ready"))
    with assert_raises(m.PackageError) as error:
        m.contract_source(draft, point="ready", table="entries")
    assert "explicit codec" in str(error.exception)


@test(
    [
        Param(value=term, name=str(i))
        for i, term in enumerate(
            (
                "int if True else missing_codec()",
                "int, str",
                "list[int]",
                "int]\n    injected = 1\n    #",
                "CustomInt",
                "",
            )
        )
    ],
    mark="fast",
)
def historical_source_refuses_annotation_expressions_outside_scalar_unions(
    term: str,
) -> None:
    """Raw annotation text must not become arbitrary generated Python expressions."""
    draft = m.generate("001", [WideText], backend="mariadb")
    table = draft.target.tables[0]
    column = table.columns[0].model_copy(update={"query_type": term})
    table = table.model_copy(update={"columns": (column,)})
    draft = draft.model_copy(
        update={"operations": (m.CreateTable(table=table), m.Checkpoint(name="ready"))}
    )
    with assert_raises(m.PackageError) as error:
        m.contract_source(draft, point="ready", table="entries")
    assert "explicit codec" in str(error.exception)


class MetadataScalar[S = mariadb.Pending](mariadb.Model[S]):
    """An Annotated metadata type is not another member of a logical union."""

    __tablename__ = "metadata_scalar"
    __row_type__: ClassVar[mariadb.ReadType[MetadataScalar[mariadb.Row]]]
    value: mariadb.Col[Annotated[int, str]] = mariadb.Integer()


@test(mark="fast")
def annotated_metadata_cannot_be_reinterpreted_as_a_scalar_union() -> None:
    """Generation keeps opaque logical annotations unsupported without blocking deployment."""
    draft = m.generate("001", [MetadataScalar], backend="mariadb")
    assert_eq(draft.target.tables[0].columns[0].query_type, None)
    m.Package.load(m.compile(draft).dump())
    with assert_raises(m.PackageError):
        m.contract_source(
            draft.then(m.Checkpoint(name="ready")),
            point="ready",
            table="metadata_scalar",
        )


@test(
    [
        Param(value=name, name=str(i))
        for i, name in enumerate(
            ("mariadb", "ClassVar", "Historical", "__row_type__", "𝓂ariadb", "int")
        )
    ],
    mark="fast",
)
def historical_field_cannot_shadow_its_generated_backend_namespace(name: str) -> None:
    """A valid SQL field can need a name adapter in a standalone Python declaration."""
    draft = m.generate("001", [WideText], backend="mariadb")
    table = draft.target.tables[0]
    column = table.columns[0].model_copy(
        update={"name": name, "definition": f"`{name}` BIGINT NOT NULL"}
    )
    table = table.model_copy(
        update={
            "columns": (column,),
            "sql": f"CREATE TABLE entries (`{name}` BIGINT NOT NULL) ENGINE=InnoDB",
        }
    )
    edited = draft.model_copy(
        update={
            "target": draft.target.model_copy(update={"tables": (table,)}),
            "operations": (m.CreateTable(table=table), m.Checkpoint(name="ready")),
        }
    )
    m.Package.load(m.compile(edited).dump())
    with assert_raises(m.PackageError) as error:
        m.contract_source(edited, point="ready", table="entries")
    assert "name adapter" in str(error.exception)


class JsonList[S = mariadb.Pending](mariadb.Model[S]):
    """Native JSON payload generics are not builtin scalar logical contracts."""

    __row_type__: ClassVar[mariadb.ReadType[JsonList[mariadb.Row]]]
    payload: mariadb.JsonCol[list[int]] = mariadb.Json()


class JsonDict[S = mariadb.Pending](mariadb.Model[S]):
    """Mapping type arguments must not become scalar union members."""

    __row_type__: ClassVar[mariadb.ReadType[JsonDict[mariadb.Row]]]
    payload: mariadb.JsonCol[dict[str, int]] = mariadb.Json()


@test([Param(value="list", name="list"), Param(value="dict", name="dict")], mark="fast")
def generic_json_payload_does_not_degrade_to_its_type_arguments(kind: str) -> None:
    """Opaque codecs stay opaque while their physical schemas can still deploy."""
    draft = m.generate(
        "001", [JsonList] if kind == "list" else [JsonDict], backend="mariadb"
    )
    assert_eq(draft.target.tables[0].columns[0].query_type, None)
    m.Package.load(m.compile(draft).dump())
    with assert_raises(m.PackageError):
        m.contract_source(
            draft.then(m.Checkpoint(name="ready")),
            point="ready",
            table=draft.target.tables[0].name,
        )


@test(
    [
        Param[Literal["sqlite", "mariadb"]](value="sqlite", name="sqlite"),
        Param[Literal["sqlite", "mariadb"]](value="mariadb", name="mariadb"),
    ],
    mark="fast",
)
def historical_storage_hints_cannot_override_a_physical_definition(
    backend: Literal["sqlite", "mariadb"],
) -> None:
    """Deployment does not certify hints, but source must not use a contradictory hint."""
    draft = m.generate(
        "001", [Required] if backend == "sqlite" else [NativeRequired], backend=backend
    )
    table = draft.target.tables[0]
    column = table.columns[0].model_copy(update={"storage": "TEXT"})
    table = table.model_copy(update={"columns": (column,)})
    draft = draft.model_copy(
        update={
            "target": draft.target.model_copy(update={"tables": (table,)}),
            "operations": (m.CreateTable(table=table), m.Checkpoint(name="ready")),
        }
    )
    m.Package.load(m.compile(draft).dump())
    with assert_raises(m.PackageError) as error:
        m.contract_source(draft, point="ready", table="entries")
    assert "explicit codec" in str(error.exception)


class Scalars[S = sqlite.Pending](sqlite.Model[S]):
    """Finite primitives retain ordinary logical scalar query declarations."""

    __tablename__ = "scalars"
    __row_type__: ClassVar[sqlite.ReadType[Scalars[sqlite.Row]]]
    id: sqlite.Col[int] = sqlite.Integer(primary_key=True)
    label: sqlite.Col[str] = sqlite.Text()
    flag: sqlite.Col[bool] = sqlite.Integer()
    score: sqlite.Col[float] = sqlite.Real()
    payload: sqlite.Col[bytes] = sqlite.Blob()
    note: sqlite.Col[str | None] = sqlite.Text(nullable=True)
    choice: sqlite.Col[int | str | None] = sqlite.Text(nullable=True)


class NativeScalars[S = mariadb.Pending](mariadb.Model[S]):
    """The native subset uses the same default primitive constructors explicitly."""

    __tablename__ = "scalars"
    __row_type__: ClassVar[mariadb.ReadType[NativeScalars[mariadb.Row]]]
    id: mariadb.Col[int] = mariadb.Integer(primary_key=True)
    label: mariadb.Col[str] = mariadb.Text()
    flag: mariadb.Col[bool] = mariadb.Integer()
    score: mariadb.Col[float] = mariadb.Real()
    payload: mariadb.Col[bytes] = mariadb.Blob()
    note: mariadb.Col[str | None] = mariadb.Text(nullable=True)
    choice: mariadb.Col[int | str | None] = mariadb.Text(nullable=True)


@test(
    [
        Param[Literal["sqlite", "mariadb"]](value="sqlite", name="sqlite"),
        Param[Literal["sqlite", "mariadb"]](value="mariadb", name="mariadb"),
    ],
    mark="medium",
)
async def finite_scalar_contracts_typecheck_and_compile_without_authoring_imports(
    backend: Literal["sqlite", "mariadb"],
) -> None:
    """Generated declarations retain scalar/union typing and typed update compilation."""
    draft = m.generate(
        "001", [Scalars] if backend == "sqlite" else [NativeScalars], backend=backend
    ).then(m.Checkpoint(name="ready"))
    source = m.contract_source(draft, point="ready", table="scalars")
    assert "Col[int | str | None]" in source
    source += f"\nquery = {backend}.select(Historical.label, Historical.flag, Historical.payload, Historical.choice)\n"
    source += f"update = {backend}.update(Historical).set(Historical.label.to('kept')).all()\n"
    source += "from snekql.experimental import migrations as m\nchange = m.DataChange.from_query(update, checkpoint='ready', contract_digest=CONTRACT_DIGEST)\nassert change.params == ('kept',)\n"
    with TemporaryDirectory() as directory:
        path = Path(directory) / "historical.py"
        await asyncio.to_thread(path.write_text, source)
        for command in (
            (str(Path(sys.executable).with_name("ty")), "check", str(path)),
            (sys.executable, str(path)),
        ):
            process = await asyncio.create_subprocess_exec(
                *command, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await process.communicate()
            assert_eq((process.returncode, stderr.decode()), (0, "")), stdout.decode()


@test(mark="slow")
async def actual_old_wide_package_still_deploys_with_an_explicit_query_adapter() -> (
    None
):
    """Historical-source refusal must not block model-free deployment or explicit queries."""
    server = await load_fixture(provide_package_server())
    text = (
        Path(__file__).parent / "fixtures" / "query-contracts" / "wide-old.json"
    ).read_text()
    package = m.Package.load(text)
    assert_eq(package.dump(), text)
    assert_eq(
        package.digest,
        "7b96b56d9b2931965d62e1646ba29604c4a4d493721d514909bce8714f27e8ec",
    )
    with assert_raises(m.PackageError):
        m.contract_source(package.draft, point="ready", table="entries")
    async with m.connect(server.config()) as target:
        assert_eq(
            await target.apply(
                await target.prepare(package, schema_writers_excluded=True)
            ),
            "applied",
        )
        assert_eq((await target.status())[0].phase, "complete")
    async with (
        await mariadb.Database.initialize(server.config()) as db,
        db.transaction() as tx,
    ):
        await tx.execute(
            mariadb.raw("INSERT INTO entries(id,label) VALUES(42,'before')")
        )
        await tx.execute(
            mariadb.update(WideText).set(WideText.label.to("x" * 300)).all()
        )
        assert_eq(
            await tx.fetch_all(mariadb.raw("SELECT id,label FROM entries")),
            [{"id": 42, "label": "x" * 300}],
        )


@test(mark="fast")
def finite_union_spelling_is_normalized_without_replaying_annotation_text() -> None:
    """Duplicate builtin union terms/whitespace need no executable annotation adapter."""
    draft = m.generate("001", [Required], backend="sqlite")
    table = draft.target.tables[0]
    column = table.columns[1].model_copy(update={"query_type": " int | int "})
    table = table.model_copy(update={"columns": (table.columns[0], column)})
    draft = draft.model_copy(
        update={
            "target": draft.target.model_copy(update={"tables": (table,)}),
            "operations": (m.CreateTable(table=table), m.Checkpoint(name="ready")),
        }
    )
    m.Package.load(m.compile(draft).dump())
    source = m.contract_source(draft, point="ready", table="entries")
    assert "value: sqlite.Col[int]" in source


class OpaqueNullable[S = sqlite.Pending](sqlite.Model[S]):
    """Unknown union members need not be hashable to remain opaque query metadata."""

    __row_type__: ClassVar[sqlite.ReadType[OpaqueNullable[sqlite.Row]]]
    value: sqlite.Col[Annotated[int, {}] | None] = sqlite.Integer(nullable=True)


@test(mark="fast")
def opaque_nullable_metadata_does_not_block_physical_generation() -> None:
    """A legal model with unhashable annotation metadata still produces deployable SQL."""
    draft = m.generate("001", [OpaqueNullable], backend="sqlite")
    assert_eq(draft.target.tables[0].columns[0].query_type, None)
    m.Package.load(m.compile(draft).dump())
    with assert_raises(m.PackageError):
        m.contract_source(
            draft.then(m.Checkpoint(name="ready")),
            point="ready",
            table="opaque_nullable",
        )
