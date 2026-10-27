"""Original reviewed plans cross a worker boundary without reconstructing execution."""

import hashlib
import json
import shutil
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, ClassVar, Literal

import aiosqlite
from snektest import Param, assert_eq, assert_raises, test

from snekql import sqlite
from snekql.experimental import migrations as m
from tests.experimental.test_migration_authoring_journey import _python, _typecheck

_FIXTURES = Path(__file__).parent / "fixtures"


class Initial[S = sqlite.Pending](sqlite.Model[S]):
    """The ordinary application before its already-authored role transition."""

    __tablename__ = "accounts"
    __row_type__: ClassVar[sqlite.ReadType[Initial[sqlite.Row]]]
    id: sqlite.Col[int] = sqlite.Integer(primary_key=True)
    is_admin: sqlite.Col[bool] = sqlite.Integer()


class Account[S = sqlite.Pending](sqlite.Model[S]):
    """Current query mapping remains independent of migration ownership."""

    __tablename__ = "accounts"
    __row_type__: ClassVar[sqlite.ReadType[Account[sqlite.Row]]]
    id: sqlite.Col[int] = sqlite.Integer(primary_key=True)
    role: sqlite.Col[str] = sqlite.Text()
    note: sqlite.Col[str | None] = sqlite.Text(nullable=True)


@test(mark="slow")
async def original_deferred_role_plan_is_persisted_and_applied_by_replacement_worker() -> (
    None
):
    """Frozen contraction, preservation and target identity survive a process boundary."""
    with TemporaryDirectory() as directory:
        root = Path(directory)
        config = sqlite.Config(database=root / "app.db")
        historical = _FIXTURES / "framework-evolution" / "sqlite"
        async with m.connect(config) as target:
            first = m.Package.load((historical / "001_accounts.json").read_text())
            await target.apply(await target.prepare(first))
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
            expanded = m.Package.load((historical / "002_roles.json").read_text())
            await target.apply(await target.prepare(expanded))
        async with aiosqlite.connect(str(config.database)) as outside:
            await outside.execute(
                "ALTER TABLE accounts ADD COLUMN note TEXT DEFAULT 'kept'"
            )
            await outside.commit()
        async with m.connect(config) as target:
            package = m.Package.load((historical / "003_contract.json").read_text())
            original = await target.prepare(package, preserve_unmanaged=True)
            assert any(step.rebuild for step in original.steps)
            text = original.dump()
            restored = m.Prepared.load(text)
            assert_eq(restored, original)
            assert_eq(restored.dump(), text)
            assert_eq(restored.execution_epoch, 1)
            (root / "original-plan.json").write_text(text)
            before = await target.status()
        shutil.copyfile(
            _FIXTURES / "prepared-evidence" / "apply.py.in", root / "apply.py"
        )
        code, diagnostics = await _typecheck(root, root)
        assert_eq(code, 0, msg=diagnostics)
        completed = json.loads(
            await _python(root / "apply.py", {"database": str(config.database)})
        )
        assert_eq(completed["outcome"], "applied")
        assert_eq(completed["execution_epoch"], 1)
        assert_eq(completed["lazy_imports"], sys.get_lazy_imports())
        assert_eq((root / "original-plan.json").read_text(), text)
        async with m.connect(config) as target:
            progress = await target.status()
            assert_eq(len(progress), len(before) + 1)
            assert_eq({p.phase for p in progress}, {"complete"})
        async with (
            await sqlite.Database.initialize(config) as app,
            app.transaction() as tx,
        ):
            rows = await tx.fetch_all(sqlite.select(Account).order_by(Account.id.asc()))
        assert_eq(
            [(r.id, r.role, r.note) for r in rows],
            [(1, "admin", "kept"), (2, "user", "kept")],
        )


def _reseal(payload: dict[str, Any]) -> str:
    """Act as an independent publisher; a valid checksum is not schema admission."""
    body = {"version": payload["version"], "prepared": payload["prepared"]}
    canonical = json.dumps(
        body, sort_keys=True, ensure_ascii=False, separators=(",", ":")
    )
    payload["digest"] = hashlib.sha256(canonical.encode()).hexdigest()
    return json.dumps(payload)


type Refusal = Literal[
    "version",
    "epoch",
    "coerced_epoch",
    "missing_epoch",
    "raw_json",
    "duplicate",
    "package_version",
    "implicit_policy",
]


@test(
    [
        Param[Refusal](value=case, name=case)
        for case in (
            "version",
            "epoch",
            "coerced_epoch",
            "missing_epoch",
            "raw_json",
            "duplicate",
            "package_version",
            "implicit_policy",
        )
    ],
    mark="medium",
)
async def incompatible_or_corrupt_prepared_evidence_never_mutates_target(
    case: Refusal,
) -> None:
    """Wire admission precedes execution; fresh history is not manufactured on refusal."""
    with TemporaryDirectory() as directory:
        config = sqlite.Config(database=Path(directory) / "app.db")
        package = m.compile(m.generate("001", [Initial], backend="sqlite"))
        async with m.connect(config) as target:
            original = await target.prepare(package)
            text = original.dump()
            value = json.loads(text)
            expected = "integrity"
            if case == "version":
                value["version"] = 2
                expected = "version"
            elif case == "epoch":
                value["prepared"]["execution_epoch"] = 2
                expected = "epoch"
            elif case == "coerced_epoch":
                value["prepared"]["execution_epoch"] = True
                expected = "epoch"
            elif case == "missing_epoch":
                del value["prepared"]["execution_epoch"]
                expected = "epoch"
            elif case == "package_version":
                value["prepared"]["package"]["version"] = 2.0
                expected = "package version"
            elif case == "implicit_policy":
                del value["prepared"]["steps"][0]["transactional"]
                expected = "explicit representation"
            text = json.dumps(value)
            if case in {"package_version", "implicit_policy"}:
                text = _reseal(value)
            elif case == "raw_json":
                text = original.model_dump_json()
                expected = "envelope"
            elif case == "duplicate":
                text = text.removesuffix("}") + ', "version": 1}'
                expected = "duplicate"
            with assert_raises(m.PackageError) as error:
                await target.apply(m.Prepared.load(text))
            assert expected in str(error.exception)
            assert_eq(await target.status(), ())
        async with aiosqlite.connect(str(config.database)) as outside:
            assert_eq(
                await outside.execute_fetchall("SELECT name FROM sqlite_schema"), []
            )


@test(mark="medium")
async def valid_prepared_evidence_stays_bound_to_original_target() -> None:
    """Export/import does not grant permission to execute on a different database."""
    with TemporaryDirectory() as directory:
        first = sqlite.Config(database=Path(directory) / "first.db")
        second = sqlite.Config(database=Path(directory) / "second.db")
        package = m.compile(m.generate("001", [Initial], backend="sqlite"))
        async with m.connect(first) as target:
            text = (await target.prepare(package)).dump()
        async with m.connect(second) as wrong:
            with assert_raises(m.PackageError) as error:
                await wrong.apply(m.Prepared.load(text))
            assert "another target" in str(error.exception)
            assert_eq(await wrong.status(), ())
        async with m.connect(first) as correct:
            assert_eq(await correct.apply(m.Prepared.load(text)), "applied")


@test(
    [
        Param[Literal["steps", "catalog_digest", "preserve_unmanaged"]](
            value=field, name=field
        )
        for field in ("steps", "catalog_digest", "preserve_unmanaged")
    ],
    mark="medium",
)
async def prepared_integrity_covers_execution_observation_and_preservation(
    field: Literal["steps", "catalog_digest", "preserve_unmanaged"],
) -> None:
    """Changing retained execution evidence cannot silently produce a different plan."""
    with TemporaryDirectory() as directory:
        config = sqlite.Config(database=Path(directory) / "app.db")
        package = m.compile(m.generate("001", [Initial], backend="sqlite"))
        async with m.connect(config) as target:
            text = (await target.prepare(package)).dump()
            value = json.loads(text)
            replacements = {
                "steps": [],
                "catalog_digest": "different",
                "preserve_unmanaged": True,
            }
            value["prepared"][field] = replacements[field]
            with assert_raises(m.PackageError) as error:
                await target.apply(m.Prepared.load(json.dumps(value)))
            assert "integrity" in str(error.exception)
            assert_eq(await target.status(), ())


@test(mark="medium")
async def persisted_plan_reader_has_the_same_bounded_wire_input_contract() -> None:
    """Oversized/deep evidence is refused before nested model or package validation."""
    with TemporaryDirectory() as directory:
        config = sqlite.Config(database=Path(directory) / "app.db")
        package = m.compile(m.generate("001", [Initial], backend="sqlite"))
        async with m.connect(config) as target:
            plan = await target.prepare(package)
        text = plan.dump()
        boundary = text + " " * (8 * 1024 * 1024 - len(text.encode()))
        assert_eq(m.Prepared.load(boundary), plan)
        for wire, diagnostic in (
            (boundary + " ", "byte limit"),
            ("[" * 65 + "0" + "]" * 65, "nesting limit"),
            ("[" + ",".join("0" for _ in range(100001)) + "]", "structure limit"),
        ):
            with assert_raises(m.PackageError) as error:
                m.Prepared.load(wire)
            assert diagnostic in str(error.exception)


@test(mark="medium")
def first_prepared_wire_epoch_keeps_actual_original_contraction_bytes() -> None:
    """A literal first-writer artifact is not regenerated to accommodate a later reader."""
    text = (
        _FIXTURES / "prepared-evidence" / "sqlite-role-contraction.json"
    ).read_text()
    original = m.Prepared.load(text)
    assert_eq(original.dump(), text)
    assert_eq(original.execution_epoch, 1)
    assert_eq(original.preserve_unmanaged, True)
    assert any(step.rebuild and "note" in step.copy_columns for step in original.steps)
    assert_eq(
        original.package.dump(),
        (
            _FIXTURES / "framework-evolution" / "sqlite" / "003_contract.json"
        ).read_text(),
    )


@test(mark="medium")
def persisted_plan_version_must_be_explicit_and_not_coerced() -> None:
    """Wire metadata selects a reader, not Pydantic defaults or numeric equality."""
    text = (
        _FIXTURES / "prepared-evidence" / "sqlite-role-contraction.json"
    ).read_text()
    for version in (None, True, 1.0, "1", 2):
        value = json.loads(text)
        if version is None:
            del value["version"]
        else:
            value["version"] = version
        with assert_raises(m.PackageError) as error:
            m.Prepared.load(json.dumps(value))
        assert "version" in str(error.exception)
