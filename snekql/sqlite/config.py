"""SQLite runtime configuration for snekql."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from snekql.errors import DatabaseRuntimeError
from snekql.validation import NonNegativeFloat, PositiveInt, validate_boundary


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
