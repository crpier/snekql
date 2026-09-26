"""Inspect and smoke-test built snekql artifacts in an isolated environment."""

from __future__ import annotations

import asyncio
import subprocess
import sys
import tomllib
from argparse import ArgumentParser
from pathlib import Path
from tempfile import TemporaryDirectory


def _run(*command: str, cwd: Path) -> None:
    result = subprocess.run(  # noqa: S603
        command, cwd=cwd, check=False, text=True
    )
    if result.returncode != 0:
        raise SystemExit(result.returncode)


def _check_artifacts(*, mariadb: bool) -> None:
    """Install the sole wheel and exercise imports, CLI, runtime, and typing."""

    project_root = Path(__file__).parents[1]
    dist_directory = project_root / "dist"
    wheels = tuple(dist_directory.glob("*.whl"))
    sdists = tuple(dist_directory.glob("*.tar.gz"))
    if len(wheels) != 1 or len(sdists) != 1:
        msg = "dist must contain exactly one wheel and one source distribution"
        raise SystemExit(msg)
    metadata = tomllib.loads((project_root / "pyproject.toml").read_text())
    expected_version = metadata["project"]["version"]
    type_checker_requirement = next(
        requirement
        for requirement in metadata["dependency-groups"]["dev"]
        if requirement.startswith("ty==")
    )

    with TemporaryDirectory() as directory_name:
        directory = Path(directory_name)
        environment = directory / ".venv"
        _run("uv", "venv", "--python", sys.executable, str(environment), cwd=directory)
        python = environment / "bin" / "python"
        ty = environment / "bin" / "ty"
        _run(
            "uv",
            "pip",
            "install",
            "--python",
            str(python),
            f"{wheels[0]}[aiosqlite,aiomysql]"
            if mariadb
            else f"{wheels[0]}[aiosqlite]",
            type_checker_requirement,
            cwd=directory,
        )
        runtime_smoke = directory / "runtime_smoke.py"
        runtime_smoke.write_text(
            f"""from importlib.metadata import version
import asyncio
from pathlib import Path
import snekql
from snekql import mariadb, sqlite

if not Path(snekql.__file__).is_relative_to({str(environment)!r}):
    raise RuntimeError("artifact imported outside isolated environment")
if {mariadb!r}:
    print("aiomysql", version("aiomysql"), "PyMySQL", version("PyMySQL"))
if version("snekql") != {expected_version!r}:
    raise RuntimeError("installed version mismatch")
if sqlite.Config(database=":memory:").backend_family != "sqlite":
    raise RuntimeError("SQLite namespace unavailable")
if mariadb.Config(database="app", user="snekql").backend_family != "mariadb":
    raise RuntimeError("MariaDB namespace unavailable")

async def main() -> None:
    database = await sqlite.Database.initialize(sqlite.Config(database=":memory:"))
    await database.close()

asyncio.run(main())
"""
        )
        typing_smoke = directory / "typing_smoke.py"
        typing_smoke.write_text(
            """from typing import ClassVar
from snekql import sqlite

class User[S = sqlite.Pending](sqlite.Model[S]):
    __row_type__: ClassVar[sqlite.ReadType[User[sqlite.Row]]]
    id: User.Col[int] = sqlite.Integer(primary_key=True)

query: sqlite.ClosedRead[User[sqlite.Row]] = sqlite.ready(sqlite.select(User))
"""
        )
        _run(str(python), "-I", str(runtime_smoke), cwd=directory)
        _run(str(python), "-m", "snekql", "--help", cwd=directory)
        _run(str(ty), "check", str(typing_smoke), cwd=directory)
        if mariadb:
            _run(
                "uv",
                "pip",
                "install",
                "--python",
                str(python),
                next(
                    requirement
                    for requirement in metadata["dependency-groups"]["dev"]
                    if requirement.startswith("snektest")
                ),
                cwd=directory,
            )
            native_tests = directory / "test_installed_driver.py"
            native_tests.write_text(
                (project_root / "tests/mariadb/test_installed_driver.py").read_text()
            )
            _run(
                str(python),
                "-I",
                "-X",
                "context_aware_warnings=1",
                "-m",
                "snektest",
                native_tests.name,
                cwd=directory,
            )


def main() -> None:
    """Optionally test fresh MariaDB extras against locally installed binaries."""
    parser = ArgumentParser(description=__doc__)
    parser.add_argument(
        "--mariadb",
        action="store_true",
        help="exercise fresh MariaDB extras against a temporary native server",
    )
    arguments = parser.parse_args()
    asyncio.run(asyncio.to_thread(_check_artifacts, mariadb=arguments.mariadb))


if __name__ == "__main__":
    main()
