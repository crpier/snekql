"""An explicit migration lifetime does not confuse disposal with target usability."""

import asyncio
from pathlib import Path
from tempfile import TemporaryDirectory

from snektest import assert_eq, assert_raises, load_fixture, test

from snekql import sqlite
from snekql.experimental import migrations as m
from tests.experimental.test_migration_io_deadlines import Account
from tests.experimental.test_migration_targets import Entry, provide_package_server


@test(mark="medium")
async def lifetime_is_unopened_single_use_and_waits_only_after_exit() -> None:
    """Construction is inert; joining cannot shut down an active target or reopen it."""
    with TemporaryDirectory() as directory:
        path = Path(directory) / "app.db"
        lifetime = m.connect(sqlite.Config(database=path))
        with assert_raises(m.PackageError):
            await lifetime.wait_closed()
        assert_eq(await asyncio.to_thread(path.exists), False)
        package = m.compile(m.generate("001", [Account], backend="sqlite"))
        async with lifetime as target:
            with assert_raises(m.PackageError):
                await lifetime.wait_closed()
            assert_eq(await target.apply(await target.prepare(package)), "applied")
        await lifetime.wait_closed()
        await lifetime.wait_closed()
        with assert_raises(m.PackageError):
            await target.status()
        with assert_raises(m.PackageError):
            async with lifetime:
                msg = "a completed lifetime reopened"
                raise AssertionError(msg)
        async with m.connect(sqlite.Config(database=path)) as fresh:
            assert_eq(
                await fresh.apply(await fresh.prepare(package)), "already_applied"
            )


@test(mark="slow")
async def native_lifetime_waits_after_exit_without_reopening_or_replaying() -> None:
    """Local native disposal and migration completion remain separate facts."""
    server = await load_fixture(provide_package_server())
    package = m.compile(m.generate("001", [Entry], backend="mariadb"))
    lifetime = m.connect(server.config())
    async with lifetime as target:
        with assert_raises(m.PackageError):
            await lifetime.wait_closed()
        original = await target.prepare(package, schema_writers_excluded=True)
        wire = original.dump()
        assert_eq(await target.apply(original), "applied")
    await lifetime.wait_closed()
    await lifetime.wait_closed()
    with assert_raises(m.PackageError):
        await target.status()
    async with m.connect(server.config()) as fresh:
        assert_eq(await fresh.apply(m.Prepared.load(wire)), "already_applied")
    assert_eq(original.dump(), wire)


@test(mark="medium")
async def unused_lifetime_cannot_open_a_database_by_exiting() -> None:
    """Invalid protocol ordering must not turn exit into physical acquisition."""
    with TemporaryDirectory() as directory:
        path = Path(directory) / "unopened.db"
        lifetime = m.connect(sqlite.Config(database=path))
        with assert_raises(m.PackageError):
            await lifetime.__aexit__(None, None, None)
        assert_eq(await asyncio.to_thread(path.exists), False)
