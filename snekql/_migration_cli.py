"""Read-only migration commands using trusted application-owned database contexts."""

import sys
from argparse import ArgumentParser
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from importlib import import_module
from inspect import iscoroutine
from json import dumps
from typing import cast

from anyio import run, to_thread

from snekql._migrations import MigrationStatus, prepare_migrations
from snekql.errors import MigrationDeclarationError
from snekql.runtime import Database


def _load_reference(reference: str) -> object:
    """Resolve one explicit trusted Python export without evaluating expressions."""
    module_name, separator, attribute = reference.partition(":")
    if (
        not separator
        or not attribute.isidentifier()
        or not all(part.isidentifier() for part in module_name.split("."))
    ):
        msg = "migration command references must use module:attribute"
        raise MigrationDeclarationError(msg)
    try:
        return getattr(import_module(module_name), attribute)
    except (ImportError, AttributeError) as e:
        msg = "could not load migration command reference"
        raise MigrationDeclarationError(msg) from e


async def _inspect(
    database_reference: str, migrations_reference: str
) -> tuple[MigrationStatus, dict[str, str]]:
    """Snapshot declarations before entering the factory; finish cleanup before output."""
    declaration = await to_thread.run_sync(_load_reference, migrations_reference)
    plan = prepare_migrations(declaration)
    migrations = {migration.name: migration.sql for migration in plan}
    factory = await to_thread.run_sync(_load_reference, database_reference)
    if not callable(factory):
        msg = "database export must be a zero-argument context-manager factory"
        raise MigrationDeclarationError(msg)
    # Python exports have no static callable signature. Wrong argument counts
    # fail here and are translated by the command, before any status is printed.
    context = cast("Callable[[], object]", factory)()
    if iscoroutine(context):
        context.close()
    if not isinstance(context, AbstractAsyncContextManager):
        msg = "database factory must return an async context manager"
        raise MigrationDeclarationError(msg)
    async with context as database:
        if not isinstance(database, Database):
            msg = "database context must yield a snekql Database"
            raise MigrationDeclarationError(msg)
        return await database.migration_status(migrations), migrations
    msg = "database context suppressed a migration inspection failure"
    raise MigrationDeclarationError(msg)


def run_migrations_cli(argv: list[str]) -> int:
    """Inspect history or print pending SQL without executing migration bodies."""
    parser = ArgumentParser(prog="snekql migrations")
    parser.add_argument("command", choices=("status", "plan"))
    parser.add_argument("--database", required=True, metavar="MODULE:FACTORY")
    parser.add_argument("--migrations", required=True, metavar="MODULE:DECLARATION")
    parser.add_argument("--json", action="store_true")
    parser.add_argument(
        "--sql", action="store_true", help="include pending SQL, plan only"
    )
    options = parser.parse_args(argv)
    if options.sql and options.command != "plan":
        parser.error("--sql is only valid with plan")
    try:
        status, migrations = run(_inspect, options.database, options.migrations)
    except Exception:
        # Import, factory, and driver exception messages may contain credentials
        # or SQL. Never print an arbitrary exception or its chained traceback.
        print(
            "Migration inspection failed. Check configuration and migration history.",
            file=sys.stderr,
        )
        return 1
    if options.json:
        document: dict[str, object] = {
            "history_present": status.history_present,
            "applied": status.applied,
            "pending": status.pending,
        }
        if options.sql:
            document["sql"] = {name: migrations[name] for name in status.pending}
        print(dumps(document))
    else:
        print(f"History: {'present' if status.history_present else 'absent'}")
        if options.command == "status":
            print(f"Applied: {len(status.applied)}")
            for name in status.applied:
                print(f"  {name!r}")
        print(f"Pending: {len(status.pending)}")
        for name in status.pending:
            print(f"  {name!r}")
            if options.sql:
                print(migrations[name])
    return 0
