"""Real COMMIT request/acknowledgement loss must be settled by fresh durable evidence."""

import asyncio
from contextlib import suppress
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


class _CommitProxy:
    """Forward a real plaintext protocol; omit one request or actual server reply only."""

    def __init__(self, upstream: mariadb.Config) -> None:
        self.upstream = upstream
        self.arm: tuple[int, Literal["before", "after", "eof"]] | None = None
        self.commits = 0
        self.hit = asyncio.Event()
        self.disposed = asyncio.Event()
        self.server_ok: bytes | None = None
        self.session_id: int | None = None
        self.forwarded: list[str] = []
        self.tasks: list[asyncio.Task[None]] = []
        self.writers: set[asyncio.StreamWriter] = set()

    def accept(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        """Own each real socket and forwarding task until test teardown."""
        self.tasks.append(asyncio.create_task(self._connection(reader, writer)))

    @staticmethod
    async def _packet(reader: asyncio.StreamReader) -> tuple[bytes, bytes]:
        """Preserve actual packet framing/content, including greeting/authentication."""
        header = await reader.readexactly(4)
        return header, await reader.readexactly(int.from_bytes(header[:3], "little"))

    async def _connection(  # noqa: C901, PLR0915 - real framing, fault and physical ownership kept together
        self, client: asyncio.StreamReader, downstream: asyncio.StreamWriter
    ) -> None:
        """Never synthesize a greeting, SQL result, receipt or driver response."""
        peers = [downstream]
        pumps: list[asyncio.Task[None]] = []
        self.writers.add(downstream)
        affected = False
        waiting_ack = False
        close_on_ack = False
        try:
            server, upstream = await asyncio.open_connection(
                self.upstream.host, self.upstream.port
            )
            self.writers.add(upstream)
            peers.append(upstream)

            async def requests() -> None:
                """Drop selected COMMIT before forwarding, or mark its real reply."""
                nonlocal affected, waiting_ack, close_on_ack
                while True:
                    header, body = await self._packet(client)
                    if body[:1] == b"\x03":
                        sql = body[1:].decode("utf-8")
                        if self.arm is not None and sql.upper() == "COMMIT":
                            self.commits += 1
                            if self.commits == self.arm[0]:
                                where = self.arm[1]
                                self.arm = None
                                affected = True
                                if where == "before":
                                    self.hit.set()
                                    continue
                                waiting_ack = True
                                close_on_ack = where == "eof"
                        self.forwarded.append(sql)
                    upstream.write(header + body)
                    await upstream.drain()

            async def responses() -> None:
                """Retain the actual server COMMIT OK without delivering it to client."""
                nonlocal waiting_ack
                greeting = True
                while True:
                    header, body = await self._packet(server)
                    if greeting:
                        assert body[:1] == b"\x0a"
                        offset = body.index(0, 1) + 1
                        self.session_id = int.from_bytes(
                            body[offset : offset + 4], "little"
                        )
                        greeting = False
                    if waiting_ack:
                        assert body[:1] == b"\x00", repr(body)
                        waiting_ack = False
                        self.server_ok = body
                        self.hit.set()
                        if close_on_ack:
                            return
                        continue
                    downstream.write(header + body)
                    await downstream.drain()

            pumps = [asyncio.create_task(requests()), asyncio.create_task(responses())]
            done, _ = await asyncio.wait(pumps, return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                with suppress(asyncio.IncompleteReadError, ConnectionError):
                    await task
        finally:
            for task in pumps:
                task.cancel()
            await asyncio.gather(*pumps, return_exceptions=True)
            for writer in peers:
                writer.close()
                with suppress(ConnectionError):
                    await writer.wait_closed()
                self.writers.discard(writer)
            if affected:
                self.disposed.set()

    async def close(self) -> None:
        """Close only owned sockets, join pumps and surface unexpected fixture failures."""
        for writer in tuple(self.writers):
            writer.close()
        await asyncio.gather(*self.tasks)


@test(
    [
        Param[
            Literal[
                "first_before",
                "first_after",
                "final_before",
                "final_after",
                "first_eof",
            ]
        ](value=mode, name=mode)
        for mode in (
            "first_before",
            "first_after",
            "final_before",
            "final_after",
            "first_eof",
        )
    ],
    mark="slow",
)
async def missing_commit_response_requires_fresh_original_evidence(  # noqa: PLR0915 - network/evidence/recovery
    mode: Literal[
        "first_before", "first_after", "final_before", "final_after", "first_eof"
    ],
) -> None:
    """Client COMMIT error alone proves neither rollback nor absence of completion."""
    completed = mode.startswith("final")
    acknowledged = 3 if completed else (0 if mode == "first_before" else 1)
    with TemporaryDirectory(prefix="commit-", dir=".snektest") as directory:
        async with temporary_mariadb_server(
            auth="password", transports={"tcp"}, data_directory=Path(directory) / "data"
        ) as server:
            direct = server.config(transport="tcp")
            proxy = _CommitProxy(direct)
            async with await asyncio.start_server(
                proxy.accept, "127.0.0.1", 0
            ) as listener:
                config = replace(
                    direct,
                    port=listener.sockets[0].getsockname()[1],
                    operation_timeout=0.3,
                )
                observer = await aiomysql.connect(
                    host=direct.host,
                    port=direct.port,
                    user=direct.user,
                    password=direct.password,
                    db=direct.database,
                    autocommit=True,
                )
                try:
                    fixed = Path(__file__).parent / "fixtures/role-interruption/mariadb"
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
                        await mariadb.Database.initialize(direct) as app,
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
                    async with m.connect(config) as target:
                        proxy.arm = (
                            3 if completed else 1,
                            "before"
                            if mode.endswith("before")
                            else "eof"
                            if mode.endswith("eof")
                            else "after",
                        )
                        proxy.commits = 0
                        proxy.forwarded.clear()
                        applying = asyncio.create_task(
                            target.apply(m.Prepared.load(wire))
                        )
                        try:
                            await asyncio.wait_for(proxy.hit.wait(), timeout=5)
                            assert_eq(
                                proxy.server_ok is not None, not mode.endswith("before")
                            )
                            async with observer.cursor() as cursor:
                                await cursor.execute(
                                    "SELECT id,role FROM accounts ORDER BY id"
                                    if completed
                                    else "SELECT id,is_admin,role FROM accounts ORDER BY id"
                                )
                                expected = (
                                    ((1, "admin"), (2, "user"))
                                    if completed
                                    else ((1, 1, None), (2, 0, None))
                                    if mode == "first_before"
                                    else ((1, 1, "user"), (2, 0, "user"))
                                )
                                assert_eq(await cursor.fetchall(), expected)
                                await cursor.execute(
                                    "SELECT phase,acknowledged FROM snekql_experimental_migrations WHERE revision='003_roles'"
                                )
                                assert_eq(
                                    await cursor.fetchall(),
                                    (
                                        (
                                            "complete" if completed else "started",
                                            acknowledged,
                                        ),
                                    ),
                                )
                            if mode.endswith("eof"):
                                with assert_raises(aiomysql.OperationalError) as error:
                                    await applying
                                assert_eq(error.exception.args[0], 2013)
                            else:
                                with assert_raises(
                                    mariadb.DatabaseOperationTimeoutError
                                ) as timeout:
                                    await applying
                                assert_eq(
                                    timeout.exception.operation, "migration commit"
                                )
                            with assert_raises(m.PackageError) as closed:
                                await target.status()
                            assert "closed" in str(closed.exception)
                        finally:
                            if not applying.done():
                                applying.cancel()
                            await asyncio.gather(applying, return_exceptions=True)
                    await asyncio.wait_for(proxy.disposed.wait(), timeout=5)
                    assert proxy.session_id is not None
                    await _wait_disconnected(direct, proxy.session_id)
                    assert_eq(
                        [sql for sql in proxy.forwarded if sql.upper() == "ROLLBACK"],
                        [],
                    )
                    first_update = next(
                        sql
                        for sql in proxy.forwarded
                        if sql.startswith("UPDATE `accounts`")
                    )
                    async with m.connect(config) as fresh:
                        progress = next(
                            p for p in await fresh.status() if p.revision == "003_roles"
                        )
                        assert_eq(
                            (progress.phase, progress.acknowledged_steps),
                            ("complete" if completed else "uncertain", acknowledged),
                        )
                        if not completed:
                            with assert_raises(m.PackageError):
                                await fresh.apply(m.Prepared.load(wire))
                            recovery = await fresh.inspect_recovery(
                                m.Prepared.load(wire), schema_writers_excluded=True
                            )
                            assert_eq(
                                (recovery.disposition, recovery.acknowledged_steps),
                                ("retry_remaining", acknowledged),
                            )
                            assert_eq(
                                await fresh.resume(
                                    recovery, schema_writers_excluded=True
                                ),
                                "applied",
                            )
                        assert_eq(
                            await fresh.apply(m.Prepared.load(wire)), "already_applied"
                        )
                        assert_eq(
                            sorted((p.revision, p.phase) for p in await fresh.status()),
                            [
                                ("001_accounts", "complete"),
                                ("002_expand", "complete"),
                                ("003_roles", "complete"),
                            ],
                        )
                    assert_eq(
                        proxy.forwarded.count(first_update),
                        2 if mode == "first_before" else 1,
                    )
                    async with observer.cursor() as cursor:
                        await cursor.execute(
                            "SELECT * FROM snekql_experimental_migrations ORDER BY revision"
                        )
                        assert_eq((await cursor.fetchall())[: len(before)], before)
                    async with (
                        await mariadb.Database.initialize(direct) as app,
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
                    assert_eq([p.dump() for p in packages], originals)
                    assert_eq(original.dump(), wire)
                finally:
                    observer.close()
                    await proxy.close()
