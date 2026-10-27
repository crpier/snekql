"""Partial native metadata cannot authorize a supposedly complete migration catalog."""

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


@test(
    [
        Param[Literal["routine", "table"]](value="routine", name="routine"),
        Param[Literal["routine", "table"]](value="table", name="table"),
    ],
    mark="slow",
)
async def invisible_objects_refuse_before_original_role_work(  # noqa: PLR0915 - retain metadata authority, original evidence and recovery
    mode: Literal["routine", "table"],
) -> None:
    """Privilege-filtered absence is not proof that the whole schema was observed."""
    with TemporaryDirectory(prefix="metadata-", dir=".snektest") as directory:
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
            restricted = None
            try:
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
                originals = [p.dump() for p in packages]
                async with m.connect(config) as target:
                    await target.apply(
                        await target.prepare(first, schema_writers_excluded=True)
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
                        await target.prepare(expansion, schema_writers_excluded=True)
                    )
                    original = await target.prepare(roles, schema_writers_excluded=True)
                    wire = original.dump()
                async with observer.cursor() as cursor:
                    await cursor.execute(
                        "SELECT * FROM snekql_experimental_migrations ORDER BY revision"
                    )
                    before = await cursor.fetchall()
                    if mode == "routine":
                        await cursor.execute(
                            "CREATE FUNCTION external_constant() RETURNS INT DETERMINISTIC RETURN 7"
                        )
                    else:
                        await cursor.execute(
                            "CREATE TABLE external_hidden(id INTEGER PRIMARY KEY) ENGINE=MyISAM"
                        )
                        await cursor.execute("INSERT INTO external_hidden VALUES(7)")
                    await cursor.execute(
                        "SHOW CREATE FUNCTION external_constant"
                        if mode == "routine"
                        else "SHOW CREATE TABLE external_hidden"
                    )
                    function = await cursor.fetchall()
                    await cursor.execute(
                        "CREATE USER 'metadata_user'@'localhost' IDENTIFIED BY 'owned-test-only'"
                    )
                    if mode == "routine":
                        await cursor.execute(
                            "GRANT SELECT,INSERT,UPDATE,DELETE,CREATE,ALTER,DROP,INDEX,REFERENCES,TRIGGER,SHOW VIEW ON test.* TO 'metadata_user'@'localhost'"
                        )
                    else:
                        await cursor.execute(
                            "GRANT ALL PRIVILEGES ON test.accounts TO 'metadata_user'@'localhost'"
                        )
                        await cursor.execute(
                            "GRANT ALL PRIVILEGES ON test.snekql_experimental_migrations TO 'metadata_user'@'localhost'"
                        )
                limited = replace(
                    config, user="metadata_user", password="owned-test-only"
                )
                restricted = await aiomysql.connect(
                    unix_socket=str(limited.unix_socket),
                    user=limited.user,
                    password=limited.password,
                    db=limited.database,
                    autocommit=True,
                )
                async with restricted.cursor() as cursor:
                    await cursor.execute(
                        "SELECT ROUTINE_NAME FROM information_schema.ROUTINES WHERE ROUTINE_SCHEMA=DATABASE()"
                    )
                    assert_eq(await cursor.fetchall(), ())
                    await cursor.execute("SHOW FULL TABLES")
                    assert_eq(
                        await cursor.fetchall(),
                        (
                            ("accounts", "BASE TABLE"),
                            ("snekql_experimental_migrations", "BASE TABLE"),
                        ),
                    )
                yielded = False
                with assert_raises(mariadb.DatabaseRuntimeError) as error:
                    async with m.connect(limited) as target:
                        yielded = True
                        await target.apply(m.Prepared.load(wire))
                assert_eq(yielded, False)
                assert "metadata coverage" in str(error.exception)
                assert "EXECUTE" in str(error.exception)
                async with observer.cursor() as cursor:
                    await cursor.execute(
                        "SELECT * FROM snekql_experimental_migrations ORDER BY revision"
                    )
                    assert_eq(await cursor.fetchall(), before)
                    await cursor.execute(
                        "SELECT id,is_admin,role FROM accounts ORDER BY id"
                    )
                    assert_eq(await cursor.fetchall(), ((1, 1, None), (2, 0, None)))
                    await cursor.execute(
                        "SHOW CREATE FUNCTION external_constant"
                        if mode == "routine"
                        else "SHOW CREATE TABLE external_hidden"
                    )
                    assert_eq(await cursor.fetchall(), function)
                    if mode == "table":
                        await cursor.execute("SELECT id FROM external_hidden")
                        assert_eq(await cursor.fetchall(), ((7,),))
                    await cursor.execute(
                        "GRANT SELECT,TRIGGER,SHOW VIEW,EXECUTE ON test.* TO 'metadata_user'@'localhost'"
                    )
                # Positive metadata coverage reveals the existing operational obstacle;
                # it neither executes nor automatically deletes the external function.
                async with m.connect(limited) as target:
                    with assert_raises(m.PackageError) as obstacle:
                        await target.apply(m.Prepared.load(wire))
                    assert (
                        "without triggers or stored routines"
                        if mode == "routine"
                        else "catalog differs"
                    ) in str(obstacle.exception)
                    if mode == "routine":
                        recovery = await target.inspect_recovery(
                            m.Prepared.load(wire), schema_writers_excluded=True
                        )
                        assert_eq(
                            (recovery.disposition, recovery.acknowledged_steps),
                            ("ambiguous", 0),
                        )
                    else:
                        assert_eq(len(await target.status()), 2)
                # External owner deliberately removes its OWN prerequisite obstacle.
                async with observer.cursor() as cursor:
                    await cursor.execute(
                        "DROP FUNCTION external_constant"
                        if mode == "routine"
                        else "DROP TABLE external_hidden"
                    )
                async with m.connect(limited) as target:
                    if mode == "routine":
                        with assert_raises(m.PackageError):
                            await target.apply(m.Prepared.load(wire))
                        recovery = await target.inspect_recovery(
                            m.Prepared.load(wire), schema_writers_excluded=True
                        )
                        assert_eq(
                            (recovery.disposition, recovery.acknowledged_steps),
                            ("retry_remaining", 0),
                        )
                        assert_eq(
                            await target.resume(recovery, schema_writers_excluded=True),
                            "applied",
                        )
                    else:
                        assert_eq(await target.apply(m.Prepared.load(wire)), "applied")
                    assert_eq(
                        await target.apply(m.Prepared.load(wire)), "already_applied"
                    )
                    assert_eq(
                        sorted((p.revision, p.phase) for p in await target.status()),
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
                    assert_eq((await cursor.fetchall())[: len(before)], before)
                async with (
                    await mariadb.Database.initialize(limited) as app,
                    app.transaction() as tx,
                ):
                    await tx.execute(mariadb.insert(NativeAccount(id=3, role="user")))
                    rows = await tx.fetch_all(
                        mariadb.select(NativeAccount).order_by(NativeAccount.id.asc())
                    )
                    assert_eq(
                        [(r.id, r.role) for r in rows],
                        [(1, "admin"), (2, "user"), (3, "user")],
                    )
                assert_eq([p.dump() for p in packages], originals)
                assert_eq(original.dump(), wire)
            finally:
                if restricted is not None:
                    restricted.close()
                async with observer.cursor() as cursor:
                    await cursor.execute("DROP FUNCTION IF EXISTS external_constant")
                    await cursor.execute("DROP TABLE IF EXISTS external_hidden")
                    await cursor.execute(
                        "DROP USER IF EXISTS 'metadata_user'@'localhost'"
                    )
                observer.close()


@test(
    [
        Param[Literal["quoted", "account_case", "schema_case", "role_only"]](
            value=mode, name=mode
        )
        for mode in ("quoted", "account_case", "schema_case", "role_only")
    ],
    mark="slow",
)
async def metadata_coverage_uses_authenticated_direct_scope(  # noqa: PLR0915 - actual principals, role and case-sensitive schema scopes
    mode: Literal["quoted", "account_case", "schema_case", "role_only"],
) -> None:
    """Do not borrow another account/database/role's grants or misquote a real user."""
    with TemporaryDirectory(prefix="metadata-identity-", dir=".snektest") as directory:
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
            username = "m'@viewer" if mode == "quoted" else "metadata_viewer"
            limited = replace(config, user=username, password="owned-test-only")
            try:
                async with observer.cursor() as cursor:
                    await cursor.execute(
                        "CREATE USER %s@'localhost' IDENTIFIED BY 'owned-test-only'",
                        (username,),
                    )
                    if mode == "role_only":
                        await cursor.execute("CREATE ROLE metadata_role")
                        await cursor.execute(
                            "GRANT ALL PRIVILEGES ON test.* TO metadata_role"
                        )
                        await cursor.execute(
                            "GRANT metadata_role TO %s@'localhost'", (username,)
                        )
                        await cursor.execute(
                            "SET DEFAULT ROLE metadata_role FOR %s@'localhost'",
                            (username,),
                        )
                    else:
                        await cursor.execute(
                            "GRANT SELECT ON *.* TO %s@'localhost'", (username,)
                        )
                        if mode == "quoted":
                            await cursor.execute(
                                "GRANT SHOW VIEW,TRIGGER,EXECUTE,INSERT,UPDATE,CREATE,ALTER,DROP,INDEX ON test.* TO %s@'localhost'",
                                (username,),
                            )
                        elif mode == "account_case":
                            await cursor.execute(
                                "CREATE USER 'METADATA_VIEWER'@'localhost'"
                            )
                            await cursor.execute(
                                "GRANT ALL PRIVILEGES ON test.* TO 'METADATA_VIEWER'@'localhost'"
                            )
                        else:
                            await cursor.execute("SELECT @@lower_case_table_names")
                            assert_eq(await cursor.fetchall(), ((0,),))
                            await cursor.execute("CREATE DATABASE TEST")
                            await cursor.execute(
                                "GRANT ALL PRIVILEGES ON TEST.* TO %s@'localhost'",
                                (username,),
                            )
                if mode != "quoted":
                    with assert_raises(mariadb.DatabaseRuntimeError) as error:
                        async with m.connect(limited) as target:
                            await target.status()
                    assert "metadata coverage" in str(error.exception)
                    async with observer.cursor() as cursor:
                        # The operator explicitly supplies direct metadata scope, NOT the library.
                        await cursor.execute(
                            "GRANT SELECT,SHOW VIEW,TRIGGER,EXECUTE,INSERT,UPDATE,CREATE,ALTER,DROP,INDEX ON test.* TO %s@'localhost'",
                            (username,),
                        )
                first = m.Package.load(
                    (
                        Path(__file__).parent
                        / "fixtures/role-interruption/mariadb/001_accounts.json"
                    ).read_text()
                )
                wire = first.dump()
                async with m.connect(limited) as target:
                    assert_eq(await target.status(), ())
                    assert_eq(
                        await target.apply(
                            await target.prepare(first, schema_writers_excluded=True)
                        ),
                        "applied",
                    )
                    assert_eq(
                        await target.apply(
                            await target.prepare(first, schema_writers_excluded=True)
                        ),
                        "already_applied",
                    )
                async with (
                    await mariadb.Database.initialize(limited) as app,
                    app.transaction() as tx,
                ):
                    await tx.execute(mariadb.insert(NativeInitial(id=7, is_admin=True)))
                    rows = await tx.fetch_all(mariadb.select(NativeInitial))
                    assert_eq([(r.id, r.is_admin) for r in rows], [(7, True)])
                assert_eq(first.dump(), wire)
            finally:
                async with observer.cursor() as cursor:
                    await cursor.execute(
                        "DROP USER IF EXISTS %s@'localhost'", (username,)
                    )
                    await cursor.execute(
                        "DROP USER IF EXISTS 'METADATA_VIEWER'@'localhost'"
                    )
                    await cursor.execute("DROP ROLE IF EXISTS metadata_role")
                    await cursor.execute("DROP DATABASE IF EXISTS TEST")
                observer.close()


@test(mark="slow")
async def grant_disabled_server_has_explicit_unrestricted_metadata_authority() -> None:
    """The actual grant-bypass server profile is not a missing-grants restricted user."""
    async with temporary_mariadb_server() as server:
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
                await cursor.execute("SELECT @@GLOBAL.skip_grant_tables")
                assert_eq(await cursor.fetchall(), ((1,),))
            first = m.Package.load(
                (
                    Path(__file__).parent
                    / "fixtures/role-interruption/mariadb/001_accounts.json"
                ).read_text()
            )
            async with m.connect(config) as target:
                assert_eq(await target.status(), ())
                assert_eq(
                    await target.apply(
                        await target.prepare(first, schema_writers_excluded=True)
                    ),
                    "applied",
                )
            async with (
                await mariadb.Database.initialize(config) as app,
                app.transaction() as tx,
            ):
                await tx.execute(mariadb.insert(NativeInitial(id=7, is_admin=True)))
                rows = await tx.fetch_all(mariadb.select(NativeInitial))
                assert_eq([(r.id, r.is_admin) for r in rows], [(7, True)])
        finally:
            observer.close()
