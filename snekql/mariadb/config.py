"""MariaDB runtime configuration for snekql."""

from __future__ import annotations

from dataclasses import dataclass, field
from importlib import import_module
from pathlib import Path
from ssl import Purpose, SSLContext, TLSVersion, create_default_context
from typing import Annotated, Any, Literal, cast

from annotated_types import Gt
from pydantic import FiniteFloat

from snekql._telemetry import ParameterVisibility
from snekql.errors import DatabaseRuntimeError
from snekql.validation import NonNegativeFloat, PositiveInt, validate_boundary

type _ConnectionDuration = Annotated[FiniteFloat, Gt(0)]

_MAX_TCP_PORT = 65535


@dataclass(frozen=True, kw_only=True)
class TLSConfig:
    """Certificate-verifying MariaDB TLS configuration.

    System trust roots are used when ``ca_file`` is omitted. Client certificate
    authentication is enabled only when both client files are supplied.
    """

    ca_file: Path | None = None
    cert_file: Path | None = None
    key_file: Path | None = None

    def __post_init__(self) -> None:
        if (self.cert_file is None) != (self.key_file is None):
            msg = "MariaDB TLS client certificate and private key must be provided together"
            raise DatabaseRuntimeError(msg)

    def _create_ssl_context(self) -> SSLContext:
        """Build a fresh verified context for one driver pool."""

        context = create_default_context(
            Purpose.SERVER_AUTH,
            cafile=str(self.ca_file) if self.ca_file is not None else None,
        )
        context.minimum_version = TLSVersion.TLSv1_2
        if self.cert_file is not None and self.key_file is not None:
            context.load_cert_chain(
                certfile=str(self.cert_file),
                keyfile=str(self.key_file),
            )
        return context


@validate_boundary(error_type=DatabaseRuntimeError)
def _validate_config(  # noqa: PLR0913
    *,
    acquire_timeout: NonNegativeFloat,
    operation_timeout: NonNegativeFloat,
    health_check: Literal["passive", "checkout"],
    max_connection_idle: _ConnectionDuration | None,
    max_connection_lifetime: _ConnectionDuration | None,
    pool_size: PositiveInt,
    port: PositiveInt,
    parameter_visibility: ParameterVisibility,
) -> None:
    """Validate numeric options and policy choices before connection checks."""

    del acquire_timeout, operation_timeout, parameter_visibility, pool_size, port
    del health_check, max_connection_idle, max_connection_lifetime


def _validate_non_empty_string(name: str, value: str) -> None:
    """Reject empty string settings that cannot identify a database endpoint."""

    if not isinstance(value, str):
        msg = f"MariaDB {name} must be a string"
        raise DatabaseRuntimeError(msg)
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
    >>> Config(database="app", user="snekql", health_check="checkout").health_check
    'checkout'

    Recycling limits are finite positive seconds or None to disable. Lifetime
    starts at physical connection establishment; idle time starts on pool return.
    Policies run before checkout, never during a Transaction. Checkout health
    probes cannot reconnect the existing session or replay transaction work.
    """

    database: str
    acquire_timeout: NonNegativeFloat = 30.0
    operation_timeout: NonNegativeFloat = 30.0
    charset: str = "utf8mb4"
    health_check: Literal["passive", "checkout"] = "passive"
    host: str = "127.0.0.1"
    max_connection_idle: _ConnectionDuration | None = None
    max_connection_lifetime: _ConnectionDuration | None = None
    password: str = field(default="", repr=False)
    pool_size: PositiveInt = 5
    parameter_visibility: ParameterVisibility = "redacted"
    port: PositiveInt = 3306
    unix_socket: Path | None = None
    tls: TLSConfig | None = None
    user: str

    def __post_init__(self) -> None:
        _validate_config(
            acquire_timeout=self.acquire_timeout,
            operation_timeout=self.operation_timeout,
            health_check=self.health_check,
            max_connection_idle=self.max_connection_idle,
            max_connection_lifetime=self.max_connection_lifetime,
            pool_size=self.pool_size,
            port=self.port,
            parameter_visibility=self.parameter_visibility,
        )
        _validate_port(self.port)
        _validate_non_empty_string("database", self.database)
        _validate_non_empty_string("host", self.host)
        _validate_non_empty_string("user", self.user)
        _validate_non_empty_string("charset", self.charset)
        if self.tls is not None and self.unix_socket is not None:
            msg = "MariaDB TLS requires TCP; unix_socket must be None"
            raise DatabaseRuntimeError(msg)

    @property
    def backend_family(self) -> Literal["mariadb"]:
        """Identify the backend family this config initializes."""

        return "mariadb"

    async def initialize_runtime(self) -> object:
        """Import and initialize the MariaDB Backend Runtime Adapter lazily."""

        runtime_module = import_module("snekql.mariadb.runtime")
        return await cast("Any", runtime_module).initialize_runtime(self)
