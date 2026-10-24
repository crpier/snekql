"""Generated default contracts through public native deployment seams."""

from typing import ClassVar

from snektest import Param, assert_eq, assert_raises, load_fixture, test

from snekql import mariadb
from snekql.experimental import migrations as m
from snekql.mariadb import UtcDatetime
from tests.experimental.test_migration_targets import provide_package_server


class Defaults[S = mariadb.Pending](mariadb.Model[S]):
    """The finite ordinary generated server-default surface."""

    __row_type__: ClassVar[mariadb.ReadType[Defaults[mariadb.Row]]]
    id: mariadb.Col[int] = mariadb.Integer(primary_key=True)
    number: mariadb.GenCol[int] = mariadb.Integer(default=mariadb.LiteralDefault(7))
    flag: mariadb.GenCol[bool] = mariadb.Boolean(default=mariadb.LiteralDefault(True))
    label: mariadb.GenCol[str] = mariadb.Text(default=mariadb.LiteralDefault("seed"))
    nullable_text: mariadb.GenCol[str | None] = mariadb.Text(
        nullable=True, default=mariadb.LiteralDefault("NULL")
    )
    collated: mariadb.GenCol[str] = mariadb.Text(
        collation="utf8mb4_general_ci", default=mariadb.LiteralDefault("Case")
    )
    empty: mariadb.GenCol[str] = mariadb.Text(default=mariadb.LiteralDefault(""))
    clock_text: mariadb.GenCol[UtcDatetime] = mariadb.Text(
        default=mariadb.CurrentTimestamp
    )
    escaped: mariadb.GenCol[str] = mariadb.Text(
        default=mariadb.LiteralDefault("A'\\é\0 DEFAULT")
    )
    minimum: mariadb.GenCol[int] = mariadb.Integer(
        default=mariadb.LiteralDefault(-9223372036854775808)
    )
    clock: mariadb.GenCol[UtcDatetime] = mariadb.DateTime(
        default=mariadb.CurrentTimestamp
    )


@test(
    [
        Param(value="number", name="integer"),
        Param(value="flag", name="boolean"),
        Param(value="label", name="text"),
        Param(value="clock", name="clock"),
        Param(value="clock_text", name="clock-text-vs-literal"),
        Param(value="nullable_text", name="literal-null-vs-sql-null"),
        Param(value="collated", name="case-insensitive-collation"),
    ],
    mark="slow",
)
async def recorded_default_mismatch_should_not_certify(name: str) -> None:
    """Recorded generated defaults guard both completion and recovery finish."""
    server = await load_fixture(provide_package_server())
    draft = m.generate("001", [Defaults], backend="mariadb")
    table = draft.target.tables[0]
    column = next(c for c in table.columns if c.name == name)
    replacement = (
        column.definition.split(" DEFAULT ")[0]
        + {
            "number": " DEFAULT 8",
            "flag": " DEFAULT 0",
            "label": " DEFAULT 'other'",
            "clock": "",
            "nullable_text": " DEFAULT NULL",
            "collated": " DEFAULT 'case'",
            "clock_text": " DEFAULT 'concat(replace(current_timestamp(6),'' '',''T''),''Z'')'",
        }[name]
    )
    assert table.sql.count(column.definition) == 1
    table = table.model_copy(
        update={"sql": table.sql.replace(column.definition, replacement)}
    )
    package = m.compile(
        draft.model_copy(
            update={
                "target": draft.target.model_copy(update={"tables": (table,)}),
                "operations": (m.CreateTable(table=table),),
            }
        )
    )
    async with m.connect(server.config()) as target:
        plan = await target.prepare(package, schema_writers_excluded=True)
        with assert_raises(m.PackageError) as error:
            await target.apply(plan)
        assert "default" in str(error.exception).lower()
        assert_eq((await target.status())[0].phase, "uncertain")
    async with m.connect(server.config()) as target:
        recovery = await target.inspect_recovery(plan, schema_writers_excluded=True)
        assert_eq(recovery.disposition, "ambiguous")
        assert "default" in recovery.explanation.lower()
        with assert_raises(m.PackageError):
            await target.resume(recovery, schema_writers_excluded=True)


@test(mark="slow")
async def generated_defaults_round_trip_and_deploy_without_models() -> None:
    """The compiler's ordinary literal/clock forms remain executable as frozen packages."""
    server = await load_fixture(provide_package_server())
    package = m.Package.load(
        m.compile(m.generate("001", [Defaults], backend="mariadb")).dump()
    )
    async with m.connect(server.config()) as target:
        plan = await target.prepare(package, schema_writers_excluded=True)
        assert_eq(await target.apply(plan), "applied")
        assert_eq(await target.apply(plan), "already_applied")
        assert_eq((await target.status())[0].phase, "complete")


@test(mark="slow")
async def unsupported_default_expressions_fail_preparation_without_history() -> None:
    """Unknown expressions are refused, not evaluated or treated as verified defaults."""
    server = await load_fixture(provide_package_server())
    for expression in (
        "(CAST(7 AS SIGNED))",
        "(coalesce(NULL,7))",
        "(rand())",
        "7 + 1",
        "7--1",
    ):
        draft = m.generate("001", [Defaults], backend="mariadb")
        table = draft.target.tables[0]
        columns = tuple(
            c.model_copy(
                update={"definition": "`number` BIGINT NOT NULL DEFAULT " + expression}
            )
            if c.name == "number"
            else c
            for c in table.columns
        )
        table = table.model_copy(update={"columns": columns})
        package = m.compile(
            draft.model_copy(
                update={
                    "target": draft.target.model_copy(update={"tables": (table,)}),
                    "operations": (m.CreateTable(table=table),),
                }
            )
        )
        async with m.connect(server.config()) as target:
            with assert_raises(m.PackageError) as error:
                await target.prepare(package, schema_writers_excluded=True)
            assert "DEFAULT" in str(error.exception)
            assert_eq(await target.status(), ())


class NoDefaults[S = mariadb.Pending](mariadb.Model[S]):
    """Absence claims exclude non-NULL defaults without promising omission success."""

    __row_type__: ClassVar[mariadb.ReadType[NoDefaults[mariadb.Row]]]
    id: mariadb.Col[int] = mariadb.Integer(primary_key=True)
    required: mariadb.Col[int] = mariadb.Integer()
    optional: mariadb.Col[int | None] = mariadb.Integer(nullable=True)


@test(
    [
        Param(value="required", name="required"),
        Param(value="optional", name="nullable"),
    ],
    mark="slow",
)
async def absent_default_claim_refuses_a_hidden_native_default(name: str) -> None:
    """A surviving scalar default cannot certify an absence claim or recovery finish."""
    server = await load_fixture(provide_package_server())
    draft = m.generate("001", [NoDefaults], backend="mariadb")
    table = draft.target.tables[0]
    column = next(c for c in table.columns if c.name == name)
    table = table.model_copy(
        update={
            "sql": table.sql.replace(
                column.definition, column.definition + " DEFAULT 7"
            )
        }
    )
    package = m.Package.load(
        m.compile(
            draft.model_copy(
                update={
                    "target": draft.target.model_copy(update={"tables": (table,)}),
                    "operations": (m.CreateTable(table=table),),
                }
            )
        ).dump()
    )
    async with m.connect(server.config()) as target:
        plan = await target.prepare(package, schema_writers_excluded=True)
        with assert_raises(m.PackageError) as error:
            await target.apply(plan)
        assert "default" in str(error.exception).lower()
        assert_eq((await target.status())[0].phase, "uncertain")
    async with m.connect(server.config()) as target:
        recovery = await target.inspect_recovery(plan, schema_writers_excluded=True)
        assert_eq(recovery.disposition, "ambiguous")
        with assert_raises(m.PackageError):
            await target.resume(recovery, schema_writers_excluded=True)


@test(
    [
        Param(value="implicit", name="implicit-null"),
        Param(value="explicit", name="explicit-null"),
    ],
    mark="slow",
)
async def absent_defaults_accept_native_nullable_null_and_detect_later_drift(
    explicit: str,
) -> None:
    """Nullable absence is effective NULL; required omission remains session-dependent."""
    server = await load_fixture(provide_package_server())
    draft = m.generate("001", [NoDefaults], backend="mariadb")
    table = draft.target.tables[0]
    if explicit == "explicit":
        column = next(c for c in table.columns if c.name == "optional")
        table = table.model_copy(
            update={
                "sql": table.sql.replace(
                    column.definition, column.definition + " DEFAULT NULL"
                )
            }
        )
        draft = draft.model_copy(
            update={
                "target": draft.target.model_copy(update={"tables": (table,)}),
                "operations": (m.CreateTable(table=table),),
            }
        )
    package = m.Package.load(m.compile(draft).dump())
    async with m.connect(server.config()) as target:
        plan = await target.prepare(package, schema_writers_excluded=True)
        assert_eq(await target.apply(plan), "applied")
        assert_eq(await target.apply(plan), "already_applied")
    async with (
        await mariadb.Database.initialize(server.config()) as database,
        database.transaction() as transaction,
    ):
        await transaction.execute(
            mariadb.raw(
                f"INSERT INTO {table.quoted_name} (`id`, `required`) VALUES (1, 42)"
            )
        )
        assert_eq(
            await transaction.fetch_all(
                mariadb.raw(f"SELECT `required`, `optional` FROM {table.quoted_name}")
            ),
            [{"required": 42, "optional": None}],
        )
    # A later native change must be caught while preparing the next revision,
    # not merely when certifying an initially inconsistent CREATE statement.
    await server.run_sql(
        f"ALTER TABLE {table.quoted_name} ALTER COLUMN `optional` SET DEFAULT 7"
    )
    followup = m.compile(
        m.Draft(
            revision="002",
            predecessor=package.digest,
            before=package.target,
            target=package.target,
            operations=(),
        )
    )
    async with m.connect(server.config()) as target:
        with assert_raises(m.PackageError):
            await target.prepare(followup, schema_writers_excluded=True)
        assert_eq(len(await target.status()), 1)
