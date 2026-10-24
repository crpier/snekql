"""Recorded migration contracts exercised through the authoring interface."""

import asyncio
import json
import sys
from pathlib import Path
from sqlite3 import IntegrityError
from tempfile import TemporaryDirectory
from typing import Any, ClassVar

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

    # Hiding the table from the endpoint must not bypass metadata protection.
    ledger = migrations.generate("001", [Ledger], backend="sqlite").target.tables[0]
    transient = migrations.generate("001", [], backend="sqlite").then(
        migrations.CreateTable(table=ledger),
        migrations.RelinquishTable(table_name=ledger.name),
    )
    with assert_raises(migrations.PackageError):
        migrations.compile(transient)

    transient_adoption = migrations.generate("001", [], backend="sqlite").then(
        migrations.AdoptTable(table=ledger),
        migrations.RelinquishTable(table_name=ledger.name),
    )
    with assert_raises(migrations.PackageError):
        migrations.compile(transient_adoption)


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
async def admin_role_expand_backfill_does_not_implicitly_authorize_contraction() -> (
    None
):
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


@test(mark="fast")
def package_check_detects_authoring_changes_not_yet_compiled() -> None:
    """CI can compare a supplied current draft with its committed deployment artifact."""
    draft = migrations.generate("001", [Entry], backend="sqlite")
    package = migrations.compile(draft)
    package.check(draft)
    changed = draft.then(migrations.Checkpoint(name="new_authoring_point"))
    with assert_raises(migrations.PackageError):
        package.check(changed)


@test(mark="fast")
def serialized_execution_packages_are_reviewable_without_a_formatter() -> None:
    """Committed artifacts expose individual statements in a readable JSON layout."""
    package = migrations.compile(migrations.generate("001", [Entry], backend="sqlite"))
    assert_true('\n  "statements": [' in package.dump())
    assert_eq(migrations.Package.load(package.dump()), package)


@test(mark="medium")
async def incompatible_experimental_ledger_has_an_explicit_format_error() -> None:
    """An older prototype journal is never silently converted or treated as empty."""
    with TemporaryDirectory() as directory:
        config = sqlite.Config(database=Path(directory) / "app.db")
        async with aiosqlite.connect(str(config.database)) as app:
            await app.execute(
                "CREATE TABLE snekql_experimental_migrations (digest TEXT PRIMARY KEY, revision TEXT, predecessor TEXT, phase TEXT, catalog TEXT, acknowledged INTEGER, total INTEGER, state TEXT, plan TEXT)"
            )
            await app.commit()
        package = migrations.compile(
            migrations.generate("001", [Entry], backend="sqlite")
        )
        async with migrations.connect(config) as target:
            with assert_raises(migrations.PackageError) as error:
                await target.prepare(package)
            assert_true(
                "unsupported experimental ledger layout" in str(error.exception)
            )


@test(mark="fast")
def omitted_table_requires_explicit_non_destructive_relinquishment() -> None:
    """Removing ownership is a recorded decision, not an implicit DROP TABLE."""
    first = migrations.compile(migrations.generate("001", [Entry], backend="sqlite"))
    draft = migrations.generate("002", [], backend="sqlite", previous=first)
    with assert_raises(migrations.PackageError):
        migrations.compile(draft)
    resolved = draft.resolve(migrations.RelinquishTable(table_name="entry"))
    second = migrations.compile(resolved)
    assert_eq(second.target.tables, ())
    assert_eq(second.statements, ())
    assert_eq(second.draft.before, first.target)
    assert_eq(migrations.Package.load(second.dump()), second)
    second.check(resolved)
    with assert_raises(migrations.PackageError):
        draft.resolve(migrations.RelinquishTable(table_name="other"))
    with assert_raises(migrations.PackageError):
        resolved.resolve(migrations.RelinquishTable(table_name="entry"))


@test(mark="fast")
def relinquishment_changes_only_subsequent_managed_contracts() -> None:
    """Earlier query declarations survive, but later ownership snapshots omit the table."""
    first = migrations.compile(migrations.generate("001", [Entry], backend="sqlite"))
    draft = (
        migrations.generate("002", [], backend="sqlite", previous=first)
        .then(migrations.Checkpoint(name="before_handoff"))
        .resolve(migrations.RelinquishTable(table_name="entry"))
        .then(migrations.Checkpoint(name="after_handoff"))
    )
    source = migrations.contract_source(draft, point="before_handoff", table="entry")
    assert_true("__tablename__ = 'entry'" in source)
    with assert_raises(migrations.PackageError):
        migrations.contract_source(draft, point="after_handoff", table="entry")
    assert_true(
        migrations.contract_digest(draft, point="before_handoff")
        != migrations.contract_digest(draft, point="after_handoff")
    )
    assert_eq(migrations.compile(draft).statements, ())


@test(mark="medium")
async def sqlite_relinquishment_preserves_objects_and_query_mapping() -> None:
    """A journaled handoff leaves application structure, rows and query models usable."""
    first = migrations.compile(migrations.generate("001", [Entry], backend="sqlite"))
    second = migrations.Package.load(
        migrations.compile(
            migrations.generate("002", [], backend="sqlite", previous=first).resolve(
                migrations.RelinquishTable(table_name="entry")
            )
        ).dump()
    )
    with TemporaryDirectory() as directory:
        config = sqlite.Config(database=Path(directory) / "app.db")
        async with migrations.connect(config) as target:
            await target.apply(await target.prepare(first))
            async with aiosqlite.connect(str(config.database)) as app:
                await app.executescript("""
                    CREATE TABLE audit(title TEXT);
                    CREATE INDEX entry_title ON entry(title);
                    CREATE VIEW entry_view AS SELECT id,title FROM entry;
                    CREATE TRIGGER entry_audit AFTER UPDATE ON entry
                    BEGIN INSERT INTO audit VALUES(new.title); END;
                    INSERT INTO entry VALUES(17,'kept');
                """)
            with assert_raises(migrations.PackageError):
                await target.prepare(second)
            plan = await target.prepare(second, preserve_unmanaged=True)
            assert_eq(plan.statements, ())
            async with await sqlite.Database.initialize(config) as db:
                catalog = sqlite.raw(
                    "SELECT type,name,sql FROM sqlite_schema WHERE name IN ('entry','audit','entry_title','entry_view','entry_audit') ORDER BY name"
                )
                async with db.transaction() as tx:
                    before = await tx.fetch_all(catalog)
                assert_eq(await target.apply(plan), "applied")
                assert_eq(await target.apply(plan), "already_applied")
                async with db.transaction() as tx:
                    assert_eq(await tx.fetch_all(catalog), before)
                    assert_eq(await tx.fetch_all(sqlite.select(Entry.title)), ["kept"])
                    await tx.execute(
                        sqlite.update(Entry).set(Entry.title.to("edited")).all()
                    )
                    assert_eq(await tx.fetch_all(sqlite.select(Entry.id)), [17])
                    assert_eq(
                        await tx.fetch_all(sqlite.raw("SELECT title FROM audit")),
                        [{"title": "edited"}],
                    )
                    assert_eq(
                        await tx.fetch_all(sqlite.raw("SELECT title FROM entry_view")),
                        [{"title": "edited"}],
                    )
            progress = next(p for p in await target.status() if p.revision == "002")
            assert_eq((progress.phase, progress.total_steps), ("complete", 0))
            # Mapping the table again is not authorization to reclaim an existing object.
            reclaim = migrations.compile(
                migrations.generate("003", [Entry], backend="sqlite", previous=second)
            )
            with assert_raises(migrations.PackageError):
                await target.prepare(reclaim)


@test(mark="fast")
def relinquishment_cannot_be_used_as_a_physical_table_removal() -> None:
    """A state-only handoff cannot make CREATE safe against the retained object."""
    first = migrations.compile(migrations.generate("001", [Entry], backend="sqlite"))
    draft = migrations.generate("002", [Entry], backend="sqlite", previous=first).then(
        migrations.RelinquishTable(table_name="entry"),
        migrations.CreateTable(table=first.target.tables[0]),
    )
    with assert_raises(migrations.PackageError):
        migrations.compile(draft)


@test(mark="fast")
def relinquished_tables_reject_later_managed_operations() -> None:
    """Every route interpreter reports a missing ownership contract, not a KeyError."""
    first = migrations.compile(
        migrations.generate("001", [EntryWithNote], backend="sqlite")
    )
    released = migrations.generate("002", [], backend="sqlite", previous=first).resolve(
        migrations.RelinquishTable(table_name="entry")
    )
    for operation in (
        migrations.RequireNotNull(table_name="entry", column_name="note"),
        migrations.DropColumn(table_name="entry", column_name="note"),
        migrations.AddColumn(
            table_name="entry", column=first.target.tables[0].columns[-1]
        ),
        migrations.RelinquishTable(table_name="entry"),
    ):
        invalid = released.then(operation, migrations.Checkpoint(name="invalid"))
        with assert_raises(migrations.PackageError):
            migrations.compile(invalid)
        with assert_raises(migrations.PackageError):
            migrations.contract_source(invalid, point="invalid", table="entry")
        with assert_raises(migrations.PackageError):
            migrations.contract_digest(invalid, point="invalid")


@test(mark="fast")
def backfill_contract_cannot_be_moved_across_an_ownership_handoff() -> None:
    """A pre-handoff query contract must be used before, not after, relinquishment."""
    first = migrations.compile(
        migrations.generate("001", [EntryWithNote], backend="sqlite")
    )
    draft = migrations.generate("002", [], backend="sqlite", previous=first).then(
        migrations.Checkpoint(name="backfill")
    )
    change = migrations.DataChange.from_query(
        sqlite.update(EntryWithNote).set(EntryWithNote.note.to("handed off")).all(),
        checkpoint="backfill",
        contract_digest=migrations.contract_digest(draft, point="backfill"),
    )
    release = migrations.RelinquishTable(table_name="entry")
    ordered = migrations.compile(draft.then(change).resolve(release))
    assert_eq(len(ordered.statements), 1)
    assert_eq(ordered.target.tables, ())
    with assert_raises(migrations.PackageError):
        migrations.compile(draft.resolve(release).then(change))


@test(mark="fast")
def adoption_is_an_explicit_alternative_to_proposed_creation() -> None:
    """Choosing adoption retains the declared contract but emits no creation SQL."""
    draft = migrations.generate("001", [Entry], backend="sqlite").then(
        migrations.Checkpoint(name="ready")
    )
    adopted = draft.adopt("entry")
    package = migrations.compile(adopted)
    assert_eq(package.statements, ())
    assert_eq(package.target, draft.target)
    assert_true(isinstance(adopted.operations[0], migrations.AdoptTable))
    assert_eq(
        migrations.contract_digest(adopted, point="ready"),
        migrations.contract_digest(draft, point="ready"),
    )
    assert_true(
        "__tablename__ = 'entry'"
        in migrations.contract_source(adopted, point="ready", table="entry")
    )
    assert_eq(migrations.Package.load(package.dump()), package)
    with assert_raises(migrations.PackageError):
        package.check(draft)
    with assert_raises(migrations.PackageError):
        draft.adopt("missing")
    with assert_raises(migrations.PackageError):
        draft.adopt("entry", "entry")
    with assert_raises(migrations.PackageError):
        adopted.adopt("entry")


@test(mark="medium")
async def adoption_rejects_missing_mismatched_and_extended_tables_without_stamping() -> (
    None
):
    """The preservation opt-in cannot weaken the strict first adoption contract."""
    package = migrations.compile(
        migrations.generate("001", [Entry], backend="sqlite").adopt("entry")
    )
    with TemporaryDirectory() as directory:
        for index, ddl in enumerate(
            (
                "",
                "CREATE VIEW entry AS SELECT 1 AS id, 'x' AS title",
                "CREATE TABLE entry(id INTEGER PRIMARY KEY, title BLOB NOT NULL) STRICT",
                "CREATE TABLE entry(id INTEGER PRIMARY KEY) STRICT",
                "CREATE TABLE entry(id INTEGER PRIMARY KEY, title TEXT) STRICT",
                "CREATE TABLE entry(id INTEGER PRIMARY KEY, title TEXT NOT NULL)",
                "CREATE TABLE entry(id INTEGER PRIMARY KEY, title TEXT NOT NULL, extra TEXT) STRICT",
                "CREATE TABLE entry(id INTEGER PRIMARY KEY, title TEXT NOT NULL CHECK(title <> '')) STRICT",
                "CREATE TABLE entry(id INTEGER PRIMARY KEY, title TEXT NOT NULL DEFAULT 'x') STRICT",
                "CREATE TABLE entry(id INTEGER PRIMARY KEY, title TEXT NOT NULL) STRICT; CREATE INDEX extra ON entry(title)",
                "CREATE TABLE entry(id INTEGER PRIMARY KEY, title TEXT NOT NULL) STRICT; CREATE TRIGGER extra AFTER UPDATE ON entry BEGIN SELECT 1; END",
            )
        ):
            config = sqlite.Config(database=Path(directory) / f"case-{index}.db")
            async with aiosqlite.connect(str(config.database)) as app:
                await app.executescript(ddl)
            async with migrations.connect(config) as target:
                for preserve in (False, True):
                    with assert_raises(migrations.PackageError) as error:
                        await target.prepare(package, preserve_unmanaged=preserve)
                    category = (
                        "existing table",
                        "existing table",
                        "column/constraint",
                        "column/constraint",
                        "column/constraint",
                        "storage",
                        "column/constraint",
                        "column/constraint",
                        "column/constraint",
                        "index",
                        "trigger",
                    )[index]
                    assert_true(category in str(error.exception))
                assert_eq(await target.status(), ())


@test(mark="medium")
async def sqlite_adoption_preserves_rows_then_allows_recorded_expansion() -> None:
    """Explicit adoption validates existing structure and begins an ordinary chain."""
    first = migrations.Package.load(
        migrations.compile(
            migrations.generate("001", [Entry], backend="sqlite").adopt("entry")
        ).dump()
    )
    second = migrations.compile(
        migrations.generate("002", [EntryWithNote], backend="sqlite", previous=first)
    )
    with TemporaryDirectory() as directory:
        config = sqlite.Config(database=Path(directory) / "app.db")
        async with aiosqlite.connect(str(config.database)) as app:
            await app.executescript(
                "CREATE TABLE entry(id INTEGER PRIMARY KEY, title TEXT NOT NULL) STRICT; INSERT INTO entry VALUES(17,'kept');"
            )
        async with migrations.connect(config) as target:
            plan = await target.prepare(first)
            assert_eq(plan.statements, ())
            assert_eq(await target.status(), ())
            assert_eq(await target.apply(plan), "applied")
            assert_eq(await target.apply(plan), "already_applied")
            await target.apply(await target.prepare(second))
            # Already-applied adoption must not revalidate the obsolete initial shape.
            assert_eq(
                await target.apply(await target.prepare(first)), "already_applied"
            )
            assert_eq([p.revision for p in await target.status()], ["001", "002"])
        async with (
            await sqlite.Database.initialize(config) as db,
            db.transaction() as tx,
        ):
            assert_eq(await tx.fetch_all(sqlite.select(Entry.id)), [17])
            assert_eq(await tx.fetch_all(sqlite.select(Entry.title)), ["kept"])
            assert_eq(await tx.fetch_all(sqlite.select(EntryWithNote.note)), [None])


@test(mark="medium")
async def adoption_revalidates_the_claim_and_catalog_before_writing_history() -> None:
    """Neither edited plans nor schema changes after review can authorize adoption."""
    first = migrations.compile(
        migrations.generate("001", [Entry], backend="sqlite").adopt("entry")
    )
    different = migrations.compile(
        migrations.generate("001", [EntryWithNote], backend="sqlite").adopt("entry")
    )
    with TemporaryDirectory() as directory:
        config = sqlite.Config(database=Path(directory) / "app.db")
        async with aiosqlite.connect(str(config.database)) as app:
            await app.execute(
                "CREATE TABLE entry(id INTEGER PRIMARY KEY, title TEXT NOT NULL) STRICT"
            )
        async with migrations.connect(config) as target:
            plan = await target.prepare(first)
            with assert_raises(migrations.PackageError):
                await target.apply(plan.model_copy(update={"package": different}))
            async with aiosqlite.connect(str(config.database)) as app:
                await app.execute("ALTER TABLE entry ADD COLUMN extra TEXT")
            with assert_raises(migrations.PackageError):
                await target.apply(plan)
            assert_eq(await target.status(), ())


@test(mark="medium")
async def failed_backfill_rolls_back_adoption_instead_of_stamping_existing_rows() -> (
    None
):
    """Adoption and supported data work share SQLite's package transaction."""
    draft = (
        migrations.generate("001", [Entry], backend="sqlite")
        .adopt("entry")
        .then(migrations.Checkpoint(name="adopted"))
    )
    change = migrations.DataChange.from_query(
        sqlite.update(Entry).set(Entry.id.to(1)).all(),
        checkpoint="adopted",
        contract_digest=migrations.contract_digest(draft, point="adopted"),
    )
    package = migrations.compile(draft.then(change))
    with TemporaryDirectory() as directory:
        config = sqlite.Config(database=Path(directory) / "app.db")
        async with aiosqlite.connect(str(config.database)) as app:
            await app.executescript(
                "CREATE TABLE entry(id INTEGER PRIMARY KEY, title TEXT NOT NULL) STRICT; INSERT INTO entry VALUES(1,'one'),(2,'two');"
            )
        async with migrations.connect(config) as target:
            with assert_raises(aiosqlite.IntegrityError):
                await target.apply(await target.prepare(package))
            assert_eq(await target.status(), ())
            await target.apply(await target.prepare(migrations.compile(draft)))
        async with (
            await sqlite.Database.initialize(config) as db,
            db.transaction() as tx,
        ):
            assert_eq(
                sorted(await tx.fetch_all(sqlite.select(Entry.title))), ["one", "two"]
            )


@test(mark="medium")
async def relinquished_matching_table_can_be_explicitly_readopted() -> None:
    """A later revision can reclaim a verified table without recreating its rows."""
    first = migrations.compile(migrations.generate("001", [Entry], backend="sqlite"))
    second = migrations.compile(
        migrations.generate("002", [], backend="sqlite", previous=first).resolve(
            migrations.RelinquishTable(table_name="entry")
        )
    )
    third = migrations.compile(
        migrations.generate("003", [Entry], backend="sqlite", previous=second).adopt(
            "entry"
        )
    )
    with TemporaryDirectory() as directory:
        config = sqlite.Config(database=Path(directory) / "app.db")
        async with migrations.connect(config) as target:
            await target.apply(await target.prepare(first))
            async with aiosqlite.connect(str(config.database)) as app:
                await app.execute("INSERT INTO entry VALUES(17,'kept')")
                await app.commit()
            await target.apply(await target.prepare(second))
            plan = await target.prepare(third)
            assert_eq(plan.statements, ())
            await target.apply(plan)
            assert_eq(third.target, first.target)
            assert_eq(
                [p.revision for p in await target.status()], ["001", "002", "003"]
            )
        async with (
            await sqlite.Database.initialize(config) as db,
            db.transaction() as tx,
        ):
            assert_eq(await tx.fetch_all(sqlite.select(Entry.title)), ["kept"])


@test(mark="fast")
def adoption_cannot_overwrite_or_cycle_current_route_ownership() -> None:
    """Adoption is checked against entry-time observation, not guessed intermediate DDL."""
    first = migrations.compile(migrations.generate("001", [Entry], backend="sqlite"))
    draft = migrations.generate("002", [Entry], backend="sqlite", previous=first)
    adopt = migrations.AdoptTable(table=first.target.tables[0])
    with assert_raises(migrations.PackageError):
        migrations.compile(draft.then(adopt))
    with assert_raises(migrations.PackageError):
        migrations.compile(
            draft.then(migrations.RelinquishTable(table_name="entry"), adopt)
        )


@test(mark="medium")
async def ordinary_table_named_virtual_is_not_mistaken_for_a_virtual_table() -> None:
    """Adoption interprets CREATE syntax, not incidental table-name words."""

    class Virtual[S = sqlite.Pending](sqlite.Model[S]):
        """An ordinary table with a legal SQL-keyword name."""

        __row_type__: ClassVar[sqlite.ReadType[Virtual[sqlite.Row]]]
        id: sqlite.Col[int] = sqlite.Integer(primary_key=True)

    package = migrations.compile(
        migrations.generate("001", [Virtual], backend="sqlite").adopt("virtual")
    )
    with TemporaryDirectory() as directory:
        config = sqlite.Config(database=Path(directory) / "app.db")
        async with aiosqlite.connect(str(config.database)) as app:
            await app.execute('CREATE TABLE "virtual" (id INTEGER PRIMARY KEY) STRICT')
        async with migrations.connect(config) as target:
            assert_eq(await target.apply(await target.prepare(package)), "applied")


@test(mark="medium")
async def adopted_bare_identifiers_remain_valid_during_later_preservation_review() -> (
    None
):
    """Adoption and preservation agree on the same recorded column declarations."""
    first = migrations.compile(
        migrations.generate("001", [Entry], backend="sqlite").adopt("entry")
    )
    second = migrations.compile(
        migrations.generate("002", [EntryWithNote], backend="sqlite", previous=first)
    )
    with TemporaryDirectory() as directory:
        config = sqlite.Config(database=Path(directory) / "app.db")
        async with aiosqlite.connect(str(config.database)) as app:
            await app.execute(
                "CREATE TABLE entry(id INTEGER PRIMARY KEY, title TEXT NOT NULL) STRICT"
            )
        async with migrations.connect(config) as target:
            await target.apply(await target.prepare(first))
            async with aiosqlite.connect(str(config.database)) as app:
                await app.execute("CREATE INDEX extra_title ON entry(title)")
            with assert_raises(migrations.PackageError):
                await target.prepare(second)
            plan = await target.prepare(second, preserve_unmanaged=True)
            assert_eq(await target.apply(plan), "applied")


@test(mark="medium")
async def adoption_requires_declared_indexes_to_exist_and_match() -> None:
    """A matching table name and columns cannot hide an absent or wrong index."""

    class Indexed[S = sqlite.Pending](sqlite.Model[S]):
        """Existing table with an explicitly managed index."""

        __tablename__ = "entry"
        __row_type__: ClassVar[sqlite.ReadType[Indexed[sqlite.Row]]]
        id: sqlite.Col[int] = sqlite.Integer(primary_key=True)
        title: sqlite.Col[str] = sqlite.Text()
        __indexes__: ClassVar[list[sqlite.Index[Any]]] = [
            sqlite.Index(title, name="entry_title")
        ]

    package = migrations.compile(
        migrations.generate("001", [Indexed], backend="sqlite").adopt("entry")
    )
    with TemporaryDirectory() as directory:
        config = sqlite.Config(database=Path(directory) / "app.db")
        async with aiosqlite.connect(str(config.database)) as app:
            await app.execute(
                "CREATE TABLE entry(id INTEGER PRIMARY KEY, title TEXT NOT NULL) STRICT"
            )
        async with migrations.connect(config) as target:
            with assert_raises(migrations.PackageError):
                await target.prepare(package)
            async with aiosqlite.connect(str(config.database)) as app:
                await app.execute('CREATE INDEX "entry_title" ON "entry" ("id")')
            with assert_raises(migrations.PackageError):
                await target.prepare(package)
            assert_eq(await target.status(), ())
            async with aiosqlite.connect(str(config.database)) as app:
                await app.execute('DROP INDEX "entry_title"')
                await app.execute('CREATE INDEX "entry_title" ON "entry" ("title")')
            plan = await target.prepare(package)
            assert_eq(plan.statements, ())
            assert_eq(await target.apply(plan), "applied")


@test(mark="medium")
async def sqlite_completion_requires_the_managed_index_to_materialize() -> None:
    """Successful statements are insufficient when conditional DDL skipped a constraint."""
    draft = migrations.generate("001", [Entry], backend="sqlite")
    table = draft.target.tables[0].model_copy(
        update={
            "indexes": (
                'CREATE UNIQUE INDEX IF NOT EXISTS "entry_title" ON "entry" ("title")',
            )
        }
    )
    package = migrations.compile(
        draft.model_copy(
            update={
                "target": migrations.State(backend="sqlite", tables=(table,)),
                "operations": (migrations.CreateTable(table=table),),
            }
        )
    )
    with TemporaryDirectory() as directory:
        config = sqlite.Config(database=Path(directory) / "app.db")
        async with aiosqlite.connect(str(config.database)) as app:
            await app.executescript("""
                CREATE TABLE other(value TEXT);
                INSERT INTO other VALUES('kept');
                CREATE INDEX entry_title ON other(value);
            """)
        async with migrations.connect(config) as target:
            with assert_raises(migrations.PackageError) as error:
                await target.apply(await target.prepare(package))
            assert_true("postcondition" in str(error.exception))
            assert_eq(await target.status(), ())
        async with aiosqlite.connect(str(config.database)) as app:
            assert_eq(
                await (await app.execute("SELECT value FROM other")).fetchall(),
                [("kept",)],
            )
            assert_eq(
                await (
                    await app.execute(
                        "SELECT name FROM sqlite_schema WHERE name='entry'"
                    )
                ).fetchall(),
                [],
            )
            assert_eq(
                await (
                    await app.execute(
                        "SELECT tbl_name FROM sqlite_schema WHERE name='entry_title'"
                    )
                ).fetchall(),
                [("other",)],
            )


@test(mark="medium")
async def failed_postcondition_rolls_back_backfill_and_preserves_prior_history() -> (
    None
):
    """Endpoint rejection rolls back the whole package, not just its final receipt."""
    first = migrations.compile(migrations.generate("001", [Entry], backend="sqlite"))
    added = first.target.tables[0].model_copy(
        update={
            "name": "new_entry",
            "quoted_name": '"new_entry"',
            "sql": first.target.tables[0].sql.replace('"entry"', '"new_entry"'),
            "indexes": (
                'CREATE UNIQUE INDEX IF NOT EXISTS "occupied" ON "new_entry" ("title")',
            ),
        }
    )
    draft = migrations.Draft(
        revision="002",
        predecessor=first.digest,
        before=first.target,
        target=migrations.State(backend="sqlite", tables=(*first.target.tables, added)),
        operations=(
            migrations.CreateTable(table=added),
            migrations.Checkpoint(name="backfill"),
        ),
    )
    package = migrations.compile(
        draft.then(
            migrations.DataChange.from_query(
                sqlite.update(Entry).set(Entry.title.to("must roll back")).all(),
                checkpoint="backfill",
                contract_digest=migrations.contract_digest(draft, point="backfill"),
            )
        )
    )
    with TemporaryDirectory() as directory:
        config = sqlite.Config(database=Path(directory) / "app.db")
        async with aiosqlite.connect(str(config.database)) as app:
            await app.executescript(
                "CREATE TABLE other(value TEXT); CREATE INDEX occupied ON other(value);"
            )
        async with migrations.connect(config) as target:
            await target.apply(await target.prepare(first))
            async with aiosqlite.connect(str(config.database)) as app:
                await app.execute("INSERT INTO entry VALUES(1,'kept')")
                await app.commit()
            with assert_raises(migrations.PackageError):
                await target.apply(await target.prepare(package))
            assert_eq([p.revision for p in await target.status()], ["001"])
            assert_eq(
                await target.apply(await target.prepare(first)), "already_applied"
            )
        async with (
            await sqlite.Database.initialize(config) as db,
            db.transaction() as tx,
        ):
            assert_eq(await tx.fetch_all(sqlite.select(Entry.title)), ["kept"])
            assert_eq(
                await tx.fetch_all(
                    sqlite.raw("SELECT name FROM sqlite_schema WHERE name='new_entry'")
                ),
                [],
            )


@test(mark="medium")
async def sqlite_postcondition_accepts_a_materialized_conditional_index() -> None:
    """IF NOT EXISTS is an execution guard, not a persistent index property."""
    draft = migrations.generate("001", [Entry], backend="sqlite")
    table = draft.target.tables[0].model_copy(
        update={
            "indexes": (
                'CREATE UNIQUE INDEX IF NOT EXISTS "entry_title" ON "entry" ("title")',
            )
        }
    )
    package = migrations.compile(
        draft.model_copy(
            update={
                "target": migrations.State(backend="sqlite", tables=(table,)),
                "operations": (migrations.CreateTable(table=table),),
            }
        )
    )
    with TemporaryDirectory() as directory:
        config = sqlite.Config(database=Path(directory) / "app.db")
        async with migrations.connect(config) as target:
            assert_eq(await target.apply(await target.prepare(package)), "applied")
        async with aiosqlite.connect(str(config.database)) as app:
            await app.execute("INSERT INTO entry VALUES(1,'one')")
            with assert_raises(aiosqlite.IntegrityError):
                await app.execute("INSERT INTO entry VALUES(2,'one')")


@test(mark="medium")
async def sqlite_wrong_construction_owner_refuses_before_execution() -> None:
    """Wrong-owner construction is refused before creating objects or recording history."""
    draft = migrations.generate("001", [Entry], backend="sqlite")
    table = draft.target.tables[0].model_copy(
        update={
            "sql": draft.target.tables[0].sql.replace('"entry"', '"wrong_table"'),
        }
    )
    with TemporaryDirectory() as directory:
        config = sqlite.Config(database=Path(directory) / "app.db")
        async with migrations.connect(config) as target:
            with assert_raises(migrations.PackageError) as error:
                migrations.compile(
                    draft.model_copy(
                        update={
                            "target": migrations.State(
                                backend="sqlite", tables=(table,)
                            ),
                            "operations": (migrations.CreateTable(table=table),),
                        }
                    )
                )
            assert_true("construction header" in str(error.exception))
            assert_eq(await target.status(), ())
        async with aiosqlite.connect(str(config.database)) as app:
            assert_eq(
                await (await app.execute("SELECT name FROM sqlite_schema")).fetchall(),
                [],
            )


@test(mark="medium")
async def managed_constraint_occurrences_cannot_disappear_during_preservation_review() -> (
    None
):
    """Repeated declarations remain recorded facts, not a deduplicated token set."""
    draft = migrations.generate("001", [Entry], backend="sqlite")
    table = draft.target.tables[0]
    sql = table.sql.removesuffix(") STRICT")
    check = ", CHECK(length(title)>0)"
    table = table.model_copy(update={"sql": sql + check + check + ") STRICT"})
    first = migrations.compile(
        draft.model_copy(
            update={
                "target": migrations.State(backend="sqlite", tables=(table,)),
                "operations": (migrations.CreateTable(table=table),),
            }
        )
    )
    next_package = migrations.compile(
        migrations.Draft(
            revision="002",
            predecessor=first.digest,
            before=first.target,
            target=first.target,
            operations=(),
        )
    )
    with TemporaryDirectory() as directory:
        config = sqlite.Config(database=Path(directory) / "app.db")
        async with migrations.connect(config) as target:
            await target.apply(await target.prepare(first))
            async with aiosqlite.connect(str(config.database)) as app:
                await app.execute("DROP TABLE entry")
                await app.execute(sql + check + ") STRICT")
            with assert_raises(migrations.PackageError):
                await target.prepare(next_package, preserve_unmanaged=True)
            assert_eq([p.revision for p in await target.status()], ["001"])


class StreetNames[S = sqlite.Pending](sqlite.Model[S]):
    """SQLite distinguishes these identifiers even though Unicode casefold does not."""

    __tablename__ = "street_names"
    __row_type__: ClassVar[sqlite.ReadType[StreetNames[sqlite.Row]]]
    id: sqlite.Col[int] = sqlite.Integer(primary_key=True)
    straße: sqlite.Col[str] = sqlite.Text()  # noqa: PLC2401 - distinct SQLite identifier under test
    strasse: sqlite.Col[str] = sqlite.Text()


@test(mark="medium")
async def sqlite_adoption_does_not_fold_distinct_unicode_index_columns() -> None:
    """An index on strasse does not establish the promised uniqueness of straße."""
    draft = migrations.generate("001", [StreetNames], backend="sqlite")
    table = draft.target.tables[0].model_copy(
        update={
            "indexes": (
                'CREATE UNIQUE INDEX "unique_street" ON "street_names" (straße)',
            )
        }
    )
    draft = draft.model_copy(
        update={
            "target": migrations.State(backend="sqlite", tables=(table,)),
            "operations": (migrations.CreateTable(table=table),),
        }
    )
    package = migrations.compile(draft.adopt("street_names"))
    with TemporaryDirectory() as directory:
        config = sqlite.Config(database=Path(directory) / "app.db")
        async with aiosqlite.connect(str(config.database)) as app:
            await app.execute(table.sql)
            await app.execute(
                'CREATE UNIQUE INDEX "unique_street" ON "street_names" (strasse)'
            )
            await app.execute(
                "INSERT INTO street_names VALUES(1,'same','one'),(2,'same','two')"
            )
            await app.commit()
        async with migrations.connect(config) as target:
            with assert_raises(migrations.PackageError):
                await target.prepare(package)
            assert_eq(await target.status(), ())


@test(mark="medium")
async def sqlite_adoption_keeps_ascii_case_insensitivity_inside_unicode_names() -> None:
    """ASCII case changes are harmless even when the identifier contains sharp s."""
    draft = migrations.generate("001", [StreetNames], backend="sqlite")
    table = draft.target.tables[0].model_copy(
        update={
            "indexes": (
                'CREATE UNIQUE INDEX "unique_street" ON "street_names" (straße)',
            )
        }
    )
    package = migrations.compile(
        draft.model_copy(
            update={
                "target": migrations.State(backend="sqlite", tables=(table,)),
                "operations": (migrations.CreateTable(table=table),),
            }
        ).adopt("street_names")
    )
    with TemporaryDirectory() as directory:
        config = sqlite.Config(database=Path(directory) / "app.db")
        async with aiosqlite.connect(str(config.database)) as app:
            await app.execute(table.sql)
            await app.execute(
                'create unique index "unique_street" on "street_names" (STRAßE)'
            )
        async with migrations.connect(config) as target:
            assert_eq(await target.apply(await target.prepare(package)), "applied")
            assert_eq([p.revision for p in await target.status()], ["001"])
        async with aiosqlite.connect(str(config.database)) as app:
            await app.execute("INSERT INTO street_names VALUES(1,'same','one')")
            with assert_raises(aiosqlite.IntegrityError):
                await app.execute("INSERT INTO street_names VALUES(2,'same','two')")
