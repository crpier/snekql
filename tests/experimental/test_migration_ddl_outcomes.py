"""Real native DDL OK loss requires explicit structural acceptance, never replay."""

import asyncio
import json
import os
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Literal

import aiomysql
from snektest import Param, assert_eq, assert_raises, test

from snekql import mariadb
from snekql.experimental import migrations as m
from snekql.testing.mariadb import temporary_mariadb_server
from tests.experimental.test_migration_commit_outcomes import _CommitProxy
from tests.experimental.test_migration_io_deadlines import NativeAccount, NativeInitial
from tests.experimental.test_migration_role_interruption import _wait_disconnected
from tests.experimental.test_migration_wal_interruption import _save_original


@test(
    [
        Param[Literal["after", "eof"]](value=mode, name=mode)
        for mode in ("after", "eof")
    ],
    mark="slow",
)
async def lost_actual_role_ddl_ok_requires_original_structural_reconciliation(  # noqa: PLR0915 - actual packet, physical outcome, explicit reviewed recovery
    mode: Literal["after", "eof"],
) -> None:
    """Library never turns a lost DDL reply into a rollback or automatic receipt."""
    home = os.environ.get("SNEKQL_TEST_MARIADB_HOME")
    installation = await asyncio.to_thread(Path(home).resolve) if home else None
    with TemporaryDirectory(prefix="ddl-outcome-", dir=".snektest") as directory:
        root = Path(directory)
        async with temporary_mariadb_server(
            auth="password",
            transports={"tcp"},
            data_directory=root / "data",
            mariadbd=installation / "bin/mariadbd" if installation else "mariadbd",
            install_db=installation / "scripts/mariadb-install-db"
            if installation
            else "mariadb-install-db",
            client=installation / "bin/mariadb" if installation else "mariadb",
            server_args=(f"--basedir={installation}",) if installation else (),
        ) as server:
            direct = server.config(transport="tcp")
            proxy = _CommitProxy(direct)
            async with await asyncio.start_server(
                proxy.accept, "127.0.0.1", 0
            ) as listener:
                config = replace(
                    direct,
                    port=listener.sockets[0].getsockname()[1],
                    operation_timeout=2,
                )
                observer = await aiomysql.connect(
                    host=direct.host,
                    port=direct.port,
                    user=direct.user,
                    password=direct.password,
                    db=direct.database,
                    autocommit=True,
                )
                try:
                    fixed = Path(__file__).parent / "fixtures/role-interruption/mariadb"
                    packages = [
                        m.Package.load((fixed / name).read_text())
                        for name in (
                            "001_accounts.json",
                            "002_expand.json",
                            "003_roles.json",
                        )
                    ]
                    first, expand, roles = packages
                    originals = [p.dump() for p in packages]
                    async with m.connect(config) as target:
                        await target.apply(
                            await target.prepare(first, schema_writers_excluded=True)
                        )
                    async with (
                        await mariadb.Database.initialize(direct) as app,
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
                        await target.apply(
                            await target.prepare(expand, schema_writers_excluded=True)
                        )
                        original = await target.prepare(
                            roles, schema_writers_excluded=True
                        )
                        wire = original.dump()
                    await asyncio.to_thread(
                        _save_original, root / "original-plan.json", wire
                    )
                    async with observer.cursor() as cursor:
                        await cursor.execute(
                            "SELECT * FROM snekql_experimental_migrations ORDER BY revision"
                        )
                        before = await cursor.fetchall()
                    ddl = original.steps[-1].statements[0]
                    assert (
                        ddl.startswith("ALTER TABLE `accounts`")
                        and "DROP COLUMN `is_admin`" in ddl
                    )
                    async with m.connect(config) as target:
                        proxy.statement = ddl
                        proxy.arm = (1, mode)
                        proxy.forwarded.clear()
                        applying = asyncio.create_task(
                            target.apply(m.Prepared.load(wire))
                        )
                        try:
                            await asyncio.wait_for(proxy.hit.wait(), 10)
                            assert (
                                proxy.server_ok is not None
                                and proxy.server_ok[:1] == b"\x00"
                            )
                            fault_id = proxy.session_id
                            async with observer.cursor() as cursor:
                                await cursor.execute("SHOW COLUMNS FROM accounts")
                                columns = await cursor.fetchall()
                                assert_eq(
                                    [(row[0], row[2]) for row in columns],
                                    [("id", "NO"), ("role", "NO")],
                                )
                                await cursor.execute(
                                    "SELECT id,role FROM accounts ORDER BY id"
                                )
                                fault_rows = await cursor.fetchall()
                                assert_eq(fault_rows, ((1, "admin"), (2, "user")))
                                await cursor.execute(
                                    "SELECT phase,acknowledged,total FROM snekql_experimental_migrations WHERE revision='003_roles'"
                                )
                                fault_progress = await cursor.fetchall()
                                assert_eq(fault_progress, (("started", 2, 3),))
                            if mode == "eof":
                                with assert_raises(aiomysql.OperationalError) as lost:
                                    await applying
                                assert_eq(lost.exception.args[0], 2013)
                            else:
                                with assert_raises(
                                    mariadb.DatabaseOperationTimeoutError
                                ) as expired:
                                    await applying
                                assert_eq(
                                    expired.exception.operation, "migration execute"
                                )
                            with assert_raises(m.PackageError):
                                await target.status()
                        finally:
                            if not applying.done():
                                applying.cancel()
                            await asyncio.gather(applying, return_exceptions=True)
                    await asyncio.wait_for(proxy.disposed.wait(), 5)
                    assert proxy.session_id is not None
                    await _wait_disconnected(direct, proxy.session_id)
                    assert "ROLLBACK" not in proxy.forwarded
                    async with m.connect(config) as fresh:
                        progress = next(
                            p for p in await fresh.status() if p.revision == "003_roles"
                        )
                        assert_eq(
                            (progress.phase, progress.acknowledged_steps),
                            ("uncertain", 2),
                        )
                        with assert_raises(m.PackageError):
                            await fresh.apply(m.Prepared.load(wire))
                        recovery = await fresh.inspect_recovery(
                            m.Prepared.load(wire), schema_writers_excluded=True
                        )
                        assert_eq(
                            (recovery.disposition, recovery.acknowledged_steps),
                            ("reconcile_structural", 2),
                        )
                        with assert_raises(m.PackageError):
                            await fresh.resume(recovery, schema_writers_excluded=True)
                        accepted = await fresh.reconcile(
                            recovery,
                            reason="Reviewed real lost ALTER OK: required role and removed flag both independently observed",
                            schema_writers_excluded=True,
                        )
                        assert_eq(accepted.disposition, "finish")
                        assessment = recovery.model_dump(mode="json")
                    async with m.connect(config) as fresh:
                        recovery = await fresh.inspect_recovery(
                            m.Prepared.load(wire), schema_writers_excluded=True
                        )
                        assert_eq(recovery.disposition, "finish")
                        assert_eq(
                            await fresh.resume(recovery, schema_writers_excluded=True),
                            "applied",
                        )
                        assert_eq(
                            await fresh.apply(m.Prepared.load(wire)), "already_applied"
                        )
                        progress = sorted(
                            await fresh.status(), key=lambda p: p.revision
                        )
                        assert_eq(
                            [(p.revision, p.phase) for p in progress],
                            [
                                ("001_accounts", "complete"),
                                ("002_expand", "complete"),
                                ("003_roles", "complete"),
                            ],
                        )
                        assert_eq(len(progress[-1].reconciliations), 1)
                    assert_eq(proxy.forwarded.count(ddl), 1)
                    assert_eq(
                        len(
                            [
                                sql
                                for sql in proxy.forwarded
                                if sql.startswith("UPDATE `accounts`")
                            ]
                        ),
                        2,
                    )
                    async with observer.cursor() as cursor:
                        await cursor.execute(
                            "SELECT * FROM snekql_experimental_migrations ORDER BY revision"
                        )
                        final_history = await cursor.fetchall()
                        assert_eq(final_history[: len(before)], before)
                    async with (
                        await mariadb.Database.initialize(direct) as app,
                        app.transaction() as tx,
                    ):
                        await tx.execute(
                            mariadb.insert(NativeAccount(id=3, role="user"))
                        )
                        rows = await tx.fetch_all(
                            mariadb.select(NativeAccount).order_by(
                                NativeAccount.id.asc()
                            )
                        )
                        assert_eq(
                            [(r.id, r.role) for r in rows],
                            [(1, "admin"), (2, "user"), (3, "user")],
                        )
                    assert_eq(original.dump(), wire)
                    assert_eq([p.dump() for p in packages], originals)
                    report = os.environ.get("SNEKQL_TEST_DDL_REPORT")
                    if report:
                        destination = Path(report) / mode
                        await asyncio.to_thread(
                            destination.mkdir, parents=True, exist_ok=True
                        )
                        await asyncio.to_thread(
                            (destination / "original-plan.json").write_text, wire
                        )
                        record = {
                            "mode": mode,
                            "ddl": ddl,
                            "fault_session": fault_id,
                            "server_ok_hex": proxy.server_ok.hex(),
                            "columns_at_fault": columns,
                            "rows_at_fault": fault_rows,
                            "progress_at_fault": fault_progress,
                            "before": before,
                            "final_history": final_history,
                            "assessment": assessment,
                            "reconciliations": [
                                r.model_dump(mode="json")
                                for r in progress[-1].reconciliations
                            ],
                            "forwarded": proxy.forwarded,
                            "original_unchanged": original.dump() == wire,
                            "current_app": [(r.id, r.role) for r in rows],
                            "physical_session_absence_observed": True,
                            "runtime_fix_claimed": False,
                        }
                        await asyncio.to_thread(
                            (destination / "trace.json").write_text,
                            json.dumps(record, indent=2) + "\n",
                        )
                finally:
                    observer.close()
                    await proxy.close()
