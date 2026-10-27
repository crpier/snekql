"""Real process death and competing operators on the model-derived role journey."""

import asyncio
import json
import os
import shutil
import signal
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, Literal

import aiomysql
import aiosqlite
from snektest import assert_eq, assert_raises, test

from snekql import mariadb
from snekql.experimental import migrations as m
from snekql.testing.mariadb import temporary_mariadb_server
from tests.experimental.test_migration_authoring_journey import _python, _typecheck

_FIXTURES = Path(__file__).parent / "fixtures" / "role-interruption"


async def _render(root: Path, backend: Literal["sqlite", "mariadb"]) -> Path:
    """Run visible author programs, then remove all authoring sources from deployment."""
    author = root / "author"
    deploy = root / "deploy"
    author.mkdir()
    deploy.mkdir()
    for source in _FIXTURES.glob("*.py.in"):
        text = (
            source.read_text()
            .replace("BACKEND", backend)
            .replace("NATIVE", repr(backend == "mariadb"))
            .replace(
                "CONFIG",
                'db.Config(database=Path(payload["database"]),acquire_timeout=30)'
                if backend == "sqlite"
                else 'db.Config(**payload["config"])',
            )
        )
        target = (
            deploy
            if source.stem in ("worker.py", "writer.py", "app.py", "lock_probe.py")
            else author
        )
        (target / source.name.removesuffix(".in")).write_text(text)
    await _python(author / "stage.py")
    await _python(author / "review.py")
    code, diagnostics = await _typecheck(root, author)
    assert_eq(code, 0, msg=diagnostics)
    for source in author.glob("*.json"):
        committed = _FIXTURES / backend / source.name
        assert_eq(source.read_text(), committed.read_text())
        shutil.copyfile(committed, deploy / source.name)
    shutil.rmtree(author)
    return deploy


async def _start(script: Path, payload: dict[str, Any]) -> asyncio.subprocess.Process:
    """Synchronize BEFORE public execution; no callbacks or hooks inside migration work."""
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        *(["-X", "lazy_imports=all"] if sys.get_lazy_imports() == "all" else []),
        "-B",
        str(script),
        cwd=script.parent,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    assert process.stdin is not None and process.stdout is not None
    process.stdin.write(json.dumps(payload).encode() + b"\n")
    await process.stdin.drain()
    try:
        async with asyncio.timeout(15):
            line = await process.stdout.readline()
        if not line:
            _, error = await process.communicate()
            assert line, error.decode()
        assert_eq(
            json.loads(line), {"ready": True, "lazy_imports": sys.get_lazy_imports()}
        )
    except BaseException:
        if process.returncode is None:
            process.kill()
            await process.wait()
        raise
    return process


def _go(process: asyncio.subprocess.Process) -> None:
    """Release a caller-owned pre-apply rendezvous, not a migration-step seam."""
    assert process.stdin is not None
    process.stdin.write(b"go\n")


async def _finish(process: asyncio.subprocess.Process) -> dict[str, Any]:
    """Collect a real process result and avoid leaving a blocked worker on failure."""
    try:
        async with asyncio.timeout(20):
            out, error = await process.communicate()
        assert_eq(process.returncode, 0, msg=error.decode())
        return json.loads(out)
    finally:
        if process.returncode is None:
            process.kill()
            await process.wait()


async def _apply(deploy: Path, payload: dict[str, Any], package: str) -> dict[str, Any]:
    """Use the same standalone deployment program for initial and terminal applications."""
    process = await _start(
        deploy / "worker.py", payload | {"mode": "apply", "package": package}
    )
    _go(process)
    return await _finish(process)


async def _race(
    deploy: Path, payload: dict[str, Any], *, mode: Literal["retry", "resume"]
) -> list[dict[str, Any]]:
    """Two operators assess BEFORE either resumes; clean up partial startup failures."""
    workers = []
    try:
        while len(workers) < 2:
            workers.append(
                await _start(
                    deploy / "worker.py",
                    payload | {"mode": mode, "package": "003_roles.json"},
                )
            )
        for worker in workers:
            _go(worker)
        return list(await asyncio.gather(*(_finish(worker) for worker in workers)))
    finally:
        for worker in workers:
            if worker.returncode is None:
                worker.kill()
                await worker.wait()


@test(mark="slow")
async def sqlite_role_process_death_rolls_back_and_competing_retries_converge() -> None:
    """Kill the actual active writer behind a real reader, not a fake production error."""
    with TemporaryDirectory() as directory:
        root = Path(directory)
        deploy = await _render(root, "sqlite")
        payload = {"database": str(root / "app.db")}
        async with aiosqlite.connect(payload["database"]) as setup:
            await setup.execute("CREATE TABLE audit_log(id INTEGER PRIMARY KEY) STRICT")
            await setup.commit()
        await _apply(deploy, payload, "001_accounts.json")
        async with aiosqlite.connect(payload["database"]) as setup:
            await setup.execute("INSERT INTO accounts VALUES(1,1),(2,0)")
            await setup.commit()
        await _apply(deploy, payload, "002_expand.json")
        async with aiosqlite.connect(payload["database"]) as reader:
            await reader.execute("BEGIN")
            await reader.execute("SELECT * FROM accounts")
            process = await _start(
                deploy / "worker.py",
                payload | {"mode": "apply", "package": "003_roles.json", "save": True},
            )
            try:
                _go(process)
                async with asyncio.timeout(10):
                    while True:
                        if json.loads(await _python(deploy / "lock_probe.py", payload))[
                            "busy"
                        ]:
                            break
                        assert process.returncode is None
                        await asyncio.sleep(0.01)
                assert await asyncio.to_thread(
                    Path(payload["database"] + "-journal").exists
                )
                process.kill()
                await process.wait()
                assert_eq(process.returncode, -9)
            finally:
                if process.returncode is None:
                    process.kill()
                    await process.wait()
                await reader.rollback()
        async with aiosqlite.connect(payload["database"]) as observed:
            assert_eq(
                await observed.execute_fetchall(
                    "SELECT id,is_admin,role FROM accounts ORDER BY id"
                ),
                [(1, 1, None), (2, 0, None)],
            )
            assert_eq(
                await observed.execute_fetchall(
                    "SELECT revision,phase FROM snekql_experimental_migrations ORDER BY revision"
                ),
                [("001_accounts", "complete"), ("002_expand", "complete")],
            )
        results = await _race(deploy, payload, mode="retry")
        assert_eq(sorted(r["outcome"] for r in results), ["already_applied", "applied"])
        assert all(
            [(p[0], p[1]) for p in r["status"]]
            == [
                ("001_accounts", "complete"),
                ("002_expand", "complete"),
                ("003_roles", "complete"),
            ]
            for r in results
        )
        assert_eq(
            json.loads(await _python(deploy / "app.py", payload)),
            {"before": [[1, "admin"], [2, "user"]], "created": [3, "user"]},
        )


def _payload(config: mariadb.Config) -> dict[str, Any]:
    """Transfer this privately owned server's public connection configuration only."""
    return {
        "config": {
            "database": config.database,
            "host": config.host,
            "port": config.port,
            "user": config.user,
            "password": config.password,
            "unix_socket": str(config.unix_socket),
            "charset": config.charset,
        }
    }


async def _waiting_update(config: mariadb.Config) -> dict[str, Any]:
    """Observe an actual partially performed UPDATE waiting on an InnoDB row lock."""
    async with await mariadb.Database.initialize(config) as app:
        async with asyncio.timeout(15):
            while True:
                async with app.transaction() as tx:
                    rows = await tx.fetch_all(
                        mariadb.raw(
                            "SELECT trx_mysql_thread_id AS id,trx_rows_modified AS modified FROM information_schema.INNODB_TRX WHERE trx_state='LOCK WAIT' AND trx_query LIKE 'UPDATE%accounts%'"
                        )
                    )
                if rows:
                    assert (
                        isinstance(rows[0]["modified"], int)
                        and rows[0]["modified"] >= 1
                    )
                    return rows[0]
                await asyncio.sleep(0.15)


async def _wait_disconnected(config: mariadb.Config, connection_id: int) -> None:
    """Disconnect must have reached the engine before inspecting rolled-back data."""
    async with await mariadb.Database.initialize(config) as app:
        async with asyncio.timeout(15):
            while True:
                async with app.transaction() as tx:
                    rows = await tx.fetch_all(
                        mariadb.raw(
                            "SELECT ID FROM information_schema.PROCESSLIST WHERE ID=%s",
                            params=(connection_id,),
                        )
                    )
                if not rows:
                    return
                await asyncio.sleep(0.15)


async def _stop(process: asyncio.subprocess.Process | None) -> None:
    """Dispose only an owned child when setup or engine observation fails."""
    if process is not None and process.returncode is None:
        process.kill()
        await process.wait()


async def _kill_native_backfill(deploy: Path, config: mariadb.Config) -> dict[str, Any]:
    """Hold a real row lock, let UPDATE change an earlier row, then kill only our client."""
    payload = _payload(config)
    blocker = await aiomysql.connect(
        host=config.host,
        port=config.port,
        user=config.user,
        password=config.password,
        db=config.database,
        unix_socket=str(config.unix_socket),
        autocommit=False,
    )
    process = None
    try:
        async with blocker.cursor() as cursor:
            await cursor.execute("SELECT id FROM accounts WHERE id=2 FOR UPDATE")
        process = await _start(
            deploy / "worker.py",
            payload | {"mode": "apply", "package": "003_roles.json", "save": True},
        )
        _go(process)
        observed = await _waiting_update(config)
        assert_eq(
            json.loads(await _python(deploy / "writer.py", payload)), {"written": 42}
        )
        assert_eq((await _waiting_update(config))["id"], observed["id"])
        process.kill()
        await process.wait()
        assert_eq(process.returncode, -signal.SIGKILL)
    finally:
        await _stop(process)
        await blocker.rollback()
        blocker.close()
    await _wait_disconnected(config, observed["id"])
    async with (
        await mariadb.Database.initialize(config) as app,
        app.transaction() as tx,
    ):
        assert_eq(
            await tx.fetch_all(
                mariadb.raw("SELECT id,is_admin,role FROM accounts ORDER BY id")
            ),
            [
                {"id": 1, "is_admin": 1, "role": None},
                {"id": 2, "is_admin": 0, "role": None},
            ],
        )
        assert_eq(
            await tx.fetch_all(mariadb.raw("SELECT id FROM audit_log")), [{"id": 42}]
        )
    async with m.connect(config) as target:
        progress = next(p for p in await target.status() if p.revision == "003_roles")
        assert_eq((progress.phase, progress.acknowledged_steps), ("uncertain", 0))
    return observed


@test(mark="slow")
async def native_role_restart_requires_recovery_and_competing_resumers_reassess() -> (
    None
):
    """Committed expansion survives; partial DML rolls back; durable uncertainty is not replayed."""
    with TemporaryDirectory() as directory:
        root = Path(directory)
        deploy = await _render(root, "mariadb")
        data = root / "data"
        socket = root / "server.sock"
        async with temporary_mariadb_server(
            data_directory=data, socket_path=socket
        ) as server:
            config = server.config()
            payload = _payload(config)
            await server.run_sql(
                "CREATE TABLE audit_log(id BIGINT PRIMARY KEY) ENGINE=InnoDB"
            )
            await _apply(deploy, payload, "001_accounts.json")
            await server.run_sql("INSERT INTO accounts VALUES(1,1),(2,0)")
            await _apply(deploy, payload, "002_expand.json")
            await _kill_native_backfill(deploy, config)
            original = await asyncio.to_thread(
                (deploy / "original-plan.json").read_bytes
            )
            os.kill(
                int(await asyncio.to_thread(server.pid_path.read_text)), signal.SIGKILL
            )
        async with temporary_mariadb_server(
            data_directory=data, socket_path=socket
        ) as restarted:
            config = restarted.config()
            payload = _payload(config)
            saved = m.Prepared.load(original.decode())
            assert_eq(saved.execution_epoch, 1)
            assert_eq(saved.dump().encode(), original)
            async with m.connect(config) as target:
                before = await target.status()
                changed = saved.model_copy(update={"preserve_unmanaged": True})
                with assert_raises(m.PackageError) as error:
                    await target.inspect_recovery(
                        m.Prepared.load(changed.dump()), schema_writers_excluded=True
                    )
                assert "original reviewed prepared plan" in str(error.exception)
                assert_eq(await target.status(), before)
            async with (
                await mariadb.Database.initialize(config) as app,
                app.transaction() as tx,
            ):
                assert_eq(
                    await tx.fetch_all(mariadb.raw("SELECT id FROM audit_log")),
                    [{"id": 42}],
                )
            results = await _race(deploy, payload, mode="resume")
            assert_eq(sorted(r["outcome"] for r in results), ["applied", "refused"])
            assert all(
                [(p[0], p[1]) for p in r["status"]]
                == [
                    ("001_accounts", "complete"),
                    ("002_expand", "complete"),
                    ("003_roles", "complete"),
                ]
                for r in results
            )
            assert "no unique incomplete execution" in next(
                r["refusal"] for r in results if r["outcome"] == "refused"
            )
            assert_eq(
                await asyncio.to_thread((deploy / "original-plan.json").read_bytes),
                original,
            )
            assert_eq(
                (await _apply(deploy, payload, "003_roles.json"))["outcome"],
                "already_applied",
            )
            assert_eq(
                json.loads(await _python(deploy / "app.py", payload)),
                {"before": [[1, "admin"], [2, "user"]], "created": [3, "user"]},
            )
