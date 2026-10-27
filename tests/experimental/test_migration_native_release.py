"""Native migration completion must leave no recursive coordination ownership."""

import re
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Literal

import aiomysql
from snektest import Param, assert_eq, assert_raises, test

from snekql import mariadb
from snekql.experimental import migrations as m
from snekql.testing.mariadb import temporary_mariadb_server
from tests.experimental.test_migration_io_deadlines import NativeAccount, NativeInitial
from tests.experimental.test_migration_role_interruption import _wait_disconnected


@test(
    [
        Param[Literal["applied", "refused", "deadline"]](
            value="applied", name="applied"
        ),
        Param[Literal["applied", "refused", "deadline"]](
            value="refused", name="refused"
        ),
        Param[Literal["applied", "refused", "deadline"]](
            value="deadline", name="deadline"
        ),
    ],
    mark="slow",
)
async def original_role_application_positively_drains_recursive_native_lock(  # noqa: PLR0915 - retain actual bootstrap, role/error execution and independent release observation
    mode: Literal["applied", "refused", "deadline"],
) -> None:
    """Actual server init_connect ownership cannot leak past a coordinated operation."""
    with TemporaryDirectory(prefix="release-", dir=".snektest") as directory:
        async with temporary_mariadb_server(
            auth="password", data_directory=Path(directory) / "data"
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
                    await cursor.execute(
                        "SELECT @@GLOBAL.general_log,@@GLOBAL.log_output,@@GLOBAL.init_connect"
                    )
                    saved = await cursor.fetchone()
                    assert saved is not None
                try:
                    async with observer.cursor() as cursor:
                        await cursor.execute(
                            "CREATE USER 'release_user'@'localhost' IDENTIFIED BY 'owned-test-only'"
                        )
                        await cursor.execute(
                            "GRANT ALL PRIVILEGES ON `test`.* TO 'release_user'@'localhost'"
                        )
                        await cursor.execute("SET GLOBAL log_output='TABLE'")
                        await cursor.execute("SET GLOBAL general_log=1")
                    fixed = (
                        Path(__file__).parent
                        / "fixtures"
                        / "role-interruption"
                        / "mariadb"
                    )
                    first, expansion, roles = [
                        m.Package.load((fixed / name).read_text())
                        for name in (
                            "001_accounts.json",
                            "002_expand.json",
                            "003_roles.json",
                        )
                    ]
                    originals = [p.dump() for p in (first, expansion, roles)]
                    async with m.connect(config) as target:
                        await target.apply(
                            await target.prepare(first, schema_writers_excluded=True)
                        )
                    async with observer.cursor() as cursor:
                        await cursor.execute(
                            "SELECT argument FROM mysql.general_log "
                            "WHERE command_type='Query' AND argument LIKE 'SELECT GET_LOCK(%' "
                            "ORDER BY event_time DESC LIMIT 1"
                        )
                        row = await cursor.fetchone()
                        assert row is not None
                        found = re.search(
                            r"GET_LOCK\s*\(\s*'([^']+)'", str(row[0]), re.IGNORECASE
                        )
                        assert found is not None
                        name = found.group(1)
                        await cursor.execute("SET GLOBAL general_log=%s", (saved[0],))
                        await cursor.execute("SET GLOBAL log_output=%s", (saved[1],))
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
                        before = await cursor.fetchall()
                        initializer = "DO " + ",".join(
                            [f"GET_LOCK('{name}',0)"] * 3
                            + ["GET_LOCK('release-unrelated',0)"]
                        )
                        if mode == "deadline":
                            await cursor.execute("CREATE DATABASE release_bootstrap")
                            await cursor.execute(
                                "CREATE PROCEDURE release_bootstrap.claim() BEGIN "
                                "DECLARE remaining INT DEFAULT 65536; "
                                "WHILE remaining>0 DO "
                                f"DO GET_LOCK('{name}',0); "
                                "SET remaining=remaining-1; END WHILE; "
                                "DO GET_LOCK('release-unrelated',0); END"
                            )
                            await cursor.execute(
                                "GRANT EXECUTE ON PROCEDURE release_bootstrap.claim "
                                "TO 'release_user'@'localhost'"
                            )
                            initializer = "CALL release_bootstrap.claim()"
                        await cursor.execute(
                            "SET GLOBAL init_connect=%s", (initializer,)
                        )
                    user_config = replace(
                        config,
                        user="release_user",
                        password="owned-test-only",
                        operation_timeout=1.5 if mode == "deadline" else 30,
                    )
                    async with m.connect(user_config) as target:
                        async with observer.cursor() as cursor:
                            await cursor.execute("SELECT IS_USED_LOCK(%s)", (name,))
                            owner = await cursor.fetchone()
                            assert owner is not None and owner[0] is not None
                        if mode == "refused":
                            async with observer.cursor() as cursor:
                                await cursor.execute(
                                    "CREATE TABLE caller_marker(id INTEGER)"
                                )
                            try:
                                with assert_raises(m.PackageError) as refusal:
                                    await target.apply(m.Prepared.load(wire))
                                assert "catalog differs" in str(refusal.exception)
                                assert_eq(
                                    sorted(p.revision for p in await target.status()),
                                    ["001_accounts", "002_expand"],
                                )
                            finally:
                                async with observer.cursor() as cursor:
                                    await cursor.execute("DROP TABLE caller_marker")
                        elif mode == "deadline":
                            with assert_raises(
                                mariadb.DatabaseOperationTimeoutError
                            ) as deadline:
                                await target.apply(m.Prepared.load(wire))
                            assert_eq(
                                deadline.exception.operation,
                                "migration advisory lock release",
                            )
                            assert_eq(deadline.exception.timeout, 1.5)
                            with assert_raises(m.PackageError):
                                await target.status()
                            await _wait_disconnected(config, owner[0])
                        else:
                            assert_eq(
                                await target.apply(m.Prepared.load(wire)), "applied"
                            )
                        async with observer.cursor() as cursor:
                            await cursor.execute("SELECT GET_LOCK(%s,0)", (name,))
                            assert_eq(
                                await cursor.fetchone(),
                                (1,),
                                msg="native migration returned with coordination still owned",
                            )
                            await cursor.execute("SELECT RELEASE_LOCK(%s)", (name,))
                            assert_eq(await cursor.fetchone(), (1,))
                            await cursor.execute(
                                "SELECT IS_USED_LOCK('release-unrelated')"
                            )
                            assert_eq(
                                await cursor.fetchone(),
                                (None,) if mode == "deadline" else owner,
                            )
                        if mode == "refused":
                            assert_eq(
                                await target.apply(m.Prepared.load(wire)), "applied"
                            )
                        if mode != "deadline":
                            assert_eq(
                                await target.apply(m.Prepared.load(wire)),
                                "already_applied",
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
                    async with m.connect(config) as fresh:
                        assert_eq(
                            await fresh.apply(m.Prepared.load(wire)), "already_applied"
                        )
                    async with observer.cursor() as cursor:
                        await cursor.execute(
                            "SELECT * FROM snekql_experimental_migrations ORDER BY revision"
                        )
                        after = await cursor.fetchall()
                        assert_eq(after[: len(before)], before)
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
                        [(r.id, r.role) for r in rows],
                        [(1, "admin"), (2, "user"), (3, "user")],
                    )
                    assert_eq(original.dump(), wire)
                    assert_eq([p.dump() for p in (first, expansion, roles)], originals)
                finally:
                    async with observer.cursor() as cursor:
                        await cursor.execute("SET GLOBAL init_connect=%s", (saved[2],))
                        await cursor.execute("SET GLOBAL general_log=%s", (saved[0],))
                        await cursor.execute("SET GLOBAL log_output=%s", (saved[1],))
                        await cursor.execute(
                            "DROP USER IF EXISTS 'release_user'@'localhost'"
                        )
                        await cursor.execute(
                            "DROP DATABASE IF EXISTS release_bootstrap"
                        )
            finally:
                observer.close()
