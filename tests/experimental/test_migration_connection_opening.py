"""Opening deadlines and partial native transport ownership at the public seam."""

import asyncio
from collections.abc import AsyncGenerator
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Literal

from anyio import CancelScope, TemporaryDirectory
from anyio import Path as AsyncPath
from snektest import Param, assert_eq, assert_raises, fail, fixture, load_fixture, test

from snekql import mariadb
from snekql.experimental import migrations as m
from snekql.testing.mariadb import temporary_mariadb_server
from tests.experimental.test_migration_io_deadlines import NativeAccount, NativeInitial
from tests.mariadb.test_required_tls import tls_peer


@dataclass
class _UnansweredPeer:
    """A real listening transport, not a database protocol implementation."""

    port: int
    accepted: asyncio.Queue[asyncio.StreamReader]


@fixture
async def unanswered_peer() -> AsyncGenerator[_UnansweredPeer]:
    """Own all accepted sockets, even when a test fails before receiving one."""
    accepted: asyncio.Queue[asyncio.StreamReader] = asyncio.Queue()
    writers: list[asyncio.StreamWriter] = []

    def accept(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        writers.append(writer)
        accepted.put_nowait(reader)

    async with await asyncio.start_server(accept, "127.0.0.1", 0) as listener:
        try:
            yield _UnansweredPeer(listener.sockets[0].getsockname()[1], accepted)
        finally:
            for writer in writers:
                writer.close()
            await asyncio.gather(*(writer.wait_closed() for writer in writers))


@test(mark="slow")
async def native_opening_uses_acquisition_budget_and_closes_unanswered_handshake() -> (
    None
):
    """An accepted TCP connection is not yet an acquired migration session."""
    peer = await load_fixture(unanswered_peer())
    config = mariadb.Config(
        database="unopened",
        user="not_authenticated",
        host="127.0.0.1",
        port=peer.port,
        acquire_timeout=0.15,
        operation_timeout=5,
    )

    lifetime = m.connect(config)

    async def open_target() -> None:
        async with lifetime:
            fail("target yielded without database handshake")

    opening = asyncio.create_task(open_target())
    try:
        reader = await asyncio.wait_for(peer.accepted.get(), timeout=2)
        # Detect an absent library deadline without cancelling as the test action.
        done, _ = await asyncio.wait({opening}, timeout=1)
        assert_eq(bool(done), True, msg="native opening acquisition deadline ignored")
        with assert_raises(mariadb.PoolTimeoutError) as error:
            await opening
        assert "opening migration connection" in str(error.exception)
        await lifetime.wait_closed()
        # Real peer EOF, not an internal connection/task flag. No greeting was
        # sent, so the client must send zero authentication or SQL bytes.
        assert_eq(await asyncio.wait_for(reader.read(), timeout=1), b"")
    finally:
        if not opening.done():
            opening.cancel()
        await asyncio.gather(opening, return_exceptions=True)


@test(mark="slow")
async def required_native_tls_is_not_opportunistic_during_migration_opening() -> None:
    """The shared Config's required TLS cannot silently authenticate over plaintext."""
    async with TemporaryDirectory() as directory:
        client = AsyncPath(directory) / "plaintext-client"
        await client.write_text(
            '#!/bin/sh\nexec mariadb --no-defaults --skip-ssl "$@"\n'
        )
        await client.chmod(0o700)
        async with temporary_mariadb_server(
            auth="password",
            transports={"tcp"},
            client=Path(client),
            data_directory=Path(directory) / "data",
            server_args=("--skip-ssl",),
        ) as server:
            config = replace(server.config(transport="tcp"), tls=mariadb.TLSConfig())
            with assert_raises(mariadb.DatabaseRuntimeError) as error:
                async with m.connect(config):
                    pass
            assert "does not support required TLS" in str(error.exception)


@test(
    [
        Param[Literal["task", "scope"]](value="task", name="task"),
        Param[Literal["task", "scope"]](value="scope", name="scope"),
    ],
    mark="slow",
)
async def cancelled_native_opening_keeps_the_partial_socket_owned(
    mode: Literal["task", "scope"],
) -> None:
    """Caller cancellation survives cleanup; operation_timeout is not the open budget."""
    peer = await load_fixture(unanswered_peer())
    config = mariadb.Config(
        database="unopened",
        user="not_authenticated",
        host="127.0.0.1",
        port=peer.port,
        acquire_timeout=3,
        operation_timeout=0.01,
    )
    scope = CancelScope()
    lifetime = m.connect(config)

    async def open_target() -> None:
        with scope:
            async with lifetime:
                fail("target yielded without database handshake")

    opening = asyncio.create_task(open_target())
    try:
        reader = await asyncio.wait_for(peer.accepted.get(), timeout=2)
        await asyncio.sleep(0.05)
        assert_eq(
            opening.done(), False, msg="opening charged to checked-out I/O budget"
        )
        if mode == "task":
            opening.cancel()
            with assert_raises(asyncio.CancelledError):
                await opening
        else:
            scope.cancel()
            await opening
            assert scope.cancelled_caught
        await lifetime.wait_closed()
        assert_eq(await asyncio.wait_for(reader.read(), timeout=1), b"")
    finally:
        if not opening.done():
            opening.cancel()
        await asyncio.gather(opening, return_exceptions=True)


@test(mark="slow")
async def verified_tls_opening_deploys_frozen_role_packages_and_ordinary_typed_app() -> (
    None
):
    """The owned opener is shared with the runtime, not a separate migration transport."""
    peer = await load_fixture(tls_peer())
    config = replace(peer.config, acquire_timeout=2, operation_timeout=1)
    fixed = Path(__file__).parent / "fixtures" / "role-interruption" / "mariadb"
    first = m.Package.load((fixed / "001_accounts.json").read_text())
    expansion = m.Package.load((fixed / "002_expand.json").read_text())
    roles = m.Package.load((fixed / "003_roles.json").read_text())
    originals = (first.dump(), expansion.dump(), roles.dump())
    async with m.connect(config) as target:
        assert_eq(await target.status(), ())
        # The opening scope must end before yielding; caller time is not charged.
        await asyncio.sleep(2.1)
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
        original = await target.prepare(roles, schema_writers_excluded=True)
        wire = original.dump()
        assert_eq(await target.apply(m.Prepared.load(wire)), "applied")
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
    assert_eq((first.dump(), expansion.dump(), roles.dump()), originals)
