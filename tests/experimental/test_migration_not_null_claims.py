"""Explicit NOT NULL policy/label binding through public frozen migration seams."""

from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Literal

from snektest import Param, assert_eq, assert_raises, load_fixture, test

from snekql import mariadb, sqlite
from snekql.errors import ExecutionError
from snekql.experimental import migrations as m
from tests.experimental.test_migration_nullability import NativeRequired, Required
from tests.experimental.test_migration_targets import provide_package_server


def _draft(
    backend: Literal["sqlite", "mariadb"], declaration: str, construction: str
) -> m.Draft:
    """Review a required column's explicit clause independently from construction."""
    draft = m.generate(
        "001", [Required] if backend == "sqlite" else [NativeRequired], backend=backend
    )
    table = draft.target.tables[0]
    old = table.columns[1]
    column = old.model_copy(
        update={"definition": old.definition.replace("NOT NULL", declaration)}
    )
    table = table.model_copy(
        update={
            "columns": (table.columns[0], column),
            "sql": table.sql.replace(
                old.definition, old.definition.replace("NOT NULL", construction)
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
async def required_flags_cannot_hide_a_not_null_conflict_policy_change() -> None:
    """IGNORE skips a NULL write; REPLACE can insert the non-NULL default instead."""
    with assert_raises(m.PackageError) as error:
        m.compile(
            _draft(
                "sqlite", "NOT NULL ON CONFLICT IGNORE", "NOT NULL ON CONFLICT REPLACE"
            )
        )
    assert "NOT NULL clause" in str(error.exception)


@test(mark="fast")
async def identical_required_policies_cannot_rename_explicit_not_null_constraints() -> (
    None
):
    """Labels are separate recorded facts, not nullable bits or keyword cosmetics."""
    with assert_raises(m.PackageError) as error:
        m.compile(
            _draft(
                "sqlite", 'CONSTRAINT "chosen" NOT NULL', 'CONSTRAINT "other" NOT NULL'
            )
        )
    assert "NOT NULL clause" in str(error.exception)


@test(mark="fast")
async def named_native_not_null_requires_an_adapter_even_with_matching_bytes() -> None:
    """Canonical native requiredness is supported without guessing named-clause syntax."""
    clause = "UNIQUE CONSTRAINT picked NOT NULL"
    draft = _draft("mariadb", clause, clause)
    table = draft.target.tables[0]
    table = table.model_copy(
        update={
            "columns": tuple(
                c.model_copy(
                    update={"definition": c.definition.replace(" DEFAULT 7", "")}
                )
                for c in table.columns
            ),
            "sql": table.sql.replace(" DEFAULT 7", ""),
        }
    )
    with assert_raises(m.PackageError) as error:
        m.compile(
            draft.model_copy(
                update={
                    "target": draft.target.model_copy(update={"tables": (table,)}),
                    "operations": (m.CreateTable(table=table),),
                }
            )
        )
    assert "NOT NULL clause" in str(error.exception)


@test(
    [
        Param(value=policy, name=policy or "implicit")
        for policy in ("", "ABORT", "FAIL", "ROLLBACK", "IGNORE", "REPLACE")
    ],
    mark="medium",
)
async def sqlite_not_null_policy_keeps_its_null_write_behavior(policy: str) -> None:
    """IGNORE skips a NULL row, REPLACE uses default7, and rejecting policies raise."""
    clause = 'CONSTRAINT "chosen" NOT NULL' + (
        f" ON CONFLICT {policy}" if policy else ""
    )
    package = m.Package.load(m.compile(_draft("sqlite", clause, clause)).dump())
    with TemporaryDirectory() as directory:
        config = sqlite.Config(database=Path(directory) / "required.db")
        async with m.connect(config) as target:
            await target.apply(await target.prepare(package))
        async with await sqlite.Database.initialize(config) as db:
            if policy in {"IGNORE", "REPLACE"}:
                async with db.transaction() as tx:
                    await tx.execute(
                        sqlite.raw("INSERT INTO entries(id,value) VALUES(42,NULL)")
                    )
            else:
                with assert_raises(ExecutionError):
                    async with db.transaction() as tx:
                        await tx.execute(
                            sqlite.raw("INSERT INTO entries(id,value) VALUES(42,NULL)")
                        )
            async with db.transaction() as tx:
                assert_eq(
                    await tx.fetch_all(sqlite.raw("SELECT id,value FROM entries")),
                    [{"id": 42, "value": 7}] if policy == "REPLACE" else [],
                )


@test(
    [
        Param(value=default, name=str(i))
        for i, default in enumerate(("", " DEFAULT NULL"))
    ],
    mark="medium",
)
async def replace_without_a_nonnull_default_rejects_instead_of_inventing_values(
    default: str,
) -> None:
    """REPLACE's behavior composes with the separately frozen default contract."""
    clause = "NOT NULL ON CONFLICT REPLACE"
    draft = _draft("sqlite", clause, clause)
    table = draft.target.tables[0]
    column = table.columns[1].model_copy(
        update={
            "definition": table.columns[1].definition.replace(" DEFAULT 7", default)
        }
    )
    table = table.model_copy(
        update={
            "columns": (table.columns[0], column),
            "sql": table.sql.replace(" DEFAULT 7", default),
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
    with TemporaryDirectory() as directory:
        config = sqlite.Config(database=Path(directory) / "required.db")
        async with m.connect(config) as target:
            await target.apply(await target.prepare(package))
        async with await sqlite.Database.initialize(config) as db:
            with assert_raises(ExecutionError):
                async with db.transaction() as tx:
                    await tx.execute(
                        sqlite.raw("INSERT INTO entries(id,value) VALUES(42,NULL)")
                    )
            async with db.transaction() as tx:
                assert_eq(await tx.fetch_all(sqlite.raw("SELECT id FROM entries")), [])


@test(
    [
        Param(value=pair, name=str(i))
        for i, pair in enumerate(
            (
                ("NOT NULL", 'CONSTRAINT "picked" NOT NULL'),
                ('CONSTRAINT "picked" NOT NULL', "NOT NULL"),
                ('CONSTRAINT "Picked" NOT NULL', 'CONSTRAINT "picked" NOT NULL'),
            )
        )
    ],
    mark="fast",
)
async def explicit_not_null_identity_does_not_fold_or_disappear(
    pair: tuple[str, str],
) -> None:
    """Label presence and spelling bind independently of equivalent requiredness."""
    with assert_raises(m.PackageError) as error:
        m.compile(_draft("sqlite", *pair))
    assert "NOT NULL clause" in str(error.exception)


@test(mark="fast")
async def explicit_abort_and_identifier_quoting_are_known_cosmetics() -> None:
    """Normalize known ABORT omission and quotes, not arbitrary constraint equivalence."""
    package = m.compile(
        _draft(
            "sqlite",
            'CONSTRAINT "chosen" NOT NULL',
            "CONSTRAINT [chosen] not null on conflict abort",
        )
    )
    assert_eq(m.Package.load(package.dump()).digest, package.digest)


@test(
    [Param(value=source, name=source) for source in ("implicit", "explicit")],
    mark="fast",
)
async def key_implied_requiredness_does_not_erase_explicit_not_null_clauses(
    source: str,
) -> None:
    """Equal effective key-nullability flags are not explicit clause/policy agreement."""
    draft = m.generate("001", [Required], backend="sqlite")
    table = draft.target.tables[0]
    old = table.columns[0]
    explicit = old.definition.replace("PRIMARY KEY", "NOT NULL PRIMARY KEY")
    column = old.model_copy(
        update={"definition": explicit if source == "explicit" else old.definition}
    )
    table = table.model_copy(
        update={
            "columns": (column, table.columns[1]),
            "sql": table.sql.replace(
                old.definition, old.definition if source == "explicit" else explicit
            ),
        }
    )
    with assert_raises(m.PackageError) as error:
        m.compile(
            draft.model_copy(
                update={
                    "target": draft.target.model_copy(update={"tables": (table,)}),
                    "operations": (m.CreateTable(table=table),),
                }
            )
        )
    assert "NOT NULL clause" in str(error.exception)


@test(mark="fast")
async def a_following_unique_policy_cannot_mask_a_not_null_policy_mismatch() -> None:
    """A last-ON-CONFLICT scan would miss the NOT NULL change behind equal UNIQUE."""
    with assert_raises(m.PackageError) as error:
        m.compile(
            _draft(
                "sqlite",
                "NOT NULL ON CONFLICT IGNORE UNIQUE ON CONFLICT IGNORE",
                "NOT NULL ON CONFLICT REPLACE UNIQUE ON CONFLICT IGNORE",
            )
        )
    assert "NOT NULL clause" in str(error.exception)


@test(
    [Param(value=scope, name=scope) for scope in ("before", "create", "adopt")],
    mark="fast",
)
async def relinquishment_cannot_hide_not_null_policy_claims(scope: str) -> None:
    """Before/intermediate payload claims survive an empty final owned state."""
    table = _draft(
        "sqlite", "NOT NULL ON CONFLICT IGNORE", "NOT NULL ON CONFLICT REPLACE"
    ).target.tables[0]
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
    assert "NOT NULL clause" in str(error.exception)


@test(
    [
        Param(value=clause, name=str(i))
        for i, clause in enumerate(
            (
                "NOT NULL ON CONFLICT MYSTERY",
                "NOT NULL DESC",
                "CONSTRAINT 'picked' NOT NULL",
            )
        )
    ],
    mark="fast",
)
async def equal_unknown_not_null_clauses_require_adapters(clause: str) -> None:
    """Matching bytes cannot admit unsupported policies, suffixes or name roles."""
    with assert_raises(m.PackageError) as error:
        m.compile(_draft("sqlite", clause, clause))
    assert "NOT NULL clause" in str(error.exception)


@test(mark="slow")
async def native_plain_requiredness_deploys_without_guessing_named_policy_support() -> (
    None
):
    """Known native keyword case normalizes and NOT NULL still rejects NULL writes."""
    server = await load_fixture(provide_package_server())
    package = m.Package.load(
        m.compile(_draft("mariadb", "NOT NULL", "not null")).dump()
    )
    async with m.connect(server.config()) as target:
        await target.apply(await target.prepare(package, schema_writers_excluded=True))
    async with await mariadb.Database.initialize(server.config()) as db:
        async with db.transaction() as tx:
            await tx.execute(mariadb.raw("SET SESSION sql_mode='STRICT_ALL_TABLES'"))
            await tx.execute(mariadb.raw("INSERT INTO entries(id) VALUES(42)"))
        with assert_raises(ExecutionError):
            async with db.transaction() as tx:
                await tx.execute(
                    mariadb.raw("INSERT INTO entries(id,value) VALUES(43,NULL)")
                )
        async with db.transaction() as tx:
            assert_eq(
                await tx.fetch_all(mariadb.raw("SELECT id,value FROM entries")),
                [{"id": 42, "value": 7}],
            )


@test(mark="medium")
async def old_policy_contradiction_refuses_without_rewriting_a_valid_ignore_identity() -> (
    None
):
    """A real format2 false completion refuses load/typed prepare before schema/history."""
    root = Path(__file__).parent / "fixtures" / "not-null-policy"
    invalid = (root / "invalid-old.json").read_text()
    old = m.Package.model_validate_json(invalid)
    assert_eq(
        old.digest, "3c730b701101b3a2c04cdad4994f880c3b289740749d68e168a4624c90805ee2"
    )
    with assert_raises(m.PackageError) as error:
        m.Package.load(invalid)
    assert "NOT NULL clause" in str(error.exception)
    valid = (root / "valid-old.json").read_text()
    good = m.Package.load(valid)
    assert_eq(
        good.digest, "d57c16bdec96277408d7c4db89a91e4cc618c73ebdd9e8dd6fd9919eb4047049"
    )
    assert_eq(good.dump(), valid)
    with TemporaryDirectory() as directory:
        config = sqlite.Config(database=Path(directory) / "required.db")
        async with m.connect(config) as target:
            with assert_raises(m.PackageError) as error:
                await target.prepare(old)
            assert "NOT NULL clause" in str(error.exception)
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
        async with (
            await sqlite.Database.initialize(config) as db,
            db.transaction() as tx,
        ):
            await tx.execute(
                sqlite.raw("INSERT INTO entries(id,value) VALUES(42,NULL)")
            )
            assert_eq(
                await tx.fetch_all(sqlite.raw("SELECT id,value FROM entries")), []
            )


@test(
    [
        Param[Literal["sqlite", "mariadb"]](value="sqlite", name="sqlite"),
        Param[Literal["sqlite", "mariadb"]](value="mariadb", name="mariadb"),
    ],
    mark="fast",
)
async def literal_identifier_and_nested_not_null_mentions_are_not_clauses(
    backend: Literal["sqlite", "mariadb"],
) -> None:
    """Keyword-looking text/defaults/CHECK expressions do not manufacture NOT NULL."""
    definition = (
        "`not null` "
        + ("TEXT" if backend == "sqlite" else "VARCHAR(128)")
        + " DEFAULT 'NOT NULL ON CONFLICT REPLACE' CHECK (`not null` IS NOT NULL)"
    )
    column = m.ColumnState(
        name="not null",
        definition=definition,
        nullable=True,
        storage="TEXT",
        query_type="str | None",
    )
    table = m.TableState(
        name="entries",
        quoted_name="`entries`",
        columns=(column,),
        sql=f"CREATE TABLE entries ({definition})"
        + (" STRICT" if backend == "sqlite" else " ENGINE=InnoDB"),
    )
    draft = m.Draft(
        revision="001",
        predecessor=None,
        before=m.State(backend=backend),
        target=m.State(backend=backend, tables=(table,)),
        operations=(m.CreateTable(table=table),),
    )
    package = m.compile(draft)
    assert_eq(m.Package.load(package.dump()).digest, package.digest)


@test([Param(value=kind, name=kind) for kind in ("add", "default")], mark="fast")
async def standalone_not_null_language_cannot_hide_after_handoff(kind: str) -> None:
    """Unsupported explicit clauses are admitted independently of final ownership."""
    first = m.compile(_draft("sqlite", "NOT NULL", "NOT NULL"))
    if kind == "add":
        column = m.ColumnState(
            name="extra",
            definition='"extra" INTEGER NOT NULL ON CONFLICT MYSTERY',
            nullable=False,
            storage="INTEGER",
            query_type=None,
        )
        operation = m.AddColumn(table_name="entries", column=column)
    else:
        column = (
            first.target.tables[0]
            .columns[1]
            .model_copy(
                update={
                    "definition": '"value" INTEGER NOT NULL ON CONFLICT MYSTERY DEFAULT 8'
                }
            )
        )
        operation = m.ChangeDefault(table_name="entries", column=column)
    draft = m.Draft(
        revision="002",
        predecessor=first.digest,
        before=first.target,
        target=m.State(backend="sqlite"),
        operations=(operation, m.RelinquishTable(table_name="entries")),
    )
    with assert_raises(m.PackageError) as error:
        m.compile(draft)
    assert "NOT NULL clause" in str(error.exception)


@test(mark="fast")
async def extra_required_columns_do_not_manufacture_column_authority() -> None:
    """Extra executable NOT NULL declarations do not populate the recorded column set."""
    draft = _draft("sqlite", "NOT NULL", "NOT NULL")
    table = draft.target.tables[0]
    table = table.model_copy(
        update={
            "sql": table.sql.replace(
                ") STRICT", ', "extra" INTEGER NOT NULL DEFAULT 9) STRICT'
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


@test(mark="fast")
async def naming_requiredness_does_not_authorize_check_removal() -> None:
    """A NOT NULL label does not become a recorded named table CHECK authority."""
    clause = 'CONSTRAINT "required" NOT NULL'
    first = m.compile(_draft("sqlite", clause, clause))
    draft = m.Draft(
        revision="002",
        predecessor=first.digest,
        before=first.target,
        target=first.target,
        operations=(m.DropCheck(table_name="entries", check_name="required"),),
    )
    with assert_raises(m.PackageError):
        m.compile(draft)
