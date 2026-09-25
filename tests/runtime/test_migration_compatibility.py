"""Rolling deployments verify a complete known chain plus approved later history."""

import asyncio
from collections.abc import AsyncGenerator
from pathlib import Path
from typing import ClassVar

from anyio import TemporaryDirectory, wait_all_tasks_blocked
from snektest import Param, assert_eq, assert_raises, fixture, load_fixture, test

from snekql import mariadb, sqlite
from snekql.errors import (
    MigrationDeclarationError,
    MigrationHistoryError,
    SchemaVerificationError,
)
from snekql.model import BackendFamily
from snekql.runtime import Database
from tests.helpers import provide_mariadb_server
from tests.runtime.test_raw_execution import RawCase, provide_raw_case

_KNOWN = {"001_entries": "CREATE TABLE rollout_entries (id INTEGER PRIMARY KEY)"}
_APPROVED = {"002_note": "ALTER TABLE rollout_entries ADD COLUMN note TEXT"}


@fixture
async def provide_upgraded_case(backend: BackendFamily) -> AsyncGenerator[RawCase]:
    """The deploy job has already applied the next application's additive change."""
    case = await load_fixture(provide_raw_case(backend))
    await case.database.migrate(_KNOWN | _APPROVED)
    yield case


@test(
    [
        Param[BackendFamily](value="sqlite", name="sqlite"),
        Param[BackendFamily](value="mariadb", name="mariadb"),
    ],
    [
        Param(value=(_KNOWN, _APPROVED), name="approved-tail"),
        Param(value=(_KNOWN | _APPROVED, {}), name="empty-approval"),
        Param(value=({}, _KNOWN | _APPROVED), name="empty-known"),
    ],
    mark="slow",
)
async def approved_later_migration_accepts_old_application(
    backend: BackendFamily,
    declarations: tuple[dict[str, str], dict[str, str]],
) -> None:
    """An old application's complete chain can approve a precise later migration."""
    case = await load_fixture(provide_upgraded_case(backend))

    known, approved = declarations
    result = await case.database.verify_migrations(
        known, policy="compatible", approved_later=approved
    )

    assert_eq(result, None)


@test(
    [
        Param[BackendFamily](value="sqlite", name="sqlite"),
        Param[BackendFamily](value="mariadb", name="mariadb"),
    ],
    [Param(value="default", name="default"), Param(value="explicit", name="explicit")],
    mark="slow",
)
async def strict_verification_rejects_later_history(
    backend: BackendFamily, mode: str
) -> None:
    """Opt-in compatibility does not weaken either spelling of exact-head verification."""
    case = await load_fixture(provide_upgraded_case(backend))

    with assert_raises(MigrationHistoryError):
        if mode == "default":
            await case.database.verify_migrations(_KNOWN)
        else:
            await case.database.verify_migrations(_KNOWN, policy="strict")


@test(
    [
        Param[BackendFamily](value="sqlite", name="sqlite"),
        Param[BackendFamily](value="mariadb", name="mariadb"),
    ],
    mark="slow",
)
async def compatible_verification_does_not_require_pending_approvals(
    backend: BackendFamily,
) -> None:
    """Approvals bound permitted history rather than requiring a future deployment."""
    case = await load_fixture(provide_upgraded_case(backend))

    await case.database.verify_migrations(
        _KNOWN,
        policy="compatible",
        approved_later=_APPROVED | {"003_pending": "DROP TABLE rollout_entries"},
    )
    async with case.database.transaction() as transaction:
        rows = await transaction.fetch_all(
            case.namespace.raw("SELECT id FROM rollout_entries")
        )
    assert_eq(rows, [])


@test(
    [
        Param[BackendFamily](value="sqlite", name="sqlite"),
        Param[BackendFamily](value="mariadb", name="mariadb"),
    ],
    [
        Param(value=({}, {}), name="unknown-history"),
        Param(value=(_KNOWN, {}), name="unapproved-tail"),
        Param(
            value=(
                _KNOWN,
                {"002_note": "ALTER TABLE rollout_entries ADD COLUMN other TEXT"},
            ),
            name="changed-approved-body",
        ),
        Param(
            value=(
                {"001_entries": "CREATE TABLE other_entries (id INTEGER PRIMARY KEY)"},
                _APPROVED,
            ),
            name="changed-known-body",
        ),
        Param(value=(_APPROVED | _KNOWN, {}), name="reordered-known"),
        Param(
            value=(
                _KNOWN | _APPROVED | {"003_required": "DROP TABLE rollout_entries"},
                {},
            ),
            name="missing-known",
        ),
        Param(
            value=(
                _KNOWN,
                {"003_other": "CREATE TABLE other_entries (id INTEGER)"} | _APPROVED,
            ),
            name="skipped-approval",
        ),
    ],
    mark="slow",
)
async def compatible_verification_rejects_divergence(
    backend: BackendFamily, declarations: tuple[dict[str, str], dict[str, str]]
) -> None:
    """Approval never permits an unknown, changed, reordered, or incomplete chain."""
    case = await load_fixture(provide_upgraded_case(backend))
    known, approved = declarations

    with assert_raises(MigrationHistoryError):
        await case.database.verify_migrations(
            known, policy="compatible", approved_later=approved
        )


@test(
    [
        Param[BackendFamily](value="sqlite", name="sqlite"),
        Param[BackendFamily](value="mariadb", name="mariadb"),
    ],
    [
        Param(value="invalid-policy", name="invalid-policy"),
        Param(value="strict-approvals", name="strict-approvals"),
        Param(value="missing-approvals", name="missing-approvals"),
        Param(value="repeated-name", name="repeated-name"),
        Param(value="invalid-body", name="invalid-body"),
    ],
    mark="slow",
)
async def invalid_policy_is_rejected_before_acquisition(
    backend: BackendFamily, invalid: str
) -> None:
    """Declaration errors win over the closed database's acquisition error."""
    case = await load_fixture(provide_raw_case(backend))
    await case.database.close()

    with assert_raises(MigrationDeclarationError):
        if invalid == "invalid-policy":
            await case.database.verify_migrations(_KNOWN, policy="prefix")  # ty: ignore[invalid-argument-type]
        elif invalid == "strict-approvals":
            await case.database.verify_migrations(_KNOWN, approved_later={})
        elif invalid == "missing-approvals":
            await case.database.verify_migrations(_KNOWN, policy="compatible")
        elif invalid == "repeated-name":
            await case.database.verify_migrations(
                _KNOWN, policy="compatible", approved_later=_KNOWN
            )
        else:
            await case.database.verify_migrations(
                _KNOWN, policy="compatible", approved_later={"later": " "}
            )


@test(
    [
        Param[BackendFamily](value="sqlite", name="sqlite"),
        Param[BackendFamily](value="mariadb", name="mariadb"),
    ],
    mark="slow",
)
async def compatible_empty_known_chain_accepts_absent_history(
    backend: BackendFamily,
) -> None:
    """Zero known migrations require no history even when later changes are approved."""
    case = await load_fixture(provide_raw_case(backend))

    await case.database.verify_migrations(
        {}, policy="compatible", approved_later=_KNOWN
    )
    await case.database.verify_migrations({})


@test(
    [
        Param[BackendFamily](value="sqlite", name="sqlite"),
        Param[BackendFamily](value="mariadb", name="mariadb"),
    ],
    mark="slow",
)
async def compatible_policy_does_not_relax_migrate(backend: BackendFamily) -> None:
    """An old replica may verify history but cannot run its shortened migration chain."""
    case = await load_fixture(provide_upgraded_case(backend))
    await case.database.verify_migrations(
        _KNOWN, policy="compatible", approved_later=_APPROVED
    )

    with assert_raises(MigrationHistoryError):
        await case.database.migrate(_KNOWN)


@fixture
async def provide_rollout_case(
    backend: BackendFamily,
) -> AsyncGenerator[tuple[RawCase, sqlite.Config | mariadb.Config, dict[str, str]]]:
    """Keep an old application connected while independent deploy/restart pools open."""
    async with TemporaryDirectory() as directory:
        if backend == "mariadb":
            server = await load_fixture(provide_mariadb_server())
            config = server.config(pool_size=1)
            namespace = mariadb
            body = "CREATE TABLE rollout_entries (id BIGINT NOT NULL PRIMARY KEY) ENGINE=InnoDB"
        else:
            config = sqlite.Config(database=Path(directory) / "rollout.db", pool_size=1)
            namespace = sqlite
            body = "CREATE TABLE rollout_entries (id INTEGER PRIMARY KEY) STRICT"
        async with await Database.initialize(config) as database:
            known = {"001_entries": body}
            await database.migrate(known)
            yield RawCase(database, namespace), config, known


@test(
    [
        Param[BackendFamily](value="sqlite", name="sqlite"),
        Param[BackendFamily](value="mariadb", name="mariadb"),
    ],
    mark="slow",
)
async def old_application_restarts_after_additive_deployment(
    backend: BackendFamily,
) -> None:
    """Old code accepts the same approved range before deployment and after restart."""
    old, config, known = await load_fixture(provide_rollout_case(backend))
    await old.database.verify_migrations(
        known, policy="compatible", approved_later=_APPROVED
    )
    async with await Database.initialize(config) as deployer:
        await deployer.migrate(known | _APPROVED)
        await deployer.verify_migrations(known | _APPROVED, policy="strict")
    await old.database.close()

    async with await Database.initialize(config) as restarted:
        await restarted.verify_migrations(
            known, policy="compatible", approved_later=_APPROVED
        )
        async with restarted.transaction() as transaction:
            rows = await transaction.fetch_all(
                old.namespace.raw("SELECT id FROM rollout_entries")
            )
    assert_eq(rows, [])


@test(
    [
        Param[BackendFamily](value="sqlite", name="sqlite"),
        Param[BackendFamily](value="mariadb", name="mariadb"),
    ],
    mark="slow",
)
async def breaking_deployment_exceeds_old_application_approval(
    backend: BackendFamily,
) -> None:
    """Old applications fail startup once a contract migration exceeds their range."""
    old, config, known = await load_fixture(provide_rollout_case(backend))
    async with await Database.initialize(config) as deployer:
        await deployer.migrate(
            known | _APPROVED | {"003_contract": "DROP TABLE rollout_entries"}
        )

    with assert_raises(MigrationHistoryError):
        await old.database.verify_migrations(
            known, policy="compatible", approved_later=_APPROVED
        )


@test(
    [
        Param[BackendFamily](value="sqlite", name="sqlite"),
        Param[BackendFamily](value="mariadb", name="mariadb"),
    ],
    mark="slow",
)
async def history_approval_does_not_override_schema_verification(
    backend: BackendFamily,
) -> None:
    """The old model matches initially, but approved extra columns still report drift."""
    old, config, known = await load_fixture(provide_rollout_case(backend))

    class SQLiteEntry[S = sqlite.Pending](sqlite.Model[S]):
        __row_type__: ClassVar[sqlite.ReadType[SQLiteEntry[sqlite.Row]]]
        __tablename__ = "rollout_entries"
        id: sqlite.Col[int] = sqlite.Integer(primary_key=True)

    class MariaDBEntry[S = mariadb.Pending](mariadb.Model[S]):
        __row_type__: ClassVar[mariadb.ReadType[MariaDBEntry[mariadb.Row]]]
        __tablename__ = "rollout_entries"
        id: mariadb.Col[int] = mariadb.Integer(primary_key=True)

    model = SQLiteEntry if backend == "sqlite" else MariaDBEntry
    await old.database.verify([model])
    async with await Database.initialize(config) as deployer:
        await deployer.migrate(known | _APPROVED)
    await old.database.verify_migrations(
        known, policy="compatible", approved_later=_APPROVED
    )

    with assert_raises(SchemaVerificationError):
        await old.database.verify([model])


@test(
    [
        Param[BackendFamily](value="sqlite", name="sqlite"),
        Param[BackendFamily](value="mariadb", name="mariadb"),
    ],
    mark="slow",
)
async def approvals_are_snapshotted_before_waiting_for_connection(
    backend: BackendFamily,
) -> None:
    """Caller mutation while checkout waits cannot change the accepted history range."""
    old, config, known = await load_fixture(provide_rollout_case(backend))
    async with await Database.initialize(config) as deployer:
        await deployer.migrate(known | _APPROVED)
    approved = dict(_APPROVED)

    async with old.database.transaction():
        verifying = asyncio.create_task(
            old.database.verify_migrations(
                known, policy="compatible", approved_later=approved
            )
        )
        await wait_all_tasks_blocked()
        known.clear()
        approved.clear()
    assert_eq(await verifying, None)
