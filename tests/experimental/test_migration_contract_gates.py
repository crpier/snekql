"""Preparation refuses generated physical claims without endpoint support."""

from typing import ClassVar

from snektest import Param, assert_eq, assert_raises, load_fixture, test

from snekql import mariadb
from snekql.experimental import migrations as m
from tests.experimental.test_migration_targets import provide_package_server


class Checked[S = mariadb.Pending](mariadb.Model[S]):
    """An ordinary generated CHECK must not be mistaken for JSON validity proof."""

    __row_type__: ClassVar[mariadb.ReadType[Checked[mariadb.Row]]]
    value: mariadb.Col[int] = mariadb.Integer()

    @classmethod
    def __checks__(cls) -> list[mariadb.CheckConstraint[Checked[S]]]:
        return [mariadb.CheckConstraint(cls.value.gte(0), name="ck_positive")]


@test(mark="slow")
async def generated_general_checks_can_complete() -> None:
    """A frozen generated CHECK contract can be deployed and verified."""
    server = await load_fixture(provide_package_server())
    package = m.compile(m.generate("001", [Checked], backend="mariadb"))
    async with m.connect(server.config()) as target:
        plan = await target.prepare(
            m.Package.load(package.dump()), schema_writers_excluded=True
        )
        await target.apply(plan)
        assert_eq((await target.status())[0].phase, "complete")
    async with await mariadb.Database.initialize(server.config()) as database:
        async with database.transaction() as transaction:
            await transaction.execute(mariadb.insert(Checked(value=5)))
            assert_eq(await transaction.fetch_all(mariadb.select(Checked.value)), [5])
        with assert_raises(mariadb.ExecutionError):
            async with database.transaction() as transaction:
                await transaction.execute(mariadb.insert(Checked(value=-1)))


@test(mark="slow")
async def column_check_claims_cannot_hide_outside_construction_sql() -> None:
    """Both recorded declarations and construction SQL participate in refusal."""
    server = await load_fixture(provide_package_server())
    draft = m.generate("001", [Checked], backend="mariadb")
    table = draft.target.tables[0]
    column = table.columns[0].model_copy(
        update={"definition": "`value` BIGINT NOT NULL CHECK (value >= 0)"}
    )
    table = table.model_copy(
        update={
            "sql": "CREATE TABLE checked (`value` BIGINT NOT NULL) ENGINE=InnoDB",
            "columns": (column,),
        }
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
        with assert_raises(m.PackageError) as error:
            await target.prepare(package, schema_writers_excluded=True)
        assert "CHECK" in str(error.exception)
        assert_eq(await target.status(), ())


@test(
    [
        Param(value=value, name=value)
        for value in (
            "single-in",
            "comparison",
            "null",
            "in",
            "between",
            "not",
            "compound",
            "text",
            "empty",
        )
    ],
    mark="slow",
)
async def generated_check_language_survives_native_rendering(case: str) -> None:
    """Compiler expressions retain their bounded structure across native rendering."""
    server = await load_fixture(provide_package_server())

    class Rules[S = mariadb.Pending](mariadb.Model[S]):
        __row_type__: ClassVar[mariadb.ReadType[Rules[mariadb.Row]]]
        value: mariadb.Col[int | None] = mariadb.Integer(nullable=True)
        label: mariadb.Col[str] = mariadb.Text()

        @classmethod
        def __checks__(cls) -> list[mariadb.CheckConstraint[Rules[S]]]:
            expressions = {
                "single-in": cls.value.in_(1),
                "comparison": cls.value.gte(-5),
                "null": cls.value.is_null(),
                "in": cls.value.not_in(1, 2),
                "between": ~cls.value.between(1, 2),
                "not": ~cls.value.gte(0),
                "compound": ~(cls.value.gte(0) & cls.value.lte(10)),
                "text": cls.label.eq("quote'\\nul\0é"),
                "empty": cls.label.eq(""),
            }
            return [mariadb.CheckConstraint(expressions[case], name="ck_rule")]

    package = m.Package.load(
        m.compile(m.generate("001", [Rules], backend="mariadb")).dump()
    )
    async with m.connect(server.config()) as target:
        await target.apply(await target.prepare(package, schema_writers_excluded=True))
        assert_eq((await target.status())[0].phase, "complete")


@test(mark="slow")
async def changed_native_check_semantics_block_completion_and_recovery() -> None:
    """A native mode rewrite cannot certify a different recorded expression tree."""
    server = await load_fixture(provide_package_server())
    draft = m.generate("001", [Checked], backend="mariadb")
    table = draft.target.tables[0].model_copy(
        update={
            "sql": "CREATE TABLE checked (`value` BIGINT NOT NULL, CONSTRAINT ck_positive CHECK (NOT value >= 0)) ENGINE=InnoDB"
        }
    )
    package = m.compile(
        draft.model_copy(
            update={
                "target": draft.target.model_copy(update={"tables": (table,)}),
                "operations": (m.CreateTable(table=table),),
            }
        )
    )
    await server.run_sql(
        "SET GLOBAL sql_mode=CONCAT(@@GLOBAL.sql_mode,',HIGH_NOT_PRECEDENCE')"
    )
    try:
        async with m.connect(server.config()) as target:
            plan = await target.prepare(package, schema_writers_excluded=True)
            with assert_raises(m.PackageError) as error:
                await target.apply(plan)
            assert "CHECK" in str(error.exception)
            assert_eq((await target.status())[0].phase, "uncertain")
        async with m.connect(server.config()) as target:
            recovery = await target.inspect_recovery(plan, schema_writers_excluded=True)
            assert_eq(recovery.disposition, "ambiguous")
            with assert_raises(m.PackageError):
                await target.resume(recovery, schema_writers_excluded=True)
    finally:
        await server.run_sql(
            "SET GLOBAL sql_mode=REPLACE(@@GLOBAL.sql_mode,',HIGH_NOT_PRECEDENCE','')"
        )


@test(mark="slow")
async def check_expression_depth_is_bounded_before_effects() -> None:
    """An oversized compiler-language tree is refused rather than recursively expanded."""
    server = await load_fixture(provide_package_server())
    draft = m.generate("001", [Checked], backend="mariadb")
    table = draft.target.tables[0].model_copy(
        update={
            "sql": "CREATE TABLE checked (`value` BIGINT NOT NULL, CHECK ("
            + " AND ".join(["value >= 0"] * 100)
            + ")) ENGINE=InnoDB"
        }
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
        with assert_raises(m.PackageError) as error:
            await target.prepare(package, schema_writers_excluded=True)
        assert "CHECK" in str(error.exception)
        assert_eq(await target.status(), ())


@test(mark="slow")
async def recorded_column_check_names_must_agree_with_construction() -> None:
    """A redundant declaration cannot silently substitute a different constraint name."""
    server = await load_fixture(provide_package_server())
    draft = m.generate("001", [Checked], backend="mariadb")
    table = draft.target.tables[0]
    column = table.columns[0].model_copy(
        update={
            "definition": "`value` BIGINT NOT NULL CONSTRAINT other_name CHECK (value >= 0)"
        }
    )
    table = table.model_copy(update={"columns": (column,)})
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
        assert "CHECK" in str(error.exception)
        assert_eq(await target.status(), ())


@test(mark="slow")
async def check_normalization_work_is_bounded_before_effects() -> None:
    """Small but repeatedly negated trees cannot multiply normalization work freely."""
    server = await load_fixture(provide_package_server())
    expression = "value >= 0"
    for _ in range(12):
        expression = f"NOT ({expression} AND value <= 10)"
    draft = m.generate("001", [Checked], backend="mariadb")
    table = draft.target.tables[0].model_copy(
        update={
            "sql": f"CREATE TABLE checked (`value` BIGINT NOT NULL, CHECK ({expression})) ENGINE=InnoDB"
        }
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
        with assert_raises(m.PackageError) as error:
            await target.prepare(package, schema_writers_excluded=True)
        assert "CHECK" in str(error.exception)
        assert_eq(await target.status(), ())
