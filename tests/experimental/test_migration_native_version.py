"""Real native version admission; optional explicitly selected old server installation."""

import asyncio
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory

import aiomysql
from snektest import assert_eq, assert_raises, test

from snekql import mariadb
from snekql.experimental import migrations as m
from snekql.testing.mariadb import temporary_mariadb_server
from tests.experimental.test_migration_io_deadlines import NativeAccount, NativeInitial


@test(mark="slow")
async def real_native_version_admission_precedes_work_and_preserves_unowned_data() -> (  # noqa: PLR0915 - one visible native admission/role journey
    None
):
    """Run current positive workflow or explicit actual10.10.7 negative admission."""
    installation = os.environ.get("SNEKQL_TEST_MARIADB_10_10_7")
    below_floor = (
        await asyncio.to_thread(Path(installation).resolve) if installation else None
    )
    await asyncio.to_thread(Path(".snektest").mkdir, exist_ok=True)
    with TemporaryDirectory(prefix="version-", dir=".snektest") as directory:
        async with temporary_mariadb_server(
            data_directory=Path(directory) / "data",
            mariadbd=below_floor / "bin" / "mariadbd" if below_floor else "mariadbd",
            install_db=below_floor / "scripts" / "mariadb-install-db"
            if below_floor
            else "mariadb-install-db",
            client=below_floor / "bin" / "mariadb" if below_floor else "mariadb",
            server_args=(f"--basedir={below_floor}",) if below_floor else (),
        ) as server:
            config = server.config()
            observer = await aiomysql.connect(
                unix_socket=str(config.unix_socket),
                user=config.user,
                password=config.password,
                db=config.database,
                autocommit=True,
            )
            try:
                async with observer.cursor() as cursor:
                    await cursor.execute("SELECT VERSION()")
                    version = await cursor.fetchone()
                    assert version is not None and isinstance(version[0], str)
                    assert "MariaDB" in version[0]
                    if below_floor:
                        assert version[0].startswith("10.10.7-")
                    await cursor.execute(
                        "CREATE TABLE unowned_directory(id INTEGER PRIMARY KEY,note VARCHAR(255)) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4"
                    )
                    await cursor.execute(
                        "INSERT INTO unowned_directory VALUES(7,'kept ☃')"
                    )
                    await cursor.execute("SHOW CREATE TABLE unowned_directory")
                    before = await cursor.fetchall()
                    await cursor.execute(
                        "SELECT ID FROM information_schema.PROCESSLIST WHERE DB=DATABASE() AND ID<>CONNECTION_ID() ORDER BY ID"
                    )
                    sessions = await cursor.fetchall()
                fixed = (
                    Path(__file__).parent / "fixtures" / "role-interruption" / "mariadb"
                )
                packages = [
                    m.Package.load((fixed / name).read_text())
                    for name in (
                        "001_accounts.json",
                        "002_expand.json",
                        "003_roles.json",
                    )
                ]
                first, expansion, roles = packages
                original_packages = [package.dump() for package in packages]
                if below_floor:
                    yielded = False
                    with assert_raises(mariadb.DatabaseRuntimeError) as error:
                        async with m.connect(config) as target:
                            yielded = True
                            await target.apply(
                                await target.prepare(
                                    first, schema_writers_excluded=True
                                )
                            )
                    assert_eq(yielded, False)
                    assert "requires MariaDB >= 10.11" in str(error.exception)
                    assert "10.10.7" in str(error.exception)
                    async with observer.cursor() as cursor:
                        await cursor.execute("SHOW FULL TABLES")
                        assert_eq(
                            await cursor.fetchall(),
                            (("unowned_directory", "BASE TABLE"),),
                        )
                        await cursor.execute(
                            "SELECT ID FROM information_schema.PROCESSLIST WHERE DB=DATABASE() AND ID<>CONNECTION_ID() ORDER BY ID"
                        )
                        assert_eq(await cursor.fetchall(), sessions)
                else:
                    async with m.connect(config) as target:
                        assert_eq(
                            await target.apply(
                                await target.prepare(
                                    first, schema_writers_excluded=True
                                )
                            ),
                            "applied",
                        )
                    async with (
                        await mariadb.Database.initialize(config) as app,
                        app.transaction() as tx,
                    ):
                        await tx.execute(
                            mariadb.insert_many(
                                NativeInitial,
                                [
                                    NativeInitial(id=1, is_admin=True),
                                    NativeInitial(id=2, is_admin=False),
                                ],
                            )
                        )
                    async with m.connect(config) as target:
                        await target.apply(
                            await target.prepare(
                                expansion, schema_writers_excluded=True
                            )
                        )
                        original = await target.prepare(
                            roles, schema_writers_excluded=True
                        )
                        wire = original.dump()
                    async with observer.cursor() as cursor:
                        await cursor.execute(
                            "SELECT * FROM snekql_experimental_migrations ORDER BY revision"
                        )
                        earlier = await cursor.fetchall()
                    async with m.connect(config) as target:
                        assert_eq(await target.apply(m.Prepared.load(wire)), "applied")
                        assert_eq(
                            await target.apply(m.Prepared.load(wire)), "already_applied"
                        )
                        assert_eq(
                            sorted(
                                (p.revision, p.phase) for p in await target.status()
                            ),
                            [
                                ("001_accounts", "complete"),
                                ("002_expand", "complete"),
                                ("003_roles", "complete"),
                            ],
                        )
                    async with observer.cursor() as cursor:
                        await cursor.execute(
                            "SELECT * FROM snekql_experimental_migrations ORDER BY revision"
                        )
                        receipts = await cursor.fetchall()
                        assert_eq(receipts[: len(earlier)], earlier)
                        for receipt in receipts:
                            assert isinstance(receipt[9], str)
                            assert_eq(json.loads(receipt[9])["profile"][0], version[0])
                    async with (
                        await mariadb.Database.initialize(config) as app,
                        app.transaction() as tx,
                    ):
                        await tx.execute(
                            mariadb.insert(NativeAccount(id=3, role="user"))
                        )
                        rows = await tx.fetch_all(
                            mariadb.select(NativeAccount).order_by(
                                NativeAccount.id.asc()
                            )
                        )
                    assert_eq(
                        [(row.id, row.role) for row in rows],
                        [(1, "admin"), (2, "user"), (3, "user")],
                    )
                    assert_eq(original.dump(), wire)
                async with observer.cursor() as cursor:
                    await cursor.execute("SHOW CREATE TABLE unowned_directory")
                    assert_eq(await cursor.fetchall(), before)
                    await cursor.execute("SELECT * FROM unowned_directory ORDER BY id")
                    assert_eq(await cursor.fetchall(), ((7, "kept ☃"),))
                assert_eq([package.dump() for package in packages], original_packages)
            finally:
                observer.close()
