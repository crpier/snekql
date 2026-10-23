"""Preparation refuses generated physical claims without endpoint support."""

from typing import ClassVar

from snektest import assert_eq, assert_raises, load_fixture, test

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
async def generated_general_checks_require_support_before_effects() -> None:
    """General CHECKs are explicitly refused until their endpoint proof exists."""
    server = await load_fixture(provide_package_server())
    package = m.compile(m.generate("001", [Checked], backend="mariadb"))
    async with m.connect(server.config()) as target:
        with assert_raises(m.PackageError) as error:
            await target.prepare(package, schema_writers_excluded=True)
        assert "CHECK" in str(error.exception)
        assert_eq(await target.status(), ())


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
