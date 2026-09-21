"""The searchable namespace index stays consistent with public exports."""

import os
import sys
from re import DOTALL, MULTILINE, findall

from anyio import Path, TemporaryDirectory, run_process
from snektest import Param, assert_eq, test

from snekql import mariadb, sqlite


@test(mark="medium")
async def namespace_reference_matches_public_exports() -> None:
    """Every public name has correct backend availability, with no stale names."""
    source = await (Path(__file__).parent.parent / "docs/api-reference.md").read_text()
    rows = findall(
        r"^\| `([A-Za-z_][A-Za-z_0-9]*)` \| (yes|no) \| (yes|no) \|$",
        source,
        flags=MULTILINE,
    )
    documented = {
        name: (sqlite_column == "yes", mariadb_column == "yes")
        for name, sqlite_column, mariadb_column in rows
    }
    expected = {
        name: (name in sqlite.__all__, name in mariadb.__all__)
        for name in set(sqlite.__all__) | set(mariadb.__all__)
    }

    assert_eq(len(rows), len(documented), msg="Duplicate reference entries")
    assert_eq(documented, expected)


@test([Param(0, name="deploy"), Param(1, name="application")], mark="slow")
async def published_service_python_runs_as_written(block: int) -> None:
    """Copying the documented Python into a separate directory remains runnable."""
    root = Path(__file__).parent.parent
    source = await (root / "docs/service-recipes.md").read_text()
    snippets = findall(r"```python\n(.*?)\n```", source, flags=DOTALL)
    assert_eq(len(snippets), 2, msg="Add a case when adding another Python recipe")

    async with TemporaryDirectory() as directory:
        completed = await run_process(
            [sys.executable, "-c", snippets[block]],
            cwd=directory,
            env={**os.environ, "PYTHONPATH": str(root)},
            check=False,
        )

    assert_eq(completed.returncode, 0, msg=completed.stderr.decode())
