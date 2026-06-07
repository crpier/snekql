"""Backend Runtime Adapter selection for Database initialization."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from snekql.errors import DatabaseRuntimeError
from snekql.mariadb.config import Config as MariaDBConfig
from snekql.model import BackendFamily, Table, require_model_backend
from snekql.sqlite.config import Config as SQLiteConfig
from snekql.storage import SchemaPolicy
from snekql.structured_logging import ResolvedStructuredLogger
from snekql.validation import NonNegativeFloat, PositiveInt, validate_boundary

type RuntimeConfig = SQLiteConfig | MariaDBConfig


@validate_boundary(error_type=DatabaseRuntimeError)
def _build_legacy_sqlite_config(
    *,
    acquire_timeout: NonNegativeFloat,
    database: Path | Literal[":memory:"],
    pool_size: PositiveInt,
) -> SQLiteConfig:
    """Build an explicit SQLite config for the legacy initializer shape."""

    return SQLiteConfig(
        acquire_timeout=acquire_timeout,
        database=database,
        pool_size=pool_size,
    )


@dataclass(frozen=True)
class RuntimeSelection:
    """Selected backend config and runtime initializer for one Database startup."""

    backend_family: BackendFamily
    config: RuntimeConfig

    def validate_model_backends(self, models: Sequence[type[Table[Any]]]) -> None:
        """Reject models from another backend before runtime startup mutates state."""

        for model in models:
            received_backend = require_model_backend(model)
            if received_backend != self.backend_family:
                msg = (
                    f"backend mismatch: expected {self.backend_family} model, "
                    f"received {received_backend} model {model.__name__}"
                )
                raise DatabaseRuntimeError(msg)

    async def initialize_runtime(
        self,
        models: Sequence[type[Table[Any]]],
        schema_policy: SchemaPolicy,
        *,
        logger: ResolvedStructuredLogger,
    ) -> object:
        """Import and initialize the selected Backend Runtime Adapter lazily."""

        if isinstance(self.config, MariaDBConfig):
            from snekql.mariadb.runtime import (  # noqa: PLC0415
                initialize_runtime as initialize_mariadb_runtime,
            )

            return await initialize_mariadb_runtime(
                self.config,
                models,
                schema_policy,
                logger=logger,
            )
        try:
            from snekql.sqlite.runtime import (  # noqa: PLC0415
                initialize_runtime as initialize_sqlite_runtime,
            )
        except ModuleNotFoundError as error:
            if error.name == "aiosqlite":
                msg = "SQLite runtime requires the aiosqlite extra; install with snekql[aiosqlite]"
                raise DatabaseRuntimeError(msg) from error
            raise

        return await initialize_sqlite_runtime(
            self.config,
            models,
            schema_policy,
            logger=logger,
        )


def _selection_from_config(config: RuntimeConfig) -> RuntimeSelection:
    backend_family: BackendFamily = (
        "mariadb" if isinstance(config, MariaDBConfig) else "sqlite"
    )
    return RuntimeSelection(backend_family=backend_family, config=config)


def resolve_runtime_selection(
    *,
    backend: object | None,
    database: Path | Literal[":memory:"] | None,
    pool_size: PositiveInt,
    acquire_timeout: NonNegativeFloat,
) -> RuntimeSelection:
    """Resolve public Database.initialize arguments to a Runtime Adapter choice."""

    if backend is not None:
        if not isinstance(backend, SQLiteConfig | MariaDBConfig):
            msg = "unsupported database backend config"
            raise DatabaseRuntimeError(msg)
        if database is not None:
            msg = "backend config cannot be combined with database"
            raise DatabaseRuntimeError(msg)
        return _selection_from_config(backend)
    if database is None:
        msg = "Database.initialize requires a backend config or database"
        raise DatabaseRuntimeError(msg)
    config = _build_legacy_sqlite_config(
        acquire_timeout=acquire_timeout,
        database=database,
        pool_size=pool_size,
    )
    return RuntimeSelection(backend_family="sqlite", config=config)
