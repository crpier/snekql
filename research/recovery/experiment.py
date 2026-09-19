"""Isolated runtime observations; fresh reads never reuse an ORM identity map."""

import asyncio
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from importlib.metadata import version
from json import dumps
from os import fsdecode
from pathlib import Path
from platform import python_version
from tempfile import TemporaryDirectory
from typing import Any

from pydantic import ValidationError
from sqlalchemy import URL, event, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine
from sqlalchemy.schema import CreateTable

from research.recovery import mariadb_models, sqlite_models
from research.recovery.common import failure, orm_read, seed, snapshot, snek_read
from research.recovery.corruption import observe_corruption
from research.recovery.lifecycle import (
    orm_lifecycle,
    orm_statement_error,
    snek_lifecycle,
)
from research.recovery.policy import validate_patch
from research.recovery.sqlalchemy_models import models
from snekql.errors import ExecutionError, ModelValidationError, QueryCompilationError
from snekql.testing.mariadb import temporary_mariadb_server


@asynccontextmanager
async def resources(backend: str) -> AsyncIterator[tuple[AsyncEngine, Any, Any]]:
    """Only disposable files and socket-only servers are accepted by this runner."""
    if backend == "sqlite":
        directory = await asyncio.to_thread(
            TemporaryDirectory, prefix="snekql-recovery-"
        )
        try:
            path = Path(fsdecode(directory.name)) / "study.sqlite"
            async with connection(
                URL.create("sqlite+aiosqlite", database=str(path)), backend
            ) as engine:
                yield (
                    engine,
                    sqlite_models,
                    sqlite_models.db.Config(database=path, pool_size=1),
                )
        finally:
            await asyncio.to_thread(directory.cleanup)
    else:
        async with (
            temporary_mariadb_server(
                server_args=(
                    "--character-set-server=utf8mb4",
                    "--collation-server=utf8mb4_bin",
                    "--default-storage-engine=InnoDB",
                )
            ) as server,
            connection(
                URL.create(
                    "mysql+aiomysql",
                    username=server.user,
                    database=server.database,
                    query={
                        "unix_socket": str(server.socket_path),
                        "charset": "utf8mb4",
                    },
                ),
                backend,
            ) as engine,
        ):
            yield engine, mariadb_models, server.config(pool_size=1)


@asynccontextmanager
async def connection(url: URL, backend: str) -> AsyncIterator[AsyncEngine]:
    """Make connection controls explicit for the external and ORM writer."""
    engine = create_async_engine(url)

    @event.listens_for(engine.sync_engine, "connect")
    def configure(driver: Any, _record: Any) -> None:
        cursor = driver.cursor()
        try:
            if backend == "sqlite":
                cursor.execute("PRAGMA foreign_keys=ON")
            else:
                cursor.execute("SET SESSION time_zone='+00:00'")
                cursor.execute(
                    "SET SESSION sql_mode='STRICT_ALL_TABLES,NO_ZERO_IN_DATE,NO_ZERO_DATE,ERROR_FOR_DIVISION_BY_ZERO,NO_ENGINE_SUBSTITUTION'"
                )
        finally:
            cursor.close()

    try:
        yield engine
    finally:
        await engine.dispose()


async def snek_patch(
    database: Any, declarations: Any, supplied: dict[str, Any], track: str
) -> dict[str, Any]:
    stage = "build_update"
    try:
        if track == "validated":
            stage = "patch_validation"
            validate_patch(supplied)
        stage = "build_update"
        query = (
            declarations.db.update(declarations.Entry)
            .set(
                *(
                    getattr(declarations.Entry, name).to(value)
                    for name, value in supplied.items()
                )
            )
            .where(declarations.Entry.id.eq(1))
        )
        stage = "execute"
        async with database.transaction() as transaction:
            await transaction.execute(query)
            stage = "commit"
    except (
        ModelValidationError,
        QueryCompilationError,
        ExecutionError,
        ValidationError,
    ) as error:
        record = failure(error, stage)
    else:
        record = {"outcome": "accepted", "stage": stage}
    record["fresh"] = await snek_read(database, declarations)
    return record


async def orm_patch(
    engine: AsyncEngine, entry: Any, supplied: dict[str, Any], track: str
) -> dict[str, Any]:
    stage = "assignment"
    try:
        if track == "validated":
            stage = "patch_validation"
            validate_patch(supplied)
        stage = "assignment"
        async with AsyncSession(engine, expire_on_commit=False) as session:
            current = (await session.scalars(select(entry).where(entry.id == 1))).one()
            for name, value in supplied.items():
                setattr(current, name, value)
            record_before = snapshot(current)
            stage = "flush"
            await session.flush()
            stage = "commit"
            await session.commit()
    except (IntegrityError, ValidationError) as error:
        record = failure(error, stage)
    else:
        record = {
            "outcome": "accepted",
            "stage": stage,
            "after_assignment": record_before,
            "held_after_commit": snapshot(current),
        }
    record["fresh"] = await orm_read(engine, entry)
    return record


async def observe(backend: str, library: str, track: str) -> dict[str, Any]:
    """Collect one independently owned configuration."""
    async with resources(backend) as (engine, declarations, config):
        observations: dict[str, Any] = {
            "backend": backend,
            "library": library,
            "track": track,
            "patches": {},
        }
        patches = {
            "note_omitted": {"quantity": 2},
            "note_null": {"note": None},
            "quantity_null": {"quantity": None},
            "quantity_zero": {"quantity": 0},
            "quantity_bool": {"quantity": True},
            "quantity_fraction": {"quantity": 1.5},
        }
        if library == "snekql":
            async with await declarations.db.Database.initialize(config) as database:
                observations["ddl"] = declarations.db.scaffold([declarations.Entry])
                await database.migrate(
                    {
                        f"{index:03}_entries": statement
                        for index, statement in enumerate(
                            observations["ddl"].split(";"), 1
                        )
                        if statement.strip()
                    }
                )
                for name, supplied in patches.items():
                    await seed(engine, backend)
                    observations["patches"][name] = await snek_patch(
                        database, declarations, supplied, track
                    )
                observations["lifecycle"] = await snek_lifecycle(
                    engine, database, declarations, backend
                )
                observations["corruption"] = await observe_corruption(
                    engine, backend, library, database, declarations
                )
                async with database.transaction() as transaction:
                    observations[
                        "snekql_runtime_controls"
                    ] = await transaction.fetch_one(
                        declarations.db.raw(
                            "SELECT sqlite_version() AS version"
                            if backend == "sqlite"
                            else "SELECT VERSION() AS version, @@time_zone AS time_zone, @@sql_mode AS sql_mode"
                        )
                    )
        else:
            entry = models(track)
            observations["ddl"] = str(
                CreateTable(entry.__table__).compile(dialect=engine.dialect)
            )
            async with engine.begin() as handle:
                await handle.run_sync(entry.metadata.create_all)
            for name, supplied in patches.items():
                await seed(engine, backend)
                observations["patches"][name] = await orm_patch(
                    engine, entry, supplied, track
                )
            observations["lifecycle"] = await orm_lifecycle(engine, entry, backend)
            observations["corruption"] = await observe_corruption(
                engine, backend, library, entry, declarations
            )
            observations["statement_error"] = await orm_statement_error(
                engine, entry, backend
            )
        for name, supplied in patches.items():
            observations["patches"][name]["input"] = {
                key: {"value": str(value), "type": type(value).__name__}
                for key, value in supplied.items()
            }
        async with engine.connect() as handle:
            if backend == "sqlite":
                observations["installed_schema"] = [
                    dict(row)
                    for row in (
                        await handle.exec_driver_sql(
                            "SELECT type, name, sql FROM sqlite_master WHERE tbl_name='entries' ORDER BY type, name"
                        )
                    ).mappings()
                ]
                observations["connection_controls"] = {
                    "version": (
                        await handle.exec_driver_sql("SELECT sqlite_version()")
                    ).scalar_one(),
                    "foreign_keys": (
                        await handle.exec_driver_sql("PRAGMA foreign_keys")
                    ).scalar_one(),
                }
            else:
                observations["installed_schema"] = list(
                    (await handle.exec_driver_sql("SHOW CREATE TABLE entries")).one()
                )
                observations["connection_controls"] = dict(
                    (
                        await handle.exec_driver_sql(
                            "SELECT VERSION() AS version, @@time_zone AS time_zone, @@sql_mode AS sql_mode, @@collation_database AS collation, @@default_storage_engine AS engine"
                        )
                    )
                    .mappings()
                    .one()
                )
        return observations


async def observe_sqlite(library: str, track: str) -> dict[str, Any]:
    """Observe an isolated SQLite configuration through public runtime calls."""
    return await observe("sqlite", library, track)


async def observe_mariadb(library: str, track: str) -> dict[str, Any]:
    """Observe an isolated MariaDB configuration through public runtime calls."""
    return await observe("mariadb", library, track)


async def main() -> None:
    """Write evidence for all eight configurations beside the executable research."""
    evidence: dict[str, Any] = {
        "python": python_version(),
        "context_aware_warnings": sys.flags.context_aware_warnings,
        "versions": {
            name: version(name)
            for name in (
                "snekql",
                "sqlalchemy",
                "pydantic",
                "aiosqlite",
                "aiomysql",
                "PyMySQL",
                "greenlet",
            )
        },
        "runs": {},
    }
    for backend in ("sqlite", "mariadb"):
        for library in ("snekql", "sqlalchemy"):
            for track in ("native", "validated"):
                evidence["runs"][f"{backend}/{library}/{track}"] = await observe(
                    backend, library, track
                )
    directory = Path(__file__).parent
    await asyncio.to_thread(
        (directory / "results.json").write_text,
        dumps(evidence, indent=2, default=str) + "\n",
    )
    for name, run in evidence["runs"].items():
        await asyncio.to_thread(
            (directory / f"{name.replace('/', '-')}.sql").write_text,
            "\n".join(
                line.rstrip() for line in run["ddl"].strip().rstrip(";").splitlines()
            )
            + ";\n",
        )


if __name__ == "__main__":
    asyncio.run(main())
