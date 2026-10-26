"""Native migration clock work must agree with ordinary UTC query mappings."""

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import ClassVar, Literal

from snektest import Param, assert_eq, load_fixture, test

from snekql import mariadb
from snekql.experimental import migrations as m
from tests.experimental.test_migration_io_deadlines import NativeInitial
from tests.experimental.test_migration_targets import provide_package_server


class StampedAccount[S = mariadb.Pending](mariadb.Model[S]):
    """Explicit codec-bearing declaration for the actual historical clock checkpoint."""

    __tablename__: ClassVar[str] = "accounts"
    __row_type__: ClassVar[mariadb.ReadType[StampedAccount[mariadb.Row]]]
    id: mariadb.Col[int] = mariadb.Integer(primary_key=True)
    role: mariadb.Col[str] = mariadb.Text()
    changed: mariadb.Col[mariadb.UtcDatetime | None] = mariadb.DateTime(nullable=True)
    wire_changed: mariadb.Col[mariadb.UtcDatetime | None] = mariadb.Text(nullable=True)


@test(
    [
        Param[Literal["+05:30", "-07:00"]](value="+05:30", name="east"),
        Param[Literal["+05:30", "-07:00"]](value="-07:00", name="west"),
    ],
    mark="slow",
)
async def native_clock_backfill_keeps_utc_meaning_under_non_utc_server_default(  # noqa: PLR0915 - retain the actual historical clock/normal-app journey
    offset: Literal["+05:30", "-07:00"],
) -> None:
    """A completed clock backfill cannot silently label local wall time as UTC."""
    server = await load_fixture(provide_package_server())
    config = server.config()
    fixed = Path(__file__).parent / "fixtures" / "role-interruption" / "mariadb"
    first = m.Package.load((fixed / "001_accounts.json").read_text())
    expansion = m.Package.load((fixed / "002_expand.json").read_text())
    roles = m.Package.load((fixed / "003_roles.json").read_text())
    original_packages = [p.dump() for p in (first, expansion, roles)]
    draft = m.generate(
        "004_clock", [StampedAccount], backend="mariadb", previous=roles
    ).then(m.Checkpoint(name="stamp"))
    clock = m.Package.load(
        m.compile(
            draft.then(
                m.DataChange.from_query(
                    mariadb.update(StampedAccount)
                    .set(
                        StampedAccount.changed.to(mariadb.CurrentTimestamp),
                        StampedAccount.wire_changed.to(mariadb.CurrentTimestamp),
                    )
                    .all(),
                    checkpoint="stamp",
                    contract_digest=m.contract_digest(draft, point="stamp"),
                )
            )
        ).dump()
    )
    assert_eq(
        clock.dump(),
        (
            Path(__file__).parent / "fixtures" / "native-utc" / "004_clock.json"
        ).read_text(),
    )
    async with (
        await mariadb.Database.initialize(config) as app,
        app.transaction() as tx,
    ):
        saved = await tx.fetch_one(
            mariadb.raw("SELECT @@GLOBAL.time_zone AS zone,@@GLOBAL.sql_mode AS mode")
        )
    mode = str(saved["mode"])
    if "NO_BACKSLASH_ESCAPES" not in mode.split(","):
        mode += ",NO_BACKSLASH_ESCAPES"
    await server.run_sql(f"SET GLOBAL time_zone='{offset}'")
    try:
        await server.run_sql(f"SET GLOBAL sql_mode='{mode}'")
        async with (
            await mariadb.Database.initialize(config) as app,
            app.transaction() as tx,
        ):
            actual = await tx.fetch_one(mariadb.raw("SELECT @@GLOBAL.sql_mode AS mode"))
            mode = str(actual["mode"])
        async with m.connect(config) as target:
            assert_eq(
                await target.apply(
                    await target.prepare(first, schema_writers_excluded=True)
                ),
                "applied",
            )
        async with (
            await mariadb.Database.initialize(config) as app,
            app.transaction() as tx,
        ):
            await tx.execute(
                mariadb.insert_many(
                    NativeInitial,
                    [
                        NativeInitial(id=1, is_admin=True),
                        NativeInitial(id=2, is_admin=False),
                    ],
                )
            )
        async with m.connect(config) as target:
            for package in (expansion, roles):
                assert_eq(
                    await target.apply(
                        await target.prepare(package, schema_writers_excluded=True)
                    ),
                    "applied",
                )
            original = await target.prepare(clock, schema_writers_excluded=True)
            wire = original.dump()
            before = datetime.now(UTC) - timedelta(seconds=1)
            assert_eq(await target.apply(m.Prepared.load(wire)), "applied")
            after = datetime.now(UTC) + timedelta(seconds=1)
            assert_eq(original.dump(), wire)
            assert_eq(await target.apply(m.Prepared.load(wire)), "already_applied")
            assert_eq(
                sorted((p.revision, p.phase) for p in await target.status()),
                [
                    ("001_accounts", "complete"),
                    ("002_expand", "complete"),
                    ("003_roles", "complete"),
                    ("004_clock", "complete"),
                ],
            )
        async with (
            await mariadb.Database.initialize(config) as app,
            app.transaction() as tx,
        ):
            rows = await tx.fetch_all(
                mariadb.select(StampedAccount).order_by(StampedAccount.id.asc())
            )
            for row in rows:
                assert row.changed is not None and row.wire_changed is not None
                assert before <= row.changed.datetime <= after, (
                    "migration DATETIME clock labeled local time as UTC"
                )
                assert before <= row.wire_changed.datetime <= after, (
                    "migration TEXT clock labeled local time as UTC"
                )
                assert_eq(row.changed, row.wire_changed)
            assert_eq([(row.id, row.role) for row in rows], [(1, "admin"), (2, "user")])
            assert_eq(
                await tx.fetch_one(
                    mariadb.raw(
                        "SELECT @@GLOBAL.time_zone AS zone,@@GLOBAL.sql_mode AS mode"
                    )
                ),
                {"zone": offset, "mode": mode},
            )
            evidence = await tx.fetch_all(
                mariadb.raw("SELECT observation FROM snekql_experimental_migrations")
            )
            for receipt in evidence:
                observation = receipt["observation"]
                assert isinstance(observation, str)
                assert_eq(json.loads(observation)["profile"][1], mode)
            await tx.execute(
                mariadb.insert(
                    StampedAccount(
                        id=3,
                        role="user",
                        changed=None,
                        wire_changed=None,
                    )
                )
            )
            app_before = datetime.now(UTC) - timedelta(seconds=1)
            await tx.execute(
                mariadb.update(StampedAccount)
                .set(
                    StampedAccount.changed.to(mariadb.CurrentTimestamp),
                    StampedAccount.wire_changed.to(mariadb.CurrentTimestamp),
                )
                .where(StampedAccount.id.eq(3))
            )
            current = await tx.fetch_one(
                mariadb.select(StampedAccount).where(StampedAccount.id.eq(3))
            )
            assert current.changed is not None and current.wire_changed is not None
            assert (
                app_before
                <= current.changed.datetime
                <= datetime.now(UTC) + timedelta(seconds=1)
            )
            assert_eq(current.changed, current.wire_changed)
        assert_eq([p.dump() for p in (first, expansion, roles)], original_packages)
    finally:
        zone = str(saved["zone"]).replace("'", "''")
        await server.run_sql(f"SET GLOBAL time_zone='{zone}'")
        mode = str(saved["mode"]).replace("'", "''")
        await server.run_sql(f"SET GLOBAL sql_mode='{mode}'")
