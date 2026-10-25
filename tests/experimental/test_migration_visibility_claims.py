"""Native column visibility construction agrees independently of named queryability."""

from pathlib import Path

from snektest import Param, assert_eq, assert_raises, load_fixture, test

from snekql import mariadb
from snekql.experimental import migrations as m
from tests.experimental.test_migration_nullability import NativeRequired
from tests.experimental.test_migration_targets import provide_package_server


def _draft(declaration: str, construction: str) -> m.Draft:
    """Review the value's exposure attribute independently from construction SQL."""
    draft = m.generate("001", [NativeRequired], backend="mariadb")
    table = draft.target.tables[0]
    old = table.columns[1]
    column = old.model_copy(
        update={
            "definition": old.definition + (" " + declaration if declaration else "")
        }
    )
    table = table.model_copy(
        update={
            "columns": (table.columns[0], column),
            "sql": table.sql.replace(
                old.definition,
                old.definition + (" " + construction if construction else ""),
            ),
        }
    )
    return draft.model_copy(
        update={
            "target": draft.target.model_copy(update={"tables": (table,)}),
            "operations": (m.CreateTable(table=table),),
        }
    )


@test(mark="fast")
async def named_queryability_does_not_prove_a_visible_construction_contract() -> None:
    """An INVISIBLE column is addressable by name but omitted from wildcard exposure."""
    with assert_raises(m.PackageError) as error:
        m.compile(_draft("", "INVISIBLE"))
    assert "construction visibility" in str(error.exception)


@test(mark="fast")
async def declared_invisible_exposure_cannot_become_visible_in_construction() -> None:
    """The inverse mismatch changes wildcard exposure despite addressable values."""
    with assert_raises(m.PackageError) as error:
        m.compile(_draft("INVISIBLE", ""))
    assert "construction visibility" in str(error.exception)


@test(
    [
        Param(value=pair, name=str(i))
        for i, pair in enumerate((("INVISIBLE", "invisible"), ("", "")))
    ],
    mark="fast",
)
async def canonical_native_visibility_presence_and_case_roundtrip(
    pair: tuple[str, str],
) -> None:
    """Known keyword case normalizes, including truthful implicit visibility."""
    package = m.compile(_draft(*pair))
    assert_eq(m.Package.load(package.dump()).digest, package.digest)


@test([Param(value=scope, name=scope) for scope in ("before", "create")], mark="fast")
async def relinquishment_cannot_hide_visibility_claims(scope: str) -> None:
    """Before/intermediate CREATE payload claims survive empty final ownership."""
    table = _draft("INVISIBLE", "").target.tables[0]
    empty = m.State(backend="mariadb")
    if scope == "before":
        draft = m.Draft(
            revision="002",
            predecessor="previous",
            before=m.State(backend="mariadb", tables=(table,)),
            target=empty,
            operations=(m.RelinquishTable(table_name="entries"),),
        )
    else:
        draft = m.Draft(
            revision="001",
            predecessor=None,
            before=empty,
            target=empty,
            operations=(
                m.CreateTable(table=table),
                m.RelinquishTable(table_name="entries"),
            ),
        )
    with assert_raises(m.PackageError) as error:
        m.compile(draft)
    assert "construction visibility" in str(error.exception)


@test(
    [
        Param(value=clause, name=str(i))
        for i, clause in enumerate(
            (
                "INVISIBLE INVISIBLE",
                "VISIBLE",
                "INVISIBLE VISIBLE",
                "REFERENCES invisible(id)",
            )
        )
    ],
    mark="fast",
)
async def equal_unknown_visibility_forms_require_adapters_at_compilation(
    clause: str,
) -> None:
    """Repeated/conflicting/explicit VISIBLE/unparsed roles keep existing conservative scope."""
    with assert_raises(m.PackageError) as error:
        m.compile(_draft(clause, clause))
    assert "visibility attribute" in str(error.exception)


@test([Param(value=kind, name=kind) for kind in ("add", "default")], mark="fast")
async def standalone_visibility_language_needs_admission_after_handoff(
    kind: str,
) -> None:
    """Duplicate exposure attributes cannot hide in standalone payloads with no ownership."""
    first = m.compile(_draft("", ""))
    name = "extra" if kind == "add" else "value"
    column = m.ColumnState(
        name=name,
        definition=f"`{name}` BIGINT NOT NULL DEFAULT 7 INVISIBLE INVISIBLE",
        nullable=False,
        storage="INTEGER",
        query_type=None,
    )
    op = (
        m.AddColumn(table_name="entries", column=column)
        if kind == "add"
        else m.ChangeDefault(table_name="entries", column=column)
    )
    draft = m.Draft(
        revision="002",
        predecessor=first.digest,
        before=first.target,
        target=m.State(backend="mariadb"),
        operations=(op, m.RelinquishTable(table_name="entries")),
    )
    with assert_raises(m.PackageError) as error:
        m.compile(draft)
    assert "visibility attribute" in str(error.exception)


@test(mark="fast")
async def names_literals_comments_and_nested_mentions_do_not_create_exposure_attributes() -> (
    None
):
    """Quoted names, text defaults/comments and expression words are separate roles."""
    definition = "`invisible` VARCHAR(64) DEFAULT 'INVISIBLE VISIBLE' COMMENT 'INVISIBLE' CHECK (`invisible` <> 'VISIBLE')"
    column = m.ColumnState(
        name="invisible",
        definition=definition,
        nullable=True,
        storage="TEXT",
        query_type="str | None",
    )
    table = m.TableState(
        name="entries",
        quoted_name="`entries`",
        columns=(column,),
        sql=f"CREATE TABLE entries ({definition}) ENGINE=InnoDB",
    )
    draft = m.Draft(
        revision="001",
        predecessor=None,
        before=m.State(backend="mariadb"),
        target=m.State(backend="mariadb", tables=(table,)),
        operations=(m.CreateTable(table=table),),
    )
    package = m.compile(draft)
    assert_eq(m.Package.load(package.dump()).digest, package.digest)


@test(mark="fast")
async def extra_invisible_sql_columns_do_not_create_recorded_ownership() -> None:
    """One-way executable exposure facts do not populate managed columns/indexes."""
    draft = _draft("", "")
    table = draft.target.tables[0]
    table = table.model_copy(
        update={
            "sql": table.sql.replace(
                ") ENGINE", ", extra BIGINT NOT NULL DEFAULT 9 INVISIBLE) ENGINE"
            )
        }
    )
    package = m.compile(
        draft.model_copy(
            update={
                "target": draft.target.model_copy(update={"tables": (table,)}),
                "operations": (m.CreateTable(table=table),),
            }
        )
    )
    assert_eq(tuple(c.name for c in package.target.tables[0].columns), ("id", "value"))
    assert_eq(package.target.tables[0].indexes, ())


@test(mark="slow")
async def archived_native_visibility_late_refusal_now_precedes_effects() -> None:
    """Old committed DDL followed by uncertainty was not native false completion."""
    server = await load_fixture(provide_package_server())
    text = (
        Path(__file__).parent / "fixtures" / "native-visibility" / "invalid-old.json"
    ).read_text()
    bad = m.Package.model_validate_json(text)
    assert_eq(
        bad.digest, "48abe822d254b94121e6a245593b19c6bc0d87b7a1490f02c3ad29d90a2c10ef"
    )
    with assert_raises(m.PackageError) as error:
        m.Package.load(text)
    assert "construction visibility" in str(error.exception)
    async with m.connect(server.config()) as target:
        with assert_raises(m.PackageError) as error:
            await target.prepare(bad, schema_writers_excluded=True)
        assert "construction visibility" in str(error.exception)
        assert_eq(await target.status(), ())
    async with (
        await mariadb.Database.initialize(server.config()) as db,
        db.transaction() as tx,
    ):
        assert_eq(await tx.fetch_all(mariadb.raw("SHOW FULL TABLES")), [])


@test(mark="slow")
async def truthful_archived_visibility_retains_identity_named_access_and_default7() -> (
    None
):
    """INVISIBLE is wildcard/positional behavior, not access control or value erasure."""
    server = await load_fixture(provide_package_server())
    text = (
        Path(__file__).parent / "fixtures" / "native-visibility" / "valid-old.json"
    ).read_text()
    package = m.Package.load(text)
    assert_eq(
        package.digest,
        "fe9f16f9103939d61fff632374bceb154015d039ee6dd1e5f9f2ea1edc55194f",
    )
    assert_eq(package.dump(), text)
    async with m.connect(server.config()) as target:
        await target.apply(await target.prepare(package, schema_writers_excluded=True))
    async with (
        await mariadb.Database.initialize(server.config()) as db,
        db.transaction() as tx,
    ):
        await tx.execute(mariadb.raw("INSERT INTO entries VALUES(42)"))
        assert_eq(
            await tx.fetch_all(mariadb.raw("SELECT * FROM entries")), [{"id": 42}]
        )
        assert_eq(
            await tx.fetch_all(mariadb.raw("SELECT id,value FROM entries")),
            [{"id": 42, "value": 7}],
        )


@test(mark="slow")
async def truthful_visible_columns_keep_wildcard_and_positional_behavior() -> None:
    """Implicit ordinary visibility is unchanged, not normalized from unsupported syntax."""
    server = await load_fixture(provide_package_server())
    package = m.Package.load(m.compile(_draft("", "")).dump())
    async with m.connect(server.config()) as target:
        await target.apply(await target.prepare(package, schema_writers_excluded=True))
    async with (
        await mariadb.Database.initialize(server.config()) as db,
        db.transaction() as tx,
    ):
        await tx.execute(mariadb.raw("INSERT INTO entries VALUES(42,9)"))
        assert_eq(
            await tx.fetch_all(mariadb.raw("SELECT * FROM entries")),
            [{"id": 42, "value": 9}],
        )


@test(mark="slow")
async def native_visibility_drift_still_blocks_followup_after_valid_completion() -> (
    None
):
    """Construction agreement does not replace independent accepted-catalog drift proof."""
    server = await load_fixture(provide_package_server())
    first = m.compile(_draft("INVISIBLE", "INVISIBLE"))
    async with m.connect(server.config()) as target:
        await target.apply(await target.prepare(first, schema_writers_excluded=True))
    await server.run_sql("ALTER TABLE entries MODIFY value BIGINT NOT NULL DEFAULT 7")
    followup = m.compile(
        m.Draft(
            revision="002",
            predecessor=first.digest,
            before=first.target,
            target=first.target,
            operations=(),
        )
    )
    async with m.connect(server.config()) as target:
        with assert_raises(m.PackageError) as error:
            await target.prepare(followup, schema_writers_excluded=True)
        assert "catalog differs from the last accepted execution" in str(
            error.exception
        )
