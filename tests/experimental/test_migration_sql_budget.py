"""Compilation bounds SQL-bearing input independently of the JSON envelope."""

from pathlib import Path
from tempfile import TemporaryDirectory
from typing import ClassVar

from snektest import Param, assert_eq, assert_raises, test

from snekql import sqlite
from snekql.experimental import migrations as m


class Entry[S = sqlite.Pending](sqlite.Model[S]):
    """A small real declaration whose review text can be padded without new facts."""

    __tablename__ = "bounded"
    __row_type__: ClassVar[sqlite.ReadType[Entry[sqlite.Row]]]
    id: sqlite.Col[int] = sqlite.Integer(primary_key=True)


def _with_sql(draft: m.Draft, sql: str) -> m.Draft:
    table = draft.target.tables[0].model_copy(update={"sql": sql})
    return draft.model_copy(
        update={
            "target": draft.target.model_copy(update={"tables": (table,)}),
            "operations": (m.CreateTable(table=table),),
        }
    )


@test([Param(value="a", name="ascii"), Param(value="é", name="utf8")], mark="fast")
def compiler_bounds_each_sql_source_in_utf8_bytes(character: str) -> None:
    """Comments count toward the source budget even when SQL meaning is unchanged."""
    draft = m.generate("001", [Entry], backend="sqlite")
    prefix = draft.target.tables[0].sql + " /*"
    remaining = 1_048_576 - len(prefix.encode()) - 2
    sql = (
        prefix
        + character * (remaining // len(character.encode()))
        + " " * (remaining % len(character.encode()))
        + "*/"
    )
    boundary = _with_sql(draft, sql)
    package = m.compile(boundary)
    assert_eq(m.Package.load(package.dump()), package)
    with assert_raises(m.PackageError) as error:
        m.compile(_with_sql(draft, sql + " "))
    assert "SQL source" in str(error.exception)
    assert "1 MiB" in str(error.exception)


@test(mark="fast")
def compiler_bounds_aggregate_sql_including_emitted_statements() -> None:
    """Individually small strings cannot bypass the aggregate SQL allowance."""
    draft = m.generate("001", [Entry], backend="sqlite")
    original = draft.target.tables[0]
    index = "CREATE INDEX bounded_id ON bounded(id)"
    table = original.model_copy(
        update={
            "sql": original.sql.ljust(600_000),
            "indexes": (index.ljust(900_000),),
        }
    )
    large = draft.model_copy(
        update={
            "target": draft.target.model_copy(update={"tables": (table,)}),
            "operations": (m.CreateTable(table=table),),
        }
    )
    with assert_raises(m.PackageError) as error:
        m.compile(large)
    assert "aggregate SQL" in str(error.exception)
    assert "4 MiB" in str(error.exception)


@test(mark="fast")
def loader_rejects_oversized_sql_before_integrity_recompilation() -> None:
    """A small-enough JSON envelope does not authorize oversized compiler input."""
    package = m.compile(m.generate("001", [Entry], backend="sqlite"))
    oversized = _with_sql(package.draft, package.target.tables[0].sql.ljust(1_048_577))
    encoded = package.model_copy(update={"draft": oversized}).dump()
    assert len(encoded.encode()) < 8 * 1024 * 1024
    with assert_raises(m.PackageError) as error:
        m.Package.load(encoded)
    assert "SQL source" in str(error.exception)


@test(mark="fast")
def aggregate_sql_counts_repeated_occurrences_before_route_processing() -> None:
    """Repeated declarations count again; object sharing is not a budget exemption."""
    draft = m.generate("001", [Entry], backend="sqlite")
    original = draft.target.tables[0]
    table = original.model_copy(
        update={
            "sql": original.sql.ljust(900_000),
            "indexes": (
                "CREATE INDEX bounded_id ON bounded(id)".ljust(900_000),
                "CREATE INDEX bounded_again ON bounded(id)".ljust(900_000),
            ),
        }
    )
    oversized = draft.model_copy(
        update={
            "target": draft.target.model_copy(update={"tables": (table,)}),
            "operations": (m.CreateTable(table=table),),
            "unresolved": ("must review",),
        }
    )
    with assert_raises(m.PackageError) as error:
        m.compile(oversized)
    assert "aggregate SQL" in str(error.exception)


@test(mark="fast")
def compiler_checks_nonexecuted_source_state_and_column_definitions() -> None:
    """Even a zero-statement ownership handoff must fit its recorded SQL budget."""
    draft = m.generate("001", [Entry], backend="sqlite")
    table = draft.target.tables[0]
    for oversized in (
        table.model_copy(update={"sql": table.sql.ljust(1_048_577)}),
        table.model_copy(
            update={
                "columns": (
                    table.columns[0].model_copy(
                        update={
                            "definition": table.columns[0].definition.ljust(1_048_577)
                        }
                    ),
                )
            }
        ),
    ):
        relinquished = m.Draft(
            revision="002",
            predecessor="prior-reviewed-package",
            before=m.State(backend="sqlite", tables=(oversized,)),
            target=m.State(backend="sqlite", tables=()),
            operations=(m.RelinquishTable(table_name="bounded"),),
        )
        with assert_raises(m.PackageError) as error:
            m.compile(relinquished)
        assert "SQL source" in str(error.exception)


@test(mark="fast")
def operation_sql_is_bounded_before_semantic_route_validation() -> None:
    """Intermediate columns and typed data SQL cannot hide outside endpoint states."""
    draft = m.generate("001", [Entry], backend="sqlite")
    column = m.ColumnState(
        name="extra",
        definition='"extra" INTEGER'.ljust(1_048_577),
        nullable=True,
        query_type="int | None",
        storage="INTEGER",
    )
    for operation in (
        m.AddColumn(table_name="bounded", column=column),
        m.ChangeDefault(table_name="bounded", column=column),
        m.DataChange(
            checkpoint="before",
            contract_digest="reviewed",
            backend="sqlite",
            sql="UPDATE bounded SET id=1".ljust(1_048_577),
            params=(),
        ),
    ):
        oversized = draft.model_copy(
            update={"operations": (operation,), "unresolved": ("review",)}
        )
        with assert_raises(m.PackageError) as error:
            m.compile(oversized)
        assert "SQL source" in str(error.exception)


@test(mark="medium")
async def oversized_sql_preparation_does_not_create_schema_or_history() -> None:
    """Deployment rejects SQL outside its compiler envelope before any DDL."""
    package = m.compile(m.generate("001", [Entry], backend="sqlite"))
    oversized = package.model_copy(
        update={
            "draft": _with_sql(
                package.draft, package.target.tables[0].sql.ljust(1_048_577)
            )
        }
    )
    with TemporaryDirectory() as directory:
        config = sqlite.Config(database=Path(directory) / "budget.db")
        async with m.connect(config) as target:
            with assert_raises(m.PackageError) as error:
                await target.prepare(oversized)
            assert "SQL source" in str(error.exception)
            assert_eq(await target.status(), ())
        async with (
            await sqlite.Database.initialize(config) as database,
            database.transaction() as transaction,
        ):
            assert_eq(
                await transaction.fetch_all(
                    sqlite.raw("SELECT name FROM sqlite_schema WHERE type='table'")
                ),
                [],
            )


@test(mark="fast")
def aggregate_sql_accepts_its_exact_boundary() -> None:
    """Count two declaration copies and three copies of each constructed SQL string."""
    draft = m.generate("001", [Entry], backend="sqlite")
    original = draft.target.tables[0]
    definition = original.columns[0].definition
    definition += " " * ((2 - len(definition) % 3) % 3)
    # Target + creation operation contain the definition; emitted SQL is a third
    # copy of table/index SQL. Pad valid SQL to the documented 4 MiB total.
    index_size = (4_194_304 - 2 * len(definition)) // 3 - 700_000
    table = original.model_copy(
        update={
            "columns": (
                original.columns[0].model_copy(update={"definition": definition}),
            ),
            "sql": original.sql.replace(
                original.columns[0].definition, definition
            ).ljust(700_000),
            "indexes": ("CREATE INDEX bounded_id ON bounded(id)".ljust(index_size),),
        }
    )
    boundary = draft.model_copy(
        update={
            "target": draft.target.model_copy(update={"tables": (table,)}),
            "operations": (m.CreateTable(table=table),),
        }
    )
    package = m.compile(boundary)
    assert_eq(m.Package.load(package.dump()), package)
    larger = table.model_copy(update={"indexes": (table.indexes[0] + " ",)})
    with assert_raises(m.PackageError) as error:
        m.compile(
            boundary.model_copy(
                update={
                    "target": boundary.target.model_copy(update={"tables": (larger,)}),
                    "operations": (m.CreateTable(table=larger),),
                }
            )
        )
    assert "aggregate SQL" in str(error.exception)


@test(mark="fast")
def emitted_sql_budget_stops_before_later_invalid_work() -> None:
    """Do not retain excessive emitted SQL while continuing through a long route."""
    draft = m.generate("001", [Entry], backend="sqlite")
    original = draft.target.tables[0]
    table = original.model_copy(
        update={
            "sql": original.sql.ljust(600_000),
            "indexes": ("CREATE INDEX bounded_id ON bounded(id)".ljust(900_000),),
        }
    )
    oversized = draft.model_copy(
        update={
            "target": draft.target.model_copy(update={"tables": (table,)}),
            "operations": (
                m.CreateTable(table=table),
                m.DataChange(
                    checkpoint="missing",
                    contract_digest="stale",
                    backend="sqlite",
                    sql="UPDATE bounded SET id=1",
                    params=(),
                ),
            ),
        }
    )
    with assert_raises(m.PackageError) as error:
        m.compile(oversized)
    assert "aggregate SQL" in str(error.exception)


class Settings[S = sqlite.Pending](sqlite.Model[S]):
    """Repeated deferred rebuilds carry full before/after SQL, not just None slots."""

    __tablename__ = "settings"
    __row_type__: ClassVar[sqlite.ReadType[Settings[sqlite.Row]]]
    value: sqlite.GenCol[int] = sqlite.Integer(default=sqlite.LiteralDefault(1))


@test(mark="fast")
def deferred_contraction_sql_counts_toward_the_compiler_budget() -> None:
    """Repeated frozen schema snapshots cannot escape the emitted SQL allowance."""
    draft = m.generate("001", [Settings], backend="sqlite")
    first = m.compile(_with_sql(draft, draft.target.tables[0].sql.ljust(500_000)))
    before = first.target.tables[0]
    after = before
    operations: list[m.ChangeDefault | m.Checkpoint] = []
    for value in range(2, 7):
        column = before.columns[0].model_copy(
            update={
                "definition": before.columns[0].definition.replace(
                    "DEFAULT 1", f"DEFAULT {value}"
                ),
            }
        )
        after = before.model_copy(
            update={
                "sql": before.sql.replace(
                    before.columns[0].definition, column.definition
                ),
                "columns": (column,),
            }
        )
        operations.extend(
            (
                m.ChangeDefault(table_name="settings", column=column),
                m.Checkpoint(name=f"step_{value}"),
            )
        )
    oversized = m.Draft(
        revision="002",
        predecessor=first.digest,
        before=first.target,
        target=m.State(backend="sqlite", tables=(after,)),
        operations=tuple(operations),
    )
    with assert_raises(m.PackageError) as error:
        m.compile(oversized)
    assert "aggregate SQL" in str(error.exception)
