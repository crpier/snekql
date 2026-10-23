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
