"""Actual old-writer packages and old-runtime receipts cross a framework capability epoch."""

import json
import shutil
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

import aiosqlite
from snektest import assert_eq, assert_raises, test

from snekql import sqlite
from snekql.experimental import migrations as m
from tests.experimental.test_migration_authoring_journey import _python, _typecheck

_FIXTURES = Path(__file__).parent / "fixtures" / "framework-evolution"


@test(mark="medium")
async def actual_old_receipt_and_frozen_role_chain_continue_into_new_compiler_capability() -> (
    None
):
    """Supported old ledger stays intact; old packages precede newly generated format5 work."""
    with TemporaryDirectory() as directory:
        root = Path(directory)
        author = root / "author"
        deploy = root / "deploy"
        author.mkdir()
        deploy.mkdir()
        config = sqlite.Config(database=root / "app.db")
        async with aiosqlite.connect(str(config.database)) as connection:
            await connection.executescript(
                (_FIXTURES / "ledger-supported.sql").read_text()
            )
            original_receipt = await connection.execute_fetchall(
                "SELECT * FROM snekql_experimental_migrations"
            )
        for name in ("001_accounts", "002_roles", "003_contract"):
            shutil.copyfile(
                _FIXTURES / "sqlite" / f"{name}.json", author / f"{name}.json"
            )
        for name in ("author_new", "runtime_new", "app_new"):
            target = author if name == "author_new" else deploy
            text = (
                (_FIXTURES / f"{name}.py.in")
                .read_text()
                .replace("BACKEND", "sqlite")
                .replace("NATIVE", "False")
                .replace("CONFIG", 'db.Config(database=Path(payload["database"]))')
            )
            (target / f"{name}.py").write_text(text)
        authored = json.loads(await _python(author / "author_new.py"))
        assert_eq(authored["version"], 5)
        assert_eq(
            (author / "004_index.json").read_text(),
            (_FIXTURES / "sqlite" / "004_index.json").read_text(),
        )
        code, diagnostics = await _typecheck(root, author)
        assert_eq(code, 0, msg=diagnostics)
        for source in author.glob("*.json"):
            shutil.copyfile(source, deploy / source.name)
        shutil.rmtree(author)
        completed = json.loads(
            await _python(deploy / "runtime_new.py", {"database": str(config.database)})
        )
        assert_eq(
            completed["initial"],
            [
                [
                    "001_accounts",
                    "complete",
                    "1a63e1c9fd6b589be10c4a78c2a39f8daea38d0b172978fe0276eb438be847b6",
                ]
            ],
        )
        assert_eq(
            [(p[0], p[1]) for p in completed["progress"]],
            [
                (r, "complete")
                for r in ("001_accounts", "002_roles", "003_contract", "004_index")
            ],
        )
        assert_eq(
            completed["rows"], [{"id": 1, "role": "admin"}, {"id": 2, "role": "user"}]
        )
        assert_eq(completed["lazy_imports"], sys.get_lazy_imports())
        async with aiosqlite.connect(str(config.database)) as connection:
            assert_eq(
                await connection.execute_fetchall(
                    "SELECT * FROM snekql_experimental_migrations WHERE revision='001_accounts'"
                ),
                original_receipt,
            )
        current = json.loads(
            await _python(deploy / "app_new.py", {"database": str(config.database)})
        )
        assert_eq(
            current, {"rows": [[1, "admin"], [2, "user"]], "created": [3, "user"]}
        )
        async with (
            await sqlite.Database.initialize(config) as app,
            app.transaction() as tx,
        ):
            assert_eq(
                await tx.fetch_all(
                    sqlite.raw(
                        "SELECT name FROM sqlite_schema WHERE type='index' AND tbl_name='accounts'"
                    )
                ),
                [{"name": "accounts_by_role"}],
            )


@test(mark="medium")
async def actual_incompatible_old_ledger_is_refused_without_rewriting_any_evidence() -> (
    None
):
    """An actual nine-column historical ledger is neither empty history nor upgrade authority."""
    with TemporaryDirectory() as directory:
        config = sqlite.Config(database=Path(directory) / "app.db")
        async with aiosqlite.connect(str(config.database)) as connection:
            await connection.executescript(
                (_FIXTURES / "ledger-unsupported.sql").read_text()
            )
        async with aiosqlite.connect(str(config.database)) as connection:
            before = [line async for line in connection.iterdump()]
        package = m.Package.load((_FIXTURES / "sqlite" / "002_roles.json").read_text())
        async with m.connect(config) as target:
            for action in (target.status, lambda: target.prepare(package)):
                with assert_raises(m.PackageError) as error:
                    await action()
                assert "unsupported experimental ledger layout" in str(error.exception)
        async with aiosqlite.connect(str(config.database)) as connection:
            assert_eq([line async for line in connection.iterdump()], before)
