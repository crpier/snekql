"""Owned aiomysql 0.3.x connection creation and mandatory TLS enforcement.

The driver does not close partial sockets on native cancellation and offers no
connection-factory hook. Keep its pool-fill adaptation local and preserve its
stale-reader checks. Import lazily after the optional driver is available.
"""

from __future__ import annotations

import asyncio
from typing import Any

from aiomysql.connection import Connection
from aiomysql.pool import Pool
from pymysql.constants.CLIENT import SSL

from snekql.errors import DatabaseRuntimeError


class _RequiredTLSConnection(Connection):
    """Reject a non-TLS greeting before the driver constructs authentication data."""

    async def _request_authentication(self) -> None:
        if self._ssl_context is None or not self.server_capabilities & SSL:
            msg = "MariaDB server does not support required TLS"
            raise DatabaseRuntimeError(msg)
        await super()._request_authentication()


class _OwnedPool(Pool):
    """Own every socket before awaiting authentication or session initialization."""

    def __init__(self, *, require_tls: bool, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._require_tls: bool = require_tls

    async def wait_closed(self) -> None:
        """Retain idle sockets until close succeeds rather than popping them first."""

        if self._closing:
            first_error: Exception | None = None
            for connection in tuple(self._free):
                try:
                    connection.close()
                except Exception as e:
                    if first_error is None:
                        first_error = e
                else:
                    self._free.remove(connection)
            if first_error is not None:
                raise first_error
        await super().wait_closed()

    async def _fill_free_pool(self, override_min: bool) -> None:  # noqa: FBT001
        # Called under the driver's condition lock. Preserve its stale-socket
        # checks, including the EOF marker used when a server sends an error
        # packet just before disconnecting.
        for connection in tuple(self._free):
            reader = connection._reader  # noqa: SLF001
            expired = (
                self._recycle > -1
                and self._loop.time() - connection.last_usage > self._recycle
            )
            if (
                reader is None
                or reader.at_eof()
                or reader.exception()
                or reader.eof_received
                or expired
            ):
                self._free.remove(connection)
                connection.close()

        while self.size < self.minsize or (
            override_min
            and not self._free
            and (not self.maxsize or self.size < self.maxsize)
        ):
            self._acquiring += 1
            try:
                connection_type = (
                    _RequiredTLSConnection if self._require_tls else Connection
                )
                connection = connection_type(
                    echo=self._echo, loop=self._loop, **self._conn_kwargs
                )
                try:
                    await connection._connect()  # noqa: SLF001
                except BaseException as error:
                    connection.close()
                    if (
                        self._require_tls
                        and isinstance(error, Exception)
                        and not isinstance(error, DatabaseRuntimeError)
                    ):
                        msg = "MariaDB required TLS connection failed"
                        raise DatabaseRuntimeError(msg) from error
                    raise
                self._free.append(connection)
                self._cond.notify()
            finally:
                self._acquiring -= 1


async def create_pool(*, require_tls: bool, **kwargs: Any) -> Pool:
    """Return an owned pool before opening sockets so startup failure can clean up.

    The runtime immediately acquires and configures its first connection inside
    its partial-pool cleanup region. Further connections use the same guard.
    """

    # aiomysql inherits AbstractServer without implementing its unused server API.
    # It is concrete at runtime; our adapter uses only the driver pool methods.
    return _OwnedPool(  # ty: ignore[call-non-callable]
        require_tls=require_tls,
        echo=False,
        pool_recycle=-1,
        loop=asyncio.get_running_loop(),
        **kwargs,
    )
