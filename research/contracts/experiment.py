"""Real transactions and ORM sessions, with independent readback and raw SQL."""

import asyncio
from dataclasses import asdict
from importlib.metadata import version
from json import dumps
from os import fsdecode
from pathlib import Path
from platform import python_version
from tempfile import TemporaryDirectory
from typing import Any

from pydantic import ValidationError
from sqlalchemy import (
    URL,
    CheckConstraint,
    DefaultClause,
    MetaData,
    delete,
    event,
    insert,
    select,
    text,
)
from sqlalchemy.exc import StatementError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine
from sqlalchemy.schema import CreateTable

from research.contracts import mariadb_models, sqlite_models
from research.contracts.cases import application_cases
from research.contracts.raw import expected_data_error, inspect_schema, observe_raw
from research.contracts.snekql_inputs import validate_integer_inputs
from research.contracts.sqlalchemy_models import models
from snekql.errors import ExecutionError, ModelValidationError, SchemaVerificationError
from snekql.testing.mariadb import temporary_mariadb_server


def _snapshot(order: Any) -> dict[str, str]:
    """Record representations; callers fetch generated ORM values before using this."""
    return {
        name: str(getattr(order, name))
        for name in ("id", "price_cents", "quantity", "status", "created_at")
    }


def _engine(url: str | URL, backend: str) -> AsyncEngine:
    engine = create_async_engine(url)

    @event.listens_for(engine.sync_engine, "connect")
    def configure(connection: Any, _record: Any) -> None:
        # SQLAlchemy adapts these synchronous event calls to the async driver.
        cursor = connection.cursor()
        try:
            if backend == "sqlite":
                cursor.execute("PRAGMA foreign_keys=ON")
            else:
                cursor.execute("SET SESSION time_zone='+00:00'")
                cursor.execute(
                    "SET SESSION sql_mode='STRICT_ALL_TABLES,NO_ZERO_IN_DATE,NO_ZERO_DATE,ERROR_FOR_DIVISION_BY_ZERO,NO_ENGINE_SUBSTITUTION'"
                )
                cursor.execute("SET SESSION check_constraint_checks=1")
        finally:
            cursor.close()

    return engine


async def _sqlalchemy_case(
    engine: AsyncEngine, order: Any, backend: str, supplied: dict[str, Any]
) -> dict[str, Any]:
    stage = "construction"
    record: dict[str, Any] = {
        "input": {
            key: {"value": str(value), "type": type(value).__name__}
            for key, value in supplied.items()
        }
    }
    try:
        pending = order(**supplied)
        record["before"] = _snapshot(pending)
        stage = "flush"
        async with AsyncSession(engine, expire_on_commit=False) as session:
            session.add(pending)
            await session.flush()
            stage = "commit"
            await session.commit()
            record["after"] = _snapshot(pending)
        stage = "fetch"
        async with AsyncSession(engine) as session:
            fetched = (await session.scalars(select(order))).one()
            record["fetched"] = _snapshot(fetched)
            record["fetched_types"] = {
                key: type(getattr(fetched, key)).__name__ for key in record["fetched"]
            }
    except ValidationError as e:
        record.update(outcome="rejected", stage=stage, error=str(e))
    except StatementError as e:
        if not isinstance(e.orig, ValidationError) and not expected_data_error(
            e.orig, backend
        ):
            raise
        record.update(
            outcome="rejected", stage=stage, error=str(e.orig), wrapper=type(e).__name__
        )
    else:
        record.update(outcome="accepted", stage=stage)
    finally:
        async with engine.begin() as connection:
            await connection.execute(delete(order))
    return record


async def _snekql_case(
    database: Any,
    declarations: Any,
    supplied: dict[str, Any],
    *,
    check_inputs: bool = True,
) -> dict[str, Any]:
    namespace = declarations.db
    order = declarations.Order
    stage = "construction"
    record: dict[str, Any] = {
        "input": {
            key: {"value": str(value), "type": type(value).__name__}
            for key, value in supplied.items()
        }
    }
    try:
        if check_inputs:
            stage = "input_validation"
            validate_integer_inputs(supplied)
        stage = "construction"
        pending = order(**supplied)
        record["before"] = _snapshot(pending)
        stage = "execute"
        async with database.transaction() as transaction:
            await transaction.execute(namespace.insert(pending))
            stage = "commit"
        record["after"] = _snapshot(pending)
        stage = "fetch"
        async with database.transaction() as transaction:
            fetched = await transaction.fetch_one(namespace.select(order).all())
            record["fetched"] = _snapshot(fetched)
            record["fetched_types"] = {
                key: type(getattr(fetched, key)).__name__ for key in record["fetched"]
            }
    except ModelValidationError as e:
        record.update(outcome="rejected", stage=stage, error=str(e))
    except ExecutionError as e:
        backend = "sqlite" if declarations is sqlite_models else "mariadb"
        if not expected_data_error(e.__cause__, backend):
            raise
        record.update(outcome="rejected", stage=stage, error=str(e))
    else:
        record.update(outcome="accepted", stage=stage)
    finally:
        async with database.transaction() as transaction:
            await transaction.execute(namespace.delete(order).all())
    return record


async def _verify_snekql(database: Any, declarations: Any) -> dict[str, Any]:
    await database.verify_migrations(declarations.MIGRATIONS)
    try:
        verification = await database.verify([declarations.Order])
    except SchemaVerificationError as e:
        return {
            "migration_history": "accepted",
            "strict": "rejected",
            "issues": [asdict(issue) for issue in e.result.issues],
        }
    return {
        "migration_history": "accepted",
        "strict": "accepted",
        "issues": [asdict(issue) for issue in verification.issues],
    }


async def _sqlalchemy_bulk(
    engine: AsyncEngine, order: Any, backend: str
) -> dict[str, Any]:
    observations: dict[str, Any] = {}
    for name, supplied in (
        ("null_timestamp", {"created_at": None}),
        ("bool_quantity", {"quantity": True}),
    ):
        try:
            async with AsyncSession(engine) as session:
                await session.execute(
                    insert(order), [{"price_cents": 123, "quantity": 1, **supplied}]
                )
                await session.commit()
        except StatementError as e:
            if not isinstance(e.orig, ValidationError) and not expected_data_error(
                e.orig, backend
            ):
                raise
            observations[name] = {
                "outcome": "rejected",
                "stage": "bulk_execute",
                "error": str(e.orig),
                "wrapper": type(e).__name__,
            }
        else:
            observations[name] = {"outcome": "accepted"}
        finally:
            async with engine.begin() as connection:
                await connection.execute(delete(order))
    return observations


async def _observe_sqlalchemy(engine: AsyncEngine, backend: str) -> dict[str, Any]:
    order = models(backend)
    observations: dict[str, Any] = {
        "application": {},
        "ddl": str(CreateTable(order.__table__).compile(dialect=engine.dialect)),
    }
    async with engine.begin() as connection:
        await connection.run_sync(order.metadata.create_all)
    for name, supplied in application_cases().items():
        observations["application"][name] = await _sqlalchemy_case(
            engine, order, backend, supplied
        )
    observations["bulk"] = await _sqlalchemy_bulk(engine, order, backend)
    observations["raw"] = await observe_raw(engine, backend)
    observations["schema"] = await inspect_schema(engine, backend)
    observations["drift"] = {}
    for name in ("removed_checks", "changed_default"):
        altered_table = order.__table__.to_metadata(MetaData())
        if name == "removed_checks":
            altered_table.constraints = {
                constraint
                for constraint in altered_table.constraints
                if not isinstance(constraint, CheckConstraint)
            }
        else:
            altered_table.c.status.server_default = DefaultClause(text("'queued'"))
        altered = str(CreateTable(altered_table).compile(dialect=engine.dialect))
        async with engine.begin() as connection:
            await connection.exec_driver_sql("DROP TABLE orders")
            await connection.exec_driver_sql(altered)
            # This is deliberately create_all, not a migration or a verifier.
            await connection.run_sync(order.metadata.create_all)
        probes = await observe_raw(engine, backend)
        observations["drift"][name] = {
            "altered_ddl": altered,
            "create_all": "completed",
            "schema": await inspect_schema(engine, backend),
            "zero_quantity": probes["zero_quantity"]["outcome"],
            "raw": probes,
            "default_readback": await _sqlalchemy_case(
                engine, order, backend, {"price_cents": 123, "quantity": 1}
            ),
        }
    return observations


async def _observe_snekql(
    engine: AsyncEngine, backend: str, config: Any
) -> dict[str, Any]:
    declarations: Any = sqlite_models if backend == "sqlite" else mariadb_models
    observations: dict[str, Any] = {
        "application": {},
        "ddl": declarations.MIGRATIONS["001_orders"],
        "scaffold": declarations.db.scaffold([declarations.Order]),
    }
    async with await declarations.db.Database.initialize(config) as database:
        observations["migrations"] = asdict(
            await database.migrate(declarations.MIGRATIONS)
        )
        observations["verification"] = await _verify_snekql(database, declarations)
        observations["native_bool_quantity"] = await _snekql_case(
            database,
            declarations,
            {"price_cents": 123, "quantity": True},
            check_inputs=False,
        )
        for name, supplied in application_cases().items():
            observations["application"][name] = await _snekql_case(
                database, declarations, supplied
            )
        observations["raw"] = await observe_raw(engine, backend)
        observations["schema"] = await inspect_schema(engine, backend)
        observations["drift"] = {}
        for name, altered in (
            (
                "removed_checks",
                observations["ddl"]
                .replace(" CHECK (price_cents BETWEEN 0 AND 9999999999)", "")
                .replace(" CHECK (quantity BETWEEN 1 AND 2147483647)", ""),
            ),
            (
                "changed_default",
                observations["ddl"].replace("DEFAULT 'pending'", "DEFAULT 'queued'"),
            ),
        ):
            async with engine.begin() as connection:
                await connection.exec_driver_sql("DROP TABLE orders")
                await connection.exec_driver_sql(altered)
            probes = await observe_raw(engine, backend)
            observations["drift"][name] = {
                "altered_ddl": altered,
                "verification": await _verify_snekql(database, declarations),
                "schema": await inspect_schema(engine, backend),
                "zero_quantity": probes["zero_quantity"]["outcome"],
                "raw": probes,
                "default_readback": await _snekql_case(
                    database, declarations, {"price_cents": 123, "quantity": 1}
                ),
            }
        async with database.transaction() as transaction:
            observations["runtime_controls"] = await transaction.fetch_one(
                declarations.db.raw(
                    "SELECT sqlite_version() AS version"
                    if backend == "sqlite"
                    else "SELECT VERSION() AS version, @@time_zone AS time_zone, @@sql_mode AS sql_mode, @@check_constraint_checks AS check_constraint_checks"
                )
            )
    return observations


async def _observe(
    url: str | URL, backend: str, library: str, config: Any
) -> dict[str, Any]:
    engine = _engine(url, backend)
    try:
        observations = await (
            _observe_snekql(engine, backend, config)
            if library == "snekql"
            else _observe_sqlalchemy(engine, backend)
        )
        async with engine.connect() as connection:
            controls = await connection.exec_driver_sql(
                "SELECT sqlite_version() AS version"
                if backend == "sqlite"
                else "SELECT VERSION() AS version, @@time_zone AS time_zone, @@sql_mode AS sql_mode, @@check_constraint_checks AS check_constraint_checks, @@default_storage_engine AS engine, @@collation_database AS collation"
            )
            observations["raw_connection_controls"] = dict(controls.mappings().one())
            if backend == "sqlite":
                observations["raw_connection_controls"]["foreign_keys"] = (
                    await connection.exec_driver_sql("PRAGMA foreign_keys")
                ).scalar_one()
        return observations
    finally:
        await engine.dispose()


async def observe_sqlite(library: str) -> dict[str, Any]:
    """Use an isolated SQLite file so external raw probes see the same database."""
    directory = await asyncio.to_thread(TemporaryDirectory, prefix="snekql-contracts-")
    try:
        path = Path(fsdecode(directory.name)) / "contracts.sqlite"
        return await _observe(
            URL.create("sqlite+aiosqlite", database=str(path)),
            "sqlite",
            library,
            sqlite_models.db.Config(database=path, pool_size=1),
        )
    finally:
        await asyncio.to_thread(directory.cleanup)


async def observe_mariadb(library: str) -> dict[str, Any]:
    """Start a socket-only server owned exclusively by this run."""
    async with temporary_mariadb_server(
        server_args=(
            "--character-set-server=utf8mb4",
            "--collation-server=utf8mb4_bin",
            "--default-storage-engine=InnoDB",
        )
    ) as server:
        return await _observe(
            URL.create(
                "mysql+aiomysql",
                username=server.user,
                database=server.database,
                query={"unix_socket": str(server.socket_path), "charset": "utf8mb4"},
            ),
            "mariadb",
            library,
            server.config(pool_size=1),
        )


async def main() -> None:
    """Retain evidence without importing or changing prior research branches."""
    observations: dict[str, Any] = {
        "python": python_version(),
        "versions": {
            name: version(name)
            for name in (
                "snekql",
                "sqlalchemy",
                "pydantic",
                "aiosqlite",
                "aiomysql",
                "greenlet",
            )
        },
        "runs": {},
    }
    for library in ("snekql", "sqlalchemy"):
        observations["runs"][f"sqlite/{library}"] = await observe_sqlite(library)
        observations["runs"][f"mariadb/{library}"] = await observe_mariadb(library)
    directory = Path(__file__).parent
    await asyncio.to_thread(
        (directory / "results.json").write_text,
        dumps(observations, indent=2, default=str) + "\n",
    )
    for name, run in observations["runs"].items():
        await asyncio.to_thread(
            (directory / f"{name.replace('/', '-')}.sql").write_text,
            run["ddl"].strip() + ";\n",
        )


if __name__ == "__main__":
    asyncio.run(main())
