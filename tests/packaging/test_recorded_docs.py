"""Run the bundled recorded-state recipe as an installed-package consumer."""

import asyncio
import hashlib
import json
import os
import platform
import sys
from collections.abc import AsyncGenerator
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, Literal
from zipfile import ZipFile

from snektest import Param, assert_eq, assert_in, fixture, load_fixture, test

from snekql.testing.mariadb import TemporaryMariaDBServer
from tests.experimental.test_migration_targets import provide_package_server
from tests.packaging.test_bundled_docs import _run, release_artifacts

_RECIPES = (
    "recorded_role_stage.py",
    "recorded_role_author.py",
    "recorded_plan_store.py",
    "recorded_application.py",
)


@fixture(scope="session")
async def installed_recorded_wheel() -> AsyncGenerator[Path]:
    """Install the candidate with exact locked runtime dependencies, offline."""
    artifacts = await load_fixture(release_artifacts())
    with TemporaryDirectory() as directory:
        root = Path(directory)
        environment = root / ".venv"
        python = environment / (
            "Scripts/python.exe" if sys.platform == "win32" else "bin/python"
        )
        export = await asyncio.to_thread(
            _run,
            [
                "uv",
                "export",
                "--frozen",
                "--no-dev",
                "--extra",
                "aiosqlite",
                "--extra",
                "aiomysql",
                "--no-emit-project",
                "--no-hashes",
            ],
            cwd=Path(__file__).parents[2],
        )
        assert_eq(export.returncode, 0, msg=export.stderr)
        requirements = root / "requirements.txt"
        await asyncio.to_thread(
            requirements.write_text, export.stdout, encoding="utf-8"
        )
        for command in (
            ["uv", "venv", "--python", sys.executable, str(environment)],
            [
                "uv",
                "pip",
                "install",
                "--offline",
                "--python",
                str(python),
                "-r",
                str(requirements),
                str(next(artifacts.glob("*.whl"))),
            ],
        ):
            result = await asyncio.to_thread(_run, command, cwd=root)
            assert_eq(result.returncode, 0, msg=result.stderr)
        yield python


async def _consumer(python: Path, root: Path, source: str) -> str:
    """Expose only the copied consumer workspace, never the source checkout."""
    mode = sys.get_lazy_imports()
    prefix = f"""
import sys
from pathlib import Path
assert sys.get_lazy_imports() == {mode!r}
sys.path.insert(0, str(Path.cwd()))
import snekql
assert Path(snekql.__file__).is_relative_to(Path(sys.prefix)), snekql.__file__
"""
    result = await asyncio.to_thread(
        _run,
        [
            str(python),
            *(["-X", "lazy_imports=all"] if mode == "all" else []),
            "-I",
            "-B",
            "-c",
            prefix + source,
        ],
        cwd=root,
    )
    assert_eq(result.returncode, 0, msg=result.stderr + result.stdout)
    return result.stdout


async def _record_environment(
    backend: Literal["sqlite", "mariadb"],
    server: TemporaryMariaDBServer | None,
    environment: dict[str, Any],
) -> None:
    """Retain optional actual interpreter/library/server provenance, never a selector."""
    expected = os.environ.get("SNEKQL_TEST_EXPECT_MARIADB")
    if server is not None and expected:
        assert environment["version"].startswith(expected + "-")
    report = os.environ.get("SNEKQL_TEST_ENVIRONMENT_REPORT")
    if report:

        def write() -> None:
            record = environment | {
                "backend": backend,
                "mode": sys.get_lazy_imports(),
                "platform": platform.platform(),
            }
            if server is not None:
                pid = int(server.pid_path.read_text())
                executable = Path(f"/proc/{pid}/exe").readlink()
                record |= {
                    "pid": pid,
                    "executable": str(executable),
                    "sha256": hashlib.sha256(executable.read_bytes()).hexdigest(),
                }
            Path(report).write_text(
                json.dumps(record, indent=2) + "\n", encoding="utf-8"
            )

        await asyncio.to_thread(write)


@test(
    [
        Param[Literal["sqlite", "mariadb"]](value=b, name=b)
        for b in ("sqlite", "mariadb")
    ],
    mark="slow",
)
async def installed_recorded_recipe_authors_freezes_deploys_and_reads(
    backend: Literal["sqlite", "mariadb"],
) -> None:
    """Actual copied sources type-check, survive author deletion, and preserve originals."""
    artifacts = await load_fixture(release_artifacts())
    python = await load_fixture(installed_recorded_wheel())
    server = (
        await load_fixture(provide_package_server()) if backend == "mariadb" else None
    )
    with TemporaryDirectory() as directory:
        root = Path(directory)

        def copy_resources() -> None:
            with ZipFile(next(artifacts.glob("*.whl"))) as archive:
                for name in _RECIPES:
                    assert_in(f"snekql/docs/examples/{name}", archive.namelist())
            (root / "evidence").mkdir(mode=0o700)

        await asyncio.to_thread(copy_resources)
        await _consumer(
            python,
            root,
            """
from importlib.resources import files
recipes = files("snekql").joinpath("docs", "examples")
destination = Path("examples")
destination.mkdir()
for source in recipes.iterdir():
    if source.name.startswith("recorded_") and source.name.endswith(".py"):
        destination.joinpath(source.name).write_bytes(source.read_bytes())
destination.joinpath("__init__.py").touch()
import runpy
runpy.run_module("examples.recorded_role_stage", run_name="__main__")
runpy.run_module("examples.recorded_role_author", run_name="__main__")
sys.argv = ["recorded_role_author", "--check"]
runpy.run_module("examples.recorded_role_author", run_name="__main__")
""",
        )
        check = await asyncio.to_thread(
            _run,
            [
                "ty",
                "check",
                "--python",
                str(python),
                "--error",
                "all",
                "--extra-search-path",
                str(root),
                str(root / "examples"),
            ],
            cwd=root,
        )
        assert_eq(check.returncode, 0, msg=check.stdout + check.stderr)
        author = root / "examples" / "recorded_role_author.py"
        valid = await asyncio.to_thread(author.read_text, encoding="utf-8")
        await asyncio.to_thread(
            author.write_text,
            valid.replace('accounts.role.to("admin")', "accounts.role.to(42)"),
            encoding="utf-8",
        )
        wrong_type = await asyncio.to_thread(
            _run,
            [
                "ty",
                "check",
                "--python",
                str(python),
                "--error",
                "all",
                "--extra-search-path",
                str(root),
                str(root / "examples"),
            ],
            cwd=root,
        )
        assert wrong_type.returncode != 0, wrong_type.stdout + wrong_type.stderr
        assert_in("accounts.role.to(42)", wrong_type.stdout + wrong_type.stderr)
        await asyncio.to_thread(author.write_text, valid, encoding="utf-8")
        freshness = json.loads(
            await _consumer(
                python,
                root,
                """
import json
import runpy
from examples.recorded_role_author import sqlite_route, mariadb_route
from snekql.experimental import migrations as m
routes = {"sqlite": sqlite_route(), "mariadb": mariadb_route()}
for name, route in routes.items():
    package = m.Package.load(Path(f"002_{name}_roles.json").read_text())
    package.check(route)
try:
    source = Path("examples/recorded_role_author.py")
    frozen = {p: p.read_bytes() for p in Path.cwd().glob("00*.json")}
    text = source.read_text()
    source.write_text(text.replace('accounts.role.to("admin")', 'accounts.role.to("administrator")'))
    sys.argv = ["recorded_role_author", "--check"]
    runpy.run_module("examples.recorded_role_author", run_name="__main__")
except m.PackageError as error:
    assert "stale" in str(error)
    print(json.dumps({"stale_refused": True}))
else:
    raise AssertionError("edited typed intent must make the frozen package stale")
finally:
    source.write_text(text)
    assert all(path.read_bytes() == data for path, data in frozen.items())
""",
            )
        )
        assert_eq(freshness, {"stale_refused": True})
        config = (
            {"database": str(root / "app.db")}
            if server is None
            else {
                "database": server.config().database,
                "user": server.config().user,
                "password": server.config().password,
                "unix_socket": str(server.config().unix_socket),
            }
        )
        config_source = (
            f"db.Config(database=Path({config['database']!r}))"
            if backend == "sqlite"
            else f"db.Config(**{config!r})"
        )
        deployment = f"""
import asyncio
import json
from snekql import {backend} as db
from snekql.experimental import migrations as m
from examples.recorded_plan_store import load_original, save_original
config = {config_source}
async def deploy():
    package = m.Package.load(Path({("001_" + backend + "_accounts.json")!r}).read_text())
    lifetime = m.connect(config)
    async with lifetime as target:
        original = await target.prepare(package, schema_writers_excluded=True)
        path = Path("evidence/001.json")
        await save_original(path, original)
        assert path.stat().st_mode & 0o777 == 0o600
        assert await target.apply(await load_original(path)) == "applied"
    await lifetime.wait_closed()
    from examples.recorded_role_stage import {("SQLiteInitial" if backend == "sqlite" else "MariaDBInitial")} as Initial
    async with await db.Database.initialize(config) as app, app.transaction() as tx:
        await tx.execute(db.insert_many(Initial, [Initial(id=1, is_admin=True), Initial(id=2, is_admin=False)]))
asyncio.run(deploy())
"""
        await _consumer(python, root, deployment)
        # Remove authoring inputs; current application imports happen only after deployment.
        await asyncio.to_thread(
            lambda: [
                p.unlink()
                for p in (root / "examples").glob("*.py")
                if p.name
                not in {
                    "__init__.py",
                    "recorded_plan_store.py",
                    "recorded_application.py",
                }
            ]
        )
        result = json.loads(
            await _consumer(
                python,
                root,
                f"""
import asyncio
import json
from snekql import {backend} as db
from snekql.experimental import migrations as m
from examples.recorded_plan_store import load_original, save_original
config = {config_source}
async def earlier_receipt():
    async with await db.Database.initialize(config) as app, app.transaction() as tx:
        return await tx.fetch_all(db.raw("SELECT * FROM snekql_experimental_migrations WHERE revision='001_accounts'"))
async def deploy():
    earlier = await earlier_receipt()
    earlier_original = Path("evidence/001.json").read_bytes()
    package = m.Package.load(Path({("002_" + backend + "_roles.json")!r}).read_text())
    lifetime = m.connect(config)
    async with lifetime as target:
        before = await target.status()
        original = await target.prepare(package, schema_writers_excluded=True)
        assert await target.status() == before
        path = Path("evidence/002.json")
        await save_original(path, original)
        saved = path.read_bytes()
        try:
            await save_original(path, original)
        except FileExistsError:
            pass
        else:
            raise AssertionError("original evidence was replaced")
        assert path.read_bytes() == saved
        assert path.stat().st_mode & 0o777 == 0o600
        original = await load_original(path)
        assert await target.apply(original) == "applied"
        assert await target.apply(original) == "already_applied"
        progress = await target.status()
        assert all(p.phase == "complete" for p in progress)
        assert {{p.digest for p in before}} <= {{p.digest for p in progress}}
    await lifetime.wait_closed()
    assert await earlier_receipt() == earlier
    assert Path("evidence/001.json").read_bytes() == earlier_original
    assert not any(name.startswith(("examples.recorded_role_", "examples.recorded_sqlite_contract", "examples.recorded_mariadb_contract", "examples.recorded_application")) for name in sys.modules)
    from examples.recorded_application import {("use_sqlite" if backend == "sqlite" else "use_mariadb")}
    rows = await {("use_sqlite" if backend == "sqlite" else "use_mariadb")}(config)
    async with await db.Database.initialize(config) as app, app.transaction() as tx:
        version = await tx.fetch_one(db.raw({("SELECT sqlite_version() AS version" if backend == "sqlite" else "SELECT VERSION() AS version")!r}))
    from importlib.metadata import version as package_version
    print(json.dumps({{
        "rows": rows, "mode": sys.get_lazy_imports(),
        "environment": {{
            "version": version["version"], "python": sys.version,
            "interpreter": sys.executable, "library": snekql.__file__,
            "packages": {{name: package_version(name) for name in ("snekql", "pydantic", "anyio", "aiosqlite", "aiomysql", "PyMySQL")}},
            "originals": {{p.name: __import__("hashlib").sha256(p.read_bytes()).hexdigest() for p in Path("evidence").glob("*.json")}},
        }},
    }}))
asyncio.run(deploy())
""",
            )
        )
        environment = result.pop("environment")
        await _record_environment(backend, server, environment)
        assert_eq(
            result,
            {
                "rows": [[1, "admin"], [2, "user"], [3, "user"]],
                "mode": sys.get_lazy_imports(),
            },
        )
