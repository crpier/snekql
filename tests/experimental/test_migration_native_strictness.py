"""InnoDB migration work requires inherited strict mode without rewriting it."""

import json
from pathlib import Path
from typing import Literal

import aiomysql
from snektest import Param, assert_eq, assert_raises, load_fixture, test

from snekql import mariadb
from snekql.experimental import migrations as m
from tests.experimental.test_migration_io_deadlines import NativeAccount, NativeInitial
from tests.experimental.test_migration_targets import provide_package_server


@test(
    [
        Param[Literal["weak", "empty", "transactional", "all"]](
            value="weak", name="weak"
        ),
        Param[Literal["weak", "empty", "transactional", "all"]](
            value="empty", name="empty"
        ),
        Param[Literal["weak", "empty", "transactional", "all"]](
            value="transactional", name="transactional"
        ),
        Param[Literal["weak", "empty", "transactional", "all"]](
            value="all", name="all"
        ),
    ],
    mark="slow",
)
async def inherited_strictness_admits_or_refuses_original_role_work_without_mode_rewrite(  # noqa: PLR0915 - one original-evidence journey
    mode: Literal["weak", "empty", "transactional", "all"],
) -> None:
    """A stronger admission refusal leaves the original work and mode evidence intact."""
    selected = {
        "weak": "NO_BACKSLASH_ESCAPES",
        "empty": "",
        "transactional": "STRICT_TRANS_TABLES,NO_BACKSLASH_ESCAPES",
        "all": "STRICT_ALL_TABLES,NO_BACKSLASH_ESCAPES",
    }[mode]
    weak = mode in {"weak", "empty"}
    server = await load_fixture(provide_package_server())
    config = server.config()
    fixed = Path(__file__).parent / "fixtures" / "role-interruption" / "mariadb"
    packages = [
        m.Package.load((fixed / name).read_text())
        for name in ("001_accounts.json", "002_expand.json", "003_roles.json")
    ]
    first, expansion, roles = packages
    originals = [package.dump() for package in packages]
    async with m.connect(config) as target:
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
    observer = await aiomysql.connect(
        unix_socket=str(config.unix_socket),
        user=config.user,
        password=config.password,
        db=config.database,
        autocommit=True,
    )
    try:
        async with observer.cursor() as cursor:
            await cursor.execute("SELECT @@GLOBAL.sql_mode")
            saved = await cursor.fetchone()
            assert saved is not None
            await cursor.execute(
                "SELECT * FROM snekql_experimental_migrations ORDER BY revision"
            )
            before = await cursor.fetchall()
        try:
            async with observer.cursor() as cursor:
                await cursor.execute("SET GLOBAL sql_mode=%s", (selected,))
                await cursor.execute("SELECT @@GLOBAL.sql_mode")
                inherited = await cursor.fetchone()
                await cursor.execute(
                    "SELECT ID FROM information_schema.PROCESSLIST "
                    "WHERE DB=DATABASE() AND ID<>CONNECTION_ID() ORDER BY ID"
                )
                sessions = await cursor.fetchall()
            if weak:
                yielded = False
                with assert_raises(mariadb.DatabaseRuntimeError) as error:
                    async with m.connect(config) as target:
                        yielded = True
                        await target.apply(m.Prepared.load(wire))
                assert_eq(yielded, False)
                assert "sql_mode" in str(error.exception)
                assert "STRICT_ALL_TABLES or STRICT_TRANS_TABLES" in str(
                    error.exception
                )
                async with observer.cursor() as cursor:
                    await cursor.execute("SELECT @@GLOBAL.sql_mode")
                    assert_eq(await cursor.fetchone(), inherited)
                    await cursor.execute(
                        "SELECT ID FROM information_schema.PROCESSLIST "
                        "WHERE DB=DATABASE() AND ID<>CONNECTION_ID() ORDER BY ID"
                    )
                    assert_eq(await cursor.fetchall(), sessions)
                    await cursor.execute(
                        "SELECT * FROM snekql_experimental_migrations ORDER BY revision"
                    )
                    assert_eq(await cursor.fetchall(), before)
                    await cursor.execute(
                        "SELECT id,is_admin,role FROM accounts ORDER BY id"
                    )
                    assert_eq(await cursor.fetchall(), ((1, 1, None), (2, 0, None)))
            else:
                async with m.connect(config) as target:
                    assert_eq(await target.apply(m.Prepared.load(wire)), "applied")
                    assert_eq(
                        await target.apply(m.Prepared.load(wire)), "already_applied"
                    )
            async with observer.cursor() as cursor:
                await cursor.execute("SELECT @@GLOBAL.sql_mode")
                assert_eq(await cursor.fetchone(), inherited)
        finally:
            async with observer.cursor() as cursor:
                await cursor.execute("SET GLOBAL sql_mode=%s", saved)
        async with m.connect(config) as target:
            assert_eq(
                await target.apply(m.Prepared.load(wire)),
                "applied" if weak else "already_applied",
            )
            assert_eq(await target.apply(m.Prepared.load(wire)), "already_applied")
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
            after = await cursor.fetchall()
            assert_eq(after[: len(before)], before)
            assert isinstance(after[-1][9], str)
            observation = json.loads(after[-1][9])
            assert inherited is not None
            assert_eq(observation["profile"][1], saved[0] if weak else inherited[0])
        async with (
            await mariadb.Database.initialize(config) as app,
            app.transaction() as tx,
        ):
            await tx.execute(mariadb.insert(NativeAccount(id=3, role="user")))
            rows = await tx.fetch_all(
                mariadb.select(NativeAccount).order_by(NativeAccount.id.asc())
            )
        assert_eq(
            [(r.id, r.role) for r in rows], [(1, "admin"), (2, "user"), (3, "user")]
        )
        assert_eq(original.dump(), wire)
        assert_eq([package.dump() for package in packages], originals)
    finally:
        observer.close()
