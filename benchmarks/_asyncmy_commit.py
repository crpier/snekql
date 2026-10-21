"""Inject COMMIT transport faults through a single-client loopback packet relay.

Only for the owned plaintext test server. No TLS, compression, pipelining, large
packets or prepared-statement protocol support is intended. Packets (including
handshake credentials) are forwarded in memory and never recorded.
"""

import asyncio
from importlib.metadata import version
from typing import Any

_MAX_PACKET = 1024 * 1024


async def _packet(reader: asyncio.StreamReader) -> tuple[bytes, bytes]:
    header = await reader.readexactly(4)
    size = int.from_bytes(header[:3], "little")
    if size > _MAX_PACKET:
        message = "Probe relay received an unsupported large packet"
        raise ValueError(message)
    body = await reader.readexactly(size)
    return header, body


class _CommitRelay:
    def __init__(self, host: str, port: int, scenario: str) -> None:
        self.host = host
        self.scenario = scenario
        self.port = port
        self.commit_seen = False
        self.commit_forwarded = False
        self.server_ok_seen = False
        self.failure: Exception | None = None
        self.tasks: set[asyncio.Task[None]] = set()
        self.writers: list[asyncio.StreamWriter] = []

    def stop(self) -> None:
        for writer in self.writers:
            writer.close()

    async def _requests(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        while True:
            header, body = await _packet(reader)
            if body == b"\x03COMMIT":
                self.commit_seen = True
                if self.scenario == "commit-drop-before":
                    self.stop()
                    return
                self.commit_forwarded = True
            writer.write(header + body)
            await writer.drain()

    async def _responses(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        while True:
            header, body = await _packet(reader)
            if self.commit_forwarded:
                # The driver issues one command at a time; the preceding INSERT
                # has completed before COMMIT. Its next reply must be COMMIT's.
                if not body or body[0] != 0:
                    message = "Probe expected a successful COMMIT reply"
                    raise RuntimeError(message)
                self.server_ok_seen = True
                if self.scenario == "commit-drop-ack":
                    self.stop()  # Deliberately withhold the observed OK packet.
                    return
            writer.write(header + body)
            await writer.drain()

    async def _pump(self, operation: Any) -> None:
        try:
            await operation
        except asyncio.IncompleteReadError, ConnectionError:
            pass
        finally:
            self.stop()

    async def handle(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        task = asyncio.current_task()
        assert task is not None  # noqa: S101 - asyncio server callback runs in a task
        self.tasks.add(task)
        self.writers.append(writer)
        try:
            backend_reader, backend_writer = await asyncio.open_connection(
                self.host, self.port
            )
            self.writers.append(backend_writer)
            async with asyncio.TaskGroup() as group:
                group.create_task(self._pump(self._requests(reader, backend_writer)))
                group.create_task(self._pump(self._responses(backend_reader, writer)))
        except Exception as error:
            self.failure = error
        finally:
            self.stop()
            self.tasks.discard(task)

    async def close(self) -> None:
        self.stop()
        tasks = tuple(self.tasks)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await asyncio.gather(
            *(writer.wait_closed() for writer in self.writers), return_exceptions=True
        )


async def probe(
    driver: Any, options: dict[str, object], scenario: str
) -> dict[str, object]:
    """Observe the client exception separately from the server's committed row."""
    relay = _CommitRelay(str(options["host"]), int(str(options["port"])), scenario)
    server = await asyncio.start_server(relay.handle, "127.0.0.1", 0)
    connection = None
    observer = None
    try:
        async with asyncio.timeout(30):
            observer = await driver.connect(**options)
            table = f"commit_probe_{driver.__name__}"  # Fixed module names only.
            async with observer.cursor() as cursor:
                await cursor.execute(
                    f"CREATE TABLE {table} (id INT PRIMARY KEY) ENGINE=InnoDB"
                )
            connection = await driver.connect(
                **{
                    **options,
                    "host": "127.0.0.1",
                    "port": server.sockets[0].getsockname()[1],
                }
            )
            await connection.begin()
            async with connection.cursor() as cursor:
                await cursor.execute(f"INSERT INTO {table} VALUES (1)")  # noqa: S608 - fixed driver names
            error_code = None
            error_type = None
            commit_returned = False
            try:
                await connection.commit()
                commit_returned = True
            except driver.Error as error:
                error_code = error.args[0]
                error_type = type(error).__name__
            if relay.failure is not None:
                raise relay.failure
            async with observer.cursor() as cursor:
                await cursor.execute(f"SELECT COUNT(*) FROM {table}")  # noqa: S608 - fixed driver names
                visible_writes = (await cursor.fetchone())[0]
            return {
                "driver": driver.__name__,
                "version": version(driver.__name__),
                "server": observer.get_server_info(),
                "commit_returned": commit_returned,
                "error_code": error_code,
                "error_type": error_type,
                "commit_seen": relay.commit_seen,
                "commit_forwarded": relay.commit_forwarded,
                "server_ok_seen": relay.server_ok_seen,
                "visible_writes": visible_writes,
            }
    finally:
        if connection is not None:
            connection.close()
        if observer is not None:
            observer.close()
        server.close()
        await server.wait_closed()
        await relay.close()
