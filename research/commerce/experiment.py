"""Collect DDL, installed schema, and isolated raw-SQL observations."""

import asyncio
from dataclasses import asdict
from datetime import datetime
from difflib import unified_diff
from importlib.metadata import version
from json import dumps
from pathlib import Path
from platform import python_version
from typing import Any

from sqlalchemy import URL, Connection, create_engine, inspect, select
from sqlalchemy.exc import DBAPIError

from research.commerce import (
    database_rules,
    mariadb_models,
    sqlalchemy_models,
    sqlite_models,
)
from research.commerce.applications import observe_construction
from research.commerce.probes import PROBES, Probe
from snekql.testing.mariadb import temporary_mariadb_server

_MARIADB_DATA_ERRORS = {1048, 1264, 1292, 1364, 1366, 1406, 4025}
"""Known null, range, conversion, missing-default, length, and CHECK violations."""
_SQLITE_CONSTRAINT = 19
"""SQLite extended constraint codes share this low byte."""


def _probe(connection: Connection, backend: str, probe: Probe) -> dict[str, Any]:
    """Preserve raw driver types; unexpected database errors abort the experiment."""
    outcome: dict[str, Any] = asdict(probe)
    try:
        for statement in probe.statements:
            connection.exec_driver_sql(statement)
        if backend == "mariadb":
            outcome["warnings"] = [
                list(row) for row in connection.exec_driver_sql("SHOW WARNINGS")
            ]
    except DBAPIError as e:
        original = e.orig
        code = getattr(original, "sqlite_errorcode", 0)
        expected = (
            code & 0xFF == _SQLITE_CONSTRAINT
            if backend == "sqlite"
            else original is not None and original.args[0] in _MARIADB_DATA_ERRORS
        )
        if not expected:
            raise
        outcome.update(
            outcome="rejected", error_type=type(original).__name__, error=str(original)
        )
    else:
        outcome["outcome"] = "accepted"
        if probe.query:
            rows = [list(row) for row in connection.exec_driver_sql(probe.query)]
            outcome["rows"] = rows
            outcome["types"] = [[type(cell).__name__ for cell in row] for row in rows]
    return outcome


def _bound_timestamp(
    connection: Connection, backend: str, library: str, track: str
) -> dict[str, str]:
    """Compare actual binding and decoding, without pretending to exercise ORM sessions."""
    if library == "sqlalchemy" and backend == "sqlite" and track == "matched":
        return {"skipped": "DDL-only TEXT match has no Decimal/datetime codecs."}
    supplied = datetime.fromisoformat("2026-01-02T08:34:05.123456+05:30")
    if library == "snekql":
        order = (sqlite_models if backend == "sqlite" else mariadb_models).models()[
            "orders"
        ]
        instance = order(quantity=1, created_at=supplied)
        encoded = order.created_at.encode(instance.created_at, backend=backend)
        statement = (
            "INSERT INTO orders (quantity,status,created_at) VALUES (1,'pending',?)"
            if backend == "sqlite"
            else "INSERT INTO orders (quantity,status,created_at) VALUES (1,'pending',%s)"
        )
        connection.exec_driver_sql(statement, (encoded,))
        raw = connection.exec_driver_sql("SELECT created_at FROM orders").scalar_one()
        typed = order.created_at.decode(raw, backend=backend)
    else:
        order = sqlalchemy_models.models(backend, track)["orders"]
        connection.execute(
            order.__table__.insert().values(
                quantity=1, status="pending", created_at=supplied
            )
        )
        raw = connection.exec_driver_sql("SELECT created_at FROM orders").scalar_one()
        typed = connection.execute(select(order.created_at)).scalar_one()
    connection.rollback()
    return {
        "input": str(supplied),
        "raw": str(raw),
        "raw_type": type(raw).__name__,
        "typed": str(typed),
        "typed_type": type(typed).__name__,
    }


def _observe(url: str | URL, backend: str, library: str, track: str) -> dict[str, Any]:
    statements = (
        (sqlite_models if backend == "sqlite" else mariadb_models).ddl()
        if library == "snekql"
        else sqlalchemy_models.ddl(backend, track)
    )
    engine = create_engine(url)
    observation: dict[str, Any] = {
        "ddl": statements,
        "probes": {},
        "application": observe_construction(backend, library, track, engine.dialect),
    }
    try:
        with engine.connect() as connection:
            if backend == "sqlite":
                connection.exec_driver_sql("PRAGMA foreign_keys=ON")
                controls = "SELECT sqlite_version() AS version"
            else:
                connection.exec_driver_sql(
                    "SET SESSION sql_mode='STRICT_ALL_TABLES,NO_ENGINE_SUBSTITUTION'"
                )
                connection.exec_driver_sql("SET SESSION time_zone='+00:00'")
                connection.exec_driver_sql("SET SESSION check_constraint_checks=1")
                # Freeze CURRENT_TIMESTAMP without depending on the wall clock.
                connection.exec_driver_sql("SET timestamp=1767323045.123456")
                controls = "SELECT VERSION() AS version, @@sql_mode AS sql_mode, @@check_constraint_checks AS check_constraint_checks, @@time_zone AS time_zone, @@timestamp AS clock, @@default_storage_engine AS engine, @@character_set_database AS charset, @@collation_database AS collation"
            observation["controls"] = dict(
                connection.exec_driver_sql(controls).mappings().one()
            )
            if backend == "sqlite":
                observation["controls"]["foreign_keys"] = connection.exec_driver_sql(
                    "PRAGMA foreign_keys"
                ).scalar_one()
            for statement in statements:
                connection.exec_driver_sql(statement)
            inspector = inspect(connection)
            observation["columns"] = {
                name: inspector.get_columns(name)
                for name in ("products", "cent_products", "orders")
            }
            observation["installed_ddl"] = (
                [
                    list(row)
                    for row in connection.exec_driver_sql(
                        "SELECT name,sql FROM sqlite_schema ORDER BY name"
                    )
                ]
                if backend == "sqlite"
                else [
                    list(
                        connection.exec_driver_sql(f"SHOW CREATE TABLE `{name}`").one()
                    )
                    for name in observation["columns"]
                ]
            )
            connection.commit()
            for probe in PROBES:
                observation["probes"][probe.name] = _probe(connection, backend, probe)
                connection.rollback()
            if library == "sqlalchemy":
                product = sqlalchemy_models.models(backend, track)["products"]
                connection.exec_driver_sql(
                    "INSERT INTO products (price) VALUES ('1.239')"
                )
                raw = connection.exec_driver_sql(
                    "SELECT price FROM products"
                ).scalar_one()
                typed = connection.execute(select(product.price)).scalar_one()
                observation["typed_price_readback"] = {
                    "raw": str(raw),
                    "raw_type": type(raw).__name__,
                    "typed": str(typed),
                    "typed_type": type(typed).__name__,
                }
                connection.rollback()
            observation["bound_timestamp"] = _bound_timestamp(
                connection, backend, library, track
            )
            rule_table = "rule_orders" if library == "sqlalchemy" else "orders"
            rule_statements = (
                database_rules.ddl(backend) if library == "sqlalchemy" else []
            )
            for statement in rule_statements:
                connection.exec_driver_sql(statement)
            connection.commit()
            rule_observations: dict[str, Any] = {
                "ddl": rule_statements,
                "snekql_scaffold_extended": False,
            }
            observation["database_rules"] = rule_observations
            for name, statement in (
                (
                    "zero_quantity",
                    f"INSERT INTO {rule_table} (quantity,status) VALUES (0,'pending')",  # noqa: S608 - fixed fixture table names.
                ),
                (
                    "literal_server_default",
                    f"INSERT INTO {rule_table} (quantity) VALUES (1)",  # noqa: S608 - fixed fixture table names.
                ),
            ):
                rule_observations[name] = _probe(
                    connection,
                    backend,
                    Probe(
                        name,
                        "Does an explicitly database-level rule enforce the desired behavior?",
                        (statement,),
                        f"SELECT status FROM {rule_table}",  # noqa: S608 - fixed fixture table names.
                    ),
                )
                connection.rollback()
            if backend == "mariadb":
                connection.exec_driver_sql("SET SESSION time_zone='+05:30'")
                observation["timezone_shift"] = _probe(
                    connection,
                    backend,
                    next(
                        probe for probe in PROBES if probe.name == "timestamp_default"
                    ),
                )
                connection.rollback()
    finally:
        engine.dispose()
    return observation


def _write_artifacts(observations: dict[str, Any]) -> None:
    directory = Path(__file__).parent
    (directory / "results.json").write_text(
        dumps(observations, indent=2, default=str) + "\n"
    )
    for name, observation in observations["runs"].items():
        (directory / f"{name.replace('/', '-')}.sql").write_text(
            ";\n\n".join(observation["ddl"]) + ";\n"
        )

    for backend in ("sqlite", "mariadb"):
        rule_ddl = observations["runs"][f"{backend}/sqlalchemy/idiomatic"][
            "database_rules"
        ]["ddl"]
        (directory / f"{backend}-sqlalchemy-database-rules.sql").write_text(
            ";\n".join(rule_ddl) + ";\n"
        )
        for track in ("idiomatic", "matched"):
            structures = [
                dumps(
                    observations["runs"][f"{backend}/{library}/{track}"]["columns"],
                    indent=2,
                    sort_keys=True,
                    default=str,
                ).splitlines(keepends=True)
                for library in ("snekql", "sqlalchemy")
            ]
            (directory / f"{backend}-{track}-columns.diff").write_text(
                "".join(
                    unified_diff(*structures, fromfile="snekql", tofile="sqlalchemy")
                )
            )


async def observe_sqlite(library: str, track: str) -> dict[str, Any]:
    """Return the evidence from one isolated SQLite run."""
    return await asyncio.to_thread(_observe, "sqlite://", "sqlite", library, track)


async def main() -> None:
    """Run both libraries on controlled temporary engines and write evidence."""
    observations: dict[str, Any] = {
        "versions": {
            name: version(name)
            for name in ("snekql", "sqlalchemy", "pymysql", "pydantic")
        },
        "python": python_version(),
        "runs": {},
    }
    for library in ("snekql", "sqlalchemy"):
        for track in ("idiomatic", "matched"):
            observations["runs"][f"sqlite/{library}/{track}"] = await observe_sqlite(
                library, track
            )
            async with temporary_mariadb_server(
                server_args=(
                    "--character-set-server=utf8mb4",
                    "--collation-server=utf8mb4_bin",
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
                    f"mariadb/{library}/{track}"
                ] = await asyncio.to_thread(_observe, url, "mariadb", library, track)
    await asyncio.to_thread(_write_artifacts, observations)


if __name__ == "__main__":
    asyncio.run(main())
