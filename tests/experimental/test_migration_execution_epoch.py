"""A defined historical execution interpretation is independent of authoring availability."""

import asyncio
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
from tests.experimental.test_migration_prepared_evidence import Account, Initial

_FIXTURES = Path(__file__).parent / "fixtures"


@test(mark="slow")
async def runtime_without_authoring_compiler_loads_and_applies_original_deferred_plan() -> (
    None
):
    """Deleting the public authoring verb does not delete historical execution support."""
    with TemporaryDirectory() as directory:
        root = Path(directory)
        runtime = root / "runtime"
        runtime.mkdir()
        config = sqlite.Config(database=root / "app.db")
        historical = _FIXTURES / "framework-evolution" / "sqlite"
        async with m.connect(config) as target:
            await target.apply(
                await target.prepare(
                    m.Package.load((historical / "001_accounts.json").read_text())
                )
            )
        async with (
            await sqlite.Database.initialize(config) as app,
            app.transaction() as tx,
        ):
            await tx.execute(
                sqlite.insert_many(
                    Initial,
                    [Initial(id=1, is_admin=True), Initial(id=2, is_admin=False)],
                )
            )
        async with m.connect(config) as target:
            await target.apply(
                await target.prepare(
                    m.Package.load((historical / "002_roles.json").read_text())
                )
            )
        async with aiosqlite.connect(str(config.database)) as outside:
            await outside.execute(
                "ALTER TABLE accounts ADD COLUMN note TEXT DEFAULT 'kept'"
            )
            await outside.commit()
        async with m.connect(config) as target:
            original = await target.prepare(
                m.Package.load((historical / "003_contract.json").read_text()),
                preserve_unmanaged=True,
            )
            (runtime / "original-plan.json").write_text(original.dump())
        shutil.copyfile(
            _FIXTURES / "execution-epoch" / "runtime.py.in", runtime / "run.py"
        )
        code, diagnostics = await _typecheck(root, runtime)
        assert_eq(code, 0, msg=diagnostics)
        source = Path(m.__file__).parents[1]
        await asyncio.to_thread(
            shutil.copytree,
            source,
            runtime / "snekql",
            ignore=shutil.ignore_patterns("__pycache__"),
        )
        copied = runtime / "snekql" / "experimental" / "migrations.py"
        with copied.open("a") as output:
            output.write(
                "\n# Runtime-only build: no public authoring compiler.\ndel compile\n"
            )
        result = json.loads(
            await _python(runtime / "run.py", {"database": str(config.database)})
        )
        assert_eq(result["outcome"], "applied")
        assert_eq(result["epoch"], 1)
        assert_eq(result["lazy_imports"], sys.get_lazy_imports())
        assert Path(result["library"]).is_relative_to(runtime)
        async with (
            await sqlite.Database.initialize(config) as app,
            app.transaction() as tx,
        ):
            rows = await tx.fetch_all(sqlite.select(Account).order_by(Account.id.asc()))
        assert_eq(
            [(r.id, r.role, r.note) for r in rows],
            [(1, "admin", "kept"), (2, "user", "kept")],
        )


@test(mark="medium")
def legacy_capability_formats_have_defined_execution_epoch_without_wire_rewriting() -> (
    None
):
    """Capability five and capability two both retain their epoch-one interpretation."""
    for name, version in (("003_contract", 2), ("004_index", 5)):
        text = (
            _FIXTURES / "framework-evolution" / "sqlite" / f"{name}.json"
        ).read_text()
        package = m.Package.load(text)
        assert_eq(package.execution_epoch, 1)
        assert_eq(package.version, version)
        assert_eq(package.dump(), text)
        assert "execution_epoch" not in json.loads(text)


@test(mark="medium")
def future_explicit_epoch_is_not_interpreted_as_legacy_by_default() -> None:
    """A future publisher needs a supported reader, not a defaulted compiler choice."""
    text = (
        _FIXTURES / "framework-evolution" / "sqlite" / "003_contract.json"
    ).read_text()
    value = json.loads(text)
    value["execution_epoch"] = 2
    with assert_raises(m.PackageError) as error:
        m.Package.load(json.dumps(value))
    assert "unsupported explicit execution epoch" in str(error.exception)
