"""Bounded physical collation claims agree before migration construction effects."""

from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Literal

from snektest import Param, assert_eq, assert_raises, load_fixture, test

from snekql import mariadb, sqlite
from snekql.errors import ExecutionError
from snekql.experimental import migrations as m
from tests.experimental.test_migration_targets import provide_package_server


def _draft(
    backend: Literal["sqlite", "mariadb"], declaration: str, construction: str
) -> m.Draft:
    """Review a text comparison domain separately from executable table construction."""
    integer = "INTEGER" if backend == "sqlite" else "BIGINT NOT NULL"
    text = "TEXT" if backend == "sqlite" else "VARCHAR(64) CHARACTER SET utf8mb4"
    id_column = m.ColumnState(
        name="id",
        definition=f"`id` {integer} PRIMARY KEY",
        nullable=False,
        storage="INTEGER",
        query_type="int",
    )

    def definition(clause: str) -> str:
        """Keep default and UNIQUE facts identical while reviewing collation."""
        return (
            f"`label` {text}"
            + (f" {clause}" if clause else "")
            + " NOT NULL DEFAULT 'Case' UNIQUE"
        )

    column = m.ColumnState(
        name="label",
        definition=definition(declaration),
        nullable=False,
        storage="TEXT",
        query_type="str",
    )
    table = m.TableState(
        name="entries",
        quoted_name="`entries`",
        columns=(id_column, column),
        sql=f"CREATE TABLE `entries` ({id_column.definition}, {definition(construction)})"
        + (" STRICT" if backend == "sqlite" else " ENGINE=InnoDB"),
    )
    return m.Draft(
        revision="001",
        predecessor=None,
        before=m.State(backend=backend),
        target=m.State(backend=backend, tables=(table,)),
        operations=(m.CreateTable(table=table),),
    )


@test(mark="fast")
async def unique_and_storage_agreement_cannot_hide_a_collation_change() -> None:
    """NOCASE rejects case-only duplicates while BINARY can store both."""
    with assert_raises(m.PackageError) as error:
        m.compile(_draft("sqlite", "COLLATE NOCASE", "COLLATE BINARY"))
    assert "construction collation" in str(error.exception)


@test(mark="fast")
async def native_explicit_collation_changes_refuse_before_ddl() -> None:
    """Known different text comparison domains do not wait for post-DDL catalog refusal."""
    with assert_raises(m.PackageError) as error:
        m.compile(
            _draft("mariadb", "COLLATE utf8mb4_bin", "COLLATE utf8mb4_general_ci")
        )
    assert "construction collation" in str(error.exception)


@test(mark="fast")
async def matching_builtin_collation_does_not_erase_its_explicit_constraint_identity() -> (
    None
):
    """SQLite COLLATE can carry its own constraint label, separate from value behavior."""
    with assert_raises(m.PackageError) as error:
        m.compile(
            _draft(
                "sqlite",
                'CONSTRAINT "recorded" COLLATE NOCASE',
                'CONSTRAINT "other" COLLATE NOCASE',
            )
        )
    assert "construction collation" in str(error.exception)


@test(
    [
        Param(value=pair, name=str(i))
        for i, pair in enumerate(
            (
                ("COLLATE NOCASE", ""),
                ("", "COLLATE NOCASE"),
                ("COLLATE RTRIM", "COLLATE BINARY"),
            )
        )
    ],
    mark="fast",
)
async def collation_binding_includes_absence_and_trim_domains(
    pair: tuple[str, str],
) -> None:
    """The implicit BINARY default does not imply NOCASE/RTRIM."""
    with assert_raises(m.PackageError) as error:
        m.compile(_draft("sqlite", *pair))
    assert "construction collation" in str(error.exception)


@test(
    [
        Param(value=pair, name=str(i))
        for i, pair in enumerate(
            (
                ("", "COLLATE BINARY"),
                ("COLLATE [NOCASE]", 'collate "nocase"'),
                (
                    'CONSTRAINT "chosen" COLLATE RTRIM',
                    "CONSTRAINT [chosen] collate `rtrim`",
                ),
            )
        )
    ],
    mark="fast",
)
async def known_builtin_case_quotes_and_implicit_binary_normalize(
    pair: tuple[str, str],
) -> None:
    """Only built-in collation spelling, known BINARY omission and quotes normalize."""
    package = m.compile(_draft("sqlite", *pair))
    assert_eq(m.Package.load(package.dump()).digest, package.digest)


@test(
    [
        Param(value=pair, name=str(i))
        for i, pair in enumerate(
            (
                ("COLLATE BINARY", 'CONSTRAINT "chosen" COLLATE BINARY'),
                (
                    'CONSTRAINT "Chosen" COLLATE NOCASE',
                    'CONSTRAINT "chosen" COLLATE NOCASE',
                ),
            )
        )
    ],
    mark="fast",
)
async def collation_constraint_label_presence_and_case_do_not_disappear(
    pair: tuple[str, str],
) -> None:
    """Known comparison behavior does not establish a named constraint's identity."""
    with assert_raises(m.PackageError) as error:
        m.compile(_draft("sqlite", *pair))
    assert "construction collation" in str(error.exception)


@test(
    [
        Param(value=clause, name=str(i))
        for i, clause in enumerate(
            (
                "COLLATE custom",
                "COLLATE NOCASE COLLATE NOCASE",
                "COLLATE BINARY DESC",
                "COLLATE 'NOCASE'",
                "CONSTRAINT 'chosen' COLLATE NOCASE",
            )
        )
    ],
    mark="fast",
)
async def equal_unknown_collation_forms_require_explicit_adapters(clause: str) -> None:
    """Matching bytes are not proof for custom/duplicate/suffix/string-role forms."""
    with assert_raises(m.PackageError) as error:
        m.compile(_draft("sqlite", clause, clause))
    assert "construction collation" in str(error.exception)


@test(
    [Param(value=scope, name=scope) for scope in ("before", "create", "adopt")],
    mark="fast",
)
async def handoff_cannot_hide_a_collation_contradiction(scope: str) -> None:
    """Before/intermediate claims survive an empty final owned state."""
    table = _draft("sqlite", "COLLATE NOCASE", "COLLATE BINARY").target.tables[0]
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
        op = (
            m.CreateTable(table=table)
            if scope == "create"
            else m.AdoptTable(table=table)
        )
        draft = m.Draft(
            revision="001",
            predecessor=None,
            before=empty,
            target=empty,
            operations=(op, m.RelinquishTable(table_name="entries")),
        )
    with assert_raises(m.PackageError) as error:
        m.compile(draft)
    assert "construction collation" in str(error.exception)


@test([Param(value=kind, name=kind) for kind in ("add", "default")], mark="fast")
async def standalone_collation_admission_survives_relinquishment(kind: str) -> None:
    """Unknown collation payloads are not hidden by final ownership or earlier clauses."""
    first = m.compile(_draft("sqlite", "", ""))
    if kind == "add":
        column = m.ColumnState(
            name="extra",
            definition="`extra` TEXT COLLATE custom NULL",
            nullable=True,
            storage="TEXT",
            query_type=None,
        )
        op = m.AddColumn(table_name="entries", column=column)
    else:
        column = (
            first.target.tables[0]
            .columns[1]
            .model_copy(
                update={
                    "definition": "`label` TEXT COLLATE custom NOT NULL DEFAULT 'next' UNIQUE"
                }
            )
        )
        op = m.ChangeDefault(table_name="entries", column=column)
    draft = m.Draft(
        revision="002",
        predecessor=first.digest,
        before=first.target,
        target=m.State(backend="sqlite"),
        operations=(op, m.RelinquishTable(table_name="entries")),
    )
    with assert_raises(m.PackageError) as error:
        m.compile(draft)
    assert "construction collation" in str(error.exception)


@test(
    [
        Param(value=collation, name=collation or "implicit")
        for collation in ("", "BINARY", "NOCASE", "RTRIM")
    ],
    mark="medium",
)
async def sqlite_comparison_domains_preserve_their_unique_write_behavior(
    collation: str,
) -> None:
    """ASCII case/trailing-space duplicates distinguish BINARY/NOCASE/RTRIM."""
    clause = f"COLLATE {collation}" if collation else ""
    package = m.Package.load(m.compile(_draft("sqlite", clause, clause)).dump())
    with TemporaryDirectory() as directory:
        config = sqlite.Config(database=Path(directory) / "collation.db")
        async with m.connect(config) as target:
            await target.apply(await target.prepare(package))
        async with await sqlite.Database.initialize(config) as db:
            async with db.transaction() as tx:
                await tx.execute(sqlite.raw("INSERT INTO entries(id) VALUES(42)"))
            for id_value, text in ((43, "case"), (44, "Case ")):
                query = sqlite.raw(
                    "INSERT INTO entries(id,label) VALUES(:id,:label)",
                    params={"id": id_value, "label": text},
                )
                reject = (collation == "NOCASE" and id_value == 43) or (
                    collation == "RTRIM" and id_value == 44
                )
                if reject:
                    with assert_raises(ExecutionError):
                        async with db.transaction() as tx:
                            await tx.execute(query)
                else:
                    async with db.transaction() as tx:
                        await tx.execute(query)
            async with db.transaction() as tx:
                expected = [{"id": 42, "label": "Case"}]
                if collation != "NOCASE":
                    expected.append({"id": 43, "label": "case"})
                if collation != "RTRIM":
                    expected.append({"id": 44, "label": "Case "})
                assert_eq(
                    await tx.fetch_all(
                        sqlite.raw("SELECT id,label FROM entries ORDER BY id")
                    ),
                    expected,
                )


@test(mark="medium")
async def old_sqlite_collation_false_completion_refuses_without_converting_valid_identity() -> (
    None
):
    """Real format2 NOCASE/BINARY contradiction refuses load/typed prepare before effects."""
    root = Path(__file__).parent / "fixtures" / "collation-claims"
    invalid = (root / "invalid-old.json").read_text()
    bad = m.Package.model_validate_json(invalid)
    assert_eq(
        bad.digest, "7255b12d6c51cbc8b40c0993591c246bbf2075a04c9af8b7d58f9ba58a5ed718"
    )
    with assert_raises(m.PackageError) as error:
        m.Package.load(invalid)
    assert "construction collation" in str(error.exception)
    valid = (root / "valid-old.json").read_text()
    good = m.Package.load(valid)
    assert_eq(
        good.digest, "08791084aef62cf8dd4b015ccad4b3dce732c495278a74782582ef2c76a66c3f"
    )
    assert_eq(good.dump(), valid)
    with TemporaryDirectory() as directory:
        config = sqlite.Config(database=Path(directory) / "collation.db")
        async with m.connect(config) as target:
            with assert_raises(m.PackageError):
                await target.prepare(bad)
            assert_eq(await target.status(), ())
        async with (
            await sqlite.Database.initialize(config) as db,
            db.transaction() as tx,
        ):
            assert_eq(
                await tx.fetch_all(
                    sqlite.raw("SELECT name FROM sqlite_schema WHERE type='table'")
                ),
                [],
            )
        async with m.connect(config) as target:
            await target.apply(await target.prepare(good))
        async with await sqlite.Database.initialize(config) as db:
            async with db.transaction() as tx:
                await tx.execute(sqlite.raw("INSERT INTO entries(id) VALUES(42)"))
            with assert_raises(ExecutionError):
                async with db.transaction() as tx:
                    await tx.execute(
                        sqlite.raw("INSERT INTO entries(id,label) VALUES(43,'case')")
                    )
            async with db.transaction() as tx:
                assert_eq(
                    await tx.fetch_all(sqlite.raw("SELECT id,label FROM entries")),
                    [{"id": 42, "label": "Case"}],
                )


@test(mark="slow")
async def native_old_late_collation_refusal_moves_before_effects() -> None:
    """Archived native behavior was uncertain committed DDL, not false completion."""
    server = await load_fixture(provide_package_server())
    text = (
        Path(__file__).parent
        / "fixtures"
        / "collation-claims"
        / "native-invalid-old.json"
    ).read_text()
    bad = m.Package.model_validate_json(text)
    with assert_raises(m.PackageError) as error:
        m.Package.load(text)
    assert "construction collation" in str(error.exception)
    async with m.connect(server.config()) as target:
        with assert_raises(m.PackageError):
            await target.prepare(bad, schema_writers_excluded=True)
        assert_eq(await target.status(), ())
    async with (
        await mariadb.Database.initialize(server.config()) as db,
        db.transaction() as tx,
    ):
        assert_eq(await tx.fetch_all(mariadb.raw("SHOW FULL TABLES")), [])


@test(
    [
        Param(value=collation, name=collation)
        for collation in ("utf8mb4_bin", "utf8mb4_general_ci")
    ],
    mark="slow",
)
async def native_matching_explicit_collations_deploy_with_known_case_behavior(
    collation: str,
) -> None:
    """Known native names still need actual availability/catalog/enforcement validation."""
    server = await load_fixture(provide_package_server())
    package = m.Package.load(
        m.compile(
            _draft("mariadb", f"COLLATE {collation}", f"COLLATE {collation.upper()}")
        ).dump()
    )
    async with m.connect(server.config()) as target:
        await target.apply(await target.prepare(package, schema_writers_excluded=True))
    async with await mariadb.Database.initialize(server.config()) as db:
        async with db.transaction() as tx:
            await tx.execute(mariadb.raw("INSERT INTO entries(id) VALUES(42)"))
        if collation == "utf8mb4_general_ci":
            with assert_raises(ExecutionError):
                async with db.transaction() as tx:
                    await tx.execute(
                        mariadb.raw("INSERT INTO entries(id,label) VALUES(43,'case')")
                    )
        else:
            async with db.transaction() as tx:
                await tx.execute(
                    mariadb.raw("INSERT INTO entries(id,label) VALUES(43,'case')")
                )
        async with db.transaction() as tx:
            assert_eq(
                await tx.fetch_all(
                    mariadb.raw("SELECT id,label FROM entries ORDER BY id")
                ),
                [{"id": 42, "label": "Case"}]
                + ([{"id": 43, "label": "case"}] if collation == "utf8mb4_bin" else []),
            )


@test(
    [
        Param(value=pair, name=str(i))
        for i, pair in enumerate(
            (("", "COLLATE utf8mb4_bin"), ("COLLATE utf8mb4_bin", ""))
        )
    ],
    mark="fast",
)
async def native_omission_is_not_assumed_to_match_an_explicit_name(
    pair: tuple[str, str],
) -> None:
    """The server/table default is not an offline certificate for a named collation."""
    with assert_raises(m.PackageError) as error:
        m.compile(_draft("mariadb", *pair))
    assert "construction collation" in str(error.exception)


@test(mark="fast")
async def collation_mentions_in_names_literals_and_expressions_are_not_column_clauses() -> (
    None
):
    """Nested CHECK collations do not manufacture a column's comparison domain."""
    definition = "`COLLATE` TEXT DEFAULT 'COLLATE NOCASE' CHECK (`COLLATE` COLLATE NOCASE <> 'blocked')"
    column = m.ColumnState(
        name="COLLATE",
        definition=definition,
        nullable=True,
        storage="TEXT",
        query_type="str | None",
    )
    table = m.TableState(
        name="entries",
        quoted_name="`entries`",
        columns=(column,),
        sql=f"CREATE TABLE entries ({definition}) STRICT",
    )
    draft = m.Draft(
        revision="001",
        predecessor=None,
        before=m.State(backend="sqlite"),
        target=m.State(backend="sqlite", tables=(table,)),
        operations=(m.CreateTable(table=table),),
    )
    package = m.compile(draft)
    assert_eq(m.Package.load(package.dump()).digest, package.digest)


@test(mark="fast")
async def extra_collated_sql_columns_do_not_create_ownership() -> None:
    """Extra executable comparison domains do not populate recorded columns/indexes."""
    draft = _draft("sqlite", "", "")
    table = draft.target.tables[0]
    table = table.model_copy(
        update={
            "sql": table.sql.replace(
                ") STRICT", ", extra TEXT COLLATE RTRIM NULL) STRICT"
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
    assert_eq(tuple(c.name for c in package.target.tables[0].columns), ("id", "label"))
    assert_eq(package.target.tables[0].indexes, ())


@test(mark="slow")
async def native_live_collation_drift_still_blocks_a_valid_followup() -> None:
    """Constructor binding does not replace independent accepted-catalog drift checks."""
    server = await load_fixture(provide_package_server())
    first = m.compile(_draft("mariadb", "COLLATE utf8mb4_bin", "COLLATE utf8mb4_bin"))
    async with m.connect(server.config()) as target:
        await target.apply(await target.prepare(first, schema_writers_excluded=True))
    await server.run_sql(
        "ALTER TABLE entries MODIFY label VARCHAR(64) CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci NOT NULL DEFAULT 'Case'"
    )
    draft = m.Draft(
        revision="002",
        predecessor=first.digest,
        before=first.target,
        target=first.target,
        operations=(m.Checkpoint(name="same"),),
    )
    package = m.compile(draft)
    async with m.connect(server.config()) as target:
        with assert_raises(m.PackageError) as error:
            await target.prepare(package, schema_writers_excluded=True)
        assert "catalog differs from the last accepted execution" in str(
            error.exception
        )


@test(mark="medium")
async def named_sqlite_collation_retains_trailing_space_unique_behavior() -> None:
    """A decoded COLLATE label is executable syntax, not just a frozen string claim."""
    clause = 'CONSTRAINT "chosen" COLLATE RTRIM'
    package = m.Package.load(m.compile(_draft("sqlite", clause, clause)).dump())
    with TemporaryDirectory() as directory:
        config = sqlite.Config(database=Path(directory) / "named.db")
        async with m.connect(config) as target:
            await target.apply(await target.prepare(package))
        async with await sqlite.Database.initialize(config) as db:
            async with db.transaction() as tx:
                await tx.execute(sqlite.raw("INSERT INTO entries(id) VALUES(42)"))
            with assert_raises(ExecutionError):
                async with db.transaction() as tx:
                    await tx.execute(
                        sqlite.raw("INSERT INTO entries(id,label) VALUES(43,'Case ')")
                    )
            async with db.transaction() as tx:
                assert_eq(
                    await tx.fetch_all(sqlite.raw("SELECT id,label FROM entries")),
                    [{"id": 42, "label": "Case"}],
                )


@test(mark="fast")
async def a_collation_symbol_is_not_named_check_removal_authority() -> None:
    """Constraint-label binding does not manufacture destructive CHECK ownership."""
    clause = 'CONSTRAINT "chosen" COLLATE NOCASE'
    first = m.compile(_draft("sqlite", clause, clause))
    draft = m.Draft(
        revision="002",
        predecessor=first.digest,
        before=first.target,
        target=first.target,
        operations=(m.DropCheck(table_name="entries", check_name="chosen"),),
    )
    with assert_raises(m.PackageError):
        m.compile(draft)
