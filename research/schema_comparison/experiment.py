"""Reproducible DDL and raw-database observations. Run as a module."""

import asyncio
from difflib import unified_diff
from importlib.metadata import version
from json import dumps
from pathlib import Path
from platform import python_version
from typing import Any

from sqlalchemy import URL, Connection, create_engine, inspect
from sqlalchemy.exc import DataError, IntegrityError, OperationalError

from research.schema_comparison import mariadb_models, sqlalchemy_models, sqlite_models
from research.schema_comparison.probes import PROBES, SEED, Probe
from snekql.testing.mariadb import temporary_mariadb_server

_MISSING_DEFAULT = 1364
"""MariaDB reports omitted required values as OperationalError."""


def _probe(connection: Connection, probe: Probe) -> dict[str, Any]:
    """Only constraint/data failures count as rejection; infrastructure errors abort."""
    outcome: dict[str, Any]
    try:
        for statement in probe.sql:
            connection.exec_driver_sql(statement)
    except (IntegrityError, DataError, OperationalError) as e:
        if isinstance(e, OperationalError) and (
            e.orig is None or e.orig.args[0] != _MISSING_DEFAULT
        ):
            raise
        outcome = {
            "outcome": "rejected",
            "error": str(e.orig),
        }
    else:
        outcome = {"outcome": "accepted"}
        if probe.query:
            outcome["rows"] = [
                list(row) for row in connection.exec_driver_sql(probe.query)
            ]
    diagnostic = probe.name in {
        "case_distinct_email",
        "id_reuse",
        "long_email",
        "wide_id",
        "blob_in_text",
    }
    outcome["matches_spec"] = (
        None
        if diagnostic
        else (
            (outcome["outcome"] == "rejected") == probe.reject
            and (
                probe.expected is None
                or outcome.get("rows") == [list(row) for row in probe.expected]
            )
        )
    )
    return outcome


def _observe(url: str | URL, library: str, track: str, backend: str) -> dict[str, Any]:
    """Blocking drivers stay confined to a worker thread and fresh database."""
    statements = (
        (sqlite_models if backend == "sqlite" else mariadb_models).ddl()
        if library == "snekql"
        else sqlalchemy_models.ddl(backend, track)
    )
    engine = create_engine(url)
    observation: dict[str, Any] = {"ddl": statements, "probes": {}}
    try:
        with engine.connect() as connection:
            if backend == "sqlite":
                connection.exec_driver_sql("PRAGMA foreign_keys=ON")
                controls = "SELECT sqlite_version() AS version"
            else:
                connection.exec_driver_sql(
                    "SET SESSION sql_mode='STRICT_ALL_TABLES,NO_ENGINE_SUBSTITUTION'"
                )
                controls = "SELECT VERSION() AS version, @@sql_mode AS sql_mode, @@character_set_database AS charset, @@collation_database AS collation, @@default_storage_engine AS engine"
            observation["controls"] = dict(
                connection.exec_driver_sql(controls).mappings().one()
            )
            if backend == "sqlite":
                observation["controls"]["foreign_keys"] = connection.exec_driver_sql(
                    "PRAGMA foreign_keys"
                ).scalar_one()
            for statement in statements:
                connection.exec_driver_sql(statement)
            connection.commit()
            inspector = inspect(connection)
            observation["schema"] = {}
            for table in ("users", "profiles", "teams", "memberships"):
                observation["schema"][table] = {
                    "columns": inspector.get_columns(table),
                    "primary_key": inspector.get_pk_constraint(table),
                    "foreign_keys": inspector.get_foreign_keys(table),
                    "indexes": inspector.get_indexes(table),
                    "unique_constraints": inspector.get_unique_constraints(table),
                }
            if backend == "sqlite":
                observation["installed_ddl"] = [
                    list(row)
                    for row in connection.exec_driver_sql(
                        "SELECT type,name,tbl_name,sql FROM sqlite_schema ORDER BY type,name"
                    )
                ]
            else:
                observation["installed_ddl"] = [
                    list(
                        connection.exec_driver_sql(f"SHOW CREATE TABLE `{table}`").one()
                    )
                    for table in observation["schema"]
                ]
            connection.commit()
            for probe in PROBES:
                with connection.begin():
                    for statement in SEED:
                        connection.exec_driver_sql(statement)
                    connection.commit()
                outcome = _probe(connection, probe)
                observation["probes"][probe.name] = outcome
                connection.rollback()
                for table in ("memberships", "profiles", "teams", "users"):
                    connection.exec_driver_sql(f"DROP TABLE `{table}`")
                for statement in statements:
                    connection.exec_driver_sql(statement)
                connection.commit()
    finally:
        engine.dispose()
    return observation


def _write_artifacts(observations: dict[str, Any]) -> None:
    """Keep raw statements and reflected structural diffs beside full evidence."""
    directory = Path(__file__).parent
    (directory / "results.json").write_text(
        dumps(observations, indent=2, default=str) + "\n"
    )
    for backend in ("sqlite", "mariadb"):
        for track in ("idiomatic", "matched"):
            schemas: list[list[str]] = []
            for library in ("snekql", "sqlalchemy"):
                observation = observations["runs"][f"{backend}/{track}/{library}"]
                (directory / f"{backend}-{track}-{library}.sql").write_text(
                    ";\n\n".join(observation["ddl"]) + ";\n"
                )
                schemas.append(
                    dumps(
                        observation["schema"], indent=2, sort_keys=True, default=str
                    ).splitlines(keepends=True)
                )
            (directory / f"{backend}-{track}.diff").write_text(
                "".join(unified_diff(*schemas, fromfile="snekql", tofile="sqlalchemy"))
            )


async def sqlite_observation(library: str, track: str) -> dict[str, Any]:
    """Observe an isolated in-memory SQLite database."""
    return await asyncio.to_thread(_observe, "sqlite://", library, track, "sqlite")


async def main() -> None:
    """Write eight isolated observations, including a temporary MariaDB server."""
    observations: dict[str, Any] = {
        "versions": {
            name: version(name) for name in ("snekql", "sqlalchemy", "pymysql")
        },
        "python": python_version(),
        "runs": {},
    }
    for track in ("idiomatic", "matched"):
        for library in ("snekql", "sqlalchemy"):
            observations["runs"][
                f"sqlite/{track}/{library}"
            ] = await sqlite_observation(library, track)
            async with temporary_mariadb_server(
                server_args=(
                    "--character-set-server=utf8mb4",
                    "--collation-server=utf8mb4_unicode_ci",
                    "--default-storage-engine=InnoDB",
                )
            ) as server:
                url = URL.create(
                    "mariadb+pymysql",
                    username=server.user,
                    database=server.database,
                    query={
                        "unix_socket": str(server.socket_path),
                        "charset": "utf8mb4",
                    },
                )
                observations["runs"][
                    f"mariadb/{track}/{library}"
                ] = await asyncio.to_thread(_observe, url, library, track, "mariadb")
    await asyncio.to_thread(_write_artifacts, observations)


if __name__ == "__main__":
    asyncio.run(main())
