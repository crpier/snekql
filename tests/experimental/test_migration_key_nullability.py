"""Effective key nullability through public frozen migration admission/deployment."""

from pathlib import Path
from tempfile import TemporaryDirectory

from snektest import Param, assert_eq, assert_raises, load_fixture, test

from snekql import mariadb, sqlite
from snekql.errors import ExecutionError
from snekql.experimental import migrations as m
from tests.experimental.test_migration_nullability import NativeRequired
from tests.experimental.test_migration_targets import provide_package_server


@test(mark="fast")
async def ordinary_sqlite_text_primary_key_cannot_claim_required_storage() -> None:
    """A non-STRICT, non-rowid key permits stored NULL absent an explicit NOT NULL."""
    column = m.ColumnState(
        name="id",
        definition='"id" TEXT PRIMARY KEY',
        nullable=False,
        storage="TEXT",
        query_type="str",
    )
    table = m.TableState(
        name="entries",
        quoted_name='"entries"',
        columns=(column,),
        sql=f'CREATE TABLE "entries" ({column.definition})',
    )
    draft = m.Draft(
        revision="001",
        predecessor=None,
        before=m.State(backend="sqlite"),
        target=m.State(backend="sqlite", tables=(table,)),
        operations=(m.CreateTable(table=table),),
    )
    with assert_raises(m.PackageError) as error:
        m.compile(draft)
    assert "primary-key nullability differs" in str(error.exception)


@test(mark="fast")
async def strict_sqlite_key_cannot_claim_nullable_storage() -> None:
    """STRICT makes a text primary key effectively required without a NULL clause."""
    column = m.ColumnState(
        name="id",
        definition='"id" TEXT PRIMARY KEY',
        nullable=True,
        storage="TEXT",
        query_type="str | None",
    )
    table = m.TableState(
        name="entries",
        quoted_name='"entries"',
        columns=(column,),
        sql=f'CREATE TABLE "entries" ({column.definition}) STRICT',
    )
    draft = m.Draft(
        revision="001",
        predecessor=None,
        before=m.State(backend="sqlite"),
        target=m.State(backend="sqlite", tables=(table,)),
        operations=(m.CreateTable(table=table),),
    )
    with assert_raises(m.PackageError) as error:
        m.compile(draft)
    assert "primary-key nullability differs" in str(error.exception)


@test(mark="fast")
async def sqlite_integer_rowid_key_cannot_claim_nullable_stored_values() -> None:
    """Accepting NULL input as a generated rowid does not make stored ids nullable."""
    column = m.ColumnState(
        name="id",
        definition='"id" INTEGER PRIMARY KEY',
        nullable=True,
        storage="INTEGER",
        query_type="int | None",
    )
    table = m.TableState(
        name="entries",
        quoted_name='"entries"',
        columns=(column,),
        sql=f'CREATE TABLE "entries" ({column.definition})',
    )
    draft = m.Draft(
        revision="001",
        predecessor=None,
        before=m.State(backend="sqlite"),
        target=m.State(backend="sqlite", tables=(table,)),
        operations=(m.CreateTable(table=table),),
    )
    with assert_raises(m.PackageError) as error:
        m.compile(draft)
    assert "primary-key nullability differs" in str(error.exception)


@test(mark="fast")
async def without_rowid_key_cannot_claim_nullable_storage() -> None:
    """WITHOUT ROWID enforces required key members even outside STRICT mode."""
    column = m.ColumnState(
        name="id",
        definition='"id" TEXT PRIMARY KEY',
        nullable=True,
        storage="TEXT",
        query_type="str | None",
    )
    table = m.TableState(
        name="entries",
        quoted_name='"entries"',
        columns=(column,),
        sql=f'CREATE TABLE "entries" ({column.definition}) WITHOUT ROWID',
    )
    draft = m.Draft(
        revision="001",
        predecessor=None,
        before=m.State(backend="sqlite"),
        target=m.State(backend="sqlite", tables=(table,)),
        operations=(m.CreateTable(table=table),),
    )
    with assert_raises(m.PackageError) as error:
        m.compile(draft)
    assert "primary-key nullability differs" in str(error.exception)


@test(mark="fast")
async def native_inline_key_cannot_claim_nullable_storage() -> None:
    """MariaDB primary keys imply NOT NULL even when the definition omits that clause."""
    column = m.ColumnState(
        name="id",
        definition="`id` BIGINT PRIMARY KEY",
        nullable=True,
        storage="INTEGER",
        query_type="int | None",
    )
    table = m.TableState(
        name="entries",
        quoted_name="`entries`",
        columns=(column,),
        sql=f"CREATE TABLE `entries` ({column.definition}) ENGINE=InnoDB",
    )
    draft = m.Draft(
        revision="001",
        predecessor=None,
        before=m.State(backend="mariadb"),
        target=m.State(backend="mariadb", tables=(table,)),
        operations=(m.CreateTable(table=table),),
    )
    with assert_raises(m.PackageError) as error:
        m.compile(draft)
    assert "primary-key nullability differs" in str(error.exception)


@test(mark="fast")
async def strict_table_key_members_cannot_evade_effective_nullability() -> None:
    """A composite table key must not turn a nullable flag into an exclusion loophole."""
    columns = (
        m.ColumnState(
            name="a",
            definition='"a" TEXT',
            nullable=True,
            storage="TEXT",
            query_type="str | None",
        ),
        m.ColumnState(
            name="b",
            definition='"b" INTEGER',
            nullable=False,
            storage="INTEGER",
            query_type="int",
        ),
    )
    table = m.TableState(
        name="entries",
        quoted_name='"entries"',
        columns=columns,
        sql='CREATE TABLE "entries" ("a" TEXT, "b" INTEGER, CONSTRAINT "pk_entries" PRIMARY KEY ("a", "b")) STRICT',
    )
    draft = m.Draft(
        revision="001",
        predecessor=None,
        before=m.State(backend="sqlite"),
        target=m.State(backend="sqlite", tables=(table,)),
        operations=(m.CreateTable(table=table),),
    )
    with assert_raises(m.PackageError) as error:
        m.compile(draft)
    assert "primary-key nullability differs" in str(error.exception)


@test(
    [
        Param(value=case, name=name)
        for name, case in (
            ("text", ('"id" TEXT PRIMARY KEY', "", "", True, "null")),
            ("int_not_integer", ('"id" INT PRIMARY KEY', "", "", True, "null")),
            ("integer_desc", ('"id" INTEGER PRIMARY KEY DESC', "", "", True, "null")),
            ("integer_alias", ('"id" INTEGER PRIMARY KEY', "", "", False, "assign")),
            ("integer_asc", ('"id" INTEGER PRIMARY KEY ASC', "", "", False, "assign")),
            (
                "explicit_required",
                ('"id" TEXT NOT NULL PRIMARY KEY', "", "", False, "reject"),
            ),
            ("strict", ('"id" TEXT NULL PRIMARY KEY', " STRICT", "", False, "reject")),
            (
                "strict_desc",
                ('"id" INTEGER PRIMARY KEY DESC', " STRICT", "", False, "reject"),
            ),
            (
                "without_rowid",
                ('"id" TEXT PRIMARY KEY', " WITHOUT ROWID", "", False, "reject"),
            ),
            (
                "strict_without",
                (
                    '"id" INTEGER PRIMARY KEY',
                    " STRICT, WITHOUT ROWID",
                    "",
                    False,
                    "reject",
                ),
            ),
            (
                "without_strict",
                (
                    '"id" TEXT PRIMARY KEY',
                    " WITHOUT ROWID, STRICT",
                    "",
                    False,
                    "reject",
                ),
            ),
            (
                "table_integer_desc",
                (
                    '"id" INTEGER',
                    "",
                    ', CONSTRAINT "pk_entries" PRIMARY KEY ("id" DESC)',
                    False,
                    "assign",
                ),
            ),
            (
                "table_text",
                (
                    '"id" TEXT',
                    "",
                    ', PRIMARY KEY ("id") ON CONFLICT ABORT',
                    True,
                    "null",
                ),
            ),
            ("table_int", ('"id" INT', "", ', PRIMARY KEY ("id")', True, "null")),
        )
    ],
    mark="medium",
)
async def sqlite_key_modes_have_their_declared_stored_null_behavior(
    case: tuple[str, str, str, bool, str],
) -> None:
    """Real SQLite distinguishes NULL storage, rowid allocation and rejected NULL writes."""
    definition, suffix, key, nullable, behavior = case
    column = m.ColumnState(
        name="id",
        definition=definition,
        nullable=nullable,
        storage="TEXT" if " TEXT" in definition else "INTEGER",
        query_type=None,
    )
    table = m.TableState(
        name="entries",
        quoted_name='"entries"',
        columns=(column,),
        sql=f'CREATE TABLE "entries" ({definition}{key}){suffix}',
    )
    draft = m.Draft(
        revision="001",
        predecessor=None,
        before=m.State(backend="sqlite"),
        target=m.State(backend="sqlite", tables=(table,)),
        operations=(m.CreateTable(table=table),),
    )
    package = m.Package.load(m.compile(draft).dump())
    with TemporaryDirectory() as directory:
        config = sqlite.Config(database=Path(directory) / "keys.db")
        async with m.connect(config) as target:
            await target.apply(await target.prepare(package))
            assert_eq((await target.status())[0].phase, "complete")
        async with await sqlite.Database.initialize(config) as db:
            if behavior == "reject":
                with assert_raises(ExecutionError):
                    async with db.transaction() as tx:
                        await tx.execute(
                            sqlite.raw("INSERT INTO entries(id) VALUES(NULL)")
                        )
                async with db.transaction() as tx:
                    assert_eq(
                        await tx.fetch_all(sqlite.raw("SELECT id FROM entries")), []
                    )
            else:
                async with db.transaction() as tx:
                    await tx.execute(sqlite.raw("INSERT INTO entries(id) VALUES(NULL)"))
                    assert_eq(
                        await tx.fetch_all(sqlite.raw("SELECT id FROM entries")),
                        [{"id": 1 if behavior == "assign" else None}],
                    )


@test(
    [Param(value=strict, name=str(strict)) for strict in (False, True)], mark="medium"
)
async def composite_sqlite_integer_member_is_not_a_rowid_alias(
    strict: bool,  # noqa: FBT001
) -> None:
    """Composite keys permit NULL outside STRICT and enforce all members inside it."""
    columns = (
        m.ColumnState(
            name="a",
            definition='"a" INTEGER',
            nullable=not strict,
            storage="INTEGER",
            query_type=None,
        ),
        m.ColumnState(
            name="b",
            definition='"b" TEXT',
            nullable=not strict,
            storage="TEXT",
            query_type=None,
        ),
    )
    table = m.TableState(
        name="entries",
        quoted_name='"entries"',
        columns=columns,
        sql='CREATE TABLE "entries" ("a" INTEGER, "b" TEXT, PRIMARY KEY ("a" DESC, "b" ASC))'
        + (" STRICT" if strict else ""),
    )
    draft = m.Draft(
        revision="001",
        predecessor=None,
        before=m.State(backend="sqlite"),
        target=m.State(backend="sqlite", tables=(table,)),
        operations=(m.CreateTable(table=table),),
    )
    package = m.Package.load(m.compile(draft).dump())
    with TemporaryDirectory() as directory:
        config = sqlite.Config(database=Path(directory) / "keys.db")
        async with m.connect(config) as target:
            await target.apply(await target.prepare(package))
        async with await sqlite.Database.initialize(config) as db:
            if strict:
                with assert_raises(ExecutionError):
                    async with db.transaction() as tx:
                        await tx.execute(
                            sqlite.raw("INSERT INTO entries VALUES(NULL,'kept')")
                        )
            else:
                async with db.transaction() as tx:
                    await tx.execute(
                        sqlite.raw("INSERT INTO entries VALUES(NULL,'kept')")
                    )
                    assert_eq(
                        await tx.fetch_all(sqlite.raw("SELECT a,b FROM entries")),
                        [{"a": None, "b": "kept"}],
                    )


@test(mark="slow")
async def native_key_flag_mismatch_refuses_before_effects_and_valid_keys_deploy() -> (
    None
):
    """Compile refusal cannot leave native DDL or history, while supported keys execute."""
    server = await load_fixture(provide_package_server())
    draft = m.generate("001", [NativeRequired], backend="mariadb")
    table = draft.target.tables[0]
    column = table.columns[0].model_copy(update={"nullable": True})
    bad = table.model_copy(update={"columns": (column, table.columns[1])})
    with assert_raises(m.PackageError) as error:
        m.compile(
            draft.model_copy(
                update={
                    "target": draft.target.model_copy(update={"tables": (bad,)}),
                    "operations": (m.CreateTable(table=bad),),
                }
            )
        )
    assert "primary-key nullability differs" in str(error.exception)
    async with m.connect(server.config()) as target:
        assert_eq(await target.status(), ())
    async with (
        await mariadb.Database.initialize(server.config()) as db,
        db.transaction() as tx,
    ):
        assert_eq(await tx.fetch_all(mariadb.raw("SHOW FULL TABLES")), [])
    first = m.Package.load(m.compile(draft).dump())
    async with m.connect(server.config()) as target:
        await target.apply(await target.prepare(first, schema_writers_excluded=True))
    async with (
        await mariadb.Database.initialize(server.config()) as db,
        db.transaction() as tx,
    ):
        await tx.execute(mariadb.raw("INSERT INTO entries(id) VALUES(42)"))
        assert_eq(
            await tx.fetch_all(mariadb.raw("SELECT id,value FROM entries")),
            [{"id": 42, "value": 7}],
        )


@test(mark="medium")
async def old_required_text_key_artifact_refuses_without_rewriting_valid_identity() -> (
    None
):
    """Real format2 contradiction refuses load/typed preparation, valid nullable key stays."""
    root = Path(__file__).parent / "fixtures" / "key-nullability"
    invalid = (root / "invalid-old.json").read_text()
    old = m.Package.model_validate_json(invalid)
    assert_eq(
        old.digest, "7e1212b672040c56705052e4653c4cd4f544917c179b8f544f28c1094a1a9d3d"
    )
    with assert_raises(m.PackageError) as error:
        m.Package.load(invalid)
    assert "primary-key nullability differs" in str(error.exception)
    valid = (root / "valid-old.json").read_text()
    package = m.Package.load(valid)
    assert_eq(
        package.digest,
        "5d11c3e2c381e4346ab451b27c775725d4c542ce1aaf43ab8ce4afe4782d8449",
    )
    assert_eq(package.dump(), valid)
    with TemporaryDirectory() as directory:
        config = sqlite.Config(database=Path(directory) / "keys.db")
        async with m.connect(config) as target:
            with assert_raises(m.PackageError) as error:
                await target.prepare(old)
            assert "primary-key nullability differs" in str(error.exception)
            assert_eq(await target.status(), ())
            await target.apply(await target.prepare(package))
        async with (
            await sqlite.Database.initialize(config) as db,
            db.transaction() as tx,
        ):
            await tx.execute(sqlite.raw("INSERT INTO entries VALUES(NULL),(NULL)"))
            assert_eq(
                await tx.fetch_all(sqlite.raw("SELECT id FROM entries")),
                [{"id": None}, {"id": None}],
            )


@test(
    [Param(value=scope, name=scope) for scope in ("before", "create", "adopt")],
    mark="fast",
)
async def relinquishment_cannot_hide_effective_key_flag_contradictions(
    scope: str,
) -> None:
    """Keys remain claims at before/intermediate payload boundaries even after handoff."""
    column = m.ColumnState(
        name="id",
        definition='"id" TEXT PRIMARY KEY',
        nullable=False,
        storage="TEXT",
        query_type="str",
    )
    table = m.TableState(
        name="entries",
        quoted_name='"entries"',
        columns=(column,),
        sql=f'CREATE TABLE "entries" ({column.definition})',
    )
    empty = m.State(backend="sqlite")
    if scope == "before":
        draft = m.Draft(
            revision="002",
            predecessor="previous",
            before=m.State(backend="sqlite", tables=(table,)),
            target=empty,
            operations=(m.RelinquishTable(table_name="entries"),),
        )
    else:
        operation = (
            m.CreateTable(table=table)
            if scope == "create"
            else m.AdoptTable(table=table)
        )
        draft = m.Draft(
            revision="001",
            predecessor=None,
            before=empty,
            target=empty,
            operations=(operation, m.RelinquishTable(table_name="entries")),
        )
    with assert_raises(m.PackageError) as error:
        m.compile(draft)
    assert "primary-key nullability differs" in str(error.exception)


@test(
    [
        Param(value=clause, name=str(i))
        for i, clause in enumerate(
            (
                'PRIMARY KEY ("id"(4))',
                'PRIMARY KEY (lower("id"))',
                'PRIMARY KEY ("id", "id")',
                'PRIMARY KEY ("unknown")',
                "PRIMARY KEY ()",
            )
        )
    ],
    mark="fast",
)
async def unsupported_or_ambiguous_table_members_do_not_suppress_nullability(
    clause: str,
) -> None:
    """Membership language is finite, not expression/prefix or SQL-equivalence guessing."""
    column = m.ColumnState(
        name="id",
        definition='"id" TEXT',
        nullable=True,
        storage="TEXT",
        query_type="str | None",
    )
    table = m.TableState(
        name="entries",
        quoted_name='"entries"',
        columns=(column,),
        sql=f'CREATE TABLE "entries" ({column.definition}, {clause})',
    )
    draft = m.Draft(
        revision="001",
        predecessor=None,
        before=m.State(backend="sqlite"),
        target=m.State(backend="sqlite", tables=(table,)),
        operations=(m.CreateTable(table=table),),
    )
    with assert_raises(m.PackageError) as error:
        m.compile(draft)
    assert "primary-key member" in str(error.exception)


@test(
    [
        Param(value=source_required, name=str(source_required))
        for source_required in (False, True)
    ],
    mark="fast",
)
async def nonstrict_key_flags_bind_definition_and_construction_independently(
    source_required: bool,  # noqa: FBT001
) -> None:
    """Matching key markers cannot hide an explicit NOT NULL change outside STRICT."""
    definition = '"id" TEXT' + (" NOT NULL" if source_required else "") + " PRIMARY KEY"
    actual = '"id" TEXT' + ("" if source_required else " NOT NULL") + " PRIMARY KEY"
    column = m.ColumnState(
        name="id",
        definition=definition,
        nullable=not source_required,
        storage="TEXT",
        query_type=None,
    )
    table = m.TableState(
        name="entries",
        quoted_name='"entries"',
        columns=(column,),
        sql=f'CREATE TABLE "entries" ({actual})',
    )
    draft = m.Draft(
        revision="001",
        predecessor=None,
        before=m.State(backend="sqlite"),
        target=m.State(backend="sqlite", tables=(table,)),
        operations=(m.CreateTable(table=table),),
    )
    with assert_raises(m.PackageError) as error:
        m.compile(draft)
    assert "primary-key nullability differs" in str(error.exception)


@test(mark="slow")
async def actual_old_native_table_key_refuses_loading_and_typed_preparation() -> None:
    """Old native late uncertainty moves to pre-DDL refusal, not false-completion repair."""
    server = await load_fixture(provide_package_server())
    text = (
        Path(__file__).parent
        / "fixtures"
        / "key-nullability"
        / "native-invalid-old.json"
    ).read_text()
    old = m.Package.model_validate_json(text)
    assert_eq(
        old.digest, "38a4b1e3d790f16fbebcedb58c08fb9fe974a86e19414fdbf505f5800e576fec"
    )
    with assert_raises(m.PackageError) as error:
        m.Package.load(text)
    assert "primary-key nullability differs" in str(error.exception)
    async with m.connect(server.config()) as target:
        with assert_raises(m.PackageError) as error:
            await target.prepare(old, schema_writers_excluded=True)
        assert "primary-key nullability differs" in str(error.exception)
        assert_eq(await target.status(), ())
    async with (
        await mariadb.Database.initialize(server.config()) as db,
        db.transaction() as tx,
    ):
        assert_eq(await tx.fetch_all(mariadb.raw("SHOW FULL TABLES")), [])
    table = old.target.tables[0]
    table = table.model_copy(
        update={"columns": (table.columns[0].model_copy(update={"nullable": False}),)}
    )
    valid = m.Package.load(
        m.compile(
            old.draft.model_copy(
                update={
                    "target": old.target.model_copy(update={"tables": (table,)}),
                    "operations": (m.CreateTable(table=table),),
                }
            )
        ).dump()
    )
    async with m.connect(server.config()) as target:
        await target.apply(await target.prepare(valid, schema_writers_excluded=True))
    async with (
        await mariadb.Database.initialize(server.config()) as db,
        db.transaction() as tx,
    ):
        await tx.execute(mariadb.raw("INSERT INTO entries VALUES(42)"))
        assert_eq(
            await tx.fetch_all(mariadb.raw("SELECT id FROM entries")), [{"id": 42}]
        )


@test(
    [
        Param(value=suffix, name=str(i))
        for i, suffix in enumerate((' "STRICT"', " STRICT, FUTURE_OPTION"))
    ],
    mark="fast",
)
async def unknown_sqlite_modes_do_not_prove_key_requiredness(suffix: str) -> None:
    """An identifier mention or unknown option is not a known required-key mode."""
    column = m.ColumnState(
        name="id",
        definition='"id" TEXT PRIMARY KEY',
        nullable=False,
        storage="TEXT",
        query_type=None,
    )
    table = m.TableState(
        name="entries",
        quoted_name='"entries"',
        columns=(column,),
        sql=f'CREATE TABLE "entries" ({column.definition}){suffix}',
    )
    draft = m.Draft(
        revision="001",
        predecessor=None,
        before=m.State(backend="sqlite"),
        target=m.State(backend="sqlite", tables=(table,)),
        operations=(m.CreateTable(table=table),),
    )
    with assert_raises(m.PackageError) as error:
        m.compile(draft)
    assert "primary-key table options" in str(error.exception)


@test(mark="fast")
async def unrecorded_key_members_do_not_manufacture_column_claims() -> None:
    """SQL may include extra declarations; reading membership never adopts their columns."""
    column = m.ColumnState(
        name="value",
        definition='"value" INTEGER',
        nullable=True,
        storage="INTEGER",
        query_type=None,
    )
    table = m.TableState(
        name="entries",
        quoted_name='"entries"',
        columns=(column,),
        sql='CREATE TABLE "entries" ("value" INTEGER, "extra" TEXT, PRIMARY KEY ("extra")) STRICT',
    )
    draft = m.Draft(
        revision="001",
        predecessor=None,
        before=m.State(backend="sqlite"),
        target=m.State(backend="sqlite", tables=(table,)),
        operations=(m.CreateTable(table=table),),
    )
    package = m.compile(draft)
    assert_eq(package.target.tables[0].columns, (column,))
