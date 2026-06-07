"""MariaDB runtime configuration for snekql."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from snekql.errors import DatabaseRuntimeError
from snekql.validation import NonNegativeFloat, PositiveInt, validate_boundary

_MAX_TCP_PORT = 65535


@validate_boundary(error_type=DatabaseRuntimeError)
def _validate_numeric_config(
    *,
    acquire_timeout: NonNegativeFloat,
    pool_size: PositiveInt,
    port: PositiveInt,
) -> None:
    """Validate numeric settings before semantic connection checks run."""

    del acquire_timeout, pool_size, port


def _validate_non_empty_string(name: str, value: str) -> None:
    """Reject empty string settings that cannot identify a database endpoint."""

    if value.strip() == "":
        msg = f"MariaDB {name} must not be empty"
        raise DatabaseRuntimeError(msg)


def _validate_port(port: PositiveInt) -> None:
    """MariaDB TCP ports must fit the valid TCP port range."""

    if port > _MAX_TCP_PORT:
        msg = "MariaDB port must be between 1 and 65535"
        raise DatabaseRuntimeError(msg)


@dataclass(frozen=True, kw_only=True)
class Config:
    """MariaDB backend configuration for explicit runtime initialization.

    >>> config = Config(database="app", user="snekql")
    >>> config.port
    3306
    """

    database: str
    acquire_timeout: NonNegativeFloat = 30.0
    charset: str = "utf8mb4"
    host: str = "127.0.0.1"
    password: str = field(default="", repr=False)
    pool_size: PositiveInt = 5
    port: PositiveInt = 3306
    unix_socket: Path | None = None
    user: str

    def __post_init__(self) -> None:
        _validate_numeric_config(
            acquire_timeout=self.acquire_timeout,
            pool_size=self.pool_size,
            port=self.port,
        )
        _validate_port(self.port)
        _validate_non_empty_string("database", self.database)
        _validate_non_empty_string("host", self.host)
        _validate_non_empty_string("user", self.user)
        _validate_non_empty_string("charset", self.charset)
