"""A queued caller's admission failure cannot discard another operation's session."""

import asyncio
from dataclasses import replace
from pathlib import Path
from typing import Literal

import aiomysql
import anyio
from snektest import Param, assert_eq, assert_raises, load_fixture, test

from snekql import mariadb
from snekql.experimental import migrations as m
from tests.experimental.test_migration_io_deadlines import NativeAccount, NativeInitial
from tests.experimental.test_migration_role_interruption import _waiting_update
from tests.experimental.test_migration_targets import provide_package_server


@test(
    [
        Param[Literal["status", "prepare", "apply", "task", "scope"]](
            value="status", name="status"
        ),
        Param[Literal["status", "prepare", "apply", "task", "scope"]](
            value="prepare", name="prepare"
        ),
        Param[Literal["status", "prepare", "apply", "task", "scope"]](
            value="apply", name="apply"
        ),
        Param[Literal["status", "prepare", "apply", "task", "scope"]](
            value="task", name="task"
        ),
        Param[Literal["status", "prepare", "apply", "task", "scope"]](
            value="scope", name="scope"
        ),
    ],
    mark="slow",
)
async def queued_caller_leaves_active_role_migration_owned_and_usable(  # noqa: PLR0915 - retain the actual consumer lifecycle
    mode: Literal["status", "prepare", "apply", "task", "scope"],
) -> None:
    """Local guard acquisition has a budget, but the current owner keeps its I/O budget."""
    server = await load_fixture(provide_package_server())
    config = server.config()
    fixed = Path(__file__).parent / "fixtures" / "role-interruption" / "mariadb"
    first = m.Package.load((fixed / "001_accounts.json").read_text())
    expansion = m.Package.load((fixed / "002_expand.json").read_text())
    roles = m.Package.load((fixed / "003_roles.json").read_text())
    originals = [p.dump() for p in (first, expansion, roles)]
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
        assert_eq(
            await target.apply(
                await target.prepare(expansion, schema_writers_excluded=True)
            ),
            "applied",
        )
    blocker = await aiomysql.connect(
        unix_socket=str(config.unix_socket),
        user=config.user,
        password=config.password,
        db=config.database,
        autocommit=False,
    )
    try:
        async with blocker.cursor() as cursor:
            await cursor.execute("SELECT id FROM accounts WHERE id=2 FOR UPDATE")
        async with m.connect(
            replace(config, acquire_timeout=0.15, operation_timeout=5)
        ) as target:
            original = await target.prepare(roles, schema_writers_excluded=True)
            wire = original.dump()
            applying = asyncio.create_task(target.apply(m.Prepared.load(wire)))
            waiting: asyncio.Task[None] | None = None
            scope = anyio.CancelScope()
            try:
                observed = await _waiting_update(config)
                assert observed["modified"] >= 1

                async def queued() -> None:
                    with scope:
                        if mode == "prepare":
                            await target.prepare(roles, schema_writers_excluded=True)
                        elif mode == "apply":
                            await target.apply(m.Prepared.load(wire))
                        else:
                            await target.status()

                waiting = asyncio.create_task(queued())
                if mode in {"task", "scope"}:
                    await asyncio.sleep(0.05)
                    assert_eq(waiting.done(), False)
                    if mode == "task":
                        waiting.cancel()
                        with assert_raises(asyncio.CancelledError):
                            await waiting
                    else:
                        scope.cancel()
                        await waiting
                        assert scope.cancelled_caught
                else:
                    done, _ = await asyncio.wait({waiting}, timeout=0.8)
                    assert_eq(
                        bool(done),
                        True,
                        msg="local migration guard acquisition deadline ignored",
                    )
                    with assert_raises(mariadb.PoolTimeoutError) as error:
                        await waiting
                    assert "migration target guard" in str(error.exception)
                assert_eq(
                    applying.done(),
                    False,
                    msg="queued caller discarded the active owner",
                )
                still_waiting = await _waiting_update(config)
                assert_eq(still_waiting["id"], observed["id"])
                assert still_waiting["modified"] >= 1
                await blocker.rollback()
                assert_eq(await applying, "applied")
                assert_eq(original.dump(), wire)
                assert_eq(
                    await target.apply(
                        await target.prepare(roles, schema_writers_excluded=True)
                    ),
                    "already_applied",
                )
                assert_eq(
                    sorted((p.revision, p.phase) for p in await target.status()),
                    [
                        ("001_accounts", "complete"),
                        ("002_expand", "complete"),
                        ("003_roles", "complete"),
                    ],
                )
            finally:
                await blocker.rollback()
                await _cancel_pending(waiting)
                await _cancel_pending(applying)
    finally:
        await blocker.rollback()
        blocker.close()
    async with (
        await mariadb.Database.initialize(config) as app,
        app.transaction() as tx,
    ):
        await tx.execute(mariadb.insert(NativeAccount(id=3, role="user")))
        current = await tx.fetch_all(
            mariadb.select(NativeAccount).order_by(NativeAccount.id.asc())
        )
    assert_eq(
        [(row.id, row.role) for row in current],
        [(1, "admin"), (2, "user"), (3, "user")],
    )
    assert_eq([p.dump() for p in (first, expansion, roles)], originals)


async def _cancel_pending[T](task: asyncio.Task[T] | None) -> None:
    """Join this test's task even when setup fails before it is assigned."""
    if task is not None:
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)
