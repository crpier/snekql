"""Deployment inspection through the installed command and real database factories."""

import sys
from collections.abc import AsyncGenerator
from dataclasses import dataclass
from json import loads
from pathlib import Path
from subprocess import CompletedProcess

from anyio import Path as AsyncPath
from anyio import TemporaryDirectory, run_process
from snektest import (
    Param,
    assert_eq,
    assert_in,
    assert_not_in,
    fixture,
    load_fixture,
    test,
)

from snekql import sqlite

_DECLARATION = {
    "001_entries": "CREATE TABLE entries (id INTEGER PRIMARY KEY)",
    "002_note": "ALTER TABLE entries ADD COLUMN note TEXT DEFAULT 'private_body_literal'",
}


@dataclass(frozen=True)
class Deployment:
    directory: str

    async def run(self, command: str, *options: str) -> CompletedProcess[bytes]:
        return await run_process(
            [
                sys.executable,
                "-m",
                "snekql",
                "migrations",
                command,
                "--database",
                "deployment:open_database",
                "--migrations",
                "deployment:MIGRATIONS",
                *options,
            ],
            cwd=self.directory,
            check=False,
        )


@fixture
async def provide_deployment() -> AsyncGenerator[Deployment]:
    async with TemporaryDirectory() as directory:
        async with await sqlite.Database.initialize(
            database=Path(directory) / "app.db"
        ) as database:
            await database.migrate({"001_entries": _DECLARATION["001_entries"]})
        await AsyncPath(directory, "deployment.py").write_text(f'''"""Trusted deployment configuration."""
from contextlib import asynccontextmanager
from pathlib import Path
from anyio import Path as AsyncPath
from snekql import sqlite

MIGRATIONS = {_DECLARATION!r}

@asynccontextmanager
async def open_database():
    try:
        async with await sqlite.Database.initialize(database=Path("app.db")) as database:
            yield database
    finally:
        await AsyncPath("closed").write_text("closed")
''')
        yield Deployment(directory)


@test(
    [Param(value="status", name="status"), Param(value="plan", name="plan")],
    mark="medium",
)
async def status_json_reports_the_current_prefix(command: str) -> None:
    """The CLI loads a trusted database context and emits the public status fields."""
    deployment = await load_fixture(provide_deployment())

    completed = await deployment.run(command, "--json")

    assert_eq(completed.returncode, 0)
    assert_eq(
        loads(completed.stdout),
        {
            "history_present": True,
            "applied": ["001_entries"],
            "pending": ["002_note"],
        },
    )


@test(mark="medium")
async def initialization_errors_do_not_print_configuration() -> None:
    """Native initialization diagnostics must not leak private configuration values."""
    deployment = await load_fixture(provide_deployment())
    module = AsyncPath(deployment.directory, "deployment.py")
    await module.write_text(
        await module.read_text()
        + """
@asynccontextmanager
async def open_database():
    async with await sqlite.Database.initialize(database="private_configuration_value") as database:
        yield database
"""
    )

    completed = await deployment.run("status", "--json")

    assert_eq(completed.returncode, 1)
    assert_eq(completed.stdout, b"")
    assert_not_in("private_configuration_value", completed.stderr.decode())
    assert_not_in("Traceback", completed.stderr.decode())


@test(
    [Param(value="status", name="status"), Param(value="plan", name="plan")],
    mark="medium",
)
async def text_output_hides_sql(command: str) -> None:
    """Ordinary CLI output contains migration names without disclosing SQL bodies."""
    deployment = await load_fixture(provide_deployment())

    completed = await deployment.run(command)

    assert_eq(completed.returncode, 0)
    assert_in("002_note", completed.stdout.decode())
    assert_not_in("private_body_literal", completed.stdout.decode())
    assert_not_in("ALTER TABLE", completed.stdout.decode())


@test(mark="medium")
async def plan_json_includes_only_pending_sql_when_requested() -> None:
    """Explicit SQL inspection never includes bodies already recorded as applied."""
    deployment = await load_fixture(provide_deployment())

    completed = await deployment.run("plan", "--json", "--sql")

    assert_eq(completed.returncode, 0)
    assert_eq(
        loads(completed.stdout)["sql"],
        {
            "002_note": "ALTER TABLE entries ADD COLUMN note TEXT DEFAULT 'private_body_literal'"
        },
    )


@test(mark="medium")
async def plan_text_can_show_pending_sql() -> None:
    """Operators explicitly request SQL rather than receiving it in normal output."""
    deployment = await load_fixture(provide_deployment())

    completed = await deployment.run("plan", "--sql")

    assert_eq(completed.returncode, 0)
    assert_in(
        "ALTER TABLE entries ADD COLUMN note TEXT DEFAULT 'private_body_literal'",
        completed.stdout.decode(),
    )
    assert_not_in("CREATE TABLE", completed.stdout.decode())


@test(mark="medium")
async def status_rejects_sql_output() -> None:
    """SQL disclosure is limited to the explicit plan command."""
    deployment = await load_fixture(provide_deployment())

    completed = await deployment.run("status", "--sql")

    assert_eq(completed.returncode, 2)
    assert_eq(completed.stdout, b"")
    assert_eq(await AsyncPath(deployment.directory, "closed").exists(), False)


@test(mark="medium")
async def inspection_closes_the_database_context() -> None:
    """Success is reported only after the factory's cleanup has completed."""
    deployment = await load_fixture(provide_deployment())

    completed = await deployment.run("status", "--json")

    assert_eq(completed.returncode, 0)
    assert_eq(await AsyncPath(deployment.directory, "closed").read_text(), "closed")


@test(mark="medium")
async def history_errors_close_the_database_context() -> None:
    """A divergent declaration produces failure, no partial JSON, and owned cleanup."""
    deployment = await load_fixture(provide_deployment())
    module = AsyncPath(deployment.directory, "deployment.py")
    await module.write_text(
        await module.read_text() + '\nMIGRATIONS["001_entries"] = "SELECT 1"\n'
    )

    completed = await deployment.run("plan", "--json")

    assert_eq(completed.returncode, 1)
    assert_eq(completed.stdout, b"")
    assert_eq(await AsyncPath(deployment.directory, "closed").read_text(), "closed")


@test(mark="medium")
async def cleanup_failure_prevents_success_output() -> None:
    """A factory exit error cannot leave a successful deployment report on stdout."""
    deployment = await load_fixture(provide_deployment())
    module = AsyncPath(deployment.directory, "deployment.py")
    await module.write_text(
        await module.read_text()
        + """
original_factory = open_database
@asynccontextmanager
async def open_database():
    async with original_factory() as database:
        yield database
    raise RuntimeError("private_cleanup_value")
"""
    )

    completed = await deployment.run("plan", "--json")

    assert_eq(completed.returncode, 1)
    assert_eq(completed.stdout, b"")
    assert_not_in("private_cleanup_value", completed.stderr.decode())


@test(mark="medium")
async def invalid_declaration_does_not_enter_the_factory() -> None:
    """Basic declaration validation happens before opening application connectivity."""
    deployment = await load_fixture(provide_deployment())
    module = AsyncPath(deployment.directory, "deployment.py")
    await module.write_text(await module.read_text() + "\nMIGRATIONS = []\n")

    completed = await deployment.run("status", "--json")

    assert_eq(completed.returncode, 1)
    assert_eq(await AsyncPath(deployment.directory, "closed").exists(), False)


@test(
    [
        Param(value="open_database = 42", name="not-callable"),
        Param(value="def open_database(): return 42", name="not-context-manager"),
        Param(value="async def open_database(): return 42", name="coroutine-factory"),
        Param(
            value="@asynccontextmanager\nasync def open_database(): yield 42",
            name="not-database",
        ),
        Param(
            value="@asynccontextmanager\nasync def open_database():\n    raise RuntimeError('private_factory_value')\n    yield",
            name="factory-error",
        ),
    ],
    mark="medium",
)
async def invalid_factory_is_a_redacted_command_failure(source: str) -> None:
    """Bad Python exports produce no successful report or leaked exception text."""
    deployment = await load_fixture(provide_deployment())
    module = AsyncPath(deployment.directory, "deployment.py")
    await module.write_text(await module.read_text() + f"\n{source}\n")

    completed = await deployment.run("status", "--json")

    assert_eq(completed.returncode, 1)
    assert_eq(completed.stdout, b"")
    assert_not_in("private_factory_value", completed.stderr.decode())
    assert_not_in("was never awaited", completed.stderr.decode())


@test(
    [
        Param(value="missing_module:MIGRATIONS", name="missing-module"),
        Param(value="deployment:missing", name="missing-export"),
        Param(value="deployment.MIGRATIONS", name="missing-colon"),
        Param(value="deployment:open_database()", name="expression"),
    ],
    mark="medium",
)
async def invalid_reference_is_not_evaluated(reference: str) -> None:
    """References identify Python exports; they do not evaluate arbitrary expressions."""
    deployment = await load_fixture(provide_deployment())

    completed = await deployment.run("status", "--json", "--migrations", reference)

    assert_eq(completed.returncode, 1)
    assert_eq(completed.stdout, b"")
    assert_eq(await AsyncPath(deployment.directory, "closed").exists(), False)


@test(mark="medium")
async def cli_inspection_does_not_apply_pending_sql() -> None:
    """Planning leaves non-idempotent pending DDL available for a separate deploy step."""
    deployment = await load_fixture(provide_deployment())

    completed = await deployment.run("plan", "--sql")
    async with await sqlite.Database.initialize(
        database=Path(deployment.directory) / "app.db"
    ) as database:
        applied = await database.migrate(_DECLARATION)

    assert_eq(completed.returncode, 0)
    assert_eq(applied.applied, ("002_note",))


@test(mark="medium")
async def sql_preview_uses_the_original_declaration_snapshot() -> None:
    """Factory-side edits cannot change the SQL paired with an inspected plan."""
    deployment = await load_fixture(provide_deployment())
    module = AsyncPath(deployment.directory, "deployment.py")
    await module.write_text(
        await module.read_text()
        + """
original_factory = open_database
@asynccontextmanager
async def open_database():
    MIGRATIONS["002_note"] = "SELECT 'changed_after_snapshot'"
    async with original_factory() as database:
        yield database
"""
    )

    completed = await deployment.run("plan", "--json", "--sql")

    assert_eq(completed.returncode, 0)
    assert_eq(
        loads(completed.stdout)["sql"],
        {
            "002_note": "ALTER TABLE entries ADD COLUMN note TEXT DEFAULT 'private_body_literal'"
        },
    )


@test(mark="medium")
async def suppressed_inspection_error_is_not_success() -> None:
    """A factory must not turn failed history validation into an empty successful report."""
    deployment = await load_fixture(provide_deployment())
    module = AsyncPath(deployment.directory, "deployment.py")
    await module.write_text(
        await module.read_text()
        + """
MIGRATIONS["001_entries"] = "SELECT 1"
original_factory = open_database
@asynccontextmanager
async def open_database():
    try:
        async with original_factory() as database:
            yield database
    except Exception:
        pass
"""
    )

    completed = await deployment.run("plan", "--json")

    assert_eq(completed.returncode, 1)
    assert_eq(completed.stdout, b"")
