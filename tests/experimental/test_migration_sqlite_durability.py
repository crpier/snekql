"""SQLite migration synchronization honors Config without changing journal policy."""

from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Literal

import aiosqlite
from snektest import Param, assert_eq, test

from snekql import sqlite
from snekql.experimental import migrations as m
from tests.experimental.test_migration_io_deadlines import Account
from tests.experimental.test_migration_prepared_evidence import Initial


@test(
    [
        Param[tuple[Literal["delete", "wal"], Literal["normal", "full"]]](
            value=("delete", "normal"), name="delete-normal"
        ),
        Param[tuple[Literal["delete", "wal"], Literal["normal", "full"]]](
            value=("delete", "full"), name="delete-full"
        ),
        Param[tuple[Literal["delete", "wal"], Literal["normal", "full"]]](
            value=("wal", "normal"), name="wal-normal"
        ),
        Param[tuple[Literal["delete", "wal"], Literal["normal", "full"]]](
            value=("wal", "full"), name="wal-full"
        ),
    ],
    mark="medium",
)
async def original_role_work_keeps_selected_journal_and_requested_synchronization(
    policy: tuple[Literal["delete", "wal"], Literal["normal", "full"]],
) -> None:
    """A real retained trigger observes the migration session, not an observer's policy."""
    journal, durability = policy
    sync = 1 if durability == "normal" else 2
    fixed = Path(__file__).parent / "fixtures" / "role-interruption" / "sqlite"
    packages = [
        m.Package.load((fixed / name).read_text())
        for name in ("001_accounts.json", "002_expand.json", "003_roles.json")
    ]
    originals = [package.dump() for package in packages]
    first, expansion, roles = packages
    with TemporaryDirectory() as directory:
        config = sqlite.Config(
            database=Path(directory) / "app.db",
            durability=durability,
            acquire_timeout=0.2,
        )
        async with m.connect(config) as target:
            assert_eq(await target.apply(await target.prepare(first)), "applied")
        async with (
            await sqlite.Database.initialize(config) as app,
            app.transaction() as tx,
        ):
            await tx.execute(
                sqlite.insert_many(
                    Initial,
                    [Initial(id=1, is_admin=True), Initial(id=2, is_admin=False)],
                )
            )
        async with aiosqlite.connect(
            str(config.database), isolation_level=None
        ) as outside:
            async with outside.execute(f"PRAGMA journal_mode={journal}") as cursor:
                assert_eq(await cursor.fetchall(), [(journal,)])
            async with m.connect(config) as target:
                assert_eq(
                    await target.apply(await target.prepare(expansion)), "applied"
                )
            await outside.execute(
                "CREATE TABLE settings_audit(id INTEGER,sync INTEGER,journal TEXT,busy INTEGER)"
            )
            await outside.execute(
                "CREATE TRIGGER observed_role AFTER UPDATE OF role ON accounts BEGIN "
                "INSERT INTO settings_audit SELECT NEW.id,"
                "(SELECT synchronous FROM pragma_synchronous),"
                "(SELECT journal_mode FROM pragma_journal_mode),"
                "(SELECT timeout FROM pragma_busy_timeout); END"
            )
            before = list(
                await outside.execute_fetchall(
                    "SELECT * FROM snekql_experimental_migrations ORDER BY revision"
                )
            )
            async with m.connect(config) as target:
                original = await target.prepare(roles, preserve_unmanaged=True)
                wire = original.dump()
                assert_eq(await target.apply(m.Prepared.load(wire)), "applied")
                assert_eq(await target.apply(m.Prepared.load(wire)), "already_applied")
                assert_eq(original.dump(), wire)
                assert_eq(
                    sorted((p.revision, p.phase) for p in await target.status()),
                    [
                        ("001_accounts", "complete"),
                        ("002_expand", "complete"),
                        ("003_roles", "complete"),
                    ],
                )
            assert_eq(
                await outside.execute_fetchall(
                    "SELECT * FROM settings_audit ORDER BY id"
                ),
                [
                    (1, sync, journal, 200),
                    (1, sync, journal, 200),
                    (2, sync, journal, 200),
                ],
            )
            after = list(
                await outside.execute_fetchall(
                    "SELECT * FROM snekql_experimental_migrations ORDER BY revision"
                )
            )
            assert_eq(after[: len(before)], before)
            async with outside.execute("PRAGMA journal_mode") as cursor:
                assert_eq(await cursor.fetchall(), [(journal,)])
        async with (
            await sqlite.Database.initialize(config) as app,
            app.transaction() as tx,
        ):
            await tx.execute(sqlite.insert(Account(id=3, role="user")))
            rows = await tx.fetch_all(sqlite.select(Account).order_by(Account.id.asc()))
        assert_eq(
            [(r.id, r.role) for r in rows], [(1, "admin"), (2, "user"), (3, "user")]
        )
        assert_eq([package.dump() for package in packages], originals)
