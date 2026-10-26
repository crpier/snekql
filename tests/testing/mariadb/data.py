"""Test-only copies of stopped native data, never application schema snapshots."""

from collections.abc import AsyncGenerator, Callable
from pathlib import Path
from shutil import copytree

from snektest import fixture

from benchmarks._artifacts import mariadb_artifacts
from snekql.testing.mariadb import temporary_mariadb_server

type MariaDBDataCopy = Callable[[Path], None]


@fixture(scope="session")
async def provide_mariadb_data_copy() -> AsyncGenerator[MariaDBDataCopy]:
    """Initialize once; give callers independent data without application history.

    The native seed server has stopped before this factory is published. Copies
    run synchronously: cancellation cannot leave a background writer using the
    seed after its fixture owner exits. Callers own destination lifetimes and
    must stop their servers before removing them. Existing destinations fail
    rather than silently reusing potentially mutated data.
    """
    async with mariadb_artifacts() as root:
        seed = root / "data"
        async with temporary_mariadb_server(
            runtime_base_directory=root, data_directory=seed
        ):
            pass

        def copy_data(destination: Path) -> None:
            _ = copytree(seed, destination)

        yield copy_data
