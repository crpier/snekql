"""Explicit target preparation and execution for experimental migration packages."""

import hashlib
import re
import secrets
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any, Literal

import anyio
lazy import aiomysql
lazy import aiosqlite

from snekql.experimental.migrations import (
    CreateTable,
    Package,
    PackageError,
    _digest,
    _Value,
)
from snekql.mariadb.config import Config as MariaDBConfig
from snekql.mariadb.identifiers import quote_identifier
from snekql.sqlite.config import Config as SQLiteConfig

_HISTORY = "snekql_experimental_migrations"


class Progress(_Value):
    """Persisted acknowledgement, not proof an unacknowledged operation did nothing."""

    revision: str
    digest: str
    phase: Literal["complete", "uncertain"]
    acknowledged_steps: int
    total_steps: int


class Prepared(_Value):
    """Inspectable execution package bound to a target catalog observation."""

    package: Package
    target_id: str
    catalog_digest: str

    @property
    def statements(self) -> tuple[str, ...]:
        """Return frozen SQL in execution order."""
        return self.package.statements


class Target:
    """An explicitly opened migration connection; never initialized implicitly.

    Connections and prepared plans are local to this context. SQLite applies one
    package atomically. The initial executor supports creation, nullable additions and typed UPDATEs.
    """

    def __init__(self, connection: Any, config: SQLiteConfig | MariaDBConfig) -> None:
        self._connection = connection
        self._config = config
        self._guard = anyio.Lock()
        self._closed = False
        self._sqlite = isinstance(config, SQLiteConfig)
        identity = (
            (
                "sqlite",
                str(config.database),
                secrets.token_hex(16) if str(config.database) == ":memory:" else None,
            )
            if isinstance(config, SQLiteConfig)
            else (
                "mariadb",
                str(config.database),
                str(config.unix_socket),
                config.host,
                config.port,
            )
        )
        self._target_id = _digest(identity)
        self._lock_name = (
            "snekql-exp:"
            + hashlib.sha256(str(config.database).encode()).hexdigest()[:40]
        )

    async def _query(
        self, sql: str, params: tuple[object, ...] = ()
    ) -> list[tuple[Any, ...]]:
        cursor = await self._connection.cursor()
        try:
            await cursor.execute(sql, params if self._sqlite else params or None)
            return [tuple(row) for row in await cursor.fetchall()]
        finally:
            await cursor.close()

    def _require_open(self) -> None:
        if self._closed:
            msg = "migration target is closed"
            raise PackageError(msg)

    async def _catalog(self) -> list[tuple[Any, ...]]:
        if not self._sqlite:
            objects = await self._query("SHOW FULL TABLES")
            return sorted(
                [
                    (
                        kind,
                        name,
                        re.sub(
                            r"(?m)(^\) ENGINE=[^\n]*?) AUTO_INCREMENT=\d+\b",
                            r"\1",
                            (
                                await self._query(
                                    "SHOW CREATE TABLE " + quote_identifier(name)
                                )
                            )[0][1],
                        ),
                    )
                    for name, kind in objects
                    if name != _HISTORY
                ]
            )
        return await self._query(
            "SELECT type,name,tbl_name,sql FROM sqlite_schema "
            "WHERE name NOT GLOB 'sqlite_*' AND name != ? ORDER BY type,name",
            (_HISTORY,),
        )

    async def _history(self) -> list[tuple[Any, ...]]:
        if self._sqlite:
            exists = await self._query(
                "SELECT name FROM sqlite_schema WHERE name=?", (_HISTORY,)
            )
        else:
            exists = await self._query(
                "SELECT TABLE_NAME FROM information_schema.TABLES "
                "WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME=%s",
                (_HISTORY,),
            )
        if not exists:
            return []
        return await self._query(
            "SELECT digest,revision,predecessor,phase,catalog,acknowledged,total,state FROM `snekql_experimental_migrations`"
        )

    async def status(self) -> tuple[Progress, ...]:
        """Read execution evidence without requiring an executable next package."""
        async with self._guard:
            self._require_open()
            return tuple(
                Progress(
                    revision=row[1],
                    digest=row[0],
                    phase="complete" if row[3] == "complete" else "uncertain",
                    acknowledged_steps=row[5],
                    total_steps=row[6],
                )
                for row in await self._history()
            )

    async def prepare(
        self, package: Package, *, schema_writers_excluded: bool = False
    ) -> Prepared:
        """Observe without creating history or modifying the target schema."""
        async with self._guard:
            self._require_open()
            Package.load(package.dump())
            if not self._sqlite and not schema_writers_excluded:
                msg = "MariaDB preparation requires caller exclusion of other schema writers"
                raise PackageError(msg)
            if package.target.backend != self._config.backend_family:
                msg = "package backend differs from target"
                raise PackageError(msg)
            objects = await self._catalog()
            catalog = _digest(objects)
            rows = await self._history()
            already_applied = self._check_history(package, rows)
            self._check_catalog_history(rows, catalog)
            if not already_applied:
                names = {row[1] for row in objects}
                conflicts = [
                    operation.table.name
                    for operation in package.draft.operations
                    if isinstance(operation, CreateTable)
                    and operation.table.name in names
                ]
                if conflicts:
                    msg = f"existing objects require explicit adoption: {conflicts}"
                    raise PackageError(msg)
            return Prepared(
                package=package,
                target_id=self._target_id,
                catalog_digest=catalog,
            )

    @staticmethod
    def _check_history(package: Package, rows: list[tuple[Any, ...]]) -> bool:
        """Validate linear ancestry and reject ambiguous progress, even on retries."""
        applied = False
        for digest, revision, _, phase, *_rest in rows:
            if phase != "complete":
                msg = f"uncertain progress for revision {revision!r}; inspect before recovery"
                raise PackageError(msg)
            if revision == package.draft.revision:
                if digest != package.digest:
                    msg = "applied revision execution identity changed"
                    raise PackageError(msg)
                applied = True
        if applied:
            return True
        predecessors = {row[2] for row in rows}
        heads = [row[0] for row in rows if row[0] not in predecessors]
        expected = [package.draft.predecessor] if package.draft.predecessor else []
        if heads != expected:
            msg = "package predecessor does not match target history head"
            raise PackageError(msg)
        prior = next((row for row in rows if row[0] == package.draft.predecessor), None)
        if (prior is None and package.draft.before.tables) or (
            prior is not None
            and prior[7] != _digest(package.draft.before.model_dump(mode="json"))
        ):
            msg = "before state does not match the recorded predecessor contract"
            raise PackageError(msg)
        return False

    @staticmethod
    def _check_catalog_history(rows: list[tuple[Any, ...]], catalog: str) -> None:
        predecessors = {row[2] for row in rows}
        heads = [row for row in rows if row[0] not in predecessors]
        if heads and heads[0][4] != catalog:
            msg = "catalog differs from the last accepted execution; adoption/reconciliation required"
            raise PackageError(msg)

    async def _begin(self) -> None:
        if self._sqlite:
            await self._query("BEGIN IMMEDIATE")
        else:
            acquired = await self._query(
                "SELECT GET_LOCK(%s,%s)",
                (self._lock_name, int(self._config.acquire_timeout)),
            )
            if acquired != [(1,)]:
                msg = "could not acquire migration advisory lock"
                raise PackageError(msg)

    async def _execute_package(self, package: Package) -> None:
        suffix = "STRICT" if self._sqlite else "ENGINE=InnoDB"
        await self._query(
            "CREATE TABLE IF NOT EXISTS `snekql_experimental_migrations` ("
            "digest VARCHAR(64) PRIMARY KEY, revision TEXT NOT NULL, predecessor VARCHAR(64), "
            "phase TEXT NOT NULL, catalog TEXT NOT NULL, acknowledged INTEGER NOT NULL, total INTEGER NOT NULL, state TEXT NOT NULL) "
            + suffix
            if not self._sqlite
            else "CREATE TABLE IF NOT EXISTS `snekql_experimental_migrations` ("
            "digest TEXT PRIMARY KEY, revision TEXT NOT NULL, predecessor TEXT, "
            "phase TEXT NOT NULL, catalog TEXT NOT NULL, acknowledged INTEGER NOT NULL, total INTEGER NOT NULL, state TEXT NOT NULL) STRICT"
        )
        markers = "?,?,?,?,?,?,?,?" if self._sqlite else "%s,%s,%s,%s,%s,%s,%s,%s"
        await self._query(
            "INSERT INTO `snekql_experimental_migrations` VALUES(" + markers + ")",
            (
                package.digest,
                package.draft.revision,
                package.draft.predecessor,
                "started",
                "",
                0,
                len(package.statements),
                _digest(package.target.model_dump(mode="json")),
            ),
        )
        # MariaDB autocommit makes the started marker durable before any DDL.
        # Any failure thereafter is deliberately uncertain, never blindly replayed.
        marker = "?" if self._sqlite else "%s"
        for index, (statement, params, transactional) in enumerate(
            zip(
                package.statements, package.bindings, package.transactional, strict=True
            ),
            start=1,
        ):
            if transactional and not self._sqlite:
                await self._connection.begin()
            await self._query(statement, params)
            await self._query(
                "UPDATE `snekql_experimental_migrations` SET acknowledged="  # noqa: S608 - only fixed placeholders are interpolated
                + marker
                + " WHERE digest="
                + marker,
                (index, package.digest),
            )
            if transactional and not self._sqlite:
                await self._connection.commit()
        await self._query(
            "UPDATE `snekql_experimental_migrations` SET phase='complete', catalog="  # noqa: S608 - only fixed placeholders are interpolated
            + marker
            + " WHERE digest="
            + marker,
            (_digest(await self._catalog()), package.digest),
        )
        await self._connection.commit()

    async def apply(self, prepared: Prepared) -> Literal["applied", "already_applied"]:
        """Recheck observations under coordination; never replay uncertain progress."""
        async with self._guard:
            self._require_open()
            package = Package.load(prepared.package.dump())
            if prepared.target_id != self._target_id:
                msg = "prepared plan belongs to another target"
                raise PackageError(msg)
            await self._begin()
            try:
                rows = await self._history()
                already_applied = self._check_history(package, rows)
                catalog = _digest(await self._catalog())
                self._check_catalog_history(rows, catalog)
                if already_applied:
                    await self._connection.rollback()
                    return "already_applied"
                if prepared.catalog_digest != catalog:
                    msg = "prepared catalog is stale; prepare and review again"
                    raise PackageError(msg)  # noqa: TRY301 - rollback covers validation
                await self._execute_package(package)
            except BaseException:
                with anyio.CancelScope(shield=True):
                    await self._connection.rollback()
                raise
            finally:
                if not self._sqlite:
                    with anyio.CancelScope(shield=True):
                        await self._query("SELECT RELEASE_LOCK(%s)", (self._lock_name,))
            return "applied"


@asynccontextmanager
async def connect(config: SQLiteConfig | MariaDBConfig) -> AsyncIterator[Target]:
    """Open a dedicated migration connection; importing the module opens nothing."""
    if isinstance(config, SQLiteConfig):
        connection = await aiosqlite.connect(
            str(config.database), isolation_level=None, timeout=config.acquire_timeout
        )
    else:
        connection = await aiomysql.connect(
            host=config.host,
            port=config.port,
            user=config.user,
            password=config.password,
            db=config.database,
            charset=config.charset,
            unix_socket=str(config.unix_socket) if config.unix_socket else None,
            ssl=config.tls._create_ssl_context() if config.tls else None,  # noqa: SLF001 - same library TLS implementation
            autocommit=True,
        )
    target = Target(connection, config)
    try:
        if isinstance(config, SQLiteConfig):
            await target._query("PRAGMA foreign_keys=ON")  # noqa: SLF001 - module owns connection lifecycle
        yield target
    finally:
        target._closed = True  # noqa: SLF001 - module owns connection lifecycle
        with anyio.CancelScope(shield=True):
            if isinstance(config, SQLiteConfig):
                await connection.close()
            else:
                connection.close()
