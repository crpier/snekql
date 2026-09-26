"""Service examples preserve explicit deployment and transaction ownership."""

import asyncio
from collections.abc import AsyncGenerator, Iterable
from unittest.mock import patch

from aiosqlite import Connection, Cursor, OperationalError, connect
from httpx import ASGITransport, AsyncClient
from snektest import assert_eq, assert_raises, load_fixture, test

from examples.incremental_adoption import open_existing
from examples.service_app import create_app
from examples.service_database import Entry, EntryInput, deploy, open_service
from examples.service_fixtures import empty_config, fresh_database
from examples.service_worker import run_worker
from snekql import sqlite


@test(mark="medium")
async def startup_requires_deployed_history() -> None:
    """An application replica cannot silently migrate a fresh database."""
    config = await load_fixture(empty_config())

    with assert_raises(sqlite.MigrationHistoryError):
        async with open_service(config):
            pass


@test(mark="medium")
async def deployed_service_closes_its_database() -> None:
    """A completed lifespan cannot leave a usable Database behind."""
    config = await load_fixture(empty_config())

    await deploy(config)
    async with open_service(config) as database:
        pass

    assert_eq(database.pool_stats().state, "closed")


@test(mark="medium")
async def successful_http_write_is_visible_to_another_pool() -> None:
    """Receiving success means the route's transaction has already committed."""
    config = await load_fixture(empty_config())

    await deploy(config)
    application = create_app(config)
    async with (
        application.router.lifespan_context(application),
        AsyncClient(
            transport=ASGITransport(app=application), base_url="http://service"
        ) as client,
    ):
        response = await client.post(
            "/entries", json={"entries": [{"entry_id": 7, "label": "ready"}]}
        )
        async with (
            open_service(config) as independent,
            independent.transaction() as transaction,
        ):
            labels = await transaction.fetch_all(sqlite.raw("SELECT label FROM entry"))

    assert_eq(response.status_code, 201)
    assert_eq(labels, [{"label": "ready"}])


@test(mark="medium")
async def rejected_http_batch_leaves_no_partial_write() -> None:
    """Constraint rejection rolls back earlier statements before HTTP 409."""
    config = await load_fixture(empty_config())
    await deploy(config)
    application = create_app(config)
    async with (
        application.router.lifespan_context(application),
        AsyncClient(
            transport=ASGITransport(app=application, raise_app_exceptions=False),
            base_url="http://service",
        ) as client,
    ):
        response = await client.post(
            "/entries",
            json={
                "entries": [
                    {"entry_id": 7, "label": "first"},
                    {"entry_id": 7, "label": "duplicate"},
                ]
            },
        )
        async with (
            open_service(config) as independent,
            independent.transaction() as transaction,
        ):
            rows = await transaction.fetch_all(sqlite.raw("SELECT entry_id FROM entry"))

    assert_eq((response.status_code, rows), (409, []))


@test(mark="medium")
async def startup_leaves_an_empty_schema_untouched() -> None:
    """Failed readiness creates neither application tables nor migration history."""
    config = await load_fixture(empty_config())
    application = create_app(config)

    with assert_raises(sqlite.MigrationHistoryError):
        async with application.router.lifespan_context(application):
            pass
    async with (
        await sqlite.Database.initialize(config) as database,
        database.transaction() as transaction,
    ):
        tables = await transaction.fetch_all(
            sqlite.raw("SELECT name FROM sqlite_master WHERE type='table'")
        )

    assert_eq(tables, [])


@test(mark="medium")
async def shutdown_revokes_the_request_dependency() -> None:
    """Requests without a live lifespan cannot retain the closed Database."""
    config = await load_fixture(empty_config())
    await deploy(config)
    application = create_app(config)
    async with application.router.lifespan_context(application):
        pass

    async with AsyncClient(
        transport=ASGITransport(app=application), base_url="http://service"
    ) as client:
        response = await client.post(
            "/entries", json={"entries": [{"entry_id": 7, "label": "too late"}]}
        )

    assert_eq(response.status_code, 503)


@test(mark="medium")
async def commit_failure_cannot_send_http_success() -> None:
    """A native COMMIT failure is not hidden by a response already sent."""
    config = await load_fixture(empty_config())
    await deploy(config)
    application = create_app(config)
    original_execute = Connection.execute
    commit_attempts = 0

    async def reject_commit(
        self: Connection, sql: str, parameters: Iterable[object] | None = None
    ) -> Cursor:
        nonlocal commit_attempts
        if sql == "COMMIT":
            commit_attempts += 1
            message = "commit transport failure"
            raise OperationalError(message)
        return await original_execute(self, sql, parameters)

    async with (
        application.router.lifespan_context(application),
        AsyncClient(
            transport=ASGITransport(app=application, raise_app_exceptions=False),
            base_url="http://service",
        ) as client,
    ):
        with patch.object(Connection, "execute", reject_commit):
            response = await client.post(
                "/entries", json={"entries": [{"entry_id": 7, "label": "uncertain"}]}
            )

    assert_eq(commit_attempts, 1)
    assert_eq(response.status_code, 500)
    assert_eq(
        response.json(), {"detail": "Write failed; check its outcome before retrying"}
    )


@test(mark="medium")
async def worker_failure_preserves_prior_committed_jobs() -> None:
    """Each delivered job has its own transaction, not one transaction per worker."""
    config = await load_fixture(empty_config())

    await deploy(config)

    async def deliveries() -> AsyncGenerator[EntryInput]:
        yield EntryInput(entry_id=1, label="committed")
        yield EntryInput(entry_id=1, label="duplicate")
        yield EntryInput(entry_id=2, label="not reached")

    with assert_raises(sqlite.ExecutionError):
        await run_worker(config, deliveries())
    async with open_service(config) as database, database.transaction() as transaction:
        rows = await transaction.fetch_all(
            sqlite.raw("SELECT entry_id, label FROM entry ORDER BY entry_id")
        )

    assert_eq(rows, [{"entry_id": 1, "label": "committed"}])


@test(mark="medium")
async def database_fixture_replays_the_deployed_schema() -> None:
    """Tests get the same migration-owned schema as a fresh service deployment."""

    database = await load_fixture(fresh_database())

    async with database.transaction() as transaction:
        entries = await transaction.fetch_all(sqlite.select(Entry))

    assert_eq(entries, [])


@test(mark="medium")
async def existing_layer_commit_is_outside_snekql_rollback() -> None:
    """An externally migrated table needs no invented snekql migration history."""
    config = await load_fixture(empty_config())

    class CancelledChange(sqlite.SnekqlError):
        """The application aborts only its new-layer transaction."""

    async with connect(str(config.database)) as existing:
        await existing.execute(
            "CREATE TABLE entry (entry_id INTEGER PRIMARY KEY, label TEXT NOT NULL) STRICT"
        )
        await existing.execute("INSERT INTO entry VALUES (1, 'external')")
        await existing.commit()

        with assert_raises(CancelledChange):
            async with (
                open_existing(config) as database,
                database.transaction() as transaction,
            ):
                await transaction.execute(
                    sqlite.insert(Entry(entry_id=2, label="rolled back"))
                )
                message = "Application cancelled this independent transaction"
                raise CancelledChange(message)
        async with existing.execute(
            "SELECT entry_id, label FROM entry ORDER BY entry_id"
        ) as cursor:
            rows = await cursor.fetchall()
        async with existing.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ) as cursor:
            tables = await cursor.fetchall()

    assert_eq(rows, [(1, "external")])
    assert_eq(tables, [("entry",)])


@test(mark="medium")
async def invalid_http_batch_cannot_write_valid_prefix() -> None:
    """Whole-request validation precedes opening a write transaction."""
    config = await load_fixture(empty_config())
    await deploy(config)
    application = create_app(config)

    async with (
        application.router.lifespan_context(application),
        AsyncClient(
            transport=ASGITransport(app=application), base_url="http://service"
        ) as client,
    ):
        response = await client.post(
            "/entries",
            json={
                "entries": [
                    {"entry_id": 1, "label": "valid"},
                    {"entry_id": 2, "label": ""},
                ]
            },
        )
    async with open_service(config) as database, database.transaction() as transaction:
        rows = await transaction.fetch_all(sqlite.select(Entry))

    assert_eq((response.status_code, rows), (422, []))


@test(mark="medium")
async def schema_drift_rejects_service_startup() -> None:
    """Matching history does not excuse a live schema mismatch."""
    config = await load_fixture(empty_config())
    await deploy(config)
    async with connect(str(config.database)) as existing:
        async with existing.execute("ALTER TABLE entry DROP COLUMN label"):
            pass
        await existing.commit()
    application = create_app(config)

    with assert_raises(sqlite.SchemaVerificationError):
        async with application.router.lifespan_context(application):
            pass


@test(mark="medium")
async def cancelled_worker_preserves_finished_deliveries() -> None:
    """Cancellation while awaiting another delivery does not undo the last job."""
    config = await load_fixture(empty_config())
    await deploy(config)
    waiting = asyncio.Event()
    never_delivered = asyncio.Event()

    async def deliveries() -> AsyncGenerator[EntryInput]:
        yield EntryInput(entry_id=1, label="finished")
        waiting.set()
        await never_delivered.wait()
        yield EntryInput(entry_id=2, label="not delivered")

    worker = asyncio.create_task(run_worker(config, deliveries()))
    try:
        await asyncio.wait_for(waiting.wait(), timeout=5)
    finally:
        worker.cancel()
        with assert_raises(asyncio.CancelledError):
            await worker
    async with open_service(config) as database, database.transaction() as transaction:
        rows = await transaction.fetch_all(sqlite.select(Entry.label))

    assert_eq(rows, ["finished"])
