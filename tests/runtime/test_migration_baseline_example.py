"""Reviewed baseline adoption through the example and public Database operations."""

from collections.abc import AsyncGenerator

from snektest import Param, assert_eq, assert_raises, fixture, load_fixture, test

from examples.migration_baseline import (
    MARIADB_MIGRATIONS,
    SQLITE_MIGRATIONS,
    BaselineReviewError,
    MariaDBAccount,
    SQLiteAccount,
    adopt_mariadb,
    adopt_sqlite,
)
from snekql import mariadb
from snekql.model import BackendFamily
from snekql.testing.mariadb import temporary_mariadb_server
from tests.runtime.test_raw_execution import RawCase, provide_raw_case

_SQLITE_EXISTING = (
    'CREATE TABLE "baseline_account" ("id" INTEGER PRIMARY KEY, '
    '"balance" INTEGER NOT NULL CHECK ("balance" >= 0)) STRICT'
)
_MARIADB_EXISTING = (
    "CREATE TABLE baseline_account (id BIGINT NOT NULL PRIMARY KEY, "
    "balance BIGINT NOT NULL, CONSTRAINT ck_baseline_balance CHECK (balance >= 0)) "
    "ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin"
)


@fixture
async def provide_baseline_case(backend: BackendFamily) -> AsyncGenerator[RawCase]:
    """Own the whole schema; shared table-only resets leave views and routines behind."""
    if backend == "sqlite":
        yield await load_fixture(provide_raw_case("sqlite"))
    else:
        async with (
            temporary_mariadb_server(auth="password", transports={"tcp"}) as server,
            await mariadb.Database.initialize(server.config()) as database,
        ):
            yield RawCase(database, mariadb)


@fixture
async def provide_existing(
    backend: BackendFamily, *, wrong_check: bool = False
) -> AsyncGenerator[RawCase]:
    case = await load_fixture(provide_baseline_case(backend))
    create_sql = _SQLITE_EXISTING if backend == "sqlite" else _MARIADB_EXISTING
    if wrong_check:
        create_sql = create_sql.replace(">= 0", ">= -100")
    async with case.database.transaction() as transaction:
        await transaction.execute(case.namespace.raw(create_sql))
        await transaction.execute(
            case.namespace.raw("INSERT INTO baseline_account VALUES (1, 25)")
        )
    yield case


@test(
    [
        Param[BackendFamily](value="sqlite", name="sqlite"),
        Param[BackendFamily](value="mariadb", name="mariadb"),
    ],
    mark="slow",
)
async def adoption_records_only_the_executed_baseline(backend: BackendFamily) -> None:
    """An existing database starts a new canonical chain, without fabricated old entries."""
    case = await load_fixture(provide_existing(backend))

    result = await (
        adopt_sqlite(case.database)
        if backend == "sqlite"
        else adopt_mariadb(case.database)
    )

    assert_eq(result.applied, ("001_reviewed_baseline",))
    assert_eq(result.legacy_adopted, False)


@test(
    [
        Param[BackendFamily](value="sqlite", name="sqlite"),
        Param[BackendFamily](value="mariadb", name="mariadb"),
    ],
    mark="slow",
)
async def existing_history_is_not_rebaselined(backend: BackendFamily) -> None:
    """Even an empty v2 history table must use its existing migration workflow."""
    case = await load_fixture(provide_existing(backend))
    await case.database.migrate({})

    with assert_raises(BaselineReviewError):
        await (
            adopt_sqlite(case.database)
            if backend == "sqlite"
            else adopt_mariadb(case.database)
        )


@test(
    [
        Param[BackendFamily](value="sqlite", name="sqlite"),
        Param[BackendFamily](value="mariadb", name="mariadb"),
    ],
    mark="slow",
)
async def missing_owned_table_is_rejected(backend: BackendFamily) -> None:
    """Adoption is not a shortcut for fresh replay or an incomplete reviewed schema."""
    case = await load_fixture(provide_baseline_case(backend))

    with assert_raises(case.namespace.SchemaVerificationError):
        await (
            adopt_sqlite(case.database)
            if backend == "sqlite"
            else adopt_mariadb(case.database)
        )
    assert_eq((await case.database.migration_status({})).history_present, False)


@test(
    [
        Param[BackendFamily](value="sqlite", name="sqlite"),
        Param[BackendFamily](value="mariadb", name="mariadb"),
    ],
    mark="slow",
)
async def unreviewed_check_is_rejected_before_history_creation(
    backend: BackendFamily,
) -> None:
    """A model-compatible but weaker CHECK cannot be silently accepted by IF NOT EXISTS."""
    case = await load_fixture(provide_existing(backend, wrong_check=True))

    with assert_raises(BaselineReviewError):
        await (
            adopt_sqlite(case.database)
            if backend == "sqlite"
            else adopt_mariadb(case.database)
        )
    assert_eq((await case.database.migration_status({})).history_present, False)


@test(
    [
        Param[BackendFamily](value="sqlite", name="sqlite"),
        Param[BackendFamily](value="mariadb", name="mariadb"),
    ],
    [
        Param(value="table", name="table"),
        Param(value="lookalike", name="reserved-prefix-lookalike"),
        Param(value="view", name="view"),
        Param(value="trigger", name="trigger"),
    ],
    mark="slow",
)
async def unreviewed_objects_are_rejected(backend: BackendFamily, kind: str) -> None:
    """Partial model verification cannot authorize unreviewed application objects."""
    case = await load_fixture(provide_existing(backend))
    if kind == "lookalike":
        extra_sql = "CREATE TABLE sqliteXunreviewed (id INTEGER)"
    elif kind == "table":
        extra_sql = "CREATE TABLE unreviewed (id INTEGER)"
    elif kind == "view":
        extra_sql = "CREATE VIEW unreviewed AS SELECT id FROM baseline_account"
    elif backend == "sqlite":
        extra_sql = "CREATE TRIGGER unreviewed BEFORE DELETE ON baseline_account BEGIN SELECT 1; END"
    else:
        extra_sql = "CREATE TRIGGER unreviewed BEFORE DELETE ON baseline_account FOR EACH ROW SET @deleted_id = OLD.id"
    async with case.database.transaction() as transaction:
        await transaction.execute(case.namespace.raw(extra_sql))

    with assert_raises(BaselineReviewError):
        await (
            adopt_sqlite(case.database)
            if backend == "sqlite"
            else adopt_mariadb(case.database)
        )
    assert_eq((await case.database.migration_status({})).history_present, False)


@test(
    [
        Param[BackendFamily](value="sqlite", name="sqlite"),
        Param[BackendFamily](value="mariadb", name="mariadb"),
    ],
    mark="slow",
)
async def invalid_existing_data_is_rejected(backend: BackendFamily) -> None:
    """The presence of a CHECK declaration does not prove old rows satisfy it."""
    case = await load_fixture(provide_existing(backend))
    disable = (
        "PRAGMA ignore_check_constraints = ON"
        if backend == "sqlite"
        else "SET SESSION check_constraint_checks = OFF"
    )
    enable = (
        "PRAGMA ignore_check_constraints = OFF"
        if backend == "sqlite"
        else "SET SESSION check_constraint_checks = ON"
    )
    async with case.database.transaction() as transaction:
        await transaction.execute(case.namespace.raw(disable))
        await transaction.execute(
            case.namespace.raw("UPDATE baseline_account SET balance = -1 WHERE id = 1")
        )
        await transaction.execute(case.namespace.raw(enable))

    with assert_raises(BaselineReviewError):
        await (
            adopt_sqlite(case.database)
            if backend == "sqlite"
            else adopt_mariadb(case.database)
        )
    assert_eq((await case.database.migration_status({})).history_present, False)


@test(
    [
        Param[BackendFamily](value="sqlite", name="sqlite"),
        Param[BackendFamily](value="mariadb", name="mariadb"),
    ],
    mark="slow",
)
async def adoption_preserves_existing_rows(backend: BackendFamily) -> None:
    """The reviewed initial migration is a no-op for the populated matching table."""
    case = await load_fixture(provide_existing(backend))

    await (
        adopt_sqlite(case.database)
        if backend == "sqlite"
        else adopt_mariadb(case.database)
    )
    async with case.database.transaction(read_only=True) as transaction:
        rows = await transaction.fetch_all(
            case.namespace.raw("SELECT id, balance FROM baseline_account")
        )

    assert_eq(rows, [{"id": 1, "balance": 25}])


@test(
    [
        Param[BackendFamily](value="sqlite", name="sqlite"),
        Param[BackendFamily](value="mariadb", name="mariadb"),
    ],
    mark="slow",
)
async def fresh_replay_builds_the_model_contract(backend: BackendFamily) -> None:
    """Fresh databases replay the same baseline SQL rather than creating from models."""
    case = await load_fixture(provide_baseline_case(backend))

    if backend == "sqlite":
        await case.database.migrate(SQLITE_MIGRATIONS)
        verified = await case.database.verify([SQLiteAccount])
    else:
        await case.database.migrate(MARIADB_MIGRATIONS)
        verified = await case.database.verify([MariaDBAccount])

    assert_eq(verified.checked_tables, ("baseline_account",))
    assert_eq(verified.issues, ())


@test(
    [
        Param[BackendFamily](value="sqlite", name="sqlite"),
        Param[BackendFamily](value="mariadb", name="mariadb"),
    ],
    mark="slow",
)
async def fresh_replay_enforces_the_reviewed_check(backend: BackendFamily) -> None:
    """Fresh replay includes the CHECK that partial model verification cannot prove."""
    case = await load_fixture(provide_baseline_case(backend))
    await case.database.migrate(
        SQLITE_MIGRATIONS if backend == "sqlite" else MARIADB_MIGRATIONS
    )

    with assert_raises(case.namespace.ExecutionError):
        async with case.database.transaction() as transaction:
            await transaction.execute(
                case.namespace.raw("INSERT INTO baseline_account VALUES (1, -1)")
            )


@test(
    [
        Param[BackendFamily](value="sqlite", name="sqlite"),
        Param[BackendFamily](value="mariadb", name="mariadb"),
    ],
    mark="slow",
)
async def adopted_database_extends_the_canonical_chain(backend: BackendFamily) -> None:
    """Later releases append to the baseline without editing or renaming its body."""
    case = await load_fixture(provide_existing(backend))
    await (
        adopt_sqlite(case.database)
        if backend == "sqlite"
        else adopt_mariadb(case.database)
    )
    declaration = {
        **(SQLITE_MIGRATIONS if backend == "sqlite" else MARIADB_MIGRATIONS),
        "002_note": "ALTER TABLE baseline_account ADD COLUMN note TEXT",
    }

    result = await case.database.migrate(declaration)
    await case.database.verify_migrations(declaration)

    assert_eq(result.applied, ("002_note",))
    assert_eq(result.already_applied, ("001_reviewed_baseline",))


@test(
    [
        Param(value="CREATE PROCEDURE unreviewed() SELECT 1", name="routine"),
        Param(
            value="CREATE EVENT unreviewed ON SCHEDULE AT CURRENT_TIMESTAMP + INTERVAL 1 DAY DISABLE DO SELECT 1",
            name="disabled-event",
        ),
    ],
    mark="slow",
)
async def mariadb_unreviewed_automation_is_rejected(statement: str) -> None:
    """Stored routines and scheduled jobs require review outside Table Model checks."""
    case = await load_fixture(provide_existing("mariadb"))
    async with case.database.transaction() as transaction:
        await transaction.execute(case.namespace.raw(statement))

    with assert_raises(BaselineReviewError):
        await adopt_mariadb(case.database)
    assert_eq((await case.database.migration_status({})).history_present, False)
