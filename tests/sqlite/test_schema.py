"""SQLite migrate-built schema DDL and verification tests."""

from __future__ import annotations

import logging
from pathlib import Path
from sqlite3 import connect
from tempfile import TemporaryDirectory
from typing import Any, ClassVar, cast

from snektest import assert_eq, assert_raises, assert_true, test

from snekql import sqlite
from snekql.sqlite import (
    PENDING_GENERATION,
    Database,
    DatabaseRuntimeError,
    Fetched,
    ForeignKey,
    Index,
    Integer,
    Model,
    Pending,
    SchemaError,
    SchemaVerificationError,
    Text,
)
from snekql.sqlite._schema_ddl import sqlite_type_affinity
from snekql.sqlite.schema import verify_sqlite_schema
from tests.helpers import capture_snekql_logs, migrate_models


def _execute_sql(database_path: Path, sql: str) -> None:
    connection = connect(database_path)
    try:
        _ = connection.execute(sql)
        connection.commit()
    finally:
        connection.close()


def _fetch_create_table(database_path: Path, table_name: str) -> str:
    connection = connect(database_path)
    try:
        cursor = connection.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = ?",
            (table_name,),
        )
        row = cursor.fetchone()
        assert row is not None
        value = row[0]
        assert isinstance(value, str)
        return value
    finally:
        connection.close()


def _fetch_create_indexes(database_path: Path, table_name: str) -> list[str]:
    connection = connect(database_path)
    try:
        cursor = connection.execute(
            """
            SELECT sql FROM sqlite_master
            WHERE type = 'index' AND tbl_name = ?
            ORDER BY rowid
            """,
            (table_name,),
        )
        values: list[str] = []
        for row in cursor.fetchall():
            value = row[0]
            assert isinstance(value, str)
            values.append(value)
        return values
    finally:
        connection.close()


class _SchemaCursor:
    """Cursor fake that records whether schema verification closes it."""

    def __init__(self, *, fetchone_row: tuple[object, ...] | None = None) -> None:
        self.closed: bool = False
        self.fetchone_row: tuple[object, ...] | None = fetchone_row

    async def fetchone(self) -> tuple[object, ...] | None:
        return self.fetchone_row

    async def fetchall(self) -> list[tuple[object, ...]]:
        return []

    async def close(self) -> None:
        self.closed = True


class _SchemaConnection:
    """Connection fake that returns close-observable cursors for every statement."""

    def __init__(self) -> None:
        self.cursors: list[_SchemaCursor] = []

    async def execute(
        self,
        sql: str,
        params: tuple[object, ...] = (),
    ) -> _SchemaCursor:
        _ = sql
        _ = params
        cursor = _SchemaCursor()
        self.cursors.append(cursor)
        return cursor


@test(mark="medium")
async def migrate_builds_quoted_strict_tables() -> None:
    """Scaffolded migrations build deterministic quoted STRICT tables."""

    class User[S = Pending](Model[S, "User[Fetched]"]):
        """Table model used for schema creation."""

        id: User.GenCol[int] = Integer(
            primary_key=True,
            auto_increment=True,
            default=PENDING_GENERATION,
        )
        email: User.Col[str] = Text(nullable=False)

    with TemporaryDirectory() as directory:
        database_path = Path(directory) / "app.db"
        database = await Database.initialize(database=database_path)
        await migrate_models(database, [User])
        await database.close()

        create_table = _fetch_create_table(database_path, "user")

    expected_sql = (
        'CREATE TABLE "user" ("id" INTEGER PRIMARY KEY AUTOINCREMENT, '
        '"email" TEXT NOT NULL) STRICT'
    )
    assert_eq(create_table, expected_sql)


@test(mark="medium")
async def migrate_emits_foreign_key_constraints_only_when_enabled() -> None:
    """`ForeignKey` renders a REFERENCES constraint; soft refs do not."""

    class User[S = Pending](Model[S, "User[Fetched]"]):
        """Referenced table whose primary key anchors the constraint."""

        id: User.GenCol[int] = Integer(
            primary_key=True,
            auto_increment=True,
            default=PENDING_GENERATION,
        )
        email: User.Col[str] = Text(nullable=False)

    class Order[S = Pending](Model[S, "Order[Fetched]"]):
        """Table with an enforced and a typed-only reference to ``User``."""

        id: Order.GenCol[int] = Integer(
            primary_key=True,
            auto_increment=True,
            default=PENDING_GENERATION,
        )
        user_id: Order.FKCol[User, int] = ForeignKey(User.id)
        soft_user_id: Order.FKCol[User, int] = Integer(nullable=False)
        note: Order.Col[str] = Text(nullable=False)

    with TemporaryDirectory() as directory:
        database_path = Path(directory) / "app.db"
        database = await Database.initialize(database=database_path)
        await migrate_models(database, [User, Order])
        await database.close()

        create_table = _fetch_create_table(database_path, "order")

    expected_sql = (
        'CREATE TABLE "order" ("id" INTEGER PRIMARY KEY AUTOINCREMENT, '
        '"user_id" INTEGER, "soft_user_id" INTEGER NOT NULL, '
        '"note" TEXT NOT NULL, '
        'FOREIGN KEY ("user_id") REFERENCES "user" ("id")) STRICT'
    )
    assert_eq(create_table, expected_sql)


@test(mark="medium")
async def migrate_builds_and_verifies_a_composite_primary_key() -> None:
    """A join table keyed on a column pair builds valid DDL and verifies clean."""

    class Team[S = Pending](Model[S, "Team[Fetched]"]):
        """Referenced table anchoring the join table's foreign keys."""

        id: Team.GenCol[int] = Integer(
            primary_key=True, auto_increment=True, default=PENDING_GENERATION
        )

    class User[S = Pending](Model[S, "User[Fetched]"]):
        """Referenced table anchoring the join table's foreign keys."""

        id: User.GenCol[int] = Integer(
            primary_key=True, auto_increment=True, default=PENDING_GENERATION
        )

    class TeamMember[S = Pending](Model[S, "TeamMember[Fetched]"]):
        """Join table whose identity is the (team, user) column pair."""

        team_id: TeamMember.FKCol[Team, int] = ForeignKey(Team.id, primary_key=True)
        user_id: TeamMember.FKCol[User, int] = ForeignKey(User.id, primary_key=True)
        role: TeamMember.Col[str] = Text(nullable=False)

    with TemporaryDirectory() as directory:
        database_path = Path(directory) / "app.db"
        database = await Database.initialize(database=database_path)
        await migrate_models(database, [Team, User, TeamMember])

        create_table = _fetch_create_table(database_path, "team_member")

        # No inline PRIMARY KEY; a single table-level constraint names both keys.
        await database.verify([Team, User, TeamMember])
        await database.close()

    expected_sql = (
        'CREATE TABLE "team_member" ('
        '"team_id" INTEGER NOT NULL, "user_id" INTEGER NOT NULL, '
        '"role" TEXT NOT NULL, '
        'PRIMARY KEY ("team_id", "user_id"), '
        'FOREIGN KEY ("team_id") REFERENCES "team" ("id"), '
        'FOREIGN KEY ("user_id") REFERENCES "user" ("id")) STRICT'
    )
    assert_eq(create_table, expected_sql)


@test(mark="medium")
async def migrate_builds_and_verifies_a_text_primary_key() -> None:
    """A non-INTEGER single-column PK is NOT NULL under STRICT and verifies clean."""

    class Doc[S = Pending](Model[S, "Doc[Fetched]"]):
        """Table keyed on an app-generated TEXT (UUID) primary key."""

        id: Doc.Col[str] = Text(primary_key=True)

    with TemporaryDirectory() as directory:
        database_path = Path(directory) / "app.db"
        database = await Database.initialize(database=database_path)
        await migrate_models(database, [Doc])

        create_table = _fetch_create_table(database_path, "doc")

        # Under STRICT a TEXT PK is reported notnull=1; the DDL emits NOT NULL to
        # match, so verification must not see drift.
        await database.verify([Doc])
        await database.close()

    expected_sql = 'CREATE TABLE "doc" ("id" TEXT PRIMARY KEY NOT NULL) STRICT'
    assert_eq(create_table, expected_sql)


@test(mark="medium")
async def migrate_emits_a_reference_to_a_non_primary_key_target_column() -> None:
    """A `ForeignKey` to a unique non-PK column references that column by name."""

    class User[S = Pending](Model[S, "User[Fetched]"]):
        """Referenced table whose unique email is the FK target."""

        id: User.GenCol[int] = Integer(
            primary_key=True,
            auto_increment=True,
            default=PENDING_GENERATION,
        )
        email: User.Col[str] = Text(nullable=False, unique=True)

    class Order[S = Pending](Model[S, "Order[Fetched]"]):
        """Table whose owner_email references ``user(email)``."""

        id: Order.GenCol[int] = Integer(
            primary_key=True,
            auto_increment=True,
            default=PENDING_GENERATION,
        )
        owner_email: Order.FKCol[User, str] = ForeignKey(User.email, nullable=False)

    with TemporaryDirectory() as directory:
        database_path = Path(directory) / "app.db"
        database = await Database.initialize(database=database_path)
        await migrate_models(database, [User, Order])
        await database.close()

        create_table = _fetch_create_table(database_path, "order")

    expected_sql = (
        'CREATE TABLE "order" ("id" INTEGER PRIMARY KEY AUTOINCREMENT, '
        '"owner_email" TEXT NOT NULL, '
        'FOREIGN KEY ("owner_email") REFERENCES "user" ("email")) STRICT'
    )
    assert_eq(create_table, expected_sql)


@test(mark="medium")
async def migrate_emits_and_verifies_referential_actions() -> None:
    """`on_delete`/`on_update` render their clauses and verify clean afterwards."""

    class User[S = Pending](Model[S, "User[Fetched]"]):
        """Referenced table anchoring the cascading foreign key."""

        id: User.GenCol[int] = Integer(
            primary_key=True, auto_increment=True, default=PENDING_GENERATION
        )

    class Order[S = Pending](Model[S, "Order[Fetched]"]):
        """Owned table whose rows cascade on parent delete, restrict on update."""

        id: Order.GenCol[int] = Integer(
            primary_key=True, auto_increment=True, default=PENDING_GENERATION
        )
        user_id: Order.FKCol[User, int] = ForeignKey(
            User.id, nullable=False, on_delete="CASCADE", on_update="RESTRICT"
        )

    with TemporaryDirectory() as directory:
        database_path = Path(directory) / "app.db"
        database = await Database.initialize(database=database_path)
        await migrate_models(database, [User, Order])

        create_table = _fetch_create_table(database_path, "order")

        # The live PRAGMA actions read back equal to the model, so verify passes.
        await database.verify([User, Order])
        await database.close()

    expected_sql = (
        'CREATE TABLE "order" ("id" INTEGER PRIMARY KEY AUTOINCREMENT, '
        '"user_id" INTEGER NOT NULL, '
        'FOREIGN KEY ("user_id") REFERENCES "user" ("id") '
        "ON DELETE CASCADE ON UPDATE RESTRICT) STRICT"
    )
    assert_eq(create_table, expected_sql)


@test(mark="medium")
async def strict_verify_raises_on_referential_action_drift() -> None:
    """A live FK whose ON DELETE action differs from the model is strict drift."""

    class User[S = Pending](Model[S, "User[Fetched]"]):
        """Referenced table for referential-action drift detection."""

        id: User.GenCol[int] = Integer(
            primary_key=True, auto_increment=True, default=PENDING_GENERATION
        )

    class Order[S = Pending](Model[S, "Order[Fetched]"]):
        """Model expecting ON DELETE CASCADE against an action-free live table."""

        id: Order.GenCol[int] = Integer(
            primary_key=True, auto_increment=True, default=PENDING_GENERATION
        )
        user_id: Order.FKCol[User, int] = ForeignKey(User.id, on_delete="CASCADE")

    with TemporaryDirectory() as directory:
        database_path = Path(directory) / "app.db"
        order_sql = (
            'CREATE TABLE "order" ("id" INTEGER PRIMARY KEY AUTOINCREMENT, '
            '"user_id" INTEGER, '
            'FOREIGN KEY ("user_id") REFERENCES "user" ("id")) STRICT'
        )
        _execute_sql(
            database_path,
            'CREATE TABLE "user" ("id" INTEGER PRIMARY KEY AUTOINCREMENT) STRICT',
        )
        _execute_sql(database_path, order_sql)

        database = await Database.initialize(database=database_path)
        try:
            with assert_raises(SchemaVerificationError):
                await database.verify([User, Order])
        finally:
            await database.close()


@test(mark="medium")
async def strict_verify_raises_when_a_foreign_key_constraint_is_missing() -> None:
    """An existing table lacking a managed FK constraint is strict-policy drift."""

    class User[S = Pending](Model[S, "User[Fetched]"]):
        """Referenced table for foreign-key drift detection."""

        id: User.GenCol[int] = Integer(
            primary_key=True,
            auto_increment=True,
            default=PENDING_GENERATION,
        )

    class Order[S = Pending](Model[S, "Order[Fetched]"]):
        """Table whose model declares a constraint absent from the database."""

        id: Order.GenCol[int] = Integer(
            primary_key=True,
            auto_increment=True,
            default=PENDING_GENERATION,
        )
        user_id: Order.FKCol[User, int] = ForeignKey(User.id)

    with TemporaryDirectory() as directory:
        database_path = Path(directory) / "app.db"
        order_sql = (
            'CREATE TABLE "order" ("id" INTEGER PRIMARY KEY AUTOINCREMENT, '
            '"user_id" INTEGER) STRICT'
        )
        _execute_sql(
            database_path,
            'CREATE TABLE "user" ("id" INTEGER PRIMARY KEY AUTOINCREMENT) STRICT',
        )
        _execute_sql(database_path, order_sql)

        database = await Database.initialize(database=database_path)
        try:
            with assert_raises(SchemaVerificationError):
                await database.verify([User, Order])
        finally:
            await database.close()


@test(mark="medium")
async def initialize_accepts_sqlite_config_object() -> None:
    """SQLite configuration objects select the SQLite runtime explicitly."""

    class User[S = Pending](sqlite.Model[S, "User[Fetched]"]):
        """Table model used for SQLite config initialization."""

        id: User.GenCol[int] = sqlite.Integer(
            primary_key=True,
            auto_increment=True,
            default=PENDING_GENERATION,
        )
        email: User.Col[str] = sqlite.Text(nullable=False)

    with TemporaryDirectory() as directory:
        database_path = Path(directory) / "app.db"
        config = sqlite.Config(database=database_path, pool_size=2)
        database = await Database.initialize(config)
        await migrate_models(database, [User])
        await database.close()

        create_table = _fetch_create_table(database_path, "user")

    expected_sql = (
        'CREATE TABLE "user" ("id" INTEGER PRIMARY KEY AUTOINCREMENT, '
        '"email" TEXT NOT NULL) STRICT'
    )
    assert_eq(create_table, expected_sql)


@test(mark="medium")
async def initialize_rejects_mixed_sqlite_config_and_legacy_database() -> None:
    """A backend config cannot be combined with legacy database arguments."""

    with TemporaryDirectory() as directory:
        database_path = Path(directory) / "app.db"
        config = sqlite.Config(database=database_path)

        initialize = cast("Any", Database.initialize)

        with assert_raises(DatabaseRuntimeError):
            _ = await initialize(config, database=database_path)


@test(mark="medium")
async def migrate_builds_column_unique_indexes_after_tables() -> None:
    """Column unique declarations build separate deterministic unique indexes."""

    class User[S = Pending](Model[S, "User[Fetched]"]):
        """Table model with a unique public identifier."""

        email: User.Col[str] = Text(nullable=False, unique=True)
        status: User.Col[str] = Text(nullable=False)

    with TemporaryDirectory() as directory:
        database_path = Path(directory) / "app.db"
        database = await Database.initialize(database=database_path)
        await migrate_models(database, [User])
        await database.close()

        create_table = _fetch_create_table(database_path, "user")
        create_indexes = _fetch_create_indexes(database_path, "user")

    assert_eq(
        create_table,
        'CREATE TABLE "user" ("email" TEXT NOT NULL, "status" TEXT NOT NULL) STRICT',
    )
    assert_eq(
        create_indexes,
        ['CREATE UNIQUE INDEX "ux_user_email" ON "user" ("email")'],
    )


@test(mark="medium")
async def migrate_builds_column_non_unique_indexes() -> None:
    """Column ``index=True`` declarations build non-unique ``ix_`` indexes."""

    class User[S = Pending](Model[S, "User[Fetched]"]):
        """Table model with a column-level non-unique index."""

        email: User.Col[str] = Text(nullable=False, unique=True)
        status: User.Col[str] = Text(nullable=False, index=True)

    with TemporaryDirectory() as directory:
        database_path = Path(directory) / "app.db"
        database = await Database.initialize(database=database_path)
        await migrate_models(database, [User])
        await database.close()

        create_indexes = _fetch_create_indexes(database_path, "user")

    assert_eq(
        create_indexes,
        [
            'CREATE UNIQUE INDEX "ux_user_email" ON "user" ("email")',
            'CREATE INDEX "ix_user_status" ON "user" ("status")',
        ],
    )


@test(mark="medium")
async def migrate_builds_table_indexes_in_declaration_order() -> None:
    """Table index declarations build deterministic index SQL after uniques."""

    class User[S = Pending](Model[S, "User[Fetched]"]):
        """Table model with single and composite table indexes."""

        email: User.Col[str] = Text(nullable=False, unique=True)
        status: User.Col[str] = Text(nullable=False)
        tenant_id: User.Col[int] = Integer(nullable=False)

        __indexes__: ClassVar[list[Index[Any]]] = [
            Index(status),
            Index(tenant_id, email, unique=True),
            Index(tenant_id, name="ix_user_tenant_custom"),
        ]

    with TemporaryDirectory() as directory:
        database_path = Path(directory) / "app.db"
        database = await Database.initialize(database=database_path)
        await migrate_models(database, [User])
        await database.close()

        create_indexes = _fetch_create_indexes(database_path, "user")

    assert_eq(
        create_indexes,
        [
            'CREATE UNIQUE INDEX "ux_user_email" ON "user" ("email")',
            'CREATE INDEX "ix_user_status" ON "user" ("status")',
            'CREATE UNIQUE INDEX "ux_user_tenant_id_email" ON "user" ("tenant_id", "email")',
            'CREATE INDEX "ix_user_tenant_custom" ON "user" ("tenant_id")',
        ],
    )


@test(mark="medium")
async def initialize_accepts_only_path_objects_and_exact_memory_string() -> None:
    """Only pathlib.Path and the exact in-memory database string are accepted."""

    initialize = cast("Any", Database.initialize)

    class OtherPath:
        """Path-like object that is intentionally not pathlib.Path."""

        def __fspath__(self) -> str:
            return "app.db"

    with assert_raises(DatabaseRuntimeError):
        _ = await initialize(database="app.db")

    with assert_raises(DatabaseRuntimeError):
        _ = await Database.initialize(database=cast("Any", "app.db"))

    with assert_raises(DatabaseRuntimeError):
        _ = await Database.initialize(database=cast("Any", "sqlite:///app.db"))

    with assert_raises(DatabaseRuntimeError):
        _ = await Database.initialize(database=cast("Any", b"app.db"))

    with assert_raises(DatabaseRuntimeError):
        _ = await Database.initialize(database=cast("Any", OtherPath()))

    database = await Database.initialize(database=":memory:")
    await database.close()


@test(mark="medium")
async def verify_accepts_existing_tables_after_controlled_normalization() -> None:
    """Equivalent snekql DDL with formatting differences verifies cleanly."""

    class User[S = Pending](Model[S, "User[Fetched]"]):
        """Table model used for existing schema verification."""

        id: User.GenCol[int] = Integer(
            primary_key=True,
            auto_increment=True,
            default=PENDING_GENERATION,
        )
        email: User.Col[str] = Text(nullable=False)

    with TemporaryDirectory() as directory:
        database_path = Path(directory) / "app.db"
        existing_sql = (
            'CREATE TABLE "user" (\n'
            '    "id" INTEGER PRIMARY KEY AUTOINCREMENT,\n'
            '    "email" TEXT NOT NULL\n'
            ") STRICT"
        )
        _execute_sql(database_path, existing_sql)

        database = await Database.initialize(database=database_path)
        await database.verify([User])
        await database.close()


@test(mark="medium")
async def cosmetically_different_ddl_verifies_semantically() -> None:
    """Unquoted identifiers, lowercase types, and reordered columns are not drift."""

    class User[S = Pending](Model[S, "User[Fetched]"]):
        """Model verified against a table whose DDL differs only cosmetically."""

        id: User.GenCol[int] = Integer(
            primary_key=True, auto_increment=True, default=PENDING_GENERATION
        )
        email: User.Col[str] = Text(nullable=False)

    with TemporaryDirectory() as directory:
        database_path = Path(directory) / "app.db"
        # Reordered columns, no identifier quoting, lowercase type tokens: a
        # migration author's hand-written DDL that is semantically identical.
        existing_sql = (
            "CREATE TABLE user (email text NOT NULL, "
            "id integer PRIMARY KEY AUTOINCREMENT) STRICT"
        )
        _execute_sql(database_path, existing_sql)

        database = await Database.initialize(database=database_path)
        await database.verify([User])
        await database.close()


@test(mark="fast")
async def sqlite_type_affinity_follows_sqlite_rules() -> None:
    """The affinity helper collapses declared types per SQLite's documented rules."""

    integer_affinity = ("INTEGER", "INT", "BIGINT", "int8", "INT UNSIGNED")
    text_affinity = ("TEXT", "VARCHAR(255)", "nvarchar", "CLOB", "CHARACTER(20)")
    blob_affinity = ("BLOB", "")
    real_affinity = ("REAL", "DOUBLE", "FLOAT", "double precision")
    numeric_affinity = ("NUMERIC", "DECIMAL(10,2)", "BOOLEAN", "DATE")

    for declared in integer_affinity:
        assert_eq(sqlite_type_affinity(declared), "INTEGER")
    for declared in text_affinity:
        assert_eq(sqlite_type_affinity(declared), "TEXT")
    for declared in blob_affinity:
        assert_eq(sqlite_type_affinity(declared), "BLOB")
    for declared in real_affinity:
        assert_eq(sqlite_type_affinity(declared), "REAL")
    for declared in numeric_affinity:
        assert_eq(sqlite_type_affinity(declared), "NUMERIC")


@test(mark="medium")
async def verify_accepts_sqlite_integer_type_aliases() -> None:
    """A STRICT column declared ``INT`` shares INTEGER affinity and is not drift."""

    class Event[S = Pending](Model[S, "Event[Fetched]"]):
        """Model whose count column maps to INTEGER but is migrated as ``INT``."""

        id: Event.GenCol[int] = Integer(
            primary_key=True, auto_increment=True, default=PENDING_GENERATION
        )
        count: Event.Col[int] = Integer(nullable=False)

    with TemporaryDirectory() as directory:
        database_path = Path(directory) / "app.db"
        # STRICT accepts the INT spelling; it carries INTEGER affinity, so a
        # migration author writing INT is semantically identical to snekql's
        # INTEGER and must not be reported as drift.
        existing_sql = (
            'CREATE TABLE "event" ("id" INTEGER PRIMARY KEY AUTOINCREMENT, '
            '"count" INT NOT NULL) STRICT'
        )
        _execute_sql(database_path, existing_sql)

        database = await Database.initialize(database=database_path)
        await database.verify([Event])
        await database.close()


@test(mark="medium")
async def verify_collapses_sqlite_text_affinity_aliases() -> None:
    """A non-STRICT ``VARCHAR(255)`` column collapses to TEXT affinity, not drift."""

    class Note[S = Pending](Model[S, "Note[Fetched]"]):
        """Model whose body is TEXT but is migrated as ``VARCHAR(255)``."""

        body: Note.Col[str] = Text(nullable=False)

    with TemporaryDirectory() as directory:
        database_path = Path(directory) / "app.db"
        # A legacy non-STRICT table: STRICT itself is reported separately as a
        # storage-option divergence, but the VARCHAR(255) column must collapse to
        # TEXT affinity and not add spurious per-column type drift. (VARCHAR is
        # rejected by STRICT, so the legacy table is built without it.)
        existing_sql = 'CREATE TABLE "note" ("body" VARCHAR(255) NOT NULL)'
        _execute_sql(database_path, existing_sql)

        database = await Database.initialize(database=database_path)
        try:
            with assert_raises(SchemaVerificationError) as raised:
                await database.verify([Note])
        finally:
            await database.close()

    # Only the missing STRICT storage option is drift; the VARCHAR(255) column
    # collapses to TEXT affinity and contributes no type divergence.
    message = str(raised.exception)
    assert_true("storage options" in message)
    assert_true("'body'" not in message)


@test(mark="medium")
async def strict_verify_raises_on_meaningful_type_affinity_drift() -> None:
    """A live column whose affinity differs from the model is genuine drift."""

    class Event[S = Pending](Model[S, "Event[Fetched]"]):
        """Model whose label is TEXT while the live column has INTEGER affinity."""

        id: Event.GenCol[int] = Integer(
            primary_key=True, auto_increment=True, default=PENDING_GENERATION
        )
        label: Event.Col[str] = Text(nullable=False)

    with TemporaryDirectory() as directory:
        database_path = Path(directory) / "app.db"
        existing_sql = (
            'CREATE TABLE "event" ("id" INTEGER PRIMARY KEY AUTOINCREMENT, '
            '"label" INTEGER NOT NULL) STRICT'
        )
        _execute_sql(database_path, existing_sql)

        database = await Database.initialize(database=database_path)
        try:
            with assert_raises(SchemaVerificationError) as raised:
                await database.verify([Event])
        finally:
            await database.close()

    message = str(raised.exception)
    assert_true("'label'" in message)
    assert_true("type" in message)


@test(mark="medium")
async def model_matching_migration_evolved_table_verifies_clean() -> None:
    """A model matches a table evolved by ALTER regardless of column order."""

    class User[S = Pending](Model[S, "User[Fetched]"]):
        """Model whose age column was appended to the table by a later ALTER."""

        id: User.GenCol[int] = Integer(
            primary_key=True, auto_increment=True, default=PENDING_GENERATION
        )
        age: User.Col[int] = Integer(nullable=True)
        email: User.Col[str] = Text(nullable=False)

    with TemporaryDirectory() as directory:
        database_path = Path(directory) / "app.db"
        existing_sql = (
            'CREATE TABLE "user" ("id" INTEGER PRIMARY KEY AUTOINCREMENT, '
            '"email" TEXT NOT NULL) STRICT'
        )
        _execute_sql(database_path, existing_sql)
        _execute_sql(database_path, 'ALTER TABLE "user" ADD COLUMN "age" INTEGER')

        database = await Database.initialize(database=database_path)
        await database.verify([User])
        await database.close()


@test(mark="medium")
async def strict_drift_error_names_the_divergent_column() -> None:
    """A column whose nullability diverges is named precisely in the error."""

    class User[S = Pending](Model[S, "User[Fetched]"]):
        """Model whose email is NOT NULL while the live column is nullable."""

        id: User.GenCol[int] = Integer(
            primary_key=True, auto_increment=True, default=PENDING_GENERATION
        )
        email: User.Col[str] = Text(nullable=False)

    with TemporaryDirectory() as directory:
        database_path = Path(directory) / "app.db"
        existing_sql = (
            'CREATE TABLE "user" ("id" INTEGER PRIMARY KEY AUTOINCREMENT, '
            '"email" TEXT) STRICT'
        )
        _execute_sql(database_path, existing_sql)

        database = await Database.initialize(database=database_path)
        try:
            with assert_raises(SchemaVerificationError) as raised:
                await database.verify([User])
        finally:
            await database.close()

    message = str(raised.exception)
    assert_true("'email'" in message)
    assert_true("nullable" in message)


@test(mark="medium")
async def strict_verify_raises_on_index_drift() -> None:
    """Strict schema verification rejects missing managed indexes."""

    class User[S = Pending](Model[S, "User[Fetched]"]):
        """Table model requiring an index for verification."""

        email: User.Col[str] = Text(nullable=False, unique=True)

    with TemporaryDirectory() as directory:
        database_path = Path(directory) / "app.db"
        _execute_sql(
            database_path, 'CREATE TABLE "user" ("email" TEXT NOT NULL) STRICT'
        )

        database = await Database.initialize(database=database_path)
        try:
            with assert_raises(SchemaVerificationError):
                await database.verify([User])
        finally:
            await database.close()


@test(mark="medium")
async def duplicate_resolved_index_names_are_rejected() -> None:
    """Verification rejects duplicate index names across configured models."""

    class User[S = Pending](Model[S, "User[Fetched]"]):
        """First model using an explicit index name."""

        email: User.Col[str] = Text(nullable=False)
        __indexes__: ClassVar[list[Index[Any]]] = [
            Index(email, name="ix_conflict"),
        ]

    class Account[S = Pending](Model[S, "Account[Fetched]"]):
        """Second model reusing the explicit index name."""

        email: Account.Col[str] = Text(nullable=False)
        __indexes__: ClassVar[list[Index[Any]]] = [
            Index(email, name="ix_conflict"),
        ]

    with TemporaryDirectory() as directory:
        database_path = Path(directory) / "app.db"
        database = await Database.initialize(database=database_path)
        try:
            with assert_raises(SchemaError):
                await database.verify([User, Account])
        finally:
            await database.close()


@test(mark="medium")
async def strict_verify_raises_on_schema_drift() -> None:
    """Strict schema verification rejects existing non-STRICT tables."""

    class User[S = Pending](Model[S, "User[Fetched]"]):
        """Table model used for drift detection."""

        email: User.Col[str] = Text(nullable=False)

    with TemporaryDirectory() as directory:
        database_path = Path(directory) / "app.db"
        _execute_sql(database_path, 'CREATE TABLE "user" ("email" TEXT NOT NULL)')

        database = await Database.initialize(database=database_path)
        try:
            with assert_raises(SchemaVerificationError):
                await database.verify([User])
        finally:
            await database.close()


@test(mark="medium")
async def warn_verify_policy_logs_drift_and_continues() -> None:
    """Warn schema verification reports drift without raising."""

    class User[S = Pending](Model[S, "User[Fetched]"]):
        """Table model used for warn policy drift detection."""

        email: User.Col[str] = Text(nullable=False)

    with capture_snekql_logs() as logs, TemporaryDirectory() as directory:
        database_path = Path(directory) / "app.db"
        _execute_sql(database_path, 'CREATE TABLE "user" ("email" TEXT NOT NULL)')

        database = await Database.initialize(database=database_path)
        await database.verify([User], policy="warn")
        await database.close()

    assert_true(logs.has(logging.WARNING, "schema drift detected"))


@test(mark="medium")
async def duplicate_resolved_table_names_are_rejected() -> None:
    """Verification rejects duplicate table names before inspecting the schema."""

    class User[S = Pending](Model[S, "User[Fetched]"]):
        """First model for duplicate table detection."""

        __tablename__ = "account"
        email: User.Col[str] = Text(nullable=False)

    class Account[S = Pending](Model[S, "Account[Fetched]"]):
        """Second model with the same resolved table name."""

        email: Account.Col[str] = Text(nullable=False)

    with TemporaryDirectory() as directory:
        database_path = Path(directory) / "app.db"
        database = await Database.initialize(database=database_path)
        try:
            with assert_raises(SchemaError):
                await database.verify([User, Account])
        finally:
            await database.close()


@test(mark="fast")
async def schema_verification_closes_control_cursors() -> None:
    """SQLite schema verification closes cursors returned by control statements."""

    class User[S = Pending](Model[S, "User[Fetched]"]):
        """Model used to force BEGIN, metadata fetch, and COMMIT."""

        email: User.Col[str] = Text(nullable=False)

    connection = _SchemaConnection()

    await verify_sqlite_schema(
        cast("Any", connection),
        [User],
        "warn",
    )

    assert connection.cursors
    assert_true(all(cursor.closed for cursor in connection.cursors))
