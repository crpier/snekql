"""Recorded migration contracts exercised through the authoring interface."""

import asyncio
import json
import sys
from pathlib import Path
from sqlite3 import IntegrityError
from tempfile import TemporaryDirectory
from typing import ClassVar

import aiosqlite
from snektest import assert_eq, assert_raises, assert_true, test

from snekql import sqlite
from snekql.experimental import migrations


class Entry[S = sqlite.Pending](sqlite.Model[S]):
    """Small managed table for initial package generation."""

    __row_type__: ClassVar[sqlite.ReadType[Entry[sqlite.Row]]]

    id: sqlite.Col[int] = sqlite.Integer(primary_key=True)
    title: sqlite.Col[str] = sqlite.Text()


@test(mark="fast")
def initial_package_round_trips_without_model_imports() -> None:
    """A deployment package retains SQL and historical state without live models."""
    draft = migrations.generate("001_entries", [Entry], backend="sqlite")
    package = migrations.compile(draft)
    restored = migrations.Package.load(package.dump())

    assert_eq(restored, package)
    assert_eq(restored.target.tables[0].name, "entry")
    assert_eq(
        restored.statements,
        (
            'CREATE TABLE "entry" ("id" INTEGER PRIMARY KEY, "title" TEXT NOT NULL) STRICT',
        ),
    )


@test(mark="medium")
async def sqlite_package_prepares_applies_and_is_not_replayed() -> None:
    """A prepared package creates usable tables and tracks its execution identity."""

    with TemporaryDirectory() as directory:
        config = sqlite.Config(database=Path(directory) / "app.db")
        package = migrations.compile(
            migrations.generate("001_entries", [Entry], backend="sqlite")
        )
        async with migrations.connect(config) as target:
            prepared = await target.prepare(package)
            assert_eq(prepared.statements, package.statements)
            assert_eq(await target.apply(prepared), "applied")
            assert_eq(await target.apply(prepared), "already_applied")
        async with (
            await sqlite.Database.initialize(config) as db,
            db.transaction() as tx,
        ):
            await tx.execute(sqlite.raw("INSERT INTO entry VALUES(1, 'kept')"))
            rows = await tx.fetch_all(sqlite.raw("SELECT title FROM entry"))
        assert_eq(rows, [{"title": "kept"}])


class EntryWithNote[S = sqlite.Pending](sqlite.Model[S]):
    """Desired state adding an optional value without rewriting existing rows."""

    __tablename__ = "entry"
    __row_type__: ClassVar[sqlite.ReadType[EntryWithNote[sqlite.Row]]]
    id: sqlite.Col[int] = sqlite.Integer(primary_key=True)
    title: sqlite.Col[str] = sqlite.Text()
    note: sqlite.Col[str | None] = sqlite.Text(nullable=True)


@test(mark="fast")
def pending_revision_generates_against_recorded_target_not_a_database() -> None:
    """A second package can be generated before the first is ever applied."""
    first = migrations.compile(migrations.generate("001", [Entry], backend="sqlite"))
    second = migrations.compile(
        migrations.generate("002", [EntryWithNote], backend="sqlite", previous=first)
    )
    assert_eq(second.statements, ('ALTER TABLE "entry" ADD COLUMN "note" TEXT',))
    assert_eq(second.draft.predecessor, first.digest)


@test(mark="medium")
async def observed_drift_cannot_be_silently_accepted_by_repreparing() -> None:
    """A fresh observation is not permission to replace the accepted managed state."""

    with TemporaryDirectory() as directory:
        config = sqlite.Config(database=Path(directory) / "app.db")
        first = migrations.compile(
            migrations.generate("001", [Entry], backend="sqlite")
        )
        second = migrations.compile(
            migrations.generate(
                "002", [EntryWithNote], backend="sqlite", previous=first
            )
        )
        async with migrations.connect(config) as target:
            await target.apply(await target.prepare(first))

            async with aiosqlite.connect(str(config.database)) as outside:
                await outside.execute("ALTER TABLE entry ADD COLUMN outsider TEXT")
                await outside.commit()
            with assert_raises(migrations.PackageError):
                await target.prepare(second)


@test(mark="fast")
def package_tampering_is_rejected() -> None:
    """Changing deployment SQL without regenerating its identity is detected."""

    package = migrations.compile(migrations.generate("001", [Entry], backend="sqlite"))
    payload = json.loads(package.dump())
    payload["statements"] = ['DROP TABLE "entry"']
    with assert_raises(migrations.PackageError):
        migrations.Package.load(json.dumps(payload))


@test(mark="fast")
def editing_route_without_matching_target_is_rejected() -> None:
    """Removing an operation cannot leave a target contract that claims it ran."""

    draft = migrations.generate("001", [Entry], backend="sqlite")
    with assert_raises(migrations.PackageError):
        migrations.compile(draft.model_copy(update={"operations": ()}))


@test(mark="fast")
def removing_a_model_does_not_silently_drop_or_relinquish_it() -> None:
    """Absence from declarations is not permission to delete owned structure."""

    first = migrations.compile(migrations.generate("001", [Entry], backend="sqlite"))
    draft = migrations.generate("002", [], backend="sqlite", previous=first)
    assert_true("relinquishing ownership" in draft.unresolved[0])
    with assert_raises(migrations.PackageError):
        migrations.compile(draft)


@test(mark="medium")
async def concurrent_sqlite_runners_recheck_history_after_writer_lock() -> None:
    """Two prepared plans cannot both execute the same non-idempotent CREATE."""

    with TemporaryDirectory() as directory:
        config = sqlite.Config(database=Path(directory) / "app.db")
        package = migrations.compile(
            migrations.generate("001", [Entry], backend="sqlite")
        )
        async with (
            migrations.connect(config) as first,
            migrations.connect(config) as second,
        ):
            a = await first.prepare(package)
            b = await second.prepare(package)
            results = await asyncio.gather(first.apply(a), second.apply(b))
        assert_eq(sorted(results), ["already_applied", "applied"])


@test(mark="medium")
async def nullable_addition_preserves_populated_rows() -> None:
    """Consecutive generated packages preserve earlier application data."""

    with TemporaryDirectory() as directory:
        config = sqlite.Config(database=Path(directory) / "app.db")
        first = migrations.compile(
            migrations.generate("001", [Entry], backend="sqlite")
        )
        second = migrations.compile(
            migrations.generate(
                "002", [EntryWithNote], backend="sqlite", previous=first
            )
        )
        async with migrations.connect(config) as target:
            await target.apply(await target.prepare(first))
            async with (
                await sqlite.Database.initialize(config) as db,
                db.transaction() as tx,
            ):
                await tx.execute(sqlite.raw("INSERT INTO entry VALUES(1, 'kept')"))
            await target.apply(await target.prepare(second))
        async with (
            await sqlite.Database.initialize(config) as db,
            db.transaction() as tx,
        ):
            rows = await tx.fetch_all(sqlite.raw("SELECT title,note FROM entry"))
        assert_eq(rows, [{"title": "kept", "note": None}])


@test(mark="medium")
async def named_intermediate_contract_typechecks_without_current_model_imports() -> (
    None
):
    """Draft typing is available before the developer authors a data transform."""

    first = migrations.compile(migrations.generate("001", [Entry], backend="sqlite"))
    draft = migrations.generate(
        "002", [EntryWithNote], backend="sqlite", previous=first
    )
    draft = draft.model_copy(
        update={
            "operations": (*draft.operations, migrations.Checkpoint(name="backfill"))
        }
    )
    source = migrations.contract_source(draft, point="backfill", table="entry")
    source += "\nquery = sqlite.select(Historical.title, Historical.note)\n"
    with TemporaryDirectory() as directory:
        path = Path(directory) / "historical.py"
        await asyncio.to_thread(path.write_text, source)
        process = await asyncio.create_subprocess_exec(
            str(Path(sys.executable).with_name("ty")),
            "check",
            str(path),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await process.communicate()
        assert_eq((process.returncode, stderr.decode()), (0, ""))
        assert_eq("All checks passed!" in stdout.decode(), True)
        process = await asyncio.create_subprocess_exec(
            sys.executable,
            str(path),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await process.communicate()
        assert_eq((process.returncode, stderr.decode()), (0, ""))


@test(mark="fast")
def corrupted_predecessor_is_not_used_as_generation_baseline() -> None:
    """Canonical state cannot be borrowed from an unchecked package."""

    first = migrations.compile(migrations.generate("001", [Entry], backend="sqlite"))
    broken = first.model_copy(update={"digest": "changed"})
    with assert_raises(migrations.PackageError):
        migrations.generate("002", [EntryWithNote], backend="sqlite", previous=broken)


@test(mark="medium")
async def typed_backfill_is_frozen_with_parameters_and_applied_to_old_rows() -> None:
    """An expand/backfill package executes compiled historical queries, not models."""
    first = migrations.compile(migrations.generate("001", [Entry], backend="sqlite"))
    draft = migrations.generate(
        "002", [EntryWithNote], backend="sqlite", previous=first
    )
    draft = draft.model_copy(
        update={
            "operations": (*draft.operations, migrations.Checkpoint(name="backfill"))
        }
    )
    contract = migrations.contract_digest(draft, point="backfill")
    change = migrations.DataChange.from_query(
        sqlite.update(EntryWithNote)
        .set(EntryWithNote.note.to("reviewed"))
        .where(EntryWithNote.note.is_null()),
        checkpoint="backfill",
        contract_digest=contract,
    )
    completed = draft.model_copy(update={"operations": (*draft.operations, change)})
    package = migrations.Package.load(migrations.compile(completed).dump())
    with TemporaryDirectory() as directory:
        config = sqlite.Config(database=Path(directory) / "app.db")
        async with migrations.connect(config) as target:
            await target.apply(await target.prepare(first))
            async with (
                await sqlite.Database.initialize(config) as db,
                db.transaction() as tx,
            ):
                await tx.execute(sqlite.raw("INSERT INTO entry VALUES(1, 'kept')"))
            await target.apply(await target.prepare(package))
        async with (
            await sqlite.Database.initialize(config) as db,
            db.transaction() as tx,
        ):
            rows = await tx.fetch_all(sqlite.raw("SELECT title,note FROM entry"))
        assert_eq(rows, [{"title": "kept", "note": "reviewed"}])


@test(mark="fast")
def moving_checkpoint_invalidates_a_previously_authored_backfill() -> None:
    """A generated query contract cannot silently describe the wrong route point."""
    first = migrations.compile(migrations.generate("001", [Entry], backend="sqlite"))
    draft = migrations.generate(
        "002", [EntryWithNote], backend="sqlite", previous=first
    )
    point = migrations.Checkpoint(name="backfill")
    draft = draft.model_copy(update={"operations": (*draft.operations, point)})
    change = migrations.DataChange.from_query(
        sqlite.update(EntryWithNote)
        .set(EntryWithNote.note.to("reviewed"))
        .where(EntryWithNote.note.is_null()),
        checkpoint="backfill",
        contract_digest=migrations.contract_digest(draft, point="backfill"),
    )
    moved = draft.model_copy(
        update={"operations": (point, *draft.operations[:-1], change)}
    )
    with assert_raises(migrations.PackageError):
        migrations.compile(moved)


@test(mark="fast")
def unknown_package_version_has_a_public_validation_error() -> None:
    """Unsupported artifact formats fail through the package error contract."""
    package = migrations.compile(migrations.generate("001", [Entry], backend="sqlite"))
    payload = json.loads(package.dump())
    payload["version"] = 999
    with assert_raises(migrations.PackageError):
        migrations.Package.load(json.dumps(payload))


@test(mark="medium")
async def generated_backfill_package_deploys_after_authoring_module_is_deleted() -> (
    None
):
    """Compile using generated historical models, then deploy with only JSON files."""
    first = migrations.compile(migrations.generate("001", [Entry], backend="sqlite"))
    draft = migrations.generate(
        "002", [EntryWithNote], backend="sqlite", previous=first
    )
    draft = draft.model_copy(
        update={
            "operations": (*draft.operations, migrations.Checkpoint(name="backfill"))
        }
    )
    author = """
from pathlib import Path
from snekql import sqlite
from snekql.experimental import migrations as m
from historical import Historical, CONTRACT_DIGEST
query = sqlite.update(Historical).set(Historical.note.to("historical")).where(Historical.note.is_null())
draft = m.Draft.model_validate_json(Path("draft.json").read_text())
change = m.DataChange.from_query(query, checkpoint="backfill", contract_digest=CONTRACT_DIGEST)
package = m.compile(draft.model_copy(update={"operations": (*draft.operations, change)}))
Path("second.json").write_text(package.dump())
"""
    deploy = """
import asyncio
import json
from pathlib import Path
from snekql import sqlite
from snekql.experimental import migrations as m
async def main():
    config = sqlite.Config(database=Path("app.db"))
    first = m.Package.load(await asyncio.to_thread(Path("first.json").read_text))
    second = m.Package.load(await asyncio.to_thread(Path("second.json").read_text))
    async with m.connect(config) as target:
        await target.apply(await target.prepare(first))
        async with await sqlite.Database.initialize(config) as db, db.transaction() as tx:
            await tx.execute(sqlite.raw("INSERT INTO entry VALUES(1, 'kept')"))
        await target.apply(await target.prepare(second))
    async with await sqlite.Database.initialize(config) as db, db.transaction() as tx:
        rows = await tx.fetch_all(sqlite.raw("SELECT note FROM entry"))
    print(json.dumps(rows))
asyncio.run(main())
"""
    with TemporaryDirectory() as directory:
        root = Path(directory)
        await asyncio.to_thread((root / "first.json").write_text, first.dump())
        await asyncio.to_thread(
            (root / "draft.json").write_text, draft.model_dump_json()
        )
        historical = root / "historical.py"
        await asyncio.to_thread(
            historical.write_text,
            migrations.contract_source(draft, point="backfill", table="entry"),
        )
        process = await asyncio.create_subprocess_exec(
            sys.executable,
            "-c",
            author,
            cwd=root,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await process.communicate()
        assert_eq((process.returncode, stderr.decode()), (0, ""))
        await asyncio.to_thread(historical.unlink)
        await asyncio.to_thread((root / "draft.json").unlink)
        process = await asyncio.create_subprocess_exec(
            sys.executable,
            "-c",
            deploy,
            cwd=root,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await process.communicate()
        assert_eq((process.returncode, stderr.decode()), (0, ""))
        assert_eq(json.loads(stdout), [{"note": "historical"}])


@test(mark="medium")
async def prepared_memory_plan_cannot_be_applied_to_another_connection() -> None:
    """Identical :memory: config strings do not identify the same database."""
    package = migrations.compile(migrations.generate("001", [Entry], backend="sqlite"))
    config = sqlite.Config(database=":memory:")
    async with (
        migrations.connect(config) as first,
        migrations.connect(config) as second,
    ):
        plan = await first.prepare(package)
        with assert_raises(migrations.PackageError):
            await second.apply(plan)


@test(mark="medium")
async def existing_objects_require_adoption_instead_of_implicit_creation() -> None:
    """Matching names do not authorize stamping or beginning a conflicting package."""
    config = sqlite.Config(database=":memory:")
    first = migrations.compile(migrations.generate("001", [Entry], backend="sqlite"))
    conflicting = migrations.compile(
        migrations.generate("other_chain", [Entry], backend="sqlite")
    )
    async with migrations.connect(config) as target:
        await target.apply(await target.prepare(first))
        with assert_raises(migrations.PackageError):
            await target.prepare(conflicting)


@test(mark="medium")
async def untracked_existing_table_is_rejected_during_preparation() -> None:
    """Observation is not adoption even when a table matches the desired model."""
    package = migrations.compile(migrations.generate("001", [Entry], backend="sqlite"))
    with TemporaryDirectory() as directory:
        config = sqlite.Config(database=Path(directory) / "app.db")
        async with aiosqlite.connect(str(config.database)) as outside:
            await outside.execute(package.statements[0])
            await outside.commit()
        async with migrations.connect(config) as target:
            with assert_raises(migrations.PackageError):
                await target.prepare(package)
            assert_eq(await target.status(), ())


@test(mark="fast")
def runner_metadata_cannot_be_claimed_as_an_application_table() -> None:
    """Managed schema declarations cannot overwrite the progress ledger."""

    class Ledger[S = sqlite.Pending](sqlite.Model[S]):
        """Deliberately conflicting model declaration."""

        __tablename__ = "snekql_experimental_migrations"
        __row_type__: ClassVar[sqlite.ReadType[Ledger[sqlite.Row]]]
        id: sqlite.Col[int] = sqlite.Integer(primary_key=True)

    with assert_raises(migrations.PackageError):
        migrations.compile(migrations.generate("001", [Ledger], backend="sqlite"))


@test(mark="medium")
async def edited_before_state_must_match_the_recorded_predecessor_contract() -> None:
    """Matching history IDs cannot legitimize an invented historical contract."""
    first = migrations.compile(migrations.generate("001", [Entry], backend="sqlite"))
    empty = migrations.State(backend="sqlite")
    invented = migrations.compile(
        migrations.Draft(
            revision="002",
            predecessor=first.digest,
            before=empty,
            target=empty,
            operations=(),
        )
    )
    async with migrations.connect(sqlite.Config(database=":memory:")) as target:
        await target.apply(await target.prepare(first))
        with assert_raises(migrations.PackageError):
            await target.prepare(invented)


@test(mark="medium")
async def application_names_similar_to_sqlite_internal_names_are_observed() -> None:
    """The underscore in SQLite's reserved prefix is literal, not a LIKE wildcard."""

    class Similar[S = sqlite.Pending](sqlite.Model[S]):
        """A legal application name adjacent to the engine-reserved prefix."""

        __tablename__ = "sqlitex_entry"
        __row_type__: ClassVar[sqlite.ReadType[Similar[sqlite.Row]]]
        id: sqlite.Col[int] = sqlite.Integer(primary_key=True)

    package = migrations.compile(
        migrations.generate("001", [Similar], backend="sqlite")
    )
    with TemporaryDirectory() as directory:
        config = sqlite.Config(database=Path(directory) / "app.db")
        async with migrations.connect(config) as target:
            await target.apply(await target.prepare(package))
            async with aiosqlite.connect(str(config.database)) as outside:
                await outside.execute("DROP TABLE sqlitex_entry")
                await outside.commit()
            with assert_raises(migrations.PackageError):
                await target.prepare(package)


@test(mark="medium")
async def failed_sqlite_backfill_rolls_back_data_and_progress() -> None:
    """A failing typed UPDATE cannot leave a pending package row or partial data."""

    first = migrations.compile(migrations.generate("001", [Entry], backend="sqlite"))
    draft = migrations.generate("002", [Entry], backend="sqlite", previous=first)
    draft = draft.model_copy(
        update={"operations": (migrations.Checkpoint(name="data"),)}
    )
    change = migrations.DataChange.from_query(
        sqlite.update(Entry).set(Entry.id.to(1)).all(),
        checkpoint="data",
        contract_digest=migrations.contract_digest(draft, point="data"),
    )
    failing = migrations.compile(
        draft.model_copy(update={"operations": (*draft.operations, change)})
    )
    with TemporaryDirectory() as directory:
        config = sqlite.Config(database=Path(directory) / "app.db")
        async with migrations.connect(config) as target:
            await target.apply(await target.prepare(first))
            async with (
                await sqlite.Database.initialize(config) as db,
                db.transaction() as tx,
            ):
                await tx.execute(
                    sqlite.raw("INSERT INTO entry VALUES(1, 'a'),(2, 'b')")
                )
            plan = await target.prepare(failing)
            with assert_raises(IntegrityError):
                await target.apply(plan)
            assert_eq([row.revision for row in await target.status()], ["001"])
        async with (
            await sqlite.Database.initialize(config) as db,
            db.transaction() as tx,
        ):
            rows = await tx.fetch_all(
                sqlite.raw("SELECT id,title FROM entry ORDER BY id")
            )
        assert_eq(rows, [{"id": 1, "title": "a"}, {"id": 2, "title": "b"}])


@test(mark="fast")
def authoring_appends_typed_steps_without_pydantic_update_dictionaries() -> None:
    """The common authoring path does not require knowing the value implementation."""
    draft = migrations.generate("001", [Entry], backend="sqlite")
    extended = draft.then(migrations.Checkpoint(name="created"))
    assert_eq(len(draft.operations), 1)
    assert_eq(len(extended.operations), 2)
    assert_eq(
        migrations.compile(extended).statements, migrations.compile(draft).statements
    )


@test(mark="medium")
async def admin_role_expand_backfill_works_and_unsupported_contraction_stops() -> None:
    """Exercise old/new fields together without pretending DROP/NOT NULL is implemented."""

    class Before[S = sqlite.Pending](sqlite.Model[S]):
        """Initial account representation."""

        __tablename__ = "account"
        __row_type__: ClassVar[sqlite.ReadType[Before[sqlite.Row]]]
        id: sqlite.Col[int] = sqlite.Integer(primary_key=True)
        is_admin: sqlite.Col[bool] = sqlite.Integer()

    class During[S = sqlite.Pending](sqlite.Model[S]):
        """Expand state retaining the old field needed by the backfill."""

        __tablename__ = "account"
        __row_type__: ClassVar[sqlite.ReadType[During[sqlite.Row]]]
        id: sqlite.Col[int] = sqlite.Integer(primary_key=True)
        is_admin: sqlite.Col[bool] = sqlite.Integer()
        role: sqlite.Col[str | None] = sqlite.Text(nullable=True)

    class After[S = sqlite.Pending](sqlite.Model[S]):
        """Desired contraction, which the prototype must not approximate."""

        __tablename__ = "account"
        __row_type__: ClassVar[sqlite.ReadType[After[sqlite.Row]]]
        id: sqlite.Col[int] = sqlite.Integer(primary_key=True)
        role: sqlite.Col[str] = sqlite.Text()

    first = migrations.compile(migrations.generate("001", [Before], backend="sqlite"))
    draft = migrations.generate("002", [During], backend="sqlite", previous=first).then(
        migrations.Checkpoint(name="backfill")
    )
    digest = migrations.contract_digest(draft, point="backfill")
    for is_admin, role in [(True, "admin"), (False, "user")]:
        draft = draft.then(
            migrations.DataChange.from_query(
                sqlite.update(During)
                .set(During.role.to(role))
                .where(During.is_admin.eq(is_admin)),
                checkpoint="backfill",
                contract_digest=digest,
            )
        )
    second = migrations.compile(draft)
    with TemporaryDirectory() as directory:
        config = sqlite.Config(database=Path(directory) / "app.db")
        async with migrations.connect(config) as target:
            await target.apply(await target.prepare(first))
            async with (
                await sqlite.Database.initialize(config) as db,
                db.transaction() as tx,
            ):
                await tx.execute(sqlite.raw("INSERT INTO account VALUES(1,1),(2,0)"))
            await target.apply(await target.prepare(second))
        async with (
            await sqlite.Database.initialize(config) as db,
            db.transaction() as tx,
        ):
            rows = await tx.fetch_all(
                sqlite.raw("SELECT id,role FROM account ORDER BY id")
            )
        assert_eq(rows, [{"id": 1, "role": "admin"}, {"id": 2, "role": "user"}])
    contraction = migrations.generate("003", [After], backend="sqlite", previous=second)
    with assert_raises(migrations.PackageError):
        migrations.compile(contraction)


@test(mark="fast")
def package_validation_uses_the_library_error_root() -> None:
    """Consumers can catch experimental validation with the ordinary snekql root."""
    with assert_raises(sqlite.SnekqlError):
        migrations.compile(migrations.generate("", [], backend="sqlite"))
