"""Backend Runtime Adapter selection for Database initialization."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, Protocol, runtime_checkable

from snekql.errors import DatabaseRuntimeError
from snekql.model import require_model_backend
from snekql.validation import NonNegativeFloat, PositiveInt

if TYPE_CHECKING:
    from collections.abc import Sequence

    from snekql.model import BackendFamily, Table
    from snekql.storage import SchemaPolicy


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
        migrations: dict[str, str] | None = None,
    ) -> object: ...

    async def apply_migrations(
        self,
        migrations: dict[str, str],
    ) -> None: ...


@runtime_checkable
class DefaultBackendFactory(Protocol):
    """Builds the backend config for the legacy ``database=`` initializer shape.

    The core stays dialect-blind: it never names a Backend Namespace. A backend
    registers itself as the default at the edge (on import) via
    ``register_default_backend_factory``, so the core resolves ``database=``
    through this injected callback instead of importing a backend config.
    """

    def __call__(
        self,
        *,
        acquire_timeout: NonNegativeFloat,
        database: Path | Literal[":memory:"],
        pool_size: PositiveInt,
    ) -> RuntimeConfig: ...


_default_backend_factory: DefaultBackendFactory | None = None


def register_default_backend_factory(factory: DefaultBackendFactory) -> None:
    """Register the backend that handles the legacy ``database=`` shape.

    Called from a Backend Namespace at import time. This is the injection seam
    that lets the core resolve ``database=`` without importing any backend.
    """

    global _default_backend_factory  # noqa: PLW0603
    _default_backend_factory = factory


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
    if _default_backend_factory is None:
        msg = "no default backend is registered for the database= initializer shape"
        raise DatabaseRuntimeError(msg)
    return _default_backend_factory(
        acquire_timeout=acquire_timeout,
        database=database,
        pool_size=pool_size,
    )
