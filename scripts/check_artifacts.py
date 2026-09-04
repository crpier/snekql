"""Inspect and smoke-test built snekql artifacts in an isolated environment."""

from __future__ import annotations

import subprocess
import sys
import tomllib
from pathlib import Path
from tempfile import TemporaryDirectory


def _run(*command: str, cwd: Path) -> None:
    result = subprocess.run(  # noqa: S603
        command, cwd=cwd, check=False, text=True
    )
    if result.returncode != 0:
        raise SystemExit(result.returncode)


def main() -> None:
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
            f"{wheels[0]}[aiosqlite]",
            type_checker_requirement,
            cwd=directory,
        )
        runtime_smoke = directory / "runtime_smoke.py"
        runtime_smoke.write_text(
            f"""from importlib.metadata import version
import asyncio
from snekql import mariadb, sqlite

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
            """from snekql import sqlite

class User[S = sqlite.Pending](sqlite.Model[S, "User[sqlite.Fetched]"]):
    id: User.Col[int] = sqlite.Integer(primary_key=True)

query: sqlite.Select[User[sqlite.Fetched]] = sqlite.select(User).all()
"""
        )
        _run(str(python), str(runtime_smoke), cwd=directory)
        _run(str(python), "-m", "snekql", "--help", cwd=directory)
        _run(str(ty), "check", str(typing_smoke), cwd=directory)


if __name__ == "__main__":
    main()
