"""Restricted experiment, not a supported backend. No global driver substitution.

Reuse snekql's transaction machinery and admission gate; adapt the native cursor
and connection explicitly. Only owned loopback TCP, passive health, one connection
and raw-query experiments are supported here. TLS/migrations/recycling are not
certified by this prototype.
"""

from importlib import import_module
from typing import Any, cast

from snekql._raw import NativeParameters
from snekql.errors import DatabaseFailure, FailureCategory
from snekql.mariadb.config import Config
from snekql.mariadb.runtime import (
    MariaDBConnectionAdapter,
    MariaDBConnectionPool,
    MariaDBCursorAdapter,
    MariaDBRuntime,
)
from snekql.validation import NonNegativeFloat

_CONNECTION_LOST = 2013
_CONSTRAINT_CATEGORIES: dict[int, FailureCategory] = {
    1062: "unique_violation",
    1048: "not_null_violation",
    4025: "check_violation",
    1451: "foreign_key_violation",
    1452: "foreign_key_violation",
}
_FAILURE_CATEGORIES: dict[int, FailureCategory] = {
    **_CONSTRAINT_CATEGORIES,
    _CONNECTION_LOST: "connection_loss",
    1205: "lock_conflict",
}


class _Cursor(MariaDBCursorAdapter):
    async def complete(self) -> bool:
        cursor = cast("Any", self.cursor)
        result = cursor._result  # noqa: SLF001 - isolated native protocol boundary
        if result is not None:
            if result.unbuffered_active:
                await result._finish_unbuffered_query()  # noqa: SLF001
            if result.has_next:
                cursor.connection.close()
                cursor.connection = None
                return True
        await self.close()
        return False


class _Connection(MariaDBConnectionAdapter):
    def _recoverable_constraint(self, error: BaseException) -> bool:
        driver = import_module("asyncmy")
        return bool(
            isinstance(error, (driver.IntegrityError, driver.OperationalError))
            and error.args
            and error.args[0] in _CONSTRAINT_CATEGORIES
            and cast("Any", self.connection).get_transaction_status()
        )

    async def _quiet_cursor(self, *, stream: bool) -> Any:
        cursors = import_module("asyncmy.cursors")
        base = cursors.SSCursor if stream else cursors.Cursor

        class QuietCursor(base):
            async def _show_warnings(self, connection: object) -> None:
                del connection

        return await cast("Any", self.connection).cursor(QuietCursor)

    async def execute_raw(
        self, sql: str, params: NativeParameters, *, stream: bool = False
    ) -> _Cursor:
        result = await super().execute_raw(sql, params, stream=stream)
        return _Cursor(result.cursor)


class _Runtime(MariaDBRuntime):
    @staticmethod
    def classify_failure(error: Exception) -> DatabaseFailure | None:
        if not isinstance(error, import_module("asyncmy").Error):
            return None
        code = error.args[0] if error.args and type(error.args[0]) is int else None
        return DatabaseFailure(
            backend="mariadb",
            category=_FAILURE_CATEGORIES.get(code, "unknown")
            if code is not None
            else "unknown",
            code=code,
        )

    async def acquire(self, acquisition_timeout: NonNegativeFloat) -> _Connection:
        connection = await self.connection_pool.acquire(acquisition_timeout)
        return _Connection(connection)


class PrototypeConfig(Config):
    """Opt into the restricted experimental adapter through Database.initialize."""

    async def initialize_runtime(self) -> object:
        if (
            self.host != "127.0.0.1"
            or self.tls is not None
            or self.unix_socket is not None
            or self.pool_size != 1
            or self.health_check != "passive"
            or self.max_connection_idle is not None
            or self.max_connection_lifetime is not None
        ):
            message = "Prototype supports only a size-one passive loopback TCP pool"
            raise ValueError(message)
        driver = import_module("asyncmy")
        pool = await driver.create_pool(
            host=self.host,
            port=self.port,
            user=self.user,
            password=self.password,
            db=self.database,
            charset=self.charset,
            autocommit=False,
            # Defer authentication into wrapper.acquire's deadline/cleanup region.
            # Eager native filling only bounds TCP connect, not authentication.
            minsize=0,
            maxsize=1,
            connect_timeout=self.acquire_timeout,
        )
        wrapper = MariaDBConnectionPool(pool, pool_size=1)
        try:
            connection = await wrapper.acquire(self.acquire_timeout)
            await wrapper.release(connection)
        except BaseException:
            pool.terminate()
            await pool.wait_closed()
            raise
        return _Runtime(
            connection_pool=wrapper,
            acquire_timeout=self.acquire_timeout,
            operation_timeout=self.operation_timeout,
            migration_lock_name="unsupported-prototype-migrations",
            parameter_visibility=self.parameter_visibility,
        )
