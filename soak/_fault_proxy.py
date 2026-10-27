"""Owned loopback TCP fault control; never alters host networking or other peers."""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from dataclasses import dataclass


@dataclass
class Peer:
    """Connection-local blackhole state, shared only by its two relay directions."""

    withhold_reply: bool = False


class Proxy:
    """A bounded test peer whose current sockets can be cut without closing admission."""

    def __init__(self, host: str, port: int) -> None:
        self.host = host
        self.port = port
        self.writers: set[asyncio.StreamWriter] = set()
        self.tasks: list[asyncio.Task[None]] = []
        self.server_bytes_forwarded = 0
        self.blackhole_commit = False
        self.watch_commits = False
        self.commit_requests_forwarded = 0
        self.reply_held = asyncio.Event()
        self.server_reply: str | None = None

    def accept(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        self.writers.add(writer)
        self.tasks.append(asyncio.create_task(self.connect(reader, writer)))

    async def pump(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
        peer: Peer,
        *,
        from_server: bool,
    ) -> None:
        try:
            while True:
                # Plaintext test-only MySQL framing; never inspect credentials or
                # relay arbitrary endpoints. Fixtures keep each packet under 1 MiB.
                header = await reader.readexactly(4)
                size = int.from_bytes(header[:3], "little")
                if size > 1024 * 1024:
                    message = "fault proxy packet exceeds fixture bound"
                    raise ValueError(message)
                payload = await reader.readexactly(size)
                data = header + payload
                if (
                    not from_server
                    and payload[:1] == b"\x03"
                    and payload[1:].strip().upper() == b"COMMIT"
                ):
                    if self.watch_commits:
                        self.commit_requests_forwarded += 1
                    if self.blackhole_commit:
                        self.blackhole_commit = False
                        peer.withhold_reply = True
                if from_server and peer.withhold_reply:
                    self.server_reply = "ok" if payload[:1] == b"\x00" else "not-ok"
                    self.reply_held.set()
                    continue  # Keep the socket open but never forward the reply.
                writer.write(data)
                await writer.drain()
                if from_server:
                    self.server_bytes_forwarded += len(data)
                await asyncio.sleep(0)
        except OSError, asyncio.IncompleteReadError:
            pass  # A real peer disconnect is deliberately visible to the database.
        finally:
            writer.close()

    async def connect(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        owned_writers = [writer]
        try:
            peer, upstream = await asyncio.open_connection(self.host, self.port)
            self.writers.add(upstream)
            owned_writers.append(upstream)
            state = Peer()
            async with asyncio.TaskGroup() as group:
                group.create_task(self.pump(reader, upstream, state, from_server=False))
                group.create_task(self.pump(peer, writer, state, from_server=True))
        finally:
            for owned in owned_writers:
                owned.close()
                with suppress(OSError):
                    await owned.wait_closed()
                self.writers.discard(owned)

    def cut(self) -> None:
        """Abort only currently owned sockets; future connections may recover."""
        for writer in self.writers:
            writer.transport.abort()


@asynccontextmanager
async def fault_proxy(host: str, port: int) -> AsyncIterator[tuple[Proxy, int]]:
    """Close listening/accepted sockets and join every connection handler on exit."""
    proxy = Proxy(host, port)
    server = await asyncio.start_server(proxy.accept, "127.0.0.1", 0)
    try:
        yield proxy, int(server.sockets[0].getsockname()[1])
    finally:
        server.close()
        await server.wait_closed()
        proxy.cut()
        for task in proxy.tasks:
            task.cancel()
        results = await asyncio.gather(*proxy.tasks, return_exceptions=True)
        for result in results:
            if isinstance(result, Exception):
                raise result
