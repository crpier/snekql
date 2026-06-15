"""Backend Runtime Adapter selection for Database initialization."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, Protocol, runtime_checkable

from snekql.errors import DatabaseRuntimeError
from snekql.model import require_model_backend
from snekql.validation import NonNegativeFloat, PositiveInt, validate_boundary

if TYPE_CHECKING:
    from collections.abc import Sequence

    from snekql.model import BackendFamily, Table
    from snekql.storage import SchemaPolicy
    from snekql.structured_logging import ResolvedStructuredLogger


@runtime_checkable
class RuntimeConfig(Protocol):
    """Backend config seam: family identity, pool settings, runtime initializer."""

    @property
    def acquire_timeout(self) -> NonNegativeFloat: ...

    @property
    def backend_family(self) -> BackendFamily: ...

    @property
    def pool_size(self) -> PositiveInt: ...

    async def initialize_runtime(
        self,
        models: Sequence[type[Table[Any]]],
        schema_policy: SchemaPolicy,
        *,
        logger: ResolvedStructuredLogger,
        migrations: dict[str, str] | None = None,
    ) -> object: ...


@validate_boundary(error_type=DatabaseRuntimeError)
def _build_legacy_sqlite_config(
    *,
    acquire_timeout: NonNegativeFloat,
    database: Path | Literal[":memory:"],
    pool_size: PositiveInt,
) -> RuntimeConfig:
    """Build an explicit SQLite config for the legacy initializer shape."""

    from snekql.sqlite.config import Config as SQLiteConfig  # noqa: PLC0415

    return SQLiteConfig(
        acquire_timeout=acquire_timeout,
        database=database,
        pool_size=pool_size,
    )


def validate_model_backends(
    backend_family: BackendFamily,
    models: Sequence[type[Table[Any]]],
) -> None:
    """Reject models from another backend before runtime startup mutates state."""

    for model in models:
        received_backend = require_model_backend(model)
        if received_backend != backend_family:
            msg = (
                f"backend mismatch: expected {backend_family} model, "
                f"received {received_backend} model {model.__name__}"
            )
            raise DatabaseRuntimeError(msg)


def resolve_runtime_config(
    *,
    backend: object | None,
    database: Path | Literal[":memory:"] | None,
    pool_size: PositiveInt,
    acquire_timeout: NonNegativeFloat,
) -> RuntimeConfig:
    """Resolve public Database.initialize arguments to a backend config."""

    if backend is not None:
        if not isinstance(backend, RuntimeConfig):
            msg = "unsupported database backend config"
            raise DatabaseRuntimeError(msg)
        if database is not None:
            msg = "backend config cannot be combined with database"
            raise DatabaseRuntimeError(msg)
        return backend
    if database is None:
        msg = "Database.initialize requires a backend config or database"
        raise DatabaseRuntimeError(msg)
    return _build_legacy_sqlite_config(
        acquire_timeout=acquire_timeout,
        database=database,
        pool_size=pool_size,
    )
