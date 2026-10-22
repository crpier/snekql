"""Interrupt owned plaintext startup traffic; never retain packet contents.

The single-client relay supports only the bounded, non-pipelined text protocol
used here. Reuse the existing relay transport/cleanup, not driver internals.
"""

import asyncio
from dataclasses import replace
from typing import Any

from benchmarks._asyncmy_commit import _CommitRelay, _packet
from snekql import mariadb


class _SettingsRelay(_CommitRelay):
    def __init__(self, host: str, port: int, *, reject: bool) -> None:
        super().__init__(host, port, "startup-settings")
        self.reject = reject
        self.settings_seen = asyncio.Event()
        self.client_finished = asyncio.Event()
        self.client_eof = False
        self.stopped_before_observation = False

    def stop(self) -> None:
        if not self.client_finished.is_set():
            self.stopped_before_observation = True
        super().stop()

    async def _requests(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        while True:
            header, body = await _packet(reader)
            if header[3] == 0 and body.upper().startswith(b"\x03SET SESSION SQL_MODE"):
                self.settings_seen.set()
                if self.reject:
                    # Ask the real server to reject a deliberately invalid value.
                    # Preserve the command sequence; retain no original payload.
                    invalid = b"\x03SET SESSION sql_mode = 'SNEKQL_INVALID_MODE'"
                    writer.write(
                        len(invalid).to_bytes(3, "little") + header[3:] + invalid
                    )
                    await writer.drain()
                # Otherwise withhold the statement. Observe the client closing itself
                # before the inherited pump's finally can close either transport.
                self.client_eof = await reader.read(1) == b""
                self.client_finished.set()
                return
            writer.write(header + body)
            await writer.drain()


async def _run(
    config: mariadb.Config, *, cancel: bool, reject: bool = False
) -> dict[str, Any]:
    relay = _SettingsRelay(config.host, config.port, reject=reject)
    listener = await asyncio.start_server(relay.handle, "127.0.0.1", 0)
    pending: asyncio.Task[mariadb.Database] | None = None
    error_type = None
    error_code = None
    public_error = False
    client_eof = False
    try:
        proxy_config = replace(
            config,
            port=listener.sockets[0].getsockname()[1],
            acquire_timeout=10 if cancel or reject else 0.5,
        )
        pending = asyncio.create_task(mariadb.Database.initialize(proxy_config))
        if cancel:
            await relay.settings_seen.wait()
            if pending.done():
                message = "initialization completed before cancellation barrier"
                raise RuntimeError(message)
            pending.cancel()
        try:
            await pending
        except (Exception, asyncio.CancelledError) as error:
            error_type = type(error).__name__
            public_error = isinstance(error, mariadb.DatabaseRuntimeError)
            error_code = (
                error.args[0] if error.args and type(error.args[0]) is int else None
            )
        try:
            async with asyncio.timeout(2):
                await relay.client_finished.wait()
            client_eof = relay.client_eof
        except TimeoutError:
            pass
        if relay.failure is not None:
            raise relay.failure
        async with (
            await mariadb.Database.initialize(config) as recovery,
            recovery.transaction() as transaction,
        ):
            row = await transaction.fetch_one(
                mariadb.raw("SELECT 42 AS answer, @@SESSION.time_zone AS zone")
            )
        return {
            "settings_seen": relay.settings_seen.is_set(),
            "error_type": error_type,
            "error_code": error_code,
            "public_error": public_error,
            "client_eof_before_cleanup": client_eof
            and not relay.stopped_before_observation,
            "relay_stopped_before_observation": relay.stopped_before_observation,
            "recovery_answer": row["answer"],
            "recovery_zone": row["zone"],
            "final_state": recovery.pool_stats().state,
        }
    finally:
        if pending is not None:  # ty: ignore[redundant-condition-strict] - setup can fail
            pending.cancel()
            await asyncio.gather(pending, return_exceptions=True)
            if not pending.cancelled() and pending.exception() is None:
                await pending.result().close()
        listener.close()
        await listener.wait_closed()
        await relay.close()


async def deadline_probe(config: mariadb.Config) -> dict[str, Any]:
    return await _run(config, cancel=False)


async def cancellation_probe(config: mariadb.Config) -> dict[str, Any]:
    return await _run(config, cancel=True)


async def rejected_setting_probe(config: mariadb.Config) -> dict[str, Any]:
    return await _run(config, cancel=False, reject=True)


class _AuthenticationRelay(_SettingsRelay):
    def __init__(self, host: str, port: int) -> None:
        super().__init__(host, port, reject=False)
        self.authentication_seen = asyncio.Event()

    async def _requests(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        del writer
        header, _ = await _packet(reader)
        if header[3] != 1:
            message = "expected initial plaintext authentication response"
            raise RuntimeError(message)
        self.authentication_seen.set()
        # Withhold the login packet; never inspect/store its authentication data.
        self.client_eof = await reader.read(1) == b""
        self.client_finished.set()


async def authentication_deadline_probe(config: mariadb.Config) -> dict[str, Any]:
    relay = _AuthenticationRelay(config.host, config.port)
    listener = await asyncio.start_server(relay.handle, "127.0.0.1", 0)
    pending: asyncio.Task[mariadb.Database] | None = None
    error_type = None
    watchdog_expired = False
    client_eof = False
    try:
        proxy = replace(
            config, port=listener.sockets[0].getsockname()[1], acquire_timeout=0.5
        )
        pending = asyncio.create_task(mariadb.Database.initialize(proxy))
        # A separate harness limit must not be mistaken for the Config deadline.
        done, _ = await asyncio.wait({pending}, timeout=2)
        if pending not in done:
            watchdog_expired = True
        else:
            try:
                await pending
            except Exception as error:
                error_type = type(error).__name__
            async with asyncio.timeout(2):
                await relay.client_finished.wait()
            client_eof = relay.client_eof and not relay.stopped_before_observation
        # Freeze evidence BEFORE cancellation/transport cleanup assists the driver.
        observation = {
            "authentication_seen": relay.authentication_seen.is_set(),
            "error_type": error_type,
            "watchdog_expired": watchdog_expired,
            "client_eof_before_cleanup": client_eof,
        }
        if relay.failure is not None:
            raise relay.failure
        pending.cancel()
        await asyncio.gather(pending, return_exceptions=True)
        async with (
            await mariadb.Database.initialize(config) as recovery,
            recovery.transaction() as transaction,
        ):
            row = await transaction.fetch_one(
                mariadb.raw("SELECT 42 AS answer, @@SESSION.time_zone AS zone")
            )
        return {
            **observation,
            "recovery_answer": row["answer"],
            "recovery_zone": row["zone"],
            "final_state": recovery.pool_stats().state,
        }
    finally:
        if pending is not None:  # ty: ignore[redundant-condition-strict] - setup can fail
            pending.cancel()
            await asyncio.gather(pending, return_exceptions=True)
            if not pending.cancelled() and pending.exception() is None:
                await pending.result().close()
        listener.close()
        await listener.wait_closed()
        await relay.close()
