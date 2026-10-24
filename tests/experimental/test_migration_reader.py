"""Frozen deployment input has explicit, bounded decoding rules."""

import asyncio
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from snektest import assert_eq, assert_raises, test

from snekql import sqlite
from snekql.experimental import migrations as m


@test(mark="fast")
def duplicate_package_keys_are_not_silently_resolved() -> None:
    """Different JSON readers must not choose different package versions."""
    package = m.compile(m.generate("001", [], backend="sqlite"))
    text = package.dump().replace('"version": 2', '"version": 999, "version": 2')
    with assert_raises(m.PackageError) as error:
        m.Package.load(text)
    assert "duplicate" in str(error.exception)
    assert_eq(m.Package.load(package.dump()), package)


@test(mark="fast")
def package_version_is_explicit_and_not_coerced() -> None:
    """Omission or numeric coercion must not silently select a compiler epoch."""
    package = m.compile(m.generate("001", [], backend="sqlite"))
    for version in (None, 2.0, "2", 1, 4.0, 5.0, 6.0, 7.0, 8):
        payload = json.loads(package.dump())
        if version is None:
            del payload["version"]
        else:
            payload["version"] = version
        with assert_raises(m.PackageError) as error:
            m.Package.load(json.dumps(payload))
        assert "version" in str(error.exception)


@test(mark="fast")
def package_input_has_an_eight_mib_utf8_budget() -> None:
    """Whitespace counts too: compact decoded data is not a wire-size exemption."""
    package = m.compile(m.generate("001", [], backend="sqlite"))
    text = package.dump()
    boundary = text + " " * (8 * 1024 * 1024 - len(text))
    assert_eq(m.Package.load(boundary), package)
    with assert_raises(m.PackageError) as error:
        m.Package.load(boundary + " ")
    assert "byte limit" in str(error.exception)


@test(mark="fast")
def package_nesting_is_bounded_before_schema_decoding() -> None:
    """Invalid deeply nested values receive a stable error, not parser recursion."""
    for levels in (65, 2000):
        text = '{"version":2,"unknown":' + "[" * levels + "0" + "]" * levels + "}"
        with assert_raises(m.PackageError) as error:
            m.Package.load(text)
        assert "nesting limit" in str(error.exception)
    package = m.compile(m.generate('escaped"\\' + "[" * 100, [], backend="sqlite"))
    assert_eq(m.Package.load(package.dump()), package)


@test(mark="fast")
def package_structural_work_is_bounded_before_schema_decoding() -> None:
    """Wide arrays cannot bypass the input's structural budget with tiny values."""
    text = '{"version":2,"unknown":[' + ",".join("0" for _ in range(100001)) + "]}"
    with assert_raises(m.PackageError) as error:
        m.Package.load(text)
    assert "structure limit" in str(error.exception)


@test(mark="fast")
def package_byte_budget_counts_multibyte_text() -> None:
    """The budget is UTF-8 bytes, not Python code points."""
    text = '{"version":2,"unknown":"' + "é" * (4 * 1024 * 1024) + '"}'
    with assert_raises(m.PackageError) as error:
        m.Package.load(text)
    assert "byte limit" in str(error.exception)


@test(mark="fast")
def nested_duplicate_keys_are_rejected_after_json_unescaping() -> None:
    """The uniqueness rule applies to decoded names inside historical state too."""
    package = m.compile(m.generate("001", [], backend="sqlite"))
    text = package.dump().replace(
        '"revision": "001"', '"revision": "ignored", "revis\\u0069on": "001"'
    )
    with assert_raises(m.PackageError) as error:
        m.Package.load(text)
    assert "duplicate" in str(error.exception)


@test(mark="medium")
async def prior_writer_packages_deploy_without_their_models() -> None:
    """A fixed old writer's bytes retain identity and execute a recorded chain."""
    root = Path(__file__).parent / "fixtures" / "format2"
    first = m.Package.load(await asyncio.to_thread((root / "001.json").read_text))
    second = m.Package.load(await asyncio.to_thread((root / "002.json").read_text))
    assert_eq(
        first.digest, "b3347011d819151583e88bb64e8cf7516a105d15ce3221fe653333d5432c1389"
    )
    assert_eq(
        second.digest,
        "2fa94d43755cd8bae4d4cb1dfc1c0fd315b69c0c512a71f8ae307f7d041d9d12",
    )
    assert_eq(second.draft.predecessor, first.digest)
    third = m.Package.load(await asyncio.to_thread((root / "003.json").read_text))
    assert_eq(
        third.digest, "4d7ad269242d5e41585f5016becb0f8d3b78b6d12e9af2ef00c08e3f5ba00004"
    )
    assert_eq(third.draft.predecessor, second.digest)
    with TemporaryDirectory() as directory:
        config = sqlite.Config(database=Path(directory) / "recorded.db")
        async with m.connect(config) as target:
            assert_eq(await target.apply(await target.prepare(first)), "applied")
        async with (
            await sqlite.Database.initialize(config) as database,
            database.transaction() as transaction,
        ):
            await transaction.execute(sqlite.raw("INSERT INTO recorded(id) VALUES (1)"))
        async with m.connect(config) as target:
            assert_eq(await target.apply(await target.prepare(second)), "applied")
            assert_eq(
                await target.apply(await target.prepare(second)), "already_applied"
            )
            assert_eq({item.phase for item in await target.status()}, {"complete"})
        async with (
            await sqlite.Database.initialize(config) as database,
            database.transaction() as transaction,
        ):
            await transaction.execute(sqlite.raw("UPDATE recorded SET note='filled'"))
        async with m.connect(config) as target:
            assert_eq(await target.apply(await target.prepare(third)), "applied")
        async with (
            await sqlite.Database.initialize(config) as database,
            database.transaction() as transaction,
        ):
            assert_eq(
                await transaction.fetch_all(
                    sqlite.raw("SELECT id, count, note FROM recorded")
                ),
                [{"id": 1, "count": 7, "note": "filled"}],
            )


@test(mark="fast")
def serialized_operations_require_explicit_kinds() -> None:
    """A reader must not select operations through union order or default fields."""
    package = m.compile(
        m.generate("001", [], backend="sqlite").then(m.Checkpoint(name="ready"))
    )
    payload = json.loads(package.dump())
    del payload["draft"]["operations"][0]["kind"]
    with assert_raises(m.PackageError) as error:
        m.Package.load(json.dumps(payload))
    assert "explicit kind" in str(error.exception)


@test(mark="medium")
async def prior_format_three_composition_retains_identity_and_deploys() -> None:
    """Old explicit composition remains executable when new generation learns it."""
    root = Path(__file__).parent / "fixtures" / "format3"
    first = m.Package.load(await asyncio.to_thread((root / "001.json").read_text))
    second = m.Package.load(await asyncio.to_thread((root / "002.json").read_text))
    assert_eq(
        first.digest, "9b6fe83e9a0f4dac823c5d26b2001cdf36ba5d578838c730752b174da9b482c5"
    )
    assert_eq(
        second.digest,
        "0dd3db18f19647b3e10f08abd913f33999859273cd8c9123f76f51fab3d6ab52",
    )
    assert_eq(second.version, 3)
    assert_eq(second.draft.predecessor, first.digest)
    with TemporaryDirectory() as directory:
        config = sqlite.Config(database=Path(directory) / "defaults.db")
        async with m.connect(config) as target:
            await target.apply(await target.prepare(first))
        async with (
            await sqlite.Database.initialize(config) as database,
            database.transaction() as transaction,
        ):
            await transaction.execute(
                sqlite.raw("INSERT INTO settings(id,value) VALUES(1,42)")
            )
        async with m.connect(config) as target:
            assert_eq(await target.apply(await target.prepare(second)), "applied")
            assert_eq(
                await target.apply(await target.prepare(second)), "already_applied"
            )
            assert_eq({item.phase for item in await target.status()}, {"complete"})
        async with (
            await sqlite.Database.initialize(config) as database,
            database.transaction() as transaction,
        ):
            await transaction.execute(sqlite.raw("INSERT INTO settings(id) VALUES(2)"))
            assert_eq(
                await transaction.fetch_all(
                    sqlite.raw("SELECT value FROM settings ORDER BY id")
                ),
                [{"value": 42}, {"value": 8}],
            )
