"""Native advisory-lock refusal differs from interrupted, unsafe driver I/O."""

import asyncio
import time
from dataclasses import replace
from pathlib import Path
from typing import Literal

import aiomysql
import anyio
from snektest import Param, assert_eq, assert_raises, load_fixture, test

from snekql import mariadb
from snekql.errors import DatabaseOperationTimeoutError, MigrationLockTimeoutError
from snekql.experimental import migrations as m
from tests.experimental.test_migration_io_deadlines import NativeAccount, NativeInitial
from tests.experimental.test_migration_local_guard import _cancel_pending
from tests.experimental.test_migration_role_interruption import (
    _wait_disconnected,
    _waiting_update,
)
from tests.experimental.test_migration_targets import provide_package_server


@test(
    [
        Param[Literal["refusal", "grant", "operation", "task", "scope"]](
            value="refusal", name="refusal"
        ),
        Param[Literal["refusal", "grant", "operation", "task", "scope"]](
            value="grant", name="grant"
        ),
        Param[Literal["refusal", "grant", "operation", "task", "scope"]](
            value="operation", name="operation"
        ),
        Param[Literal["refusal", "grant", "operation", "task", "scope"]](
            value="task", name="task"
        ),
        Param[Literal["refusal", "grant", "operation", "task", "scope"]](
            value="scope", name="scope"
        ),
    ],
    mark="slow",
)
async def server_wait_disposition_preserves_owner_and_original_role_evidence(  # noqa: PLR0915 - keep the real competing consumer lifecycle visible
    mode: Literal["refusal", "grant", "operation", "task", "scope"],
) -> None:
    """Known refusal permits reuse; interrupted I/O closes only the contender."""
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
        async with (
            m.connect(replace(config, operation_timeout=5)) as owner,
            m.connect(
                replace(
                    config,
                    acquire_timeout=0.25 if mode == "refusal" else 1.25,
                    operation_timeout=0.35 if mode == "operation" else 5,
                )
            ) as contender,
        ):
            original = await owner.prepare(roles, schema_writers_excluded=True)
            reviewed = await contender.prepare(roles, schema_writers_excluded=True)
            wire = reviewed.dump()
            applying = asyncio.create_task(
                owner.apply(m.Prepared.load(original.dump()))
            )
            waiting: asyncio.Task[str | None] | None = None
            scope = anyio.CancelScope()
            try:
                observed = await _waiting_update(config)
                assert observed["modified"] >= 1

                async def compete() -> str | None:
                    with scope:
                        return await contender.apply(m.Prepared.load(wire))
                    return None

                started = time.perf_counter()
                waiting = asyncio.create_task(compete())
                waiting_id = await _waiting_advisory(config)
                if mode == "grant":
                    await blocker.rollback()
                    assert_eq(await applying, "applied")
                    assert_eq(await waiting, "already_applied")
                else:
                    if mode == "refusal":
                        done, _ = await asyncio.wait({waiting}, timeout=0.8)
                        assert done, "server advisory-lock acquisition budget ignored"
                        with assert_raises(MigrationLockTimeoutError) as refusal:
                            await waiting
                        assert "advisory lock" in str(refusal.exception)
                        elapsed = time.perf_counter() - started
                        assert elapsed >= 0.15, (
                            "fractional advisory-lock acquisition wait truncated"
                        )
                        assert elapsed < 1, (
                            "server advisory-lock acquisition budget ignored"
                        )
                        # Reusable synchronized contender can read ongoing durable evidence.
                        assert_eq(
                            sorted(
                                (p.revision, p.phase) for p in await contender.status()
                            ),
                            [
                                ("001_accounts", "complete"),
                                ("002_expand", "complete"),
                                ("003_roles", "uncertain"),
                            ],
                        )
                    else:
                        if mode == "operation":
                            with assert_raises(
                                DatabaseOperationTimeoutError
                            ) as deadline:
                                await waiting
                            assert_eq(deadline.exception.operation, "migration execute")
                            assert_eq(deadline.exception.timeout, 0.35)
                        elif mode == "task":
                            waiting.cancel()
                            with assert_raises(asyncio.CancelledError):
                                await waiting
                        else:
                            scope.cancel()
                            await waiting
                            assert scope.cancelled_caught
                        with assert_raises(m.PackageError) as closed:
                            await contender.status()
                        assert "migration target is closed" in str(closed.exception)
                        # Await expiry/socket close is not evidence the server stopped waiting.
                        await _wait_disconnected(config, waiting_id)
                    assert_eq(applying.done(), False)
                    still = await _waiting_update(config)
                    assert_eq(still["id"], observed["id"])
                    assert still["modified"] >= 1
                    await blocker.rollback()
                    assert_eq(await applying, "applied")
                # Fresh original evidence observes the winner, never fabricates retry work.
                if mode in {"refusal", "grant"}:
                    assert_eq(
                        await contender.apply(m.Prepared.load(wire)), "already_applied"
                    )
                else:
                    async with m.connect(config) as fresh:
                        assert_eq(
                            await fresh.apply(m.Prepared.load(wire)), "already_applied"
                        )
                assert_eq(reviewed.dump(), wire)
                assert_eq(
                    sorted((p.revision, p.phase) for p in await owner.status()),
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
        [(r.id, r.role) for r in current], [(1, "admin"), (2, "user"), (3, "user")]
    )
    assert_eq([p.dump() for p in (first, expansion, roles)], originals)


async def _waiting_advisory(config: mariadb.Config) -> int:
    """Independently observe this isolated server's actual GET_LOCK waiter."""
    async with await mariadb.Database.initialize(config) as app:
        async with asyncio.timeout(2):
            while True:
                async with app.transaction() as tx:
                    rows = await tx.fetch_all(
                        mariadb.raw(
                            "SELECT ID AS id FROM information_schema.PROCESSLIST "
                            "WHERE ID != CONNECTION_ID() AND STATE='User lock' "
                            "AND INFO LIKE 'SELECT GET_LOCK(%'"
                        )
                    )
                if rows:
                    assert isinstance(rows[0]["id"], int)
                    return rows[0]["id"]
                await asyncio.sleep(0.01)
