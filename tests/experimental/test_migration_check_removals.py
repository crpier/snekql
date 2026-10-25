"""Explicit named CHECK removal through frozen packages and public target routes."""

import json
from pathlib import Path
from sqlite3 import IntegrityError
from tempfile import TemporaryDirectory
from typing import ClassVar

import aiosqlite
from pymysql.err import OperationalError
from snektest import Param, assert_eq, assert_raises, load_fixture, test

from snekql import mariadb, sqlite
from snekql.experimental import migrations as m
from tests.experimental.test_migration_check_additions import (
    Checked,
    NativeChecked,
    NativeRequired,
    Required,
)
from tests.experimental.test_migration_nullability import Optional
from tests.experimental.test_migration_targets import provide_package_server


@test(mark="medium")
async def explicit_sqlite_check_removal_preserves_rows_and_allows_negative_values() -> (
    None
):
    """Dropping a managed rule requires explicit authority, not a model omission."""
    first = m.compile(m.generate("001", [Checked], backend="sqlite"))
    draft = m.generate("002", [Required], backend="sqlite", previous=first)
    assert draft.unresolved
    with assert_raises(m.PackageError):
        m.compile(draft)
    second = m.Package.load(
        m.compile(
            draft.resolve(
                m.DropCheck(table_name="entries", check_name="ck_nonnegative")
            )
        ).dump()
    )
    assert_eq(second.version, 8)
    with TemporaryDirectory() as directory:
        config = sqlite.Config(database=Path(directory) / "checks.db")
        async with m.connect(config) as target:
            await target.apply(await target.prepare(first))
        async with (
            await sqlite.Database.initialize(config) as db,
            db.transaction() as tx,
        ):
            await tx.execute(sqlite.raw("INSERT INTO entries VALUES(1,42)"))
        async with m.connect(config) as target:
            await target.apply(await target.prepare(second))
            assert_eq(
                await target.apply(await target.prepare(second)), "already_applied"
            )
        async with (
            await sqlite.Database.initialize(config) as db,
            db.transaction() as tx,
        ):
            await tx.execute(sqlite.raw("INSERT INTO entries VALUES(2,-1)"))
            await tx.execute(sqlite.raw("INSERT INTO entries(id) VALUES(3)"))
            assert_eq(
                await tx.fetch_all(sqlite.raw("SELECT value FROM entries ORDER BY id")),
                [{"value": 42}, {"value": -1}, {"value": 7}],
            )


@test(mark="slow")
async def explicit_native_check_removal_preserves_rows_and_default() -> None:
    """Native removal drops the named CHECK, not rows or the default."""
    server = await load_fixture(provide_package_server())
    first = m.compile(m.generate("001", [NativeChecked], backend="mariadb"))
    second = m.Package.load(
        m.compile(
            m.generate(
                "002", [NativeRequired], backend="mariadb", previous=first
            ).resolve(m.DropCheck(table_name="entries", check_name="ck_nonnegative"))
        ).dump()
    )
    async with m.connect(server.config()) as target:
        await target.apply(await target.prepare(first, schema_writers_excluded=True))
    await server.run_sql("INSERT INTO entries VALUES(1,42)")
    async with m.connect(server.config()) as target:
        await target.apply(await target.prepare(second, schema_writers_excluded=True))
        assert_eq(
            await target.apply(
                await target.prepare(second, schema_writers_excluded=True)
            ),
            "already_applied",
        )
    async with (
        await mariadb.Database.initialize(server.config()) as db,
        db.transaction() as tx,
    ):
        await tx.execute(mariadb.raw("INSERT INTO entries VALUES(2,-1)"))
        await tx.execute(mariadb.raw("INSERT INTO entries(id) VALUES(3)"))
        assert_eq(
            await tx.fetch_all(mariadb.raw("SELECT value FROM entries ORDER BY id")),
            [{"value": 42}, {"value": -1}, {"value": 7}],
        )


@test(mark="fast")
def check_removal_authority_is_exact_and_cannot_broaden_old_formats() -> None:
    """Only a uniquely named recorded table CHECK is removable; old vocabulary is closed."""
    first = m.compile(m.generate("001", [Checked], backend="sqlite"))
    draft = m.generate("002", [Required], backend="sqlite", previous=first)
    for name in ("absent", "CK_NONNEGATIVE", "PRIMARY"):
        with assert_raises(m.PackageError):
            draft.resolve(m.DropCheck(table_name="entries", check_name=name))
        with assert_raises(m.PackageError):
            m.compile(
                draft.model_copy(
                    update={
                        "unresolved": (),
                        "operations": (
                            m.DropCheck(table_name="entries", check_name=name),
                        ),
                    }
                )
            )
    package = m.compile(
        draft.resolve(m.DropCheck(table_name="entries", check_name="ck_nonnegative"))
    )
    for version in range(2, 8):
        data = json.loads(package.dump())
        data["version"] = version
        with assert_raises(m.PackageError) as error:
            m.Package.load(json.dumps(data))
        assert "require execution package version 8" in str(error.exception)
    legacy = m.compile(
        m.generate(
            "002",
            [Checked],
            backend="sqlite",
            previous=m.compile(m.generate("001", [Required], backend="sqlite")),
        )
    )
    data = json.loads(legacy.dump())
    data["contractions"][0]["removed_checks"] = []
    with assert_raises(m.PackageError) as error:
        m.Package.load(json.dumps(data))
    assert "require execution package version 8" in str(error.exception)
    table = first.target.tables[0]
    inline = table.model_copy(
        update={
            "sql": 'CREATE TABLE "entries" ("id" INTEGER PRIMARY KEY, "value" INTEGER NOT NULL DEFAULT 7 CONSTRAINT "ck_nonnegative" CHECK ("value" >= 0)) STRICT'
        }
    )
    for source in (
        inline,
        table.model_copy(
            update={
                "sql": table.sql.replace(
                    ") STRICT",
                    ', CONSTRAINT "CK_NONNEGATIVE" CHECK ("value" <= 100)) STRICT',
                )
            }
        ),
    ):
        invalid = draft.model_copy(
            update={
                "before": m.State(backend="sqlite", tables=(source,)),
                "unresolved": (),
                "operations": (
                    m.DropCheck(table_name="entries", check_name="ck_nonnegative"),
                ),
            }
        )
        with assert_raises(m.PackageError) as error:
            m.compile(invalid)
        assert "exactly one explicitly managed named table CHECK" in str(
            error.exception
        )


class Smaller[S = sqlite.Pending](sqlite.Model[S]):
    """A bounded same-name replacement."""

    __tablename__ = "entries"
    __row_type__: ClassVar[sqlite.ReadType[Smaller[sqlite.Row]]]
    id: sqlite.Col[int] = sqlite.Integer(primary_key=True)
    value: sqlite.GenCol[int] = sqlite.Integer(default=sqlite.LiteralDefault(7))

    @classmethod
    def __checks__(cls) -> list[sqlite.CheckConstraint[Smaller[S]]]:
        return [sqlite.CheckConstraint(cls.value.lt(10), name="ck_nonnegative")]


class NativeSmaller[S = mariadb.Pending](mariadb.Model[S]):
    """The native replacement retains its non-atomic DROP/ADD boundary."""

    __tablename__ = "entries"
    __row_type__: ClassVar[mariadb.ReadType[NativeSmaller[mariadb.Row]]]
    id: mariadb.Col[int] = mariadb.Integer(primary_key=True)
    value: mariadb.GenCol[int] = mariadb.Integer(default=mariadb.LiteralDefault(7))

    @classmethod
    def __checks__(cls) -> list[mariadb.CheckConstraint[NativeSmaller[S]]]:
        return [mariadb.CheckConstraint(cls.value.lt(10), name="ck_nonnegative")]


@test(mark="medium")
async def sqlite_check_replacement_is_atomic_and_preserves_unmanaged_objects() -> None:
    """Failed replacement keeps the old rule; corrected retry preserves unrelated data/DDL."""
    first = m.compile(m.generate("001", [Checked], backend="sqlite"))
    second = m.Package.load(
        m.compile(
            m.generate("002", [Smaller], backend="sqlite", previous=first).resolve(
                m.DropCheck(table_name="entries", check_name="ck_nonnegative")
            )
        ).dump()
    )
    with TemporaryDirectory() as directory:
        config = sqlite.Config(database=Path(directory) / "replace.db")
        async with m.connect(config) as target:
            await target.apply(await target.prepare(first))
        async with aiosqlite.connect(str(config.database)) as app:
            for sql in (
                "ALTER TABLE entries ADD COLUMN payload BLOB DEFAULT X'00FF'",
                "CREATE INDEX external_payload ON entries(payload)",
                "CREATE TABLE audit(value INTEGER)",
                "CREATE TRIGGER audit_insert AFTER INSERT ON entries BEGIN INSERT INTO audit VALUES(new.value); END",
                "CREATE VIEW visible_entries AS SELECT id,value,payload FROM entries",
                "INSERT INTO entries VALUES(1,42,X'AB')",
            ):
                await app.execute(sql)
            await app.commit()
        async with m.connect(config) as target:
            plan = await target.prepare(second, preserve_unmanaged=True)
            with assert_raises(IntegrityError):
                await target.apply(plan)
            assert_eq(len(await target.status()), 1)
        async with await sqlite.Database.initialize(config) as db:
            with assert_raises(sqlite.ExecutionError):
                async with db.transaction() as tx:
                    await tx.execute(
                        sqlite.raw("INSERT INTO entries(id,value) VALUES(2,-1)")
                    )
            async with db.transaction() as tx:
                assert_eq(
                    await tx.fetch_all(sqlite.raw("SELECT * FROM visible_entries")),
                    [{"id": 1, "value": 42, "payload": bytes.fromhex("ab")}],
                )
                await tx.execute(sqlite.raw("UPDATE entries SET value=5"))
        async with m.connect(config) as target:
            await target.apply(plan)
        async with await sqlite.Database.initialize(config) as db:
            async with db.transaction() as tx:
                assert_eq(
                    await tx.fetch_all(sqlite.raw("SELECT * FROM visible_entries")),
                    [{"id": 1, "value": 5, "payload": bytes.fromhex("ab")}],
                )
                assert_eq(
                    await tx.fetch_all(sqlite.raw("SELECT * FROM audit")),
                    [{"value": 42}],
                )
                assert_eq(
                    await tx.fetch_all(
                        sqlite.raw(
                            "SELECT name FROM sqlite_schema WHERE type='index' AND tbl_name='entries'"
                        )
                    ),
                    [{"name": "external_payload"}],
                )
                await tx.execute(
                    sqlite.raw("INSERT INTO entries(id,value) VALUES(2,-1)")
                )
                await tx.execute(sqlite.raw("INSERT INTO entries(id) VALUES(3)"))
                assert_eq(
                    await tx.fetch_all(
                        sqlite.raw("SELECT payload FROM entries WHERE id=3")
                    ),
                    [{"payload": bytes.fromhex("00ff")}],
                )
            with assert_raises(sqlite.ExecutionError):
                async with db.transaction() as tx:
                    await tx.execute(
                        sqlite.raw("INSERT INTO entries(id,value) VALUES(4,10)")
                    )


@test(mark="slow")
async def native_check_replacement_failure_leaves_a_gap_and_retries_only_add() -> None:
    """Native DROP is durable even when the replacement rejects existing data."""
    server = await load_fixture(provide_package_server())
    first = m.compile(m.generate("001", [NativeChecked], backend="mariadb"))
    second = m.Package.load(
        m.compile(
            m.generate(
                "002", [NativeSmaller], backend="mariadb", previous=first
            ).resolve(m.DropCheck(table_name="entries", check_name="ck_nonnegative"))
        ).dump()
    )
    async with m.connect(server.config()) as target:
        await target.apply(await target.prepare(first, schema_writers_excluded=True))
    await server.run_sql("INSERT INTO entries VALUES(1,42)")
    async with m.connect(server.config()) as target:
        plan = await target.prepare(second, schema_writers_excluded=True)
        with assert_raises(OperationalError):
            await target.apply(plan)
        recovery = await target.inspect_recovery(plan, schema_writers_excluded=True)
        assert_eq(recovery.disposition, "retry_remaining")
        assert_eq(recovery.acknowledged_steps, 1)
    await server.run_sql(
        "INSERT INTO entries VALUES(2,-1); UPDATE entries SET value=5 WHERE id=1"
    )
    async with m.connect(server.config()) as target:
        recovery = await target.inspect_recovery(plan, schema_writers_excluded=True)
        await target.resume(recovery, schema_writers_excluded=True)
    async with await mariadb.Database.initialize(server.config()) as db:
        async with db.transaction() as tx:
            await tx.execute(mariadb.raw("INSERT INTO entries(id) VALUES(3)"))
            assert_eq(
                await tx.fetch_all(
                    mariadb.raw("SELECT value FROM entries ORDER BY id")
                ),
                [{"value": 5}, {"value": -1}, {"value": 7}],
            )
        with assert_raises(mariadb.ExecutionError):
            async with db.transaction() as tx:
                await tx.execute(mariadb.raw("INSERT INTO entries VALUES(4,10)"))


@test(mark="slow")
async def lost_native_check_drop_receipt_cannot_infer_completion_or_replay() -> None:
    """Physical absence is not an acknowledgement or structural-reconciliation proof."""
    server = await load_fixture(provide_package_server())
    first = m.compile(m.generate("001", [NativeChecked], backend="mariadb"))
    second = m.compile(
        m.generate("002", [NativeRequired], backend="mariadb", previous=first).resolve(
            m.DropCheck(table_name="entries", check_name="ck_nonnegative")
        )
    )
    async with m.connect(server.config()) as target:
        await target.apply(await target.prepare(first, schema_writers_excluded=True))
    await server.run_sql(
        "CREATE TRIGGER fail_receipt BEFORE UPDATE ON snekql_experimental_migrations FOR EACH ROW SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='receipt unavailable'"
    )
    async with m.connect(server.config()) as target:
        plan = await target.prepare(second, schema_writers_excluded=True)
        with assert_raises(OperationalError):
            await target.apply(plan)
    await server.run_sql("DROP TRIGGER fail_receipt; INSERT INTO entries VALUES(1,-1)")
    async with m.connect(server.config()) as target:
        recovery = await target.inspect_recovery(plan, schema_writers_excluded=True)
        assert_eq(recovery.disposition, "ambiguous")
        assert_eq(recovery.acknowledged_steps, 0)
        with assert_raises(m.PackageError):
            await target.resume(recovery, schema_writers_excluded=True)
        with assert_raises(m.PackageError):
            await target.reconcile(
                recovery, reason="CHECK absent", schema_writers_excluded=True
            )


@test(mark="medium")
async def check_removal_then_relaxation_does_not_resurrect_the_rule() -> None:
    """Dependent rebuilds retain other physical constraints, not the explicitly dropped one."""
    first = m.compile(m.generate("001", [Checked], backend="sqlite"))
    second = m.compile(
        m.generate("002", [Optional], backend="sqlite", previous=first).resolve(
            m.DropCheck(table_name="entries", check_name="ck_nonnegative")
        )
    )
    with TemporaryDirectory() as directory:
        config = sqlite.Config(database=Path(directory) / "relax.db")
        async with m.connect(config) as target:
            await target.apply(await target.prepare(first))
        async with aiosqlite.connect(str(config.database)) as app:
            await app.execute("DROP TABLE entries")
            await app.execute(
                first.target.tables[0].sql.replace(
                    ") STRICT", ', CONSTRAINT "legacy_id" CHECK ("id" > 0)) STRICT'
                )
            )
            await app.execute("INSERT INTO entries VALUES(1,42)")
            await app.commit()
        async with m.connect(config) as target:
            await target.apply(await target.prepare(second, preserve_unmanaged=True))
        async with await sqlite.Database.initialize(config) as db:
            async with db.transaction() as tx:
                await tx.execute(
                    sqlite.raw("INSERT INTO entries VALUES(2,-1),(3,NULL)")
                )
                assert_eq(
                    await tx.fetch_all(
                        sqlite.raw("SELECT value FROM entries ORDER BY id")
                    ),
                    [{"value": 42}, {"value": -1}, {"value": None}],
                )
            with assert_raises(sqlite.ExecutionError):
                async with db.transaction() as tx:
                    await tx.execute(sqlite.raw("INSERT INTO entries VALUES(-1,7)"))


@test(mark="medium")
async def sqlite_check_removal_survives_relinquishment_and_readoption() -> None:
    """Negative ownership effects remain provable after releasing the table."""
    first = m.compile(m.generate("001", [Checked], backend="sqlite"))
    draft = m.generate("002", [], backend="sqlite", previous=first).resolve(
        m.RelinquishTable(table_name="entries")
    )
    second = m.compile(
        draft.model_copy(
            update={
                "operations": (
                    m.DropCheck(table_name="entries", check_name="ck_nonnegative"),
                    *draft.operations,
                )
            }
        )
    )
    third = m.compile(
        m.generate("003", [Required], backend="sqlite", previous=second).adopt(
            "entries"
        )
    )
    with TemporaryDirectory() as directory:
        config = sqlite.Config(database=Path(directory) / "adopt.db")
        async with m.connect(config) as target:
            await target.apply(await target.prepare(first))
            await target.apply(await target.prepare(second))
        async with (
            await sqlite.Database.initialize(config) as db,
            db.transaction() as tx,
        ):
            await tx.execute(sqlite.raw("INSERT INTO entries VALUES(1,-1)"))
        async with m.connect(config) as target:
            await target.apply(await target.prepare(third))
            assert_eq(len(await target.status()), 3)
        async with (
            await sqlite.Database.initialize(config) as db,
            db.transaction() as tx,
        ):
            assert_eq(
                await tx.fetch_all(sqlite.raw("SELECT value FROM entries")),
                [{"value": -1}],
            )


@test(mark="slow")
async def native_check_removal_can_relinquish_without_losing_negative_proof() -> None:
    """Successful removal/relinquishment leaves the physical table and permits old-invalid data."""
    server = await load_fixture(provide_package_server())
    first = m.compile(m.generate("001", [NativeChecked], backend="mariadb"))
    draft = m.generate("002", [], backend="mariadb", previous=first).resolve(
        m.RelinquishTable(table_name="entries")
    )
    second = m.compile(
        draft.model_copy(
            update={
                "operations": (
                    m.DropCheck(table_name="entries", check_name="ck_nonnegative"),
                    *draft.operations,
                )
            }
        )
    )
    async with m.connect(server.config()) as target:
        await target.apply(await target.prepare(first, schema_writers_excluded=True))
        await target.apply(await target.prepare(second, schema_writers_excluded=True))
    async with (
        await mariadb.Database.initialize(server.config()) as db,
        db.transaction() as tx,
    ):
        await tx.execute(mariadb.raw("INSERT INTO entries VALUES(1,-1)"))
        assert_eq(
            await tx.fetch_all(mariadb.raw("SELECT value FROM entries")),
            [{"value": -1}],
        )


class NativeTextChecked[S = mariadb.Pending](mariadb.Model[S]):
    """Catalog strings must be parsed using the observed native SQL mode."""

    __tablename__ = "entries"
    __row_type__: ClassVar[mariadb.ReadType[NativeTextChecked[mariadb.Row]]]
    id: mariadb.Col[int] = mariadb.Integer(primary_key=True)
    value: mariadb.GenCol[str] = mariadb.Text(default=mariadb.LiteralDefault("a\\"))

    @classmethod
    def __checks__(cls) -> list[mariadb.CheckConstraint[NativeTextChecked[S]]]:
        return [mariadb.CheckConstraint(cls.value.ne("forbidden"), name="ck_allowed")]


@test(mark="slow")
async def native_check_removal_preserves_encoded_defaults_in_no_backslash_mode() -> (
    None
):
    """Generated encoded defaults survive removal without changing the native SQL mode."""
    server = await load_fixture(provide_package_server())
    async with (
        await mariadb.Database.initialize(server.config()) as db,
        db.transaction() as tx,
    ):
        saved = (await tx.fetch_all(mariadb.raw("SELECT @@GLOBAL.sql_mode AS mode")))[
            0
        ]["mode"]
    await server.run_sql("SET GLOBAL sql_mode='NO_BACKSLASH_ESCAPES'")
    try:
        first = m.compile(m.generate("001", [NativeTextChecked], backend="mariadb"))
        draft = m.generate("002", [], backend="mariadb", previous=first).resolve(
            m.RelinquishTable(table_name="entries")
        )
        second = m.compile(
            draft.model_copy(
                update={
                    "operations": (
                        m.DropCheck(table_name="entries", check_name="ck_allowed"),
                        *draft.operations,
                    )
                }
            )
        )
        async with m.connect(server.config()) as target:
            await target.apply(
                await target.prepare(first, schema_writers_excluded=True)
            )
            await target.apply(
                await target.prepare(second, schema_writers_excluded=True)
            )
        async with (
            await mariadb.Database.initialize(server.config()) as db,
            db.transaction() as tx,
        ):
            await tx.execute(mariadb.raw("INSERT INTO entries(id) VALUES(1)"))
            assert_eq(
                await tx.fetch_all(mariadb.raw("SELECT value FROM entries")),
                [{"value": "a\\"}],
            )
    finally:
        await server.run_sql(f"SET GLOBAL sql_mode='{saved}'")


@test(
    [
        Param(value="existing", name="existing"),
        Param(value="intermediate", name="intermediate"),
    ],
    mark="slow",
)
async def native_check_removal_refuses_a_foreign_key_name_collision_before_effects(
    case: str,
) -> None:
    """DROP CONSTRAINT must not resolve an implicit FK instead of the authorized CHECK."""
    server = await load_fixture(provide_package_server())
    await server.run_sql(
        "CREATE TABLE parent(id BIGINT PRIMARY KEY) ENGINE=InnoDB; CREATE TABLE entries(id BIGINT PRIMARY KEY,value BIGINT,FOREIGN KEY(value) REFERENCES parent(id)) ENGINE=InnoDB"
    )
    async with (
        await mariadb.Database.initialize(server.config()) as db,
        db.transaction() as tx,
    ):
        name = (
            await tx.fetch_all(
                mariadb.raw(
                    "SELECT CONSTRAINT_NAME AS name FROM information_schema.TABLE_CONSTRAINTS WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='entries' AND CONSTRAINT_TYPE='FOREIGN KEY'"
                )
            )
        )[0]["name"]
    assert isinstance(name, str)
    await server.run_sql("DROP TABLE entries; DROP TABLE parent")
    base = m.generate("001", [NativeChecked], backend="mariadb")
    plain = m.generate("001", [NativeRequired], backend="mariadb").target.tables[0]
    parent = plain.model_copy(
        update={
            "name": "parent",
            "quoted_name": "`parent`",
            "sql": plain.sql.replace("`entries`", "`parent`"),
        }
    )
    child = base.target.tables[0].model_copy(
        update={
            "sql": base.target.tables[0].sql.replace(
                "CONSTRAINT `ck_nonnegative`",
                "FOREIGN KEY (`value`) REFERENCES `parent` (`id`), CONSTRAINT `"
                + name.replace("`", "``")
                + "`",
            )
        }
    )
    desired = plain.model_copy(
        update={
            "sql": plain.sql.replace(
                ") ENGINE=InnoDB",
                ", FOREIGN KEY (`value`) REFERENCES `parent` (`id`)) ENGINE=InnoDB",
            )
        }
    )
    first = m.compile(
        base.model_copy(
            update={
                "target": m.State(backend="mariadb", tables=(parent, child)),
                "operations": (m.CreateTable(table=parent), m.CreateTable(table=child)),
            }
        )
    )
    second = m.compile(
        m.Draft(
            revision="002",
            predecessor=first.digest,
            before=first.target,
            target=m.State(backend="mariadb", tables=(parent, desired)),
            operations=(m.DropCheck(table_name="entries", check_name=name),),
        )
    )
    async with m.connect(server.config()) as target:
        if case == "intermediate":
            combined = m.compile(
                first.draft.model_copy(
                    update={
                        "target": second.target,
                        "operations": (
                            *first.draft.operations,
                            *second.draft.operations,
                        ),
                    }
                )
            )
            plan = await target.prepare(combined, schema_writers_excluded=True)
            with assert_raises(m.PackageError) as error:
                await target.apply(plan)
            assert "unambiguous native CHECK" in str(error.exception)
            progress = await target.status()
            assert_eq(progress[0].acknowledged_steps, 2)
            assert_eq(progress[0].phase, "uncertain")
            with assert_raises(m.PackageError) as error:
                await target.inspect_recovery(plan, schema_writers_excluded=True)
            assert "unambiguous native CHECK" in str(error.exception)
        else:
            await target.apply(
                await target.prepare(first, schema_writers_excluded=True)
            )
            with assert_raises(m.PackageError) as error:
                await target.prepare(second, schema_writers_excluded=True)
            assert "unambiguous native CHECK" in str(error.exception)
            assert_eq(len(await target.status()), 1)
    await server.run_sql("INSERT INTO parent(id) VALUES(-1),(7)")
    async with await mariadb.Database.initialize(server.config()) as db:
        for value in (-1, 999):
            with assert_raises(mariadb.ExecutionError):
                async with db.transaction() as tx:
                    await tx.execute(
                        mariadb.raw("INSERT INTO entries VALUES(1,%s)", params=(value,))
                    )
