"""Dedicated SQLite targets admit shared encoding policy without rewriting files."""

from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Literal

import aiosqlite
from snektest import Param, assert_eq, assert_raises, test

from snekql import sqlite
from snekql.experimental import migrations as m
from tests.experimental.test_migration_io_deadlines import Account
from tests.experimental.test_migration_prepared_evidence import Initial


@test(
    [
        Param[Literal["UTF-16le", "UTF-16be"]](value="UTF-16le", name="little-endian"),
        Param[Literal["UTF-16le", "UTF-16be"]](value="UTF-16be", name="big-endian"),
    ],
    mark="medium",
)
async def incompatible_encoding_refuses_before_yield_without_converting_existing_data(
    encoding: Literal["UTF-16le", "UTF-16be"],
) -> None:
    """An existing unowned UTF-16 file is not silently treated as admitted UTF-8."""
    with TemporaryDirectory() as directory:
        path = Path(directory) / "external.db"
        async with aiosqlite.connect(str(path), isolation_level=None) as outside:
            await outside.execute(f"PRAGMA encoding='{encoding}'")
            await outside.execute(
                "CREATE TABLE directory(id INTEGER PRIMARY KEY,name TEXT)"
            )
            await outside.execute("INSERT INTO directory VALUES(1,'kept é')")
            async with outside.execute("PRAGMA encoding") as cursor:
                assert_eq(await cursor.fetchall(), [(encoding,)])
        before = path.read_bytes()
        yielded = False
        with assert_raises(sqlite.DatabaseRuntimeError) as error:
            async with m.connect(sqlite.Config(database=path)):
                yielded = True
        assert_eq(yielded, False)
        assert "encoding" in str(error.exception)
        assert "UTF-8" in str(error.exception)
        assert_eq(path.read_bytes(), before)
        async with aiosqlite.connect(str(path)) as outside:
            async with outside.execute("SELECT id,name FROM directory") as cursor:
                assert_eq(await cursor.fetchall(), [(1, "kept é")])
            async with outside.execute(
                "SELECT name FROM sqlite_schema WHERE type='table'"
            ) as cursor:
                assert_eq(await cursor.fetchall(), [("directory",)])

        # A different, explicitly selected UTF-8 target follows ordinary historical work.
        config = sqlite.Config(database=Path(directory) / "app.db", acquire_timeout=0.2)
        fixed = Path(__file__).parent / "fixtures" / "role-interruption" / "sqlite"
        first = m.Package.load((fixed / "001_accounts.json").read_text())
        expansion = m.Package.load((fixed / "002_expand.json").read_text())
        roles = m.Package.load((fixed / "003_roles.json").read_text())
        original_packages = [p.dump() for p in (first, expansion, roles)]
        async with m.connect(config) as target:
            assert_eq(await target.status(), ())
            assert_eq(await target.apply(await target.prepare(first)), "applied")
        async with (
            await sqlite.Database.initialize(config) as app,
            app.transaction() as tx,
        ):
            await tx.execute(
                sqlite.insert_many(
                    Initial,
                    [
                        Initial(id=1, is_admin=True),
                        Initial(id=2, is_admin=False),
                    ],
                )
            )
        async with m.connect(config) as target:
            assert_eq(await target.apply(await target.prepare(expansion)), "applied")
            original = await target.prepare(roles)
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
        async with (
            await sqlite.Database.initialize(config) as app,
            app.transaction() as tx,
        ):
            await tx.execute(sqlite.insert(Account(id=3, role="user")))
            rows = await tx.fetch_all(sqlite.select(Account).order_by(Account.id.asc()))
        assert_eq(
            [(row.id, row.role) for row in rows],
            [(1, "admin"), (2, "user"), (3, "user")],
        )
        assert_eq([p.dump() for p in (first, expansion, roles)], original_packages)
