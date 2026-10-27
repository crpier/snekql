"""Selected native environment, real reviewed role workflow and ownership/refusal seam."""

import asyncio
import hashlib
import json
import os
import platform
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

from snektest import assert_eq, assert_raises, load_fixture, test

from snekql import mariadb
from snekql.experimental import migrations as m
from tests.experimental.test_migration_authoring_journey import _python
from tests.experimental.test_migration_io_deadlines import NativeAccount
from tests.experimental.test_migration_role_interruption import (
    _apply,
    _payload,
    _render,
)
from tests.experimental.test_migration_targets import provide_package_server
from tests.experimental.test_migration_wal_interruption import _save_original


@test(mark="slow")
async def selected_native_environment_qualifies_original_role_refusal_and_handoff(  # noqa: PLR0915 - public authored/deployed/ownership journey and actual executable provenance
) -> None:
    """Exact server evidence, no silent skip/download or production environment selector."""
    server = await load_fixture(provide_package_server())
    config = server.config()
    pid = int(await asyncio.to_thread(server.pid_path.read_text))
    executable = await asyncio.to_thread(Path(f"/proc/{pid}/exe").readlink)
    actual_sha = await asyncio.to_thread(
        lambda: hashlib.sha256(executable.read_bytes()).hexdigest()
    )
    async with await mariadb.Database.initialize(config) as db, db.transaction() as tx:
        version = (await tx.fetch_one(mariadb.raw("SELECT VERSION() AS version")))[
            "version"
        ]
    expected = os.environ.get("SNEKQL_TEST_EXPECT_MARIADB")
    if expected:
        assert isinstance(version, str) and version.startswith(expected + "-")
    with TemporaryDirectory() as directory:
        root = Path(directory)
        deploy = await _render(root, "mariadb")
        payload = _payload(config)
        await _apply(deploy, payload, "001_accounts.json")
        await server.run_sql("INSERT INTO accounts VALUES(1,1),(2,0)")
        await _apply(deploy, payload, "002_expand.json")
        roles = m.Package.load((deploy / "003_roles.json").read_text())
        async with m.connect(config) as target:
            original = await target.prepare(roles, schema_writers_excluded=True)
            wire = original.dump()
        await asyncio.to_thread(_save_original, deploy / "original-plan.json", wire)
        async with (
            await mariadb.Database.initialize(config) as db,
            db.transaction() as tx,
        ):
            before = await tx.fetch_all(
                mariadb.raw(
                    "SELECT * FROM snekql_experimental_migrations ORDER BY revision"
                )
            )
        await server.run_sql("CREATE TABLE caller_marker(id INTEGER)")
        try:
            async with m.connect(config) as target:
                with assert_raises(m.PackageError) as drift:
                    await target.apply(m.Prepared.load(wire))
                assert "catalog differs" in str(drift.exception)
            async with (
                await mariadb.Database.initialize(config) as db,
                db.transaction() as tx,
            ):
                assert_eq(
                    await tx.fetch_all(
                        mariadb.raw(
                            "SELECT * FROM snekql_experimental_migrations ORDER BY revision"
                        )
                    ),
                    before,
                )
                assert_eq(
                    await tx.fetch_all(
                        mariadb.raw("SELECT id,is_admin,role FROM accounts ORDER BY id")
                    ),
                    [
                        {"id": 1, "is_admin": 1, "role": None},
                        {"id": 2, "is_admin": 0, "role": None},
                    ],
                )
        finally:
            await server.run_sql("DROP TABLE caller_marker")
        async with m.connect(config) as target:
            assert_eq(await target.apply(m.Prepared.load(wire)), "applied")
            assert_eq(await target.apply(m.Prepared.load(wire)), "already_applied")
        assert_eq(
            json.loads(await _python(deploy / "app.py", payload)),
            {"before": [[1, "admin"], [2, "user"]], "created": [3, "user"]},
        )
        handoff = m.compile(
            m.generate("004_handoff", [], backend="mariadb", previous=roles).resolve(
                m.RelinquishTable(table_name="accounts")
            )
        )
        async with m.connect(config) as target:
            prepared = await target.prepare(handoff, schema_writers_excluded=True)
            assert_eq(prepared.statements, ())
            assert_eq(await target.apply(prepared), "applied")
            assert_eq(await target.apply(prepared), "already_applied")
            progress = sorted((p.revision, p.phase) for p in await target.status())
            assert_eq(
                progress,
                [
                    ("001_accounts", "complete"),
                    ("002_expand", "complete"),
                    ("003_roles", "complete"),
                    ("004_handoff", "complete"),
                ],
            )
        async with (
            await mariadb.Database.initialize(config) as db,
            db.transaction() as tx,
        ):
            rows = await tx.fetch_all(
                mariadb.select(NativeAccount).order_by(NativeAccount.id.asc())
            )
            assert_eq(
                [(r.id, r.role) for r in rows], [(1, "admin"), (2, "user"), (3, "user")]
            )
            assert_eq(
                (
                    await tx.fetch_all(
                        mariadb.raw(
                            "SELECT * FROM snekql_experimental_migrations ORDER BY revision"
                        )
                    )
                )[: len(before)],
                before,
            )
        assert_eq(original.dump(), wire)
        assert_eq(
            await asyncio.to_thread((deploy / "original-plan.json").read_text), wire
        )
        report = os.environ.get("SNEKQL_TEST_ENVIRONMENT_REPORT")
        if report:
            record = {
                "pid": pid,
                "executable": str(executable),
                "sha256": actual_sha,
                "version": version,
                "python": sys.version,
                "interpreter": sys.executable,
                "platform": platform.platform(),
                "lazy_imports": sys.get_lazy_imports(),
                "original_sha256": hashlib.sha256(wire.encode()).hexdigest(),
                "before": before,
                "progress": progress,
                "caller_marker_refused": True,
                "handoff_statements": list(prepared.statements),
                "author_sources_removed": not await asyncio.to_thread(
                    (root / "author").exists
                ),
            }
            await asyncio.to_thread(
                Path(report).write_text, json.dumps(record, indent=2) + "\n"
            )
