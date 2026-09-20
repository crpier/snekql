"""Function-scoped snektest database fixtures that replay real migrations."""

from collections.abc import AsyncGenerator
from pathlib import Path

from anyio import TemporaryDirectory
from snektest import fixture, load_fixture

from examples.service_database import deploy, open_service
from snekql import sqlite


@fixture
async def empty_config() -> AsyncGenerator[sqlite.Config]:
    """A file-backed database gives separate connections one shared test schema."""
    async with TemporaryDirectory() as directory:
        yield sqlite.Config(database=Path(directory) / "service.db", pool_size=2)


@fixture
async def fresh_database() -> AsyncGenerator[sqlite.Database]:
    """Replay the literal chain, verify it, and close before deleting its directory."""
    config = await load_fixture(empty_config())
    await deploy(config)
    async with open_service(config) as database:
        yield database
