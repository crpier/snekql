"""Required TLS rejects plaintext before authentication on every connection."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator
from contextlib import suppress
from dataclasses import replace
from pathlib import Path

from anyio import Path as AsyncPath
from anyio import TemporaryDirectory, run_process
from snektest import (
    assert_eq,
    assert_not_in,
    assert_raises,
    fixture,
    load_fixture,
    test,
)

from snekql import mariadb
from snekql.testing.mariadb import temporary_mariadb_server


class _GreetingProxy:
    """A TCP peer that can remove TLS capability without reading any real secrets."""

    def __init__(self, config: mariadb.Config) -> None:
        self.config: mariadb.Config = config
        self.deny_tls: bool = False
        self.pause_greeting: bool = False
        self.greeting_paused: asyncio.Event = asyncio.Event()
        self.denied_bytes: list[int] = []
        self.upstream_port: int = config.port
        self.tasks: list[asyncio.Task[None]] = []
        self.writers: set[asyncio.StreamWriter] = set()

    def accept(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        self.tasks.append(asyncio.create_task(self._forward(reader, writer)))

    async def disconnect(self) -> None:
        for writer in tuple(self.writers):
            writer.close()
        await asyncio.gather(*self.tasks)
        # Let the peer's StreamReader observe the completed TCP close too.
        await asyncio.sleep(0)

    async def _forward(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        upstream_writer: asyncio.StreamWriter | None = None
        self.writers.add(writer)
        try:
            upstream_reader, upstream_writer = await asyncio.open_connection(
                "127.0.0.1", self.upstream_port
            )
            self.writers.add(upstream_writer)
            header = await upstream_reader.readexactly(4)
            greeting = bytearray(
                await upstream_reader.readexactly(int.from_bytes(header[:3], "little"))
            )
            if self.pause_greeting:
                self.greeting_paused.set()
                self.denied_bytes.append(len(await reader.read(65536)))
                return
            denied = self.deny_tls
            if denied:
                # Protocol v10: version string, thread id, eight-byte salt,
                # filler, then the low capability word. SSL is its bit 11.
                capabilities = greeting.index(0, 1) + 14
                greeting[capabilities + 1] &= ~0x08
            writer.write(header + greeting)
            await writer.drain()
            if denied:
                self.denied_bytes.append(len(await reader.read(65536)))
            else:
                await asyncio.gather(
                    self._pipe(reader, upstream_writer),
                    self._pipe(upstream_reader, writer),
                )
        except ConnectionError, asyncio.IncompleteReadError:
            pass
        finally:
            for peer in (writer, upstream_writer):
                if peer is not None:
                    peer.close()
                    with suppress(ConnectionError):
                        await peer.wait_closed()
                    self.writers.discard(peer)

    @staticmethod
    async def _pipe(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            while chunk := await reader.read(65536):
                writer.write(chunk)
                await writer.drain()
        finally:
            writer.close()


@fixture
async def tls_peer(
    *, server_tls_version: str | None = None
) -> AsyncGenerator[_GreetingProxy]:
    """Provide real verified TLS with a controllable server greeting at the TCP edge."""

    async with TemporaryDirectory() as directory:
        certificate = Path(directory) / "server.crt"
        private_key = Path(directory) / "server.key"
        generated = await run_process(
            (
                "openssl",
                "req",
                "-x509",
                "-newkey",
                "rsa:2048",
                "-nodes",
                "-keyout",
                str(private_key),
                "-out",
                str(certificate),
                "-days",
                "1",
                "-subj",
                "/CN=127.0.0.1",
                "-addext",
                "subjectAltName=IP:127.0.0.1",
            ),
            check=False,
        )
        assert_eq(generated.returncode, 0, msg=generated.stderr.decode())
        client = AsyncPath(directory) / "plaintext-client"
        await client.write_text(
            '#!/bin/sh\nexec mariadb --no-defaults --skip-ssl "$@"\n'
        )
        await client.chmod(0o700)
        version_options = (
            ()
            if server_tls_version is None
            else (f"--tls-version={server_tls_version}",)
        )
        async with temporary_mariadb_server(
            auth="password",
            client=Path(client),
            data_directory=Path(directory) / "data",
            transports={"tcp"},
            server_args=(
                f"--ssl-ca={certificate}",
                f"--ssl-cert={certificate}",
                f"--ssl-key={private_key}",
                *version_options,
            ),
        ) as server:
            proxy = _GreetingProxy(
                replace(
                    server.config(transport="tcp"),
                    tls=mariadb.TLSConfig(ca_file=certificate),
                    pool_size=2,
                )
            )
            async with await asyncio.start_server(
                proxy.accept, "127.0.0.1", 0
            ) as listener:
                proxy.config = replace(
                    proxy.config, port=listener.sockets[0].getsockname()[1]
                )
                try:
                    yield proxy
                finally:
                    await proxy.disconnect()


@test(mark="slow")
async def required_tls_rejects_plaintext_server() -> None:
    """Explicit TLS cannot become plaintext against a password-authenticated server."""

    async with TemporaryDirectory() as directory:
        client = AsyncPath(directory) / "plaintext-client"
        await client.write_text(
            '#!/bin/sh\nexec mariadb --no-defaults --skip-ssl "$@"\n'
        )
        await client.chmod(0o700)
        async with temporary_mariadb_server(
            auth="password",
            client=Path(client),
            data_directory=Path(directory) / "data",
            server_args=("--skip-ssl",),
            transports={"tcp"},
        ) as server:
            with assert_raises(mariadb.DatabaseRuntimeError):
                async with await mariadb.Database.initialize(
                    replace(server.config(transport="tcp"), tls=mariadb.TLSConfig())
                ):
                    pass


@test(mark="slow")
async def required_tls_sends_no_authentication_to_plaintext_peer() -> None:
    """An SSL-stripped greeting receives no client response, not even auth metadata."""

    peer = await load_fixture(tls_peer())
    peer.deny_tls = True

    with assert_raises(mariadb.DatabaseRuntimeError) as rejected:
        async with await mariadb.Database.initialize(peer.config):
            pass
    await peer.disconnect()

    assert_eq(peer.denied_bytes, [0])
    assert_not_in(peer.config.password, str(rejected.exception))


@test(mark="slow")
async def pool_growth_rejects_plaintext_before_authentication() -> None:
    """A failed second physical connection cannot expose authentication data."""

    peer = await load_fixture(tls_peer())
    async with (
        await mariadb.Database.initialize(peer.config) as database,
        database.transaction(),
    ):
        peer.deny_tls = True
        with assert_raises(mariadb.DatabaseRuntimeError):
            async with database.transaction():
                pass
        peer.deny_tls = False
        async with database.transaction():
            pass
    await peer.disconnect()

    assert_eq(peer.denied_bytes, [0])


@test(mark="slow")
async def replacement_rejects_plaintext_before_authentication() -> None:
    """Replacing a disconnected idle connection uses the same required-TLS guard."""

    peer = await load_fixture(tls_peer())
    async with await mariadb.Database.initialize(peer.config) as database:
        await peer.disconnect()
        peer.deny_tls = True
        with assert_raises(mariadb.DatabaseRuntimeError):
            async with database.transaction():
                pass
        peer.deny_tls = False
        async with database.transaction():
            pass
    await peer.disconnect()

    assert_eq(peer.denied_bytes, [0])


@test(mark="slow")
async def required_tls_rejects_untrusted_certificate() -> None:
    """An advertised TLS capability does not relax certificate-chain validation."""

    peer = await load_fixture(tls_peer())
    with assert_raises(mariadb.DatabaseRuntimeError):
        async with await mariadb.Database.initialize(
            replace(peer.config, tls=mariadb.TLSConfig())
        ):
            pass


@test(mark="slow")
async def required_tls_rejects_wrong_hostname() -> None:
    """A trusted certificate for an IP does not authenticate the localhost name."""

    peer = await load_fixture(tls_peer())
    with assert_raises(mariadb.DatabaseRuntimeError):
        async with await mariadb.Database.initialize(
            replace(peer.config, host="localhost")
        ):
            pass


@test(mark="slow")
async def required_tls_rejects_legacy_protocol() -> None:
    """A server offering only TLS 1.1 cannot lower the client's minimum version."""

    peer = await load_fixture(tls_peer(server_tls_version="TLSv1.1"))
    with assert_raises(mariadb.DatabaseRuntimeError):
        async with await mariadb.Database.initialize(peer.config):
            pass


@test(mark="slow")
async def cancelled_tls_growth_releases_connection_capacity() -> None:
    """Cancelling a handshake closes its socket without consuming a pool slot."""

    peer = await load_fixture(tls_peer())
    async with (
        await mariadb.Database.initialize(peer.config) as database,
        database.transaction(),
    ):
        peer.pause_greeting = True

        async def acquire_connection() -> None:
            async with database.transaction():
                pass

        pending = asyncio.create_task(acquire_connection())
        try:
            await asyncio.wait_for(peer.greeting_paused.wait(), timeout=2)
        finally:
            pending.cancel()
            with assert_raises(asyncio.CancelledError):
                await pending
            peer.pause_greeting = False
        async with database.transaction():
            pass
    await peer.disconnect()

    assert_eq(peer.denied_bytes, [0])
