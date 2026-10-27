"""The actual author/review/deploy/application journey, not hand-built schema states."""

import asyncio
import json
import shutil
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, Literal

from snektest import Param, assert_eq, load_fixture, test

from tests.experimental.test_migration_targets import provide_package_server

_FIXTURES = Path(__file__).parent / "fixtures" / "account-role-workflow"


async def _python(script: Path, payload: dict[str, Any] | None = None) -> str:
    """Run a real consumer process without implicit imports from its parent."""
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
    try:
        stdout, stderr = await process.communicate(json.dumps(payload or {}).encode())
    finally:
        if process.returncode is None:
            process.kill()
            await process.wait()
    assert_eq(process.returncode, 0, msg=stderr.decode())
    return stdout.decode()


async def _typecheck(root: Path, author: Path) -> tuple[int, str]:
    """Check real generated/imported sources, not a runtime-only exec namespace."""
    process = await asyncio.create_subprocess_exec(
        "ty",
        "check",
        "--extra-search-path",
        str(author),
        str(root),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    try:
        stdout, _ = await process.communicate()
    finally:
        if process.returncode is None:
            process.kill()
            await process.wait()
    assert process.returncode is not None
    return process.returncode, stdout.decode()


@test(
    [
        Param[Literal["sqlite", "mariadb"]](value=b, name=b)
        for b in ("sqlite", "mariadb")
    ],
    mark="slow",
)
async def generated_role_migration_is_reviewed_deployed_and_used_by_current_application(
    backend: Literal["sqlite", "mariadb"],
) -> None:
    """Generated states/contracts travel to an authoring-free deployment and typed app."""
    server = (
        await load_fixture(provide_package_server()) if backend == "mariadb" else None
    )
    with TemporaryDirectory() as directory:
        root = Path(directory)
        author = root / "author"
        deploy = root / "deploy"
        author.mkdir()
        deploy.mkdir()
        config = (
            {"database": str(root / "app.db")}
            if server is None
            else {
                "database": server.config().database,
                "host": server.config().host,
                "port": server.config().port,
                "user": server.config().user,
                "password": server.config().password,
                "unix_socket": str(server.config().unix_socket),
                "charset": server.config().charset,
            }
        )
        for source in _FIXTURES.glob("*.py.in"):
            text = (
                source.read_text()
                .replace("BACKEND", backend)
                .replace("NATIVE", repr(backend == "mariadb"))
                .replace(
                    "CONFIG",
                    'db.Config(database=Path(payload["config"]["database"]))'
                    if backend == "sqlite"
                    else 'db.Config(**payload["config"])',
                )
            )
            destination = (
                deploy if source.name in {"runtime.py.in", "app.py.in"} else author
            )
            (destination / source.name.removesuffix(".in")).write_text(text)
        await _python(author / "stage.py")
        review = json.loads(await _python(author / "review.py"))
        assert_eq((review["target"], review["stale"]), (["accounts"], False))
        # Edit ordinary author-owned Python, not the frozen package or schema states.
        shutil.copyfile(author / "backfill_revised.py", author / "backfill.py")
        revised = json.loads(await _python(author / "review.py"))
        assert_eq(revised["stale"], True)
        assert "recompile" in revised["diagnostic"]
        assert revised["digest"] != review["digest"]
        unchanged = json.loads(await _python(author / "review.py"))
        assert_eq(unchanged["stale"], False)
        assert_eq(unchanged["digest"], revised["digest"])
        code, diagnostics = await _typecheck(root, author)
        assert_eq(code, 0, msg=diagnostics)
        backfill = author / "backfill.py"
        valid = backfill.read_text()
        backfill.write_text(
            valid.replace('Accounts.role.to("admin")', "Accounts.role.to(42)")
        )
        code, diagnostics = await _typecheck(root, author)
        assert code != 0
        assert "Accounts.role.to(42)" in diagnostics, diagnostics
        backfill.write_text(valid)
        for name in ("001_accounts.json", "002_roles.json"):
            assert_eq(
                (author / name).read_text(), (_FIXTURES / backend / name).read_text()
            )
            shutil.copyfile(_FIXTURES / backend / name, deploy / name)
        shutil.rmtree(author)  # Deployment cannot import authoring models or contracts.
        initial = json.loads(
            await _python(
                deploy / "runtime.py",
                {"action": "apply", "config": config, "package": "001_accounts.json"},
            )
        )
        assert_eq(initial["outcome"], "applied")
        await _python(deploy / "runtime.py", {"action": "seed", "config": config})
        final = json.loads(
            await _python(
                deploy / "runtime.py",
                {"action": "apply", "config": config, "package": "002_roles.json"},
            )
        )
        assert_eq(final["digest"], revised["digest"])
        assert_eq(final["lazy_imports"], sys.get_lazy_imports())
        assert_eq(final["outcome"], "applied")
        statements = final["statements"]
        assert "ADD COLUMN" in statements[0]
        updates = [i for i, sql in enumerate(statements) if sql.startswith("UPDATE ")]
        assert len(updates) == 2 and 0 < updates[0] < updates[1] < len(statements) - 1
        assert_eq(final["again"], "already_applied")
        assert_eq(final["required"], [["accounts", "role"]])
        assert_eq(
            sorted(p[:2] for p in final["progress"]),
            [["001_accounts", "complete"], ["002_roles", "complete"]],
        )
        assert_eq(
            json.loads(await _python(deploy / "app.py", {"config": config})),
            {"before": [[1, "admin"], [2, "user"]], "created": [3, "user"]},
        )
