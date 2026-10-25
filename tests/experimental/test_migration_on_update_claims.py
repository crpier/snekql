"""Native automatic timestamp updates agree with executable construction, not defaults."""

from datetime import UTC, datetime
from pathlib import Path

from snektest import Param, assert_eq, assert_raises, load_fixture, test

from snekql import mariadb
from snekql.experimental import migrations as m
from tests.experimental.test_migration_targets import provide_package_server


def _draft(declaration: str, construction: str) -> m.Draft:
    """Keep automatic update independent of nullable effective NULL defaults."""
    prefix = "`changed` DATETIME(6) NULL DEFAULT NULL"
    column = m.ColumnState(
        name="changed",
        definition=prefix + (" " + declaration if declaration else ""),
        nullable=True,
        storage="DATETIME",
        query_type=None,
    )
    table = m.TableState(
        name="entries",
        quoted_name="`entries`",
        columns=(column,),
        sql="CREATE TABLE entries (`base` BIGINT NOT NULL DEFAULT 7,"
        + prefix
        + (" " + construction if construction else "")
        + ") ENGINE=InnoDB",
    )
    return m.Draft(
        revision="001",
        predecessor=None,
        before=m.State(backend="mariadb"),
        target=m.State(backend="mariadb", tables=(table,)),
        operations=(m.CreateTable(table=table),),
    )


@test(
    [
        Param(value=pair, name=str(i))
        for i, pair in enumerate(
            (
                ("", "ON UPDATE CURRENT_TIMESTAMP(6)"),
                ("ON UPDATE CURRENT_TIMESTAMP(6)", ""),
            )
        )
    ],
    mark="fast",
)
async def automatic_timestamp_update_presence_binds_in_both_directions(
    pair: tuple[str, str],
) -> None:
    """Same storage/default do not prove whether unrelated writes change a timestamp."""
    with assert_raises(m.PackageError) as error:
        m.compile(_draft(*pair))
    assert "construction ON UPDATE differs" in str(error.exception)


@test(
    [
        Param(value=clause, name=str(i))
        for i, clause in enumerate(
            (
                "ON UPDATE CURRENT_TIMESTAMP",
                "on update current_timestamp()",
                "ON UPDATE CURRENT_TIMESTAMP(6)",
            )
        )
    ],
    mark="fast",
)
async def implicit_empty_and_explicit_precision_retain_known_equivalence(
    clause: str,
) -> None:
    """The temporal column's precision determines omitted clock precision, not zero."""
    package = m.compile(_draft("ON UPDATE CURRENT_TIMESTAMP(6)", clause))
    assert_eq(m.Package.load(package.dump()).digest, package.digest)


@test([Param(value=scope, name=scope) for scope in ("before", "create")], mark="fast")
async def relinquishment_cannot_hide_automatic_update_claims(scope: str) -> None:
    """Before/intermediate construction payloads still own their timestamp declarations."""
    table = _draft("ON UPDATE CURRENT_TIMESTAMP(6)", "").target.tables[0]
    empty = m.State(backend="mariadb")
    if scope == "before":
        draft = m.Draft(
            revision="002",
            predecessor="previous",
            before=m.State(backend="mariadb", tables=(table,)),
            target=empty,
            operations=(m.RelinquishTable(table_name="entries"),),
        )
    else:
        draft = m.Draft(
            revision="001",
            predecessor=None,
            before=empty,
            target=empty,
            operations=(
                m.CreateTable(table=table),
                m.RelinquishTable(table_name="entries"),
            ),
        )
    with assert_raises(m.PackageError) as error:
        m.compile(draft)
    assert "construction ON UPDATE differs" in str(error.exception)


@test(
    [
        Param(value=clause, name=str(i))
        for i, clause in enumerate(
            (
                "ON UPDATE now()",
                "ON UPDATE CURRENT_TIMESTAMP(0)",
                "ON UPDATE CURRENT_TIMESTAMP(7)",
                "ON UPDATE CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP",
                "CHECK (1) ON UPDATE CURRENT_TIMESTAMP",
            )
        )
    ],
    mark="fast",
)
async def matching_unsupported_update_clauses_still_require_adapters(
    clause: str,
) -> None:
    """Matching bytes cannot authorize unknown functions, positions or precision conflicts."""
    with assert_raises(m.PackageError) as error:
        m.compile(_draft(clause, clause))
    assert "ON UPDATE" in str(error.exception)


@test(mark="fast")
async def unsupported_construction_update_clause_cannot_hide_behind_ordinary_metadata() -> (
    None
):
    """Constructor-only unsupported roles need admission, not only declaration validation."""
    with assert_raises(m.PackageError) as error:
        m.compile(_draft("", "ON UPDATE now()"))
    assert "ON UPDATE" in str(error.exception)


@test([Param(value=kind, name=kind) for kind in ("add", "default")], mark="fast")
async def standalone_update_language_requires_admission_before_handoff(
    kind: str,
) -> None:
    """Standalone payload language is checked even when final ownership is empty."""
    first = m.compile(_draft("", ""))
    name = "extra" if kind == "add" else "changed"
    column = m.ColumnState(
        name=name,
        definition=f"`{name}` DATETIME(6) NULL DEFAULT NULL ON UPDATE now()",
        nullable=True,
        storage="DATETIME",
    )
    op = (
        m.AddColumn(table_name="entries", column=column)
        if kind == "add"
        else m.ChangeDefault(table_name="entries", column=column)
    )
    draft = m.Draft(
        revision="002",
        predecessor=first.digest,
        before=first.target,
        target=m.State(backend="mariadb"),
        operations=(op, m.RelinquishTable(table_name="entries")),
    )
    with assert_raises(m.PackageError) as error:
        m.compile(draft)
    assert "ON UPDATE" in str(error.exception)


@test(mark="fast")
async def comments_literals_and_quoted_names_do_not_manufacture_update_attributes() -> (
    None
):
    """Only the column attribute role, not an ON UPDATE substring, creates a claim."""
    package = m.compile(
        _draft(
            "COMMENT 'ON UPDATE CURRENT_TIMESTAMP(6)'",
            "COMMENT 'ON UPDATE CURRENT_TIMESTAMP(6)'",
        )
    )
    assert_eq(m.Package.load(package.dump()).digest, package.digest)
    draft = _draft("", "")
    table = draft.target.tables[0]
    column = m.ColumnState(
        name="on update",
        definition="`on update` VARCHAR(64) NULL DEFAULT 'ON UPDATE CURRENT_TIMESTAMP'",
        nullable=True,
        storage="TEXT",
        query_type=None,
    )
    table = table.model_copy(
        update={
            "columns": (column,),
            "sql": "CREATE TABLE entries (" + column.definition + ") ENGINE=InnoDB",
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
    assert_eq(m.Package.load(package.dump()).digest, package.digest)


@test(mark="fast")
async def unowned_automatic_timestamp_fields_do_not_manufacture_owned_columns() -> None:
    """Construction SQL extras remain executable/unclaimed, never destructive authority."""
    draft = _draft("", "")
    table = draft.target.tables[0]
    table = table.model_copy(
        update={
            "sql": table.sql.replace(
                ") ENGINE=InnoDB",
                ", extra DATETIME(6) NULL ON UPDATE CURRENT_TIMESTAMP(6)) ENGINE=InnoDB",
            )
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
    assert_eq(tuple(c.name for c in package.target.tables[0].columns), ("changed",))


@test(mark="slow")
async def automatic_updates_retain_null_default_and_deterministic_changed_write_behavior() -> (
    None
):
    """Known real writes distinguish a NULL default from an automatic update clock."""
    server = await load_fixture(provide_package_server())
    for clause in ("", "ON UPDATE CURRENT_TIMESTAMP(6)"):
        await server.reset_database()
        package = m.Package.load(m.compile(_draft(clause, clause)).dump())
        async with m.connect(server.config()) as target:
            await target.apply(
                await target.prepare(package, schema_writers_excluded=True)
            )
        async with (
            await mariadb.Database.initialize(server.config()) as db,
            db.transaction() as tx,
        ):
            await tx.execute(mariadb.raw("SET time_zone='+00:00'"))
            await tx.execute(mariadb.raw("SET timestamp=978307200"))
            await tx.execute(mariadb.raw("INSERT INTO entries () VALUES ()"))
            assert_eq(
                await tx.fetch_all(mariadb.raw("SELECT base,changed FROM entries")),
                [{"base": 7, "changed": None}],
            )
            await tx.execute(mariadb.raw("UPDATE entries SET base=8"))
            expected = (
                datetime(2001, 1, 1, tzinfo=UTC).replace(tzinfo=None)
                if clause
                else None
            )
            assert_eq(
                await tx.fetch_all(mariadb.raw("SELECT base,changed FROM entries")),
                [{"base": 8, "changed": expected}],
            )
            await tx.execute(mariadb.raw("SET timestamp=1009843200"))
            await tx.execute(mariadb.raw("UPDATE entries SET base=9, changed=changed"))
            assert_eq(
                await tx.fetch_all(mariadb.raw("SELECT base,changed FROM entries")),
                [{"base": 9, "changed": expected}],
            )


@test(mark="slow")
async def literal_old_update_artifacts_refuse_before_effects_and_retain_valid_identity() -> (
    None
):
    """Actual format2 late-refusal artifact now fails load/typed prepare without conversion."""
    server = await load_fixture(provide_package_server())
    root = Path(__file__).parent / "fixtures" / "native-on-update"
    invalid = (root / "invalid-old.json").read_text()
    bad = m.Package.model_validate_json(invalid)
    assert_eq(
        bad.digest, "46855019e64fbd2d9b59e88cf381a4083943e8a7777e7a44bb5e55940ae0b83f"
    )
    with assert_raises(m.PackageError):
        m.Package.load(invalid)
    valid = (root / "valid-old.json").read_text()
    good = m.Package.load(valid)
    assert_eq(good.dump(), valid)
    assert_eq(
        good.digest, "1141d4e610f1421b0174b40ed85878eac09651e79222852ad7511f5652f093de"
    )
    async with m.connect(server.config()) as target:
        with assert_raises(m.PackageError):
            await target.prepare(bad, schema_writers_excluded=True)
        assert_eq(await target.status(), ())
    async with (
        await mariadb.Database.initialize(server.config()) as db,
        db.transaction() as tx,
    ):
        assert_eq(await tx.fetch_all(mariadb.raw("SHOW FULL TABLES")), [])
    async with m.connect(server.config()) as target:
        await target.apply(await target.prepare(good, schema_writers_excluded=True))
    async with (
        await mariadb.Database.initialize(server.config()) as db,
        db.transaction() as tx,
    ):
        await tx.execute(mariadb.raw("SET time_zone='+00:00'"))
        await tx.execute(mariadb.raw("SET timestamp=978307200"))
        await tx.execute(mariadb.raw("INSERT INTO entries () VALUES ()"))
        await tx.execute(mariadb.raw("UPDATE entries SET base=8"))
        assert_eq(
            await tx.fetch_all(mariadb.raw("SELECT base,changed FROM entries")),
            [
                {
                    "base": 8,
                    "changed": datetime(2001, 1, 1, tzinfo=UTC).replace(tzinfo=None),
                }
            ],
        )


@test(mark="slow")
async def physical_automatic_update_drift_still_blocks_valid_followup() -> None:
    """New construction binding does not replace independent accepted-catalog drift checks."""
    server = await load_fixture(provide_package_server())
    clause = "ON UPDATE CURRENT_TIMESTAMP(6)"
    first = m.compile(_draft(clause, clause))
    async with m.connect(server.config()) as target:
        await target.apply(await target.prepare(first, schema_writers_excluded=True))
    await server.run_sql(
        "ALTER TABLE entries MODIFY changed DATETIME(6) NULL DEFAULT NULL"
    )
    followup = m.compile(
        m.Draft(
            revision="002",
            predecessor=first.digest,
            before=first.target,
            target=first.target,
            operations=(),
        )
    )
    async with m.connect(server.config()) as target:
        with assert_raises(m.PackageError) as error:
            await target.prepare(followup, schema_writers_excluded=True)
        assert "catalog differs from the last accepted execution" in str(
            error.exception
        )


@test(
    [Param(value=precision, name=str(precision)) for precision in range(7)], mark="fast"
)
async def supported_column_precisions_bind_without_default_changes(
    precision: int,
) -> None:
    """Each existing finite fractional precision keeps implicit/empty update normalization."""
    draft = _draft(
        "ON UPDATE CURRENT_TIMESTAMP", f"ON UPDATE CURRENT_TIMESTAMP({precision})"
    )
    table = draft.target.tables[0]
    column = table.columns[0].model_copy(
        update={
            "definition": table.columns[0].definition.replace(
                "DATETIME(6)", f"DATETIME({precision})"
            )
        }
    )
    table = table.model_copy(
        update={
            "columns": (column,),
            "sql": table.sql.replace("DATETIME(6)", f"DATETIME({precision})"),
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
    assert_eq(m.Package.load(package.dump()).digest, package.digest)


@test(
    [
        Param(value=action, name=action)
        for action in ("CASCADE", "RESTRICT", "NO ACTION", "SET NULL")
    ],
    mark="fast",
)
async def inline_fk_update_actions_do_not_become_timestamp_attributes(
    action: str,
) -> None:
    """Both recorded and executable REFERENCES own actions independently of auto clocks."""
    draft = _draft("", "")
    definitions = (
        "`id` BIGINT NOT NULL PRIMARY KEY",
        f"`parent_id` BIGINT NULL REFERENCES entries(id) ON DELETE NO ACTION ON UPDATE {action}",
    )
    columns = tuple(
        m.ColumnState(
            name=name,
            definition=definition,
            nullable=name != "id",
            storage="INTEGER",
            query_type=None,
        )
        for name, definition in zip(("id", "parent_id"), definitions, strict=True)
    )
    table = m.TableState(
        name="entries",
        quoted_name="`entries`",
        columns=columns,
        sql="CREATE TABLE entries (" + ",".join(definitions) + ") ENGINE=InnoDB",
    )
    package = m.compile(
        draft.model_copy(
            update={
                "target": draft.target.model_copy(update={"tables": (table,)}),
                "operations": (m.CreateTable(table=table),),
            }
        )
    )
    assert_eq(m.Package.load(package.dump()).digest, package.digest)


@test(mark="fast")
async def references_is_not_permission_to_ignore_unknown_update_roles() -> None:
    """REFERENCES tails must parse as real bounded FK actions, never blind ON suppression."""
    draft = _draft("", "")
    table = draft.target.tables[0]
    definition = (
        "`parent_id` BIGINT NULL REFERENCES entries(base) ON UPDATE CURRENT_TIMESTAMP"
    )
    column = m.ColumnState(
        name="parent_id",
        definition=definition,
        nullable=True,
        storage="INTEGER",
        query_type=None,
    )
    table = table.model_copy(
        update={
            "columns": (column,),
            "sql": "CREATE TABLE entries (`base` BIGINT NOT NULL PRIMARY KEY,"
            + definition
            + ") ENGINE=InnoDB",
        }
    )
    with assert_raises(m.PackageError) as error:
        m.compile(
            draft.model_copy(
                update={
                    "target": draft.target.model_copy(update={"tables": (table,)}),
                    "operations": (m.CreateTable(table=table),),
                }
            )
        )
    assert "foreign-key action" in str(error.exception)


@test(mark="fast")
async def native_reference_tail_is_not_permission_to_hide_ordinary_null_clauses() -> (
    None
):
    """The bounded FK parser must reject later column clauses, not merely stop scanning."""
    draft = _draft("", "")
    table = draft.target.tables[0]
    definition = (
        "`parent_id` BIGINT NULL REFERENCES entries(base) ON UPDATE SET NULL NOT NULL"
    )
    column = m.ColumnState(
        name="parent_id",
        definition=definition,
        nullable=True,
        storage="INTEGER",
        query_type=None,
    )
    table = table.model_copy(
        update={
            "columns": (column,),
            "sql": "CREATE TABLE entries (`base` BIGINT NOT NULL PRIMARY KEY,"
            + definition
            + ") ENGINE=InnoDB",
        }
    )
    with assert_raises(m.PackageError):
        m.compile(
            draft.model_copy(
                update={
                    "target": draft.target.model_copy(update={"tables": (table,)}),
                    "operations": (m.CreateTable(table=table),),
                }
            )
        )


@test(mark="slow")
async def native_fk_set_null_actions_retain_live_relationship_behavior() -> None:
    """Action NULL belongs to a foreign key; it is not a duplicate nullable flag/clock."""
    server = await load_fixture(provide_package_server())
    draft = _draft("", "")
    definitions = (
        "`id` BIGINT NOT NULL PRIMARY KEY",
        "`parent_id` BIGINT NULL REFERENCES parents(id) ON UPDATE SET NULL",
    )
    columns = tuple(
        m.ColumnState(
            name=name,
            definition=definition,
            nullable=name != "id",
            storage="INTEGER",
            query_type=None,
        )
        for name, definition in zip(("id", "parent_id"), definitions, strict=True)
    )
    table = m.TableState(
        name="entries",
        quoted_name="`entries`",
        columns=columns,
        sql="CREATE TABLE entries (" + ",".join(definitions) + ") ENGINE=InnoDB",
    )
    parent_column = m.ColumnState(
        name="id",
        definition="`id` BIGINT NOT NULL PRIMARY KEY",
        nullable=False,
        storage="INTEGER",
        query_type=None,
    )
    parent = m.TableState(
        name="parents",
        quoted_name="`parents`",
        columns=(parent_column,),
        sql="CREATE TABLE parents (`id` BIGINT NOT NULL PRIMARY KEY) ENGINE=InnoDB",
    )
    package = m.Package.load(
        m.compile(
            draft.model_copy(
                update={
                    "target": draft.target.model_copy(
                        update={"tables": (parent, table)}
                    ),
                    "operations": (
                        m.CreateTable(table=parent),
                        m.CreateTable(table=table),
                    ),
                }
            )
        ).dump()
    )
    async with m.connect(server.config()) as target:
        await target.apply(await target.prepare(package, schema_writers_excluded=True))
    async with (
        await mariadb.Database.initialize(server.config()) as db,
        db.transaction() as tx,
    ):
        await tx.execute(mariadb.raw("INSERT INTO parents (id) VALUES (1)"))
        await tx.execute(mariadb.raw("INSERT INTO entries (id,parent_id) VALUES (2,1)"))
        await tx.execute(mariadb.raw("UPDATE parents SET id=3 WHERE id=1"))
        assert_eq(
            await tx.fetch_all(
                mariadb.raw("SELECT id,parent_id FROM entries ORDER BY id")
            ),
            [{"id": 2, "parent_id": None}],
        )
