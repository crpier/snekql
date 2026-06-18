"""SQLite runtime configuration for snekql."""

from __future__ import annotations

from dataclasses import dataclass
from importlib import import_module
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, cast

from snekql._runtime_selection import register_default_backend_factory
from snekql.errors import DatabaseRuntimeError
from snekql.validation import NonNegativeFloat, PositiveInt, validate_boundary

if TYPE_CHECKING:
    from collections.abc import Sequence

    from snekql._runtime_selection import RuntimeConfig
    from snekql.model import Table
    from snekql.storage import SchemaPolicy
    from snekql.structured_logging import ResolvedStructuredLogger


def _resolve_pool_size(
    database: Path | Literal[":memory:"],
    pool_size: PositiveInt,
) -> PositiveInt:
    """Keep exact SQLite in-memory databases on a single connection."""

    if database == ":memory:":
        return 1
    return pool_size


@validate_boundary(error_type=DatabaseRuntimeError)
def _validate_sqlite_config(
    *,
    acquire_timeout: NonNegativeFloat,
    database: Path | Literal[":memory:"],
    pool_size: PositiveInt,
) -> None:
    """Validate SQLite configuration at construction time.

    Backend configuration objects are the future public seam between database
    families, so invalid numeric and database target values should fail before
    runtime initialization begins.
    """

    del acquire_timeout, database, pool_size


@dataclass(frozen=True, kw_only=True)
class Config:
    """SQLite backend configuration for explicit runtime initialization.

    >>> from pathlib import Path
    >>> config = Config(database=Path("app.db"))
    >>> config.pool_size
    5
    """

    database: Path | Literal[":memory:"]
    acquire_timeout: NonNegativeFloat = 30.0
    pool_size: PositiveInt = 5

    def __post_init__(self) -> None:
        _validate_sqlite_config(
            acquire_timeout=self.acquire_timeout,
            database=self.database,
            pool_size=self.pool_size,
        )
        pool_size = _resolve_pool_size(self.database, self.pool_size)
        object.__setattr__(self, "pool_size", pool_size)

    @property
    def backend_family(self) -> Literal["sqlite"]:
        """Identify the backend family this config initializes."""

        return "sqlite"

    async def initialize_runtime(
        self,
        models: Sequence[type[Table[Any]]],
        schema_policy: SchemaPolicy,
        *,
        logger: ResolvedStructuredLogger,
        migrations: dict[str, str] | None = None,
    ) -> object:
        """Import and initialize the SQLite Backend Runtime Adapter lazily."""

        try:
            runtime_module = import_module("snekql.sqlite.runtime")
        except ModuleNotFoundError as error:
            if error.name == "aiosqlite":
                msg = (
                    "SQLite runtime requires the aiosqlite extra; "
                    "install with snekql[aiosqlite]"
                )
                raise DatabaseRuntimeError(msg) from error
            raise

        return await cast("Any", runtime_module).initialize_runtime(
            self,
            models,
            schema_policy,
            logger=logger,
            migrations=migrations,
        )

    async def apply_migrations(
        self,
        migrations: dict[str, str],
        *,
        logger: ResolvedStructuredLogger,
    ) -> None:
        """Apply pending migrations on a migrate-only SQLite connection."""

        try:
            runtime_module = import_module("snekql.sqlite.runtime")
        except ModuleNotFoundError as error:
            if error.name == "aiosqlite":
                msg = (
                    "SQLite runtime requires the aiosqlite extra; "
                    "install with snekql[aiosqlite]"
                )
                raise DatabaseRuntimeError(msg) from error
            raise

        await cast("Any", runtime_module).migrate_runtime(
            self,
            migrations,
            logger=logger,
        )


def _build_default_config(
    *,
    acquire_timeout: NonNegativeFloat,
    database: Path | Literal[":memory:"],
    pool_size: PositiveInt,
) -> RuntimeConfig:
    """Build a SQLite config for the legacy ``database=`` initializer shape."""

    return Config(
        acquire_timeout=acquire_timeout,
        database=database,
        pool_size=pool_size,
    )


# SQLite is the default backend for the bare ``Database.initialize(database=...)``
# shape. Registering here keeps the core dialect-blind: it resolves ``database=``
# through this callback rather than importing the SQLite Config (ADR 0004).
register_default_backend_factory(_build_default_config)
