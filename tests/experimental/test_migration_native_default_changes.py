"""Native default transitions through frozen deployment and application writes."""

import asyncio
import json
import sys
from typing import ClassVar

from pymysql.err import IntegrityError, OperationalError
from snektest import assert_eq, assert_raises, load_fixture, test

from snekql import mariadb
from snekql.errors import ExecutionError
from snekql.experimental import migrations as m
from snekql.mariadb import UtcDatetime
from tests.experimental.test_migration_targets import provide_package_server


class Original[S = mariadb.Pending](mariadb.Model[S]):
    """Nullable value with no declared default."""

    __tablename__ = "settings"
    __row_type__: ClassVar[mariadb.ReadType[Original[mariadb.Row]]]
    id: mariadb.Col[int] = mariadb.Integer(primary_key=True)
    value: mariadb.Col[int | None] = mariadb.Integer(nullable=True)


class Seven[S = mariadb.Pending](mariadb.Model[S]):
    """Set a future-insert default without backfilling existing NULLs."""

    __tablename__ = "settings"
    __row_type__: ClassVar[mariadb.ReadType[Seven[mariadb.Row]]]
    id: mariadb.Col[int] = mariadb.Integer(primary_key=True)
    value: mariadb.GenCol[int | None] = mariadb.Integer(
        nullable=True, default=mariadb.LiteralDefault(7)
    )


class Eight[S = mariadb.Pending](mariadb.Model[S]):
    """Replace the default without changing old values."""

    __tablename__ = "settings"
    __row_type__: ClassVar[mariadb.ReadType[Eight[mariadb.Row]]]
    id: mariadb.Col[int] = mariadb.Integer(primary_key=True)
    value: mariadb.GenCol[int | None] = mariadb.Integer(
        nullable=True, default=mariadb.LiteralDefault(8)
    )


@test(mark="slow")
async def native_set_change_remove_defaults_preserve_existing_values() -> None:
    """Frozen packages change future omission, not existing rows or explicit NULLs."""
    server = await load_fixture(provide_package_server())
    previous = None
    for number, model in enumerate((Original, Seven, Eight, Original), 1):
        draft = m.generate(str(number), [model], backend="mariadb", previous=previous)
        assert_eq(draft.unresolved, ())
        package = m.Package.load(m.compile(draft).dump())
        async with m.connect(server.config()) as target:
            plan = await target.prepare(package, schema_writers_excluded=True)
            assert_eq(await target.apply(plan), "applied")
            assert_eq(await target.apply(plan), "already_applied")
        async with (
            await mariadb.Database.initialize(server.config()) as database,
            database.transaction() as transaction,
        ):
            await transaction.execute(
                mariadb.raw("INSERT INTO settings(id) VALUES (%s)", params=(number,))
            )
        previous = package
    async with (
        await mariadb.Database.initialize(server.config()) as database,
        database.transaction() as transaction,
    ):
        await transaction.execute(mariadb.raw("INSERT INTO settings VALUES (5,NULL)"))
        assert_eq(
            await transaction.fetch_all(
                mariadb.raw("SELECT value FROM settings ORDER BY id")
            ),
            [
                {"value": None},
                {"value": 7},
                {"value": 8},
                {"value": None},
                {"value": None},
            ],
        )


class Required[S = mariadb.Pending](mariadb.Model[S]):
    """Require an existing value and remove its old default."""

    __tablename__ = "settings"
    __row_type__: ClassVar[mariadb.ReadType[Required[mariadb.Row]]]
    id: mariadb.Col[int] = mariadb.Integer(primary_key=True)
    value: mariadb.Col[int] = mariadb.Integer()


@test(mark="slow")
async def native_required_default_removal_requires_explicit_null_correction() -> None:
    """Default removal is not a backfill; requirement checks run before native ALTER."""
    server = await load_fixture(provide_package_server())
    first = m.compile(m.generate("001", [Seven], backend="mariadb"))
    second = m.Package.load(
        m.compile(
            m.generate("002", [Required], backend="mariadb", previous=first)
        ).dump()
    )
    async with m.connect(server.config()) as target:
        await target.apply(await target.prepare(first, schema_writers_excluded=True))
    await server.run_sql("INSERT INTO settings VALUES (1,NULL),(2,42)")
    async with m.connect(server.config()) as target:
        plan = await target.prepare(second, schema_writers_excluded=True)
        with assert_raises(m.PackageError) as error:
            await target.apply(plan)
        assert "NULL rows remain" in str(error.exception)
        assert_eq(len(await target.status()), 1)
    await server.run_sql("UPDATE settings SET value=5 WHERE value IS NULL")
    async with m.connect(server.config()) as target:
        assert_eq(await target.apply(plan), "applied")
    async with (
        await mariadb.Database.initialize(server.config()) as database,
        database.transaction() as transaction,
    ):
        assert_eq(
            await transaction.fetch_all(
                mariadb.raw("SELECT value FROM settings ORDER BY id")
            ),
            [{"value": 5}, {"value": 42}],
        )

    async with await mariadb.Database.initialize(server.config()) as database:
        with assert_raises(ExecutionError):
            async with database.transaction() as transaction:
                await transaction.execute(
                    mariadb.raw("SET SESSION sql_mode='STRICT_ALL_TABLES'")
                )
                await transaction.execute(
                    mariadb.raw("INSERT INTO settings(id) VALUES (3)")
                )


@test(mark="slow")
async def native_default_recovery_does_not_replay_acknowledged_data() -> None:
    """A failed later UPDATE preserves the ALTER and resumes only unacknowledged work."""
    server = await load_fixture(provide_package_server())
    first = m.compile(m.generate("001", [Seven], backend="mariadb"))
    generated = m.generate("002", [Eight], backend="mariadb", previous=first)
    draft = generated.model_copy(update={"operations": ()}).then(
        m.Checkpoint(name="before")
    )
    draft = draft.then(
        m.DataChange.from_query(
            mariadb.update(Seven).set(Seven.value.to_expr(Seven.value.add(1))).all(),
            checkpoint="before",
            contract_digest=m.contract_digest(draft, point="before"),
        )
    )
    for operation in generated.operations:
        draft = draft.then(operation)
    draft = draft.then(m.Checkpoint(name="after"))
    draft = draft.then(
        m.DataChange.from_query(
            mariadb.update(Eight).set(Eight.id.to(1)).all(),
            checkpoint="after",
            contract_digest=m.contract_digest(draft, point="after"),
        )
    )
    second = m.Package.load(m.compile(draft).dump())
    async with m.connect(server.config()) as target:
        await target.apply(await target.prepare(first, schema_writers_excluded=True))
    await server.run_sql("INSERT INTO settings(id) VALUES (1),(2)")
    async with m.connect(server.config()) as target:
        plan = await target.prepare(second, schema_writers_excluded=True)
        with assert_raises(IntegrityError):
            await target.apply(plan)
        progress = next(p for p in await target.status() if p.revision == "002")
        assert_eq(progress.phase, "uncertain")
        assert_eq(progress.acknowledged_steps, 2)
    await server.run_sql("ALTER TABLE settings ALTER COLUMN value SET DEFAULT 9")
    async with m.connect(server.config()) as target:
        changed = await target.inspect_recovery(plan, schema_writers_excluded=True)
        assert_eq(changed.disposition, "ambiguous")
        with assert_raises(m.PackageError):
            await target.resume(changed, schema_writers_excluded=True)
    await server.run_sql("ALTER TABLE settings ALTER COLUMN value SET DEFAULT 8")
    await server.run_sql("DELETE FROM settings WHERE id=1")
    async with m.connect(server.config()) as target:
        recovery = await target.inspect_recovery(plan, schema_writers_excluded=True)
        assert_eq(recovery.disposition, "retry_remaining")
        assert_eq(
            await target.resume(recovery, schema_writers_excluded=True), "applied"
        )
    async with (
        await mariadb.Database.initialize(server.config()) as database,
        database.transaction() as transaction,
    ):
        await transaction.execute(mariadb.raw("INSERT INTO settings(id) VALUES (3)"))
        assert_eq(
            await transaction.fetch_all(
                mariadb.raw("SELECT id,value FROM settings ORDER BY id")
            ),
            [{"id": 1, "value": 8}, {"id": 3, "value": 8}],
        )


class NoClockDefaults[S = mariadb.Pending](mariadb.Model[S]):
    """Text and clock columns initially without defaults."""

    __tablename__ = "clocks"
    __row_type__: ClassVar[mariadb.ReadType[NoClockDefaults[mariadb.Row]]]
    id: mariadb.Col[int] = mariadb.Integer(primary_key=True)
    label: mariadb.Col[str | None] = mariadb.Text(nullable=True)
    clock: mariadb.Col[UtcDatetime] = mariadb.DateTime()


class ClockDefaults[S = mariadb.Pending](mariadb.Model[S]):
    """Encoded text and a parameterized clock expression, not arbitrary SQL."""

    __tablename__ = "clocks"
    __row_type__: ClassVar[mariadb.ReadType[ClockDefaults[mariadb.Row]]]
    id: mariadb.Col[int] = mariadb.Integer(primary_key=True)
    label: mariadb.GenCol[str | None] = mariadb.Text(
        nullable=True, default=mariadb.LiteralDefault("new'\\\0é DEFAULT")
    )
    clock: mariadb.GenCol[UtcDatetime] = mariadb.DateTime(
        default=mariadb.CurrentTimestamp
    )


@test(mark="slow")
async def native_encoded_text_and_clock_defaults_set_remove_and_restore() -> None:
    """Default-only plans target defaults, retain old values and handle clock precision."""
    server = await load_fixture(provide_package_server())
    previous = None
    for number, model in enumerate(
        (NoClockDefaults, ClockDefaults, NoClockDefaults, ClockDefaults), 1
    ):
        package = m.Package.load(
            m.compile(
                m.generate(str(number), [model], backend="mariadb", previous=previous)
            ).dump()
        )
        async with m.connect(server.config()) as target:
            plan = await target.prepare(package, schema_writers_excluded=True)
            if number > 1:
                assert all(
                    "ALTER COLUMN" in sql and "MODIFY COLUMN" not in sql
                    for sql in plan.statements
                )
            assert_eq(await target.apply(plan), "applied")
        async with (
            await mariadb.Database.initialize(server.config()) as database,
            database.transaction() as transaction,
        ):
            query = (
                "INSERT INTO clocks(id,clock) VALUES (%s,'2024-01-01 00:00:00')"
                if number in (1, 3)
                else "INSERT INTO clocks(id) VALUES (%s)"
            )
            await transaction.execute(mariadb.raw(query, params=(number,)))
        previous = package
    async with (
        await mariadb.Database.initialize(server.config()) as database,
        database.transaction() as transaction,
    ):
        assert_eq(
            await transaction.fetch_all(
                mariadb.raw(
                    "SELECT label, clock IS NOT NULL AS present FROM clocks ORDER BY id"
                )
            ),
            [
                {"label": None, "present": 1},
                {"label": "new'\\\0é DEFAULT", "present": 1},
                {"label": None, "present": 1},
                {"label": "new'\\\0é DEFAULT", "present": 1},
            ],
        )
        assert_eq(
            await transaction.fetch_all(
                mariadb.raw(
                    "SELECT id FROM clocks WHERE clock='2024-01-01 00:00:00' ORDER BY id"
                )
            ),
            [{"id": 1}, {"id": 3}],
        )


@test(mark="fast")
def native_default_transition_refuses_sql_comments_in_column_sources() -> None:
    """A line comment must not swallow following ALTER clauses after extraction."""
    before = m.generate("001", [Seven], backend="mariadb").target.tables[0]
    after = m.generate("002", [Eight], backend="mariadb").target.tables[0]
    tables = []
    for table in (before, after):
        old = next(c for c in table.columns if c.name == "value")
        column = old.model_copy(
            update={"definition": old.definition + " -- reviewed\n"}
        )
        tables.append(
            table.model_copy(
                update={
                    "sql": table.sql.replace(old.definition, column.definition),
                    "columns": tuple(
                        column if c.name == "value" else c for c in table.columns
                    ),
                }
            )
        )
    draft = m.Draft(
        revision="002",
        predecessor="reviewed",
        before=m.State(backend="mariadb", tables=(tables[0],)),
        target=m.State(backend="mariadb", tables=(tables[1],)),
        operations=(
            m.ChangeDefault(table_name="settings", column=tables[1].columns[1]),
        ),
    )
    with assert_raises(m.PackageError) as error:
        m.compile(draft)
    assert "comments" in str(error.exception)


@test(mark="fast")
def native_default_operations_cannot_change_other_recorded_column_facts() -> None:
    """The default operation cannot also change storage, typing, nullability or attributes."""
    first = m.compile(m.generate("001", [Seven], backend="mariadb"))
    draft = m.generate("002", [Eight], backend="mariadb", previous=first)
    table = draft.target.tables[0]
    column = next(c for c in table.columns if c.name == "value")
    for changes in (
        {"nullable": False},
        {"storage": "TEXT"},
        {"query_type": "str | None"},
        {"definition": column.definition + " COMMENT 'different'"},
    ):
        changed = column.model_copy(update=changes)
        target = table.model_copy(
            update={
                "columns": tuple(
                    changed if c.name == "value" else c for c in table.columns
                )
            }
        )
        with assert_raises(m.PackageError) as error:
            m.compile(
                draft.model_copy(
                    update={
                        "target": draft.target.model_copy(update={"tables": (target,)}),
                        "operations": (
                            m.ChangeDefault(table_name="settings", column=changed),
                        ),
                    }
                )
            )
        diagnostic = (
            "ordinary column nullability"
            if "nullable" in changes
            else "must change only the default"
        )
        assert diagnostic in str(error.exception)


_CHILD = r"""
import asyncio,json,sys
from snekql import mariadb
from snekql.experimental import migrations as m
async def main():
    payload=json.loads(sys.stdin.read())
    config=mariadb.Config(**payload['config'])
    for number,text in enumerate(payload['packages'],1):
        package=m.Package.load(text)
        async with m.connect(config) as target:
            await target.apply(await target.prepare(package,schema_writers_excluded=True))
        if number<5:
            async with await mariadb.Database.initialize(config) as db, db.transaction() as tx:
                await tx.execute(mariadb.raw('INSERT INTO settings(id) VALUES (%s)',params=(number,)))
    async with m.connect(config) as target:
        assert len(await target.status())==5
        assert all(p.phase=='complete' for p in await target.status())
    async with await mariadb.Database.initialize(config) as db, db.transaction() as tx:
        rows=await tx.fetch_all(mariadb.raw('SELECT value FROM settings ORDER BY id'))
    assert 'tests.experimental.test_migration_native_default_changes' not in sys.modules
    print(json.dumps(rows))
asyncio.run(main())
"""


@test(mark="slow")
async def frozen_native_default_chain_deploys_and_relinquishes_without_models() -> None:
    """A separate deployment process needs only frozen packages and connectivity."""
    server = await load_fixture(provide_package_server())
    packages: list[m.Package] = []
    for number, model in enumerate((Original, Seven, Eight, Original), 1):
        packages.append(
            m.compile(
                m.generate(
                    str(number),
                    [model],
                    backend="mariadb",
                    previous=packages[-1] if packages else None,
                )
            )
        )
    packages.append(
        m.compile(
            m.generate("5", [], backend="mariadb", previous=packages[-1]).resolve(
                m.RelinquishTable(table_name="settings")
            )
        )
    )
    config = server.config()
    payload = json.dumps(
        {
            "config": {
                "database": config.database,
                "host": config.host,
                "port": config.port,
                "user": config.user,
                "password": config.password,
                "unix_socket": str(config.unix_socket),
                "charset": config.charset,
            },
            "packages": [p.dump() for p in packages],
        }
    )
    child = await asyncio.create_subprocess_exec(
        sys.executable,
        "-c",
        _CHILD,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await child.communicate(payload.encode())
    finally:
        if child.returncode is None:
            child.kill()
            await child.wait()
    assert_eq(child.returncode, 0, msg=stderr.decode())
    assert_eq(
        json.loads(stdout),
        [{"value": None}, {"value": 7}, {"value": 8}, {"value": None}],
    )


class NullDefault[S = mariadb.Pending](mariadb.Model[S]):
    """Explicit nullable NULL, distinct in the recorded declaration from omission."""

    __tablename__ = "settings"
    __row_type__: ClassVar[mariadb.ReadType[NullDefault[mariadb.Row]]]
    id: mariadb.Col[int] = mariadb.Integer(primary_key=True)
    value: mariadb.GenCol[int | None] = mariadb.Integer(
        nullable=True, default=mariadb.LiteralDefault(None)
    )


@test(mark="slow")
async def native_null_default_and_removal_preserve_old_scalar_values() -> None:
    """SET DEFAULT NULL and DROP DEFAULT both retain old data despite effective equality."""
    server = await load_fixture(provide_package_server())
    previous = None
    for number, model in enumerate((Seven, NullDefault, Original), 1):
        package = m.Package.load(
            m.compile(
                m.generate(str(number), [model], backend="mariadb", previous=previous)
            ).dump()
        )
        async with m.connect(server.config()) as target:
            plan = await target.prepare(package, schema_writers_excluded=True)
            if number == 2:
                assert_eq(
                    plan.statements,
                    ("ALTER TABLE `settings` ALTER COLUMN `value` SET DEFAULT NULL",),
                )
            if number == 3:
                assert_eq(
                    plan.statements,
                    ("ALTER TABLE `settings` ALTER COLUMN `value` DROP DEFAULT",),
                )
            await target.apply(plan)
        await server.run_sql(f"INSERT INTO settings(id) VALUES ({number})")
        previous = package
    async with (
        await mariadb.Database.initialize(server.config()) as database,
        database.transaction() as transaction,
    ):
        assert_eq(
            await transaction.fetch_all(
                mariadb.raw("SELECT value FROM settings ORDER BY id")
            ),
            [{"value": 7}, {"value": None}, {"value": None}],
        )


class RequiredEight[S = mariadb.Pending](mariadb.Model[S]):
    """A combined contraction with a different final default."""

    __tablename__ = "settings"
    __row_type__: ClassVar[mariadb.ReadType[RequiredEight[mariadb.Row]]]
    id: mariadb.Col[int] = mariadb.Integer(primary_key=True)
    value: mariadb.GenCol[int] = mariadb.Integer(default=mariadb.LiteralDefault(8))


@test(mark="slow")
async def lost_default_receipt_cannot_reconcile_only_the_nullability_change() -> None:
    """The old contraction projection must not ignore a changed default claim."""
    server = await load_fixture(provide_package_server())
    first = m.compile(m.generate("001", [Seven], backend="mariadb"))
    second = m.compile(
        m.generate("002", [RequiredEight], backend="mariadb", previous=first)
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
    await server.run_sql("DROP TRIGGER fail_receipt")
    # Leave precisely the old projection's NOT NULL result, but the wrong default.
    await server.run_sql("ALTER TABLE settings ALTER COLUMN value SET DEFAULT 7")
    async with m.connect(server.config()) as target:
        recovery = await target.inspect_recovery(plan, schema_writers_excluded=True)
        assert_eq(recovery.acknowledged_steps, 0)
        assert_eq(recovery.disposition, "ambiguous")
        with assert_raises(m.PackageError):
            await target.reconcile(
                recovery,
                reason="Only nullability matches",
                schema_writers_excluded=True,
            )
        with assert_raises(m.PackageError):
            await target.resume(recovery, schema_writers_excluded=True)
    # Even the correct endpoint is not a receipt: default-aware full-catalog
    # structural reconciliation is deliberately not enabled by this slice.
    await server.run_sql("ALTER TABLE settings ALTER COLUMN value SET DEFAULT 8")
    async with m.connect(server.config()) as target:
        recovery = await target.inspect_recovery(plan, schema_writers_excluded=True)
        assert_eq(recovery.disposition, "ambiguous")
        with assert_raises(m.PackageError):
            await target.reconcile(
                recovery, reason="Default now matches", schema_writers_excluded=True
            )
