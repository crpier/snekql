"""Native AUTO_INCREMENT construction claims are independent of key existence."""

from pathlib import Path

from snektest import Param, assert_eq, assert_raises, load_fixture, test

from snekql import mariadb
from snekql.experimental import migrations as m
from tests.experimental.test_migration_nullability import NativeRequired
from tests.experimental.test_migration_targets import provide_package_server


def _draft(declaration: str, construction: str) -> m.Draft:
    """Review the id generation clause separately from executable construction."""
    draft = m.generate("001", [NativeRequired], backend="mariadb")
    table = draft.target.tables[0]
    old = table.columns[0]
    column = old.model_copy(
        update={
            "definition": old.definition.replace(
                "PRIMARY KEY", declaration + " PRIMARY KEY"
            )
        }
    )
    table = table.model_copy(
        update={
            "columns": (column, table.columns[1]),
            "sql": table.sql.replace(
                old.definition,
                old.definition.replace("PRIMARY KEY", construction + " PRIMARY KEY"),
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
async def an_inline_key_cannot_certify_a_missing_native_id_generator() -> None:
    """Matching key/type/nullability must not defer a known generator mismatch to DDL."""
    with assert_raises(m.PackageError) as error:
        m.compile(_draft("AUTO_INCREMENT", ""))
    assert "construction AUTO_INCREMENT" in str(error.exception)


@test(mark="fast")
async def equal_duplicate_native_generator_clauses_require_an_adapter() -> None:
    """Matching bytes are not bounded AUTO_INCREMENT admission for repeated attributes."""
    clause = "AUTO_INCREMENT AUTO_INCREMENT"
    with assert_raises(m.PackageError) as error:
        m.compile(_draft(clause, clause))
    assert "multiple MariaDB AUTO_INCREMENT" in str(error.exception)


@test(mark="fast")
async def constructor_cannot_add_an_unrequested_native_id_generator() -> None:
    """Absence binds as strongly as recorded presence, even on a matching primary key."""
    with assert_raises(m.PackageError) as error:
        m.compile(_draft("", "AUTO_INCREMENT"))
    assert "construction AUTO_INCREMENT" in str(error.exception)


@test(
    [
        Param(value=pair, name=str(i))
        for i, pair in enumerate((("AUTO_INCREMENT", "auto_increment"), ("", "")))
    ],
    mark="fast",
)
async def canonical_native_identity_presence_and_case_roundtrip(
    pair: tuple[str, str],
) -> None:
    """Known keyword case normalizes, including truthful absence."""
    package = m.compile(_draft(*pair))
    assert_eq(m.Package.load(package.dump()).digest, package.digest)


@test([Param(value=scope, name=scope) for scope in ("before", "create")], mark="fast")
async def relinquishment_cannot_hide_native_identity_claims(scope: str) -> None:
    """Before/intermediate construction payloads retain claims with empty final ownership."""
    table = _draft("AUTO_INCREMENT", "").target.tables[0]
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
    assert "construction AUTO_INCREMENT" in str(error.exception)


@test(mark="fast")
async def unsupported_generator_position_requires_an_adapter_even_with_equal_bytes() -> (
    None
):
    """A generator after opaque COMMENT text is not inferred from keyword presence."""
    clause = "COMMENT 'kept' AUTO_INCREMENT"
    with assert_raises(m.PackageError) as error:
        m.compile(_draft(clause, clause))
    assert "unsupported MariaDB AUTO_INCREMENT position" in str(error.exception)


@test([Param(value=kind, name=kind) for kind in ("add", "default")], mark="fast")
async def standalone_generator_language_needs_admission_without_final_ownership(
    kind: str,
) -> None:
    """Unknown generator positions in standalone operations cannot hide after handoff."""
    first = m.compile(_draft("", ""))
    name = "extra" if kind == "add" else "id"
    column = m.ColumnState(
        name=name,
        definition=f"`{name}` BIGINT NOT NULL COMMENT 'kept' AUTO_INCREMENT PRIMARY KEY",
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
    assert "unsupported MariaDB AUTO_INCREMENT position" in str(error.exception)


@test(mark="fast")
async def literal_and_quoted_generator_mentions_do_not_manufacture_identity() -> None:
    """The column name/default/comment text are not attribute tokens."""
    definition = "`auto_increment` VARCHAR(64) NOT NULL DEFAULT 'AUTO_INCREMENT' COMMENT 'AUTO_INCREMENT'"
    column = m.ColumnState(
        name="auto_increment",
        definition=definition,
        nullable=False,
        storage="TEXT",
        query_type="str",
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
async def extra_sql_generator_does_not_manufacture_column_or_index_ownership() -> None:
    """An extra indexed generator is executable input, not a managed id/unique-index claim."""
    draft = _draft("", "")
    table = draft.target.tables[0]
    table = table.model_copy(
        update={
            "sql": table.sql.replace(
                ") ENGINE", ", extra BIGINT NOT NULL AUTO_INCREMENT UNIQUE) ENGINE"
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
async def archived_late_native_identity_refusal_now_precedes_effects() -> None:
    """Real old format2 was uncertain/ambiguous, not a native false completion."""
    server = await load_fixture(provide_package_server())
    text = (
        Path(__file__).parent / "fixtures" / "native-identity" / "invalid-old.json"
    ).read_text()
    bad = m.Package.model_validate_json(text)
    assert_eq(
        bad.digest, "0ca96e5471950bb1ff6d45f4f4e2609c7db07d9b8b996e0a57b3877e91c24d40"
    )
    with assert_raises(m.PackageError) as error:
        m.Package.load(text)
    assert "construction AUTO_INCREMENT" in str(error.exception)
    async with m.connect(server.config()) as target:
        with assert_raises(m.PackageError) as error:
            await target.prepare(bad, schema_writers_excluded=True)
        assert "construction AUTO_INCREMENT" in str(error.exception)
        assert_eq(await target.status(), ())
    async with (
        await mariadb.Database.initialize(server.config()) as db,
        db.transaction() as tx,
    ):
        assert_eq(await tx.fetch_all(mariadb.raw("SHOW FULL TABLES")), [])


@test(mark="slow")
async def truthful_archived_generator_retains_identity_and_advancing_counter_behavior() -> (
    None
):
    """Model-free generation/default7 survives literal format2 loading and counter changes."""
    server = await load_fixture(provide_package_server())
    text = (
        Path(__file__).parent / "fixtures" / "native-identity" / "valid-old.json"
    ).read_text()
    package = m.Package.load(text)
    assert_eq(
        package.digest,
        "344bee433f8ea6ed72d4c0fe53c014d9aed67240538d7f733b7df253d9254f96",
    )
    assert_eq(package.dump(), text)
    async with m.connect(server.config()) as target:
        await target.apply(await target.prepare(package, schema_writers_excluded=True))
    async with (
        await mariadb.Database.initialize(server.config()) as db,
        db.transaction() as tx,
    ):
        await tx.execute(mariadb.raw("INSERT INTO entries () VALUES (),()"))
        await tx.execute(mariadb.raw("INSERT INTO entries(id) VALUES(NULL)"))
        assert_eq(
            await tx.fetch_all(mariadb.raw("SELECT id,value FROM entries ORDER BY id")),
            [{"id": 1, "value": 7}, {"id": 2, "value": 7}, {"id": 3, "value": 7}],
        )
    followup = m.compile(
        m.Draft(
            revision="002",
            predecessor=package.digest,
            before=package.target,
            target=package.target,
            operations=(),
        )
    )
    async with m.connect(server.config()) as target:
        assert_eq(
            await target.apply(
                await target.prepare(followup, schema_writers_excluded=True)
            ),
            "applied",
        )


@test(mark="slow")
async def native_identity_catalog_drift_still_blocks_followup_after_valid_completion() -> (
    None
):
    """Earlier admission does not replace the independent accepted-catalog drift guard."""
    server = await load_fixture(provide_package_server())
    first = m.compile(_draft("AUTO_INCREMENT", "AUTO_INCREMENT"))
    async with m.connect(server.config()) as target:
        await target.apply(await target.prepare(first, schema_writers_excluded=True))
    await server.run_sql("ALTER TABLE entries MODIFY id BIGINT NOT NULL")
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
