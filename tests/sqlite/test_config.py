"""Public SQLite configuration preserves database identity across connections."""

from pathlib import Path

from snektest import assert_eq, test

from snekql import sqlite


@test()
def memory_path_uses_one_connection() -> None:
    """Path(':memory:') must not create a pool of independent databases."""
    config = sqlite.Config(database=Path(":memory:"), pool_size=5)

    assert_eq(config.pool_size, 1)
