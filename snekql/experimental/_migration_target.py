"""Explicit target preparation and execution for experimental migration packages."""

import hashlib
import json
import secrets
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any, Literal

import anyio
lazy import aiomysql
lazy import aiosqlite

from snekql.experimental._migration_mariadb import (
    mariadb_declaration_obstacle,
    mariadb_declared_auto_increment,
    mariadb_declared_collation,
    mariadb_storage_type_matches,
    validate_mariadb_declarations,
)
from snekql.experimental._migration_prepare import (
    ExecutionStep,
    prepare_steps,
    validate_adopted,
    validate_completed,
    validate_preserved,
)
from snekql.experimental._migration_reconcile import matches_contraction
from snekql.experimental._migration_sql import (
    ascii_lower,
    tokens,
    without_auto_increment_counter,
)
from snekql.experimental.migrations import (
    CreateTable,
    Package,
    PackageError,
    TableState,
    _canonical,
    _digest,
    _Value,
)
from snekql.mariadb.config import Config as MariaDBConfig
from snekql.mariadb.identifiers import quote_identifier
from snekql.sqlite.config import Config as SQLiteConfig

_HISTORY = "snekql_experimental_migrations"
_MARIADB_NO_SUCH_TABLE = 1146
_MARIADB_UNKNOWN_COLUMN = 1054


class Reconciliation(_Value):
    """Durable acceptance of a structural postcondition, not an execution receipt."""

    step: int
    reason: str
    before_digest: str
    after_digest: str
    before_catalog: tuple[tuple[str, str, str], ...]
    after_catalog: tuple[tuple[str, str, str], ...]
    rendering_profile: tuple[str, ...]


class Progress(_Value):
    """Acknowledged progress, with structural acceptances distinguished from receipts."""

    revision: str
    digest: str
    phase: Literal["complete", "uncertain"]
    acknowledged_steps: int
    total_steps: int
    reconciliations: tuple[Reconciliation, ...] = ()


class Prepared(_Value):
    """Inspectable execution package bound to a target catalog observation."""

    package: Package
    target_id: str
    catalog_digest: str
    steps: tuple[ExecutionStep, ...]
    preserve_unmanaged: bool = False

    @property
    def statements(self) -> tuple[str, ...]:
        """Return frozen SQL in execution order."""
        return tuple(sql for step in self.steps for sql in step.statements)


class Recovery(_Value):
    """Inspectable evidence, not permission to guess whether uncertain work ran."""

    prepared: Prepared
    acknowledged_steps: int
    catalog_digest: str
    disposition: Literal[
        "retry_remaining", "finish", "ambiguous", "reconcile_structural"
    ]
    explanation: str
    before_catalog: tuple[tuple[str, str, str], ...]
    observed_catalog: tuple[tuple[str, str, str], ...]
    before_profile: tuple[str, ...]
    observed_profile: tuple[str, ...]


class Target:
    """An explicitly opened migration connection; never initialized implicitly.

    Connections are local to this context; prepared plans bind an observed target
    identity. SQLite applies a package atomically. MariaDB uses durable evidence
    and explicit recovery, not automatic replay.
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
        except anyio.get_cancelled_exc_class():
            if not self._sqlite:
                # Inspection also performs protocol reads outside _coordinated.
                self._closed = True
                self._connection.close()
            raise
        finally:
            await cursor.close()

    def _require_open(self) -> None:
        if self._closed:
            msg = "migration target is closed"
            raise PackageError(msg)

    async def _catalog(self) -> list[tuple[Any, ...]]:
        if not self._sqlite:
            objects = await self._query("SHOW FULL TABLES")
            mode = (await self._query("SELECT @@SESSION.sql_mode"))[0][0]
            observed = []
            for name, kind in objects:
                if name == _HISTORY:
                    continue
                sql = (
                    await self._query("SHOW CREATE TABLE " + quote_identifier(name))
                )[0][1]
                if kind == "BASE TABLE":
                    sql = without_auto_increment_counter(
                        sql,
                        backslash_escapes="NO_BACKSLASH_ESCAPES" not in mode.split(","),
                    )
                observed.append((kind, name, sql))
            return sorted(observed)
        return await self._query(
            "SELECT type,name,tbl_name,sql FROM sqlite_schema "
            "WHERE name NOT GLOB 'sqlite_*' AND name != ? ORDER BY type,name",
            (_HISTORY,),
        )

    async def _rendering_profile(self) -> tuple[str, ...]:
        if self._sqlite:
            return ()
        row = (
            await self._query(
                "SELECT VERSION(),@@SESSION.sql_mode,@@SESSION.sql_quote_show_create"
            )
        )[0]
        return tuple(str(value) for value in row)

    async def _record_observation(self, catalog: list[tuple[Any, ...]]) -> str:
        return _canonical(
            {"catalog": catalog, "profile": await self._rendering_profile()}
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
        if self._sqlite:
            columns = {
                row[1]
                for row in await self._query(
                    "PRAGMA table_info(`snekql_experimental_migrations`)"
                )
            }
        else:
            columns = {
                row[0]
                for row in await self._query(
                    "SELECT COLUMN_NAME FROM information_schema.COLUMNS WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME=%s",
                    (_HISTORY,),
                )
            }
        expected = {
            "digest",
            "revision",
            "predecessor",
            "phase",
            "catalog",
            "acknowledged",
            "total",
            "state",
            "plan",
            "observation",
            "reconciliations",
        }
        if columns != expected:
            msg = "unsupported experimental ledger layout; no automatic conversion is available"
            raise PackageError(msg)
        return await self._query(
            "SELECT digest,revision,predecessor,phase,catalog,acknowledged,total,state,plan,observation,reconciliations FROM `snekql_experimental_migrations`"
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
                    reconciliations=tuple(
                        Reconciliation.model_validate(item)
                        for item in json.loads(row[10])
                    ),
                )
                for row in await self._history()
            )

    async def prepare(
        self,
        package: Package,
        *,
        schema_writers_excluded: bool = False,
        preserve_unmanaged: bool = False,
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
            if preserve_unmanaged and not already_applied:
                if not self._sqlite:
                    msg_0 = "preservation review currently supports SQLite only"
                    raise PackageError(msg_0)
                validate_preserved(package, objects)
            else:
                self._check_catalog_history(rows, catalog)
            if not already_applied:
                validate_adopted(package, objects)
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
                steps=() if already_applied else prepare_steps(package, objects),
                preserve_unmanaged=preserve_unmanaged,
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

    async def _execute_package(
        self, prepared: Prepared, *, start: int | None = None
    ) -> None:
        package = prepared.package
        validate_mariadb_declarations(package.target)
        first = start or 0
        if first < len(prepared.steps):
            await self._check_required(prepared.steps[first])
        if start is None:
            await self._start_package(prepared)
        marker = "?" if self._sqlite else "%s"
        for index, step in enumerate(prepared.steps[first:], start=first + 1):
            if step.transactional and not self._sqlite:
                if await self._transactional_obstacles():
                    msg = "transactional data changes require InnoDB tables without triggers or stored routines"
                    raise PackageError(msg)
                await self._connection.begin()
            await self._execute_step(step)
            observation = await self._catalog()
            await self._query(
                "UPDATE `snekql_experimental_migrations` SET acknowledged="  # noqa: S608 - fixed placeholders or quoted identifiers
                + marker
                + ", catalog="
                + marker
                + ", observation="
                + marker
                + " WHERE digest="
                + marker,
                (
                    index,
                    _digest(observation),
                    await self._record_observation(observation),
                    package.digest,
                ),
            )
            if step.transactional and not self._sqlite:
                await self._connection.commit()
        if (
            self._sqlite
            and any(step.rebuild for step in prepared.steps)
            and await self._query("PRAGMA foreign_key_check")
        ):
            msg_0 = "rebuild failed foreign-key validation; transaction rolled back"
            raise PackageError(msg_0)
        completed_catalog = await self._catalog()
        if self._sqlite:
            validate_completed(package, completed_catalog)
        elif obstacle := await self._mariadb_presence_obstacle(
            package, completed_catalog
        ):
            raise PackageError(obstacle)
        await self._query(
            "UPDATE `snekql_experimental_migrations` SET phase='complete', catalog="  # noqa: S608 - fixed placeholders or quoted identifiers
            + marker
            + " WHERE digest="
            + marker,
            (_digest(completed_catalog), package.digest),
        )
        await self._connection.commit()

    async def _mariadb_presence_obstacle(
        self, package: Package, catalog: list[tuple[Any, ...]]
    ) -> str | None:
        """Explain a managed table or column that cannot resolve on this server."""
        if not package.target.tables:
            return None
        mode = (await self._query("SELECT @@SESSION.sql_mode"))[0][0]
        definitions = {sql for kind, _, sql in catalog if kind == "BASE TABLE"}
        for table in package.target.tables:
            try:
                resolved = await self._query(
                    "SHOW CREATE TABLE " + quote_identifier(table.name)
                )
            except aiomysql.ProgrammingError as error:
                if error.args[:1] != (_MARIADB_NO_SUCH_TABLE,):
                    raise
                return f"managed table postcondition failed: {table.name!r} is missing; committed MariaDB effects may remain"
            # SHOW's name column may echo the requested spelling. Its definition
            # uses the server-resolved physical name, including case-folding modes.
            if (
                len(resolved) != 1
                or without_auto_increment_counter(
                    resolved[0][1],
                    backslash_escapes="NO_BACKSLASH_ESCAPES" not in mode.split(","),
                )
                not in definitions
            ):
                return f"managed table postcondition failed: {table.name!r} is not an observed base table; committed MariaDB effects may remain"
            if obstacle := await self._mariadb_column_obstacle(table):
                return obstacle
        return None

    async def _mariadb_column_obstacle(self, table: TableState) -> str | None:
        """Bind physical metadata by server-resolved names, then check recorded facts."""
        if not table.columns:
            return None
        observed = await self._query(
            "SHOW FULL COLUMNS FROM " + quote_identifier(table.name)
        )
        if not observed or any(row[3] not in {"YES", "NO"} for row in observed):
            return f"managed column postcondition failed: {table.name!r} has no visible columns or unsupported nullability metadata; committed MariaDB effects may remain"
        metadata = {str(index): row for index, row in enumerate(observed)}
        namespace = ", ".join(
            f"'{index}' AS {quote_identifier(row[0])}"
            for index, row in metadata.items()
        )
        projection = ", ".join(
            quote_identifier(column.name) for column in table.columns
        )
        # A constant derived table has no primary-key alias such as _rowid. It
        # exposes only catalog names, including invisible columns, while letting
        # the server perform identifier matching without fetching application data.
        try:
            resolved = await self._query(
                f"SELECT {projection} FROM (SELECT {namespace}) AS snekql_columns LIMIT 1"  # noqa: S608 - quoted identifiers and validated metadata constants only
            )
        except (aiomysql.ProgrammingError, aiomysql.OperationalError) as error:
            if error.args[:1] != (_MARIADB_UNKNOWN_COLUMN,):
                raise
            return f"managed column postcondition failed: declared columns of {table.name!r} do not all resolve in the observed physical column namespace; committed MariaDB effects may remain"
        if (
            len(resolved) != 1
            or len(resolved[0]) != len(table.columns)
            or any(key not in metadata for key in resolved[0])
        ):
            return f"managed column postcondition failed: {table.name!r} has ambiguous resolved metadata; committed MariaDB effects may remain"
        matched = tuple(metadata[key] for key in resolved[0])
        for column, row in zip(table.columns, matched, strict=True):
            if row[3] != ("YES" if column.nullable else "NO"):
                return f"managed column postcondition failed: {table.name!r}.{column.name!r} nullability differs from the recorded contract; committed MariaDB effects may remain"
        return self._mariadb_type_obstacle(table, matched)

    @staticmethod
    def _mariadb_type_obstacle(
        table: TableState, observed: tuple[tuple[Any, ...], ...]
    ) -> str | None:
        """Explain unsupported or different storage, generation or collation facts."""
        for column, row in zip(table.columns, observed, strict=True):
            try:
                matches = mariadb_storage_type_matches(column.definition, row[1])
            except PackageError as error:
                return f"managed column postcondition failed: {table.name!r}.{column.name!r}: {error}; committed MariaDB effects may remain"
            if not matches:
                return f"managed column postcondition failed: {table.name!r}.{column.name!r} storage type differs from the recorded contract; committed MariaDB effects may remain"
            auto_increment = mariadb_declared_auto_increment(column.definition)
            if not isinstance(row[6], str):
                return f"managed column postcondition failed: {table.name!r}.{column.name!r} has unsupported EXTRA metadata; committed MariaDB effects may remain"
            if auto_increment != ("auto_increment" in row[6].lower().split()):
                return f"managed column postcondition failed: {table.name!r}.{column.name!r} AUTO_INCREMENT differs from the recorded contract; committed MariaDB effects may remain"
            collation = mariadb_declared_collation(column.definition)
            if collation is not None and row[2] != collation:
                return f"managed column postcondition failed: {table.name!r}.{column.name!r} collation differs from the recorded contract; committed MariaDB effects may remain"
        return None

    async def _start_package(self, prepared: Prepared) -> None:
        package = prepared.package
        suffix = "STRICT" if self._sqlite else "ENGINE=InnoDB"
        await self._query(
            "CREATE TABLE IF NOT EXISTS `snekql_experimental_migrations` ("
            "digest VARCHAR(64) PRIMARY KEY, revision TEXT NOT NULL, predecessor VARCHAR(64), "
            "phase TEXT NOT NULL, catalog TEXT NOT NULL, acknowledged INTEGER NOT NULL, total INTEGER NOT NULL, state TEXT NOT NULL, plan TEXT NOT NULL, observation LONGTEXT NOT NULL, reconciliations LONGTEXT NOT NULL) "
            + suffix
            if not self._sqlite
            else "CREATE TABLE IF NOT EXISTS `snekql_experimental_migrations` ("
            "digest TEXT PRIMARY KEY, revision TEXT NOT NULL, predecessor TEXT, "
            "phase TEXT NOT NULL, catalog TEXT NOT NULL, acknowledged INTEGER NOT NULL, total INTEGER NOT NULL, state TEXT NOT NULL, plan TEXT NOT NULL, observation TEXT NOT NULL, reconciliations TEXT NOT NULL) STRICT"
        )
        markers = (
            "?,?,?,?,?,?,?,?,?,?,?"
            if self._sqlite
            else "%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s"
        )
        observation = await self._catalog()
        await self._query(
            "INSERT INTO `snekql_experimental_migrations` (digest,revision,predecessor,phase,catalog,acknowledged,total,state,plan,observation,reconciliations) VALUES("
            + markers
            + ")",
            (
                package.digest,
                package.draft.revision,
                package.draft.predecessor,
                "started",
                _digest(observation),
                0,
                len(package.statements),
                _digest(package.target.model_dump(mode="json")),
                _digest(prepared.model_dump(mode="json")),
                await self._record_observation(observation),
                "[]",
            ),
        )

    async def _check_required(self, step: ExecutionStep) -> None:
        quote = quote_identifier
        for table, column in step.required:
            if await self._query(
                f"SELECT 1 FROM {quote(table)} WHERE {quote(column)} IS NULL LIMIT 1"  # noqa: S608 - fixed placeholders or quoted identifiers
            ):
                msg = f"{table}.{column}: NULL rows remain; backfill before requiring the column"
                raise PackageError(msg)
        if step.required and not self._sqlite:
            mode = (await self._query("SELECT @@SESSION.sql_mode"))[0][0]
            if not {"STRICT_ALL_TABLES", "STRICT_TRANS_TABLES"}.intersection(
                mode.split(",")
            ):
                msg = "required-column alteration needs strict MariaDB SQL mode"
                raise PackageError(msg)

    async def _validate_copy_contract(self, step: ExecutionStep) -> None:
        """Cross-check planned copying against SQLite's independent column metadata."""
        if step.copy_tables is None:
            return
        columns = await self._query(
            "SELECT name, hidden FROM pragma_table_xinfo(?)", (step.copy_tables[0],)
        )
        ordinary = {name for name, hidden in columns if hidden == 0}
        dropped = set(step.dropped_columns)
        copied = set(step.copy_columns)
        if (
            not columns
            or any(hidden not in {0, 2, 3} for _, hidden in columns)
            or not dropped <= {name for name, _ in columns}
            or len(copied) != len(step.copy_columns)
            or copied != ordinary - dropped
        ):
            msg = "SQLite rebuild copy contract differs from engine column metadata; reprepare or use an explicit adapter"
            raise PackageError(msg)

    async def _validate_copied_values(
        self, tables: tuple[str, str], dropped_columns: tuple[str, ...]
    ) -> None:
        """Compare retained typed values and row identity before dropping the source."""
        source, destination = tables
        columns = await self._query(
            "SELECT name, pk FROM pragma_table_xinfo(?)", (source,)
        )
        names = [name for name, _ in columns]
        retained = [name for name in names if name not in dropped_columns]
        storage = await self._query(
            "SELECT wr FROM pragma_table_list WHERE schema='main' AND name=?", (source,)
        )
        if storage == [(0,)]:
            folded = {ascii_lower(name) for name in names}
            rowid = next(
                (name for name in ("_rowid_", "rowid", "oid") if name not in folded),
                None,
            )
            if rowid is None:
                msg = "rebuild copied values cannot be checked without accessible row identity"
                raise PackageError(msg)
            identity = [rowid]
        elif storage == [(1,)]:
            identity = [name for name, primary in columns if primary]
            if not identity or not set(identity) <= set(retained):
                msg = "rebuild copied values require a retained SQLite primary key"
                raise PackageError(msg)
        else:
            msg = "rebuild copied values require known SQLite table storage"
            raise PackageError(msg)
        # Repeat the complete identity in every batch: otherwise values could move
        # between rows while each batch still has the same set of values. Equal
        # row counts and distinct identities make one-way EXCEPT sufficient.
        retained = [name for name in retained if name not in identity]
        for offset in range(0, max(len(retained), 1), 64):
            selected = identity + retained[offset : offset + 64]
            projection = ", ".join(
                f"typeof({quote_identifier(name)}), {quote_identifier(name)} COLLATE BINARY"
                for name in selected
            )
            mismatch = await self._query(
                f"SELECT 1 FROM (SELECT {projection} FROM {quote_identifier(source)} "  # noqa: S608 - fixed placeholders or quoted identifiers
                f"EXCEPT SELECT {projection} FROM {quote_identifier(destination)}) LIMIT 1"
            )
            if mismatch:
                msg = "rebuild did not preserve copied values; transaction rolled back"
                raise PackageError(msg)

    async def _execute_step(self, step: ExecutionStep) -> None:
        await self._check_required(step)
        await self._validate_copy_contract(step)
        quote = quote_identifier
        sequence = []
        if step.sequence_table:
            sequence = await self._query(
                "SELECT seq FROM sqlite_sequence WHERE name=?", (step.sequence_table,)
            )
            if len(sequence) > 1:
                msg = "ambiguous SQLite sequence metadata"
                raise PackageError(msg)
        count = None
        if step.copy_tables:
            count = (
                await self._query(f"SELECT COUNT(*) FROM {quote(step.copy_tables[0])}")  # noqa: S608 - fixed placeholders or quoted identifiers
            )[0][0]
        for index, (sql, params) in enumerate(
            zip(step.statements, step.bindings, strict=True)
        ):
            await self._query(sql, params)
            if index == step.copy_at and step.copy_tables:
                copied = (
                    await self._query(
                        f"SELECT COUNT(*) FROM {quote(step.copy_tables[1])}"  # noqa: S608 - fixed placeholders or quoted identifiers
                    )
                )[0][0]
                if copied != count:
                    msg = "rebuild did not preserve row count"
                    raise PackageError(msg)
                await self._validate_copied_values(
                    step.copy_tables, step.dropped_columns
                )
        if step.validate_triggers:
            await self._validate_triggers()
        if sequence:
            current = await self._query(
                "SELECT seq FROM sqlite_sequence WHERE name=?", (step.sequence_table,)
            )
            highwater = max(sequence[0][0], current[0][0] if current else 0)
            await self._query(
                "DELETE FROM sqlite_sequence WHERE name=?", (step.sequence_table,)
            )
            await self._query(
                "INSERT INTO sqlite_sequence(name,seq) VALUES(?,?)",
                (step.sequence_table, highwater),
            )

    async def _validate_triggers(self) -> None:
        """Ask SQLite to compile trigger programs without executing their effects."""
        for owner, sql in await self._query(
            "SELECT tbl_name,sql FROM sqlite_schema WHERE type='trigger'"
        ):
            stream = tokens(sql)
            event = next(
                (
                    token.value.casefold()
                    for token in stream[3:]
                    if token.kind == "word"
                    and token.value.casefold() in {"insert", "update", "delete"}
                ),
                None,
            )
            table = quote_identifier(owner)
            if event == "insert":
                statement = f"EXPLAIN INSERT INTO {table} DEFAULT VALUES"
            elif event == "delete":
                statement = f"EXPLAIN DELETE FROM {table} WHERE 0"  # noqa: S608 - fixed placeholders or quoted identifiers
            elif event == "update":
                columns = await self._query(f"PRAGMA table_xinfo({table})")
                assignments = ", ".join(
                    f"{quote_identifier(row[1])}={quote_identifier(row[1])}"
                    for row in columns
                    if row[6] == 0
                )
                statement = f"EXPLAIN UPDATE {table} SET {assignments} WHERE 0"  # noqa: S608 - fixed placeholders or quoted identifiers
            else:
                msg = "unsupported trigger declaration during rebuild validation"
                raise PackageError(msg)
            await self._query(statement)

    async def inspect_recovery(
        self, prepared: Prepared, *, schema_writers_excluded: bool = False
    ) -> Recovery:
        """Classify progress using durable acknowledgement and current catalog evidence."""
        async with self._guard:
            self._require_open()
            self._require_recovery_access(prepared, excluded=schema_writers_excluded)
            async with self._coordinated():
                return await self._assess_recovery(prepared)

    def _require_recovery_access(self, prepared: Prepared, *, excluded: bool) -> None:
        if self._sqlite or not excluded:
            msg = "recovery requires MariaDB with external schema writers excluded"
            raise PackageError(msg)
        if (
            prepared.target_id != self._target_id
            or prepared.package.target.backend != "mariadb"
        ):
            msg = "recovery plan belongs to another target"
            raise PackageError(msg)
        Package.load(prepared.package.dump())

    async def _transactional_obstacles(self) -> bool:
        unsafe = await self._query(
            "SELECT TABLE_NAME FROM information_schema.TABLES WHERE TABLE_SCHEMA=DATABASE() AND TABLE_TYPE='BASE TABLE' AND ENGINE <> 'InnoDB'"
        )
        triggers = await self._query("SHOW TRIGGERS")
        routines = await self._query(
            "SELECT ROUTINE_NAME FROM information_schema.ROUTINES WHERE ROUTINE_SCHEMA=DATABASE()"
        )
        return bool(unsafe or triggers or routines)

    async def _assess_recovery(self, prepared: Prepared) -> Recovery:
        rows = await self._history()
        pending = [row for row in rows if row[3] != "complete"]
        if len(pending) != 1 or pending[0][0] != prepared.package.digest:
            msg = "no unique incomplete execution matches this package"
            raise PackageError(msg)
        row = pending[0]
        if row[8] != _digest(prepared.model_dump(mode="json")):
            msg = "recovery requires the original reviewed prepared plan"
            raise PackageError(msg)
        self._check_history(
            prepared.package, [item for item in rows if item[3] == "complete"]
        )
        observation = await self._catalog()
        catalog = _digest(observation)
        recorded = json.loads(row[9])
        baseline = recorded["catalog"]
        profile = await self._rendering_profile()
        if _digest(baseline) != row[4]:
            msg = "recorded observation does not match the acknowledged catalog"
            raise PackageError(msg)
        acknowledged = int(row[5])
        if int(row[6]) != len(prepared.steps) or not 0 <= acknowledged <= len(
            prepared.steps
        ):
            msg = "invalid recorded progress"
            raise PackageError(msg)
        disposition: Literal[
            "retry_remaining", "finish", "ambiguous", "reconcile_structural"
        ] = "ambiguous"
        explanation = "catalog differs from the last acknowledgement; structural completion needs reconciliation"
        declaration_obstacle = mariadb_declaration_obstacle(prepared.package.target)
        if recorded["profile"] != list(profile) or declaration_obstacle:
            explanation = (
                declaration_obstacle
                or "server/session rendering profile differs from the acknowledged observation"
            )
        elif catalog == row[4]:
            if await self._transactional_obstacles():
                explanation = "transactional recovery is not proven with non-InnoDB tables, triggers or stored routines"
            else:
                disposition = (
                    "finish"
                    if acknowledged == len(prepared.steps)
                    else "retry_remaining"
                )
                explanation = "catalog matches the last durable acknowledgement; transactional updates and their markers commit together"
                if disposition == "finish" and (
                    obstacle := await self._mariadb_presence_obstacle(
                        prepared.package, observation
                    )
                ):
                    disposition = "ambiguous"
                    explanation = obstacle
        elif (
            acknowledged < len(prepared.steps)
            and "NO_BACKSLASH_ESCAPES" not in profile[1].split(",")
            and not await self._transactional_obstacles()
            and matches_contraction(
                prepared.package.contractions[acknowledged], baseline, observation
            )
        ):
            disposition = "reconcile_structural"
            explanation = "the entire observed catalog matches exactly the next planned contraction; explicit acceptance is required"
        return Recovery(
            prepared=prepared,
            acknowledged_steps=acknowledged,
            catalog_digest=catalog,
            disposition=disposition,
            explanation=explanation,
            before_catalog=tuple((kind, name, sql) for kind, name, sql in baseline),
            observed_catalog=tuple(
                (kind, name, sql) for kind, name, sql in observation
            ),
            before_profile=tuple(recorded["profile"]),
            observed_profile=profile,
        )

    async def reconcile(
        self, recovery: Recovery, *, reason: str, schema_writers_excluded: bool = False
    ) -> Recovery:
        """Accept one verified structural postcondition without replaying or continuing."""
        if not reason.strip():
            msg = "reconciliation requires a nonempty review reason"
            raise PackageError(msg)
        async with self._guard:
            self._require_open()
            self._require_recovery_access(
                recovery.prepared, excluded=schema_writers_excluded
            )
            async with self._coordinated():
                current = await self._assess_recovery(recovery.prepared)
                if current != recovery or current.disposition != "reconcile_structural":
                    msg = "reconciliation evidence is stale or does not prove a supported structural transition"
                    raise PackageError(msg)
                row = next(
                    row
                    for row in await self._history()
                    if row[0] == recovery.prepared.package.digest
                )
                observation = await self._catalog()
                acceptance = Reconciliation(
                    step=current.acknowledged_steps + 1,
                    reason=reason.strip(),
                    before_digest=row[4],
                    after_digest=current.catalog_digest,
                    before_catalog=current.before_catalog,
                    after_catalog=current.observed_catalog,
                    rendering_profile=current.observed_profile,
                )
                audit = [*json.loads(row[10]), acceptance.model_dump(mode="json")]
                await self._connection.begin()
                await self._query(
                    "UPDATE `snekql_experimental_migrations` SET acknowledged=%s,catalog=%s,observation=%s,reconciliations=%s WHERE digest=%s",
                    (
                        acceptance.step,
                        current.catalog_digest,
                        await self._record_observation(observation),
                        _canonical(audit),
                        recovery.prepared.package.digest,
                    ),
                )
                await self._connection.commit()
                return await self._assess_recovery(recovery.prepared)

    async def resume(
        self, recovery: Recovery, *, schema_writers_excluded: bool = False
    ) -> Literal["applied"]:
        """Recheck reviewed evidence under coordination and continue only proven work."""
        async with self._guard:
            self._require_open()
            self._require_recovery_access(
                recovery.prepared, excluded=schema_writers_excluded
            )
            async with self._coordinated():
                current = await self._assess_recovery(recovery.prepared)
                if current != recovery or current.disposition not in {
                    "retry_remaining",
                    "finish",
                }:
                    msg = "recovery evidence is stale or ambiguous; inspect before continuing"
                    raise PackageError(msg)
                await self._execute_package(
                    recovery.prepared, start=current.acknowledged_steps
                )
            return "applied"

    @asynccontextmanager
    async def _coordinated(self, *, rebuild: bool = False) -> AsyncIterator[None]:
        """Restore connection policy even if acquisition or execution is cancelled."""
        try:
            if rebuild:
                await self._query("PRAGMA foreign_keys=OFF")
            await self._begin()
            yield
        except BaseException as error:
            if not self._sqlite and isinstance(error, anyio.get_cancelled_exc_class()):
                # A cancelled protocol read may already have closed the socket.
                # Do not mask cancellation with rollback/release on that session,
                # or reuse a stream whose response boundaries are uncertain.
                self._closed = True
                self._connection.close()
            else:
                with anyio.CancelScope(shield=True):
                    await self._connection.rollback()
            raise
        finally:
            with anyio.CancelScope(shield=True):
                if rebuild:
                    await self._query("PRAGMA foreign_keys=ON")
                if not self._sqlite and not self._closed:
                    await self._query("SELECT RELEASE_LOCK(%s)", (self._lock_name,))

    async def apply(self, prepared: Prepared) -> Literal["applied", "already_applied"]:
        """Recheck observations under coordination; never replay uncertain progress."""
        async with self._guard:
            self._require_open()
            package = Package.load(prepared.package.dump())
            if package.target.backend != self._config.backend_family:
                msg = "package backend differs from target"
                raise PackageError(msg)
            if prepared.target_id != self._target_id:
                msg = "prepared plan belongs to another target"
                raise PackageError(msg)
            rebuild = self._sqlite and any(step.rebuild for step in prepared.steps)
            async with self._coordinated(rebuild=rebuild):
                rows = await self._history()
                already_applied = self._check_history(package, rows)
                objects = await self._catalog()
                catalog = _digest(objects)
                if prepared.preserve_unmanaged and not already_applied:
                    validate_preserved(package, objects)
                else:
                    self._check_catalog_history(rows, catalog)
                if already_applied:
                    await self._connection.rollback()
                    return "already_applied"
                validate_adopted(package, objects)
                if prepared.catalog_digest != catalog:
                    msg = "prepared catalog is stale; prepare and review again"
                    raise PackageError(msg)
                if prepared.steps != prepare_steps(package, objects):
                    msg_0 = "prepared execution steps have changed"
                    raise PackageError(msg_0)
                await self._execute_package(prepared)
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
