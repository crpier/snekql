"""Clean native system-data copies do not share application or account state."""

import asyncio
from pathlib import Path
from typing import Any
from unittest.mock import patch

from snektest import assert_eq, assert_raises, assert_true, load_fixture, test

from benchmarks._artifacts import mariadb_artifacts
from snekql import mariadb
from snekql.testing.mariadb import temporary_mariadb_server
from tests.testing.mariadb.data import provide_mariadb_data_copy


@test(mark="slow")
async def data_copies_isolate_schema_history_and_accounts() -> None:
    """Mutating one copy cannot contaminate the next copy from the stopped seed."""
    copy_data = await load_fixture(provide_mariadb_data_copy())
    async with mariadb_artifacts() as root:
        first = root / "first"
        copy_data(first)
        assert_true((first / "mysql").is_dir())
        async with temporary_mariadb_server(
            runtime_base_directory=root,
            data_directory=first,
            auth="password",
            password="copy_first_password",
        ) as server:
            assert_eq((await server.run_sql("SHOW TABLES")).stdout, "")
            async with await mariadb.Database.initialize(server.config()) as database:
                migrations = {
                    "001_create": "CREATE TABLE copy_probe (id INTEGER PRIMARY KEY)",
                    "002_seed": "INSERT INTO copy_probe (id) VALUES (42)",
                }
                await database.migrate(migrations)
                await database.verify_migrations(migrations)
            assert_eq(
                (await server.run_sql("SELECT id FROM copy_probe")).stdout.strip(),
                "id\n42",
            )
            await server.run_sql("CREATE USER 'copy_only_account'@'localhost'")
            assert_eq(
                (
                    await server.run_sql(
                        "SELECT COUNT(*) AS n FROM mysql.user "
                        "WHERE User='copy_only_account'"
                    )
                ).stdout.strip(),
                "n\n1",
            )

        second = root / "second"
        copy_data(second)
        assert_true((second / "mysql").is_dir())
        async with temporary_mariadb_server(
            runtime_base_directory=root,
            data_directory=second,
            auth="password",
            password="copy_second_password",
        ) as server:
            # SHOW TABLES includes both copy_probe and real migration history.
            assert_eq((await server.run_sql("SHOW TABLES")).stdout, "")
            assert_eq(
                (
                    await server.run_sql(
                        "SELECT COUNT(*) AS n FROM mysql.user "
                        "WHERE User='copy_only_account'"
                    )
                ).stdout.strip(),
                "n\n0",
            )


@test(mark="slow")
async def seed_is_reaped_before_factory_publication() -> None:
    """No seed process can still write the source when a caller can copy it."""
    spawn = asyncio.create_subprocess_exec
    servers: list[asyncio.subprocess.Process] = []

    async def observe(*args: str, **kwargs: Any) -> asyncio.subprocess.Process:
        process = await spawn(*args, **kwargs)
        if Path(args[0]).name == "mariadbd":
            servers.append(process)
        return process

    with patch("asyncio.create_subprocess_exec", observe):
        async with provide_mariadb_data_copy():
            assert_true(bool(servers), msg="the seed must use a real native server")
            assert_true(all(process.returncode is not None for process in servers))


@test(mark="slow")
async def data_copy_rejects_existing_destinations() -> None:
    """A second copy must not silently reuse or overwrite caller-mutated data."""
    copy_data = await load_fixture(provide_mariadb_data_copy())
    async with mariadb_artifacts() as root:
        destination = root / "data"
        copy_data(destination)
        marker = destination / "caller_owned"
        marker.write_text("preserve this")
        with assert_raises(FileExistsError):
            copy_data(destination)
        assert_eq(marker.read_text(), "preserve this")
