"""Bounded generated-column construction claims, independent of kind-only catalog facts."""

from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Literal

from snektest import Param, assert_eq, assert_raises, load_fixture, test

from snekql import mariadb, sqlite
from snekql.experimental import migrations as m
from tests.experimental.test_migration_targets import provide_package_server


def _draft(
    backend: Literal["sqlite", "mariadb"], declaration: str, construction: str
) -> m.Draft:
    """Review a generated value separately from executable construction."""
    datatype = "INTEGER" if backend == "sqlite" else "BIGINT"
    base = m.ColumnState(
        name="base",
        definition=f"`base` {datatype} NOT NULL DEFAULT 7",
        nullable=False,
        storage="INTEGER",
        query_type="int",
    )
    value = m.ColumnState(
        name="value",
        definition=f"`value` {datatype} {declaration}",
        nullable=True,
        storage="INTEGER",
        query_type="int | None",
    )
    table = m.TableState(
        name="entries",
        quoted_name="`entries`",
        columns=(base, value),
        sql=f"CREATE TABLE `entries` ({base.definition}, `value` {datatype} {construction})"
        + (" STRICT" if backend == "sqlite" else " ENGINE=InnoDB"),
    )
    return m.Draft(
        revision="001",
        predecessor=None,
        before=m.State(backend=backend),
        target=m.State(backend=backend, tables=(table,)),
        operations=(m.CreateTable(table=table),),
    )


@test(
    [
        Param[Literal["sqlite", "mariadb"]](value=b, name=b)
        for b in ("sqlite", "mariadb")
    ],
    mark="fast",
)
async def matching_generation_kind_cannot_certify_a_different_generated_value(
    backend: Literal["sqlite", "mariadb"],
) -> None:
    """Both columns can be VIRTUAL while computing different recorded values."""
    with assert_raises(m.PackageError) as error:
        m.compile(_draft(backend, "AS (7) VIRTUAL", "AS (8) VIRTUAL"))
    assert "construction generation" in str(error.exception)


@test(
    [
        Param[Literal["sqlite", "mariadb"]](value=b, name=b)
        for b in ("sqlite", "mariadb")
    ],
    mark="fast",
)
async def equal_generated_expressions_do_not_erase_storage_mode(
    backend: Literal["sqlite", "mariadb"],
) -> None:
    """VIRTUAL and STORED have distinct physical contracts even for constant7."""
    with assert_raises(m.PackageError) as error:
        m.compile(_draft(backend, "AS (7) VIRTUAL", "AS (7) STORED"))
    assert "construction generation" in str(error.exception)


@test(
    [
        Param[Literal["sqlite", "mariadb"]](value=b, name=b)
        for b in ("sqlite", "mariadb")
    ],
    mark="fast",
)
async def equal_unsupported_generation_expressions_need_explicit_adapters(
    backend: Literal["sqlite", "mariadb"],
) -> None:
    """Matching arbitrary function text is not admission to the bounded scalar language."""
    with assert_raises(m.PackageError) as error:
        m.compile(_draft(backend, "AS (abs(-7))", "AS (abs(-7))"))
    assert "unsupported construction generation expression" in str(error.exception)


@test(mark="fast")
async def sqlite_generated_constraint_labels_bind_independently_of_value() -> None:
    """Known generated kind/value do not erase an explicit SQLite constraint symbol."""
    with assert_raises(m.PackageError) as error:
        m.compile(
            _draft(
                "sqlite",
                'CONSTRAINT "recorded" GENERATED ALWAYS AS (7)',
                'CONSTRAINT "other" GENERATED ALWAYS AS (7)',
            )
        )
    assert "construction generation" in str(error.exception)


@test(
    [
        Param[Literal["sqlite", "mariadb"]](value=b, name=b)
        for b in ("sqlite", "mariadb")
    ],
    mark="fast",
)
async def finite_column_plus_integer_generation_binds_identifiers_by_known_table_names(
    backend: Literal["sqlite", "mariadb"],
) -> None:
    """Only declared table members authorize identifier roles, not arbitrary bare SQL words."""
    package = m.compile(_draft(backend, "AS (`BASE` + 1)", "AS (`base` + 1) VIRTUAL"))
    assert m.Package.load(package.dump()).digest == package.digest


@test(mark="fast")
async def equal_ambiguous_sqlite_generation_modes_require_an_adapter() -> None:
    """A first-mode scan must not silently ignore a second physical storage marker."""
    clause = "AS (7) VIRTUAL STORED"
    with assert_raises(m.PackageError) as error:
        m.compile(_draft("sqlite", clause, clause))
    assert "construction generation" in str(error.exception)


@test(
    [
        Param[Literal["sqlite", "mariadb"]](value=b, name=b)
        for b in ("sqlite", "mariadb")
    ],
    mark="fast",
)
async def unquoted_generated_member_roles_require_an_explicit_adapter(
    backend: Literal["sqlite", "mariadb"],
) -> None:
    """Do not guess reserved-word/function/numeric roles from a known column name."""
    with assert_raises(m.PackageError) as error:
        m.compile(_draft(backend, "AS (base)", "AS (base)"))
    assert "unsupported construction generation expression" in str(error.exception)


@test(
    [
        Param(value=pair, name=str(i))
        for i, pair in enumerate(
            (("NULL", "AS (7)"), ("AS (7)", "NULL"), ("AS (7) STORED", "AS (7)"))
        )
    ],
    mark="fast",
)
async def ordinary_and_generated_presence_and_modes_bind_both_directions(
    pair: tuple[str, str],
) -> None:
    """Ordinary writable storage cannot replace generated or stored/virtual contracts."""
    for backend in ("sqlite", "mariadb"):
        with assert_raises(m.PackageError) as error:
            m.compile(_draft(backend, *pair))
        assert "construction generation" in str(error.exception)


@test(
    [
        Param(value=pair, name=str(i))
        for i, pair in enumerate(
            (("AS (7)", "GENERATED ALWAYS AS ((+7)) VIRTUAL"), ("AS (-7)", "AS ((-7))"))
        )
    ],
    mark="fast",
)
async def known_scalar_parentheses_and_default_virtual_normalize(
    pair: tuple[str, str],
) -> None:
    """Only finite scalar cosmetics normalize, not function/algebraic equivalence."""
    for backend in ("sqlite", "mariadb"):
        package = m.compile(_draft(backend, *pair))
        assert_eq(m.Package.load(package.dump()).digest, package.digest)


@test(mark="fast")
async def native_persistent_and_cast_case_are_known_not_generic_equivalence() -> None:
    """Existing STORED/PERSISTENT aliases and bounded integer CAST syntax remain admitted."""
    package = m.compile(
        _draft(
            "mariadb",
            "AS (CAST(7 AS SIGNED)) STORED",
            "GENERATED ALWAYS AS (cast(7 as signed)) PERSISTENT",
        )
    )
    assert_eq(m.Package.load(package.dump()).digest, package.digest)


@test(
    [Param(value=scope, name=scope) for scope in ("before", "create", "adopt")],
    mark="fast",
)
async def relinquishment_cannot_hide_generated_expression_claims(scope: str) -> None:
    """Before/intermediate CREATE/SQLite ADOPT claims survive an empty final owner set."""
    table = _draft("sqlite", "AS (7)", "AS (8)").target.tables[0]
    empty = m.State(backend="sqlite")
    if scope == "before":
        draft = m.Draft(
            revision="002",
            predecessor="previous",
            before=m.State(backend="sqlite", tables=(table,)),
            target=empty,
            operations=(m.RelinquishTable(table_name="entries"),),
        )
    else:
        op = (
            m.CreateTable(table=table)
            if scope == "create"
            else m.AdoptTable(table=table)
        )
        draft = m.Draft(
            revision="001",
            predecessor=None,
            before=empty,
            target=empty,
            operations=(op, m.RelinquishTable(table_name="entries")),
        )
    with assert_raises(m.PackageError) as error:
        m.compile(draft)
    assert "construction generation" in str(error.exception)


@test([Param(value=kind, name=kind) for kind in ("add", "default")], mark="fast")
async def standalone_generation_language_needs_admission_without_ownership(
    kind: str,
) -> None:
    """Unsupported function expressions cannot hide in payloads preceding handoff."""
    first = m.compile(_draft("sqlite", "NULL", "NULL"))
    name = "extra" if kind == "add" else "value"
    column = m.ColumnState(
        name=name,
        definition=f"`{name}` INTEGER AS (abs(-7))",
        nullable=True,
        storage="INTEGER",
        query_type=None,
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
        target=m.State(backend="sqlite"),
        operations=(op, m.RelinquishTable(table_name="entries")),
    )
    with assert_raises(m.PackageError) as error:
        m.compile(draft)
    assert "unsupported construction generation expression" in str(error.exception)


@test(
    [
        Param(value=clause, name=str(i))
        for i, clause in enumerate(
            (
                "AS (7) PERSISTENT",
                "AS (7) MYSTERY",
                "GENERATED AS (7)",
                "GENERATED ALWAYS",
                "AS (7) AS (7)",
                "CONSTRAINT 'chosen' AS (7)",
            )
        )
    ],
    mark="fast",
)
async def equal_unknown_sqlite_generation_shapes_require_adapters(clause: str) -> None:
    """Unknown prefixes/modes/labels or extra clauses cannot use byte-equality fallback."""
    with assert_raises(m.PackageError) as error:
        m.compile(_draft("sqlite", clause, clause))
    assert "construction generation" in str(error.exception)


@test(mark="fast")
async def generated_language_has_token_and_integer_bounds() -> None:
    """Nested wrappers and enormous decimal literals do not cause unbounded conversion."""
    for expression in ("(" * 33 + "7" + ")" * 33, "9" * 10000):
        clause = f"AS ({expression})"
        with assert_raises(m.PackageError) as error:
            m.compile(_draft("sqlite", clause, clause))
        assert "construction generation expression" in str(error.exception)


@test(mark="fast")
async def generated_label_quotes_normalize_but_presence_and_case_do_not() -> None:
    """Generated label identity belongs to its clause, not the following CHECK/NOT NULL."""
    package = m.compile(
        _draft(
            "sqlite",
            'CONSTRAINT "chosen" GENERATED ALWAYS AS (7)',
            "CONSTRAINT [chosen] AS (7)",
        )
    )
    assert_eq(m.Package.load(package.dump()).digest, package.digest)
    for pair in (
        ("AS (7)", 'CONSTRAINT "chosen" AS (7)'),
        ('CONSTRAINT "Chosen" AS (7)', 'CONSTRAINT "chosen" AS (7)'),
    ):
        with assert_raises(m.PackageError):
            m.compile(_draft("sqlite", *pair))


@test(mark="fast")
async def extra_sql_generated_fields_do_not_manufacture_managed_columns() -> None:
    """Unknown extra expressions remain trusted construction, not recorded ownership."""
    draft = _draft("sqlite", "NULL", "NULL")
    table = draft.target.tables[0]
    table = table.model_copy(
        update={
            "sql": table.sql.replace(
                ") STRICT", ", extra INTEGER AS (abs(base))) STRICT"
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
    assert_eq(
        tuple(c.name for c in package.target.tables[0].columns), ("base", "value")
    )


@test(mark="fast")
async def missing_members_and_algebraic_rewrites_are_not_inferred() -> None:
    """Quoted names need table members and addition is ordered, not algebraically solved."""
    for expression in ("`missing`", "1 + `base`", "CURRENT_TIMESTAMP"):
        with assert_raises(m.PackageError):
            m.compile(_draft("sqlite", f"AS ({expression})", f"AS ({expression})"))


@test(mark="medium")
async def sqlite_generated_modes_recompute_finite_derived_values() -> None:
    """Quoted column-plus-integer contracts retain known default and update behavior."""
    for mode in ("VIRTUAL", "STORED"):
        clause = f"AS (`base` + 1) {mode}"
        package = m.Package.load(m.compile(_draft("sqlite", clause, clause)).dump())
        with TemporaryDirectory() as directory:
            config = sqlite.Config(database=Path(directory) / "generated.db")
            async with m.connect(config) as target:
                await target.apply(await target.prepare(package))
            async with (
                await sqlite.Database.initialize(config) as db,
                db.transaction() as tx,
            ):
                await tx.execute(sqlite.raw("INSERT INTO entries DEFAULT VALUES"))
                assert_eq(
                    await tx.fetch_all(sqlite.raw("SELECT base,value FROM entries")),
                    [{"base": 7, "value": 8}],
                )
                await tx.execute(sqlite.raw("UPDATE entries SET base=9"))
                assert_eq(
                    await tx.fetch_all(sqlite.raw("SELECT base,value FROM entries")),
                    [{"base": 9, "value": 10}],
                )


@test(mark="slow")
async def native_generated_modes_recompute_finite_derived_values() -> None:
    """Native VIRTUAL/STORED/PERSISTENT contracts need actual deployment behavior too."""
    server = await load_fixture(provide_package_server())
    for mode in ("VIRTUAL", "STORED", "PERSISTENT"):
        await server.reset_database()
        clause = f"AS (`base` + 1) {mode}"
        package = m.Package.load(m.compile(_draft("mariadb", clause, clause)).dump())
        async with m.connect(server.config()) as target:
            await target.apply(
                await target.prepare(package, schema_writers_excluded=True)
            )
        async with (
            await mariadb.Database.initialize(server.config()) as db,
            db.transaction() as tx,
        ):
            await tx.execute(mariadb.raw("INSERT INTO entries () VALUES ()"))
            assert_eq(
                await tx.fetch_all(mariadb.raw("SELECT base,value FROM entries")),
                [{"base": 7, "value": 8}],
            )
            await tx.execute(mariadb.raw("UPDATE entries SET base=9"))
            assert_eq(
                await tx.fetch_all(mariadb.raw("SELECT base,value FROM entries")),
                [{"base": 9, "value": 10}],
            )


@test(mark="medium")
async def old_sqlite_generated_false_completion_refuses_without_converting_valid_identity() -> (
    None
):
    """Actual format2 AS7/AS8 contradiction now refuses load/typed prepare pre-effects."""
    root = Path(__file__).parent / "fixtures" / "generation-claims"
    invalid = (root / "sqlite-invalid-old.json").read_text()
    bad = m.Package.model_validate_json(invalid)
    assert_eq(
        bad.digest, "a8c64b0572b425b151cbc92f8cb1842ca693a0e524f01ff0325b704bbdc5ec2a"
    )
    with assert_raises(m.PackageError):
        m.Package.load(invalid)
    valid = (root / "sqlite-valid-old.json").read_text()
    good = m.Package.load(valid)
    assert_eq(good.dump(), valid)
    assert_eq(
        good.digest, "4648402cf8adc688367bd5d3ec08ca8b700136969ea09fc9f1c387f81c74bd6c"
    )
    with TemporaryDirectory() as directory:
        config = sqlite.Config(database=Path(directory) / "generated.db")
        async with m.connect(config) as target:
            with assert_raises(m.PackageError):
                await target.prepare(bad)
            assert_eq(await target.status(), ())
        async with (
            await sqlite.Database.initialize(config) as db,
            db.transaction() as tx,
        ):
            assert_eq(
                await tx.fetch_all(
                    sqlite.raw("SELECT name FROM sqlite_schema WHERE type='table'")
                ),
                [],
            )
        async with m.connect(config) as target:
            await target.apply(await target.prepare(good))
        async with (
            await sqlite.Database.initialize(config) as db,
            db.transaction() as tx,
        ):
            await tx.execute(sqlite.raw("INSERT INTO entries DEFAULT VALUES"))
            assert_eq(
                await tx.fetch_all(sqlite.raw("SELECT base,value FROM entries")),
                [{"base": 7, "value": 7}],
            )


@test(mark="slow")
async def old_native_generated_false_completion_refuses_without_converting_valid_identity() -> (
    None
):
    """Unlike earlier attribute slices, this actual archived native case falsely completed."""
    server = await load_fixture(provide_package_server())
    root = Path(__file__).parent / "fixtures" / "generation-claims"
    invalid = (root / "mariadb-invalid-old.json").read_text()
    bad = m.Package.model_validate_json(invalid)
    assert_eq(
        bad.digest, "0ce85ed5234d5d9005fc9e6b119ac0b9eb086f50ae9ac4d62240ecfcaeb80209"
    )
    with assert_raises(m.PackageError):
        m.Package.load(invalid)
    valid = (root / "mariadb-valid-old.json").read_text()
    good = m.Package.load(valid)
    assert_eq(good.dump(), valid)
    assert_eq(
        good.digest, "ca9dc794c58ee5bf89650958137f46873d1657cca175ca079261cb3a3c4b40b7"
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
        await tx.execute(mariadb.raw("INSERT INTO entries () VALUES ()"))
        assert_eq(
            await tx.fetch_all(mariadb.raw("SELECT base,value FROM entries")),
            [{"base": 7, "value": 7}],
        )


@test(mark="medium")
async def sqlite_generated_expression_drift_still_blocks_valid_followup() -> None:
    """Binding does not replace live catalog drift proof after an accepted completion."""
    first = m.compile(_draft("sqlite", "AS (7)", "AS (7)"))
    with TemporaryDirectory() as directory:
        config = sqlite.Config(database=Path(directory) / "drift.db")
        async with m.connect(config) as target:
            await target.apply(await target.prepare(first))
        async with (
            await sqlite.Database.initialize(config) as db,
            db.transaction() as tx,
        ):
            await tx.execute(sqlite.raw("DROP TABLE entries"))
            await tx.execute(
                sqlite.raw(
                    "CREATE TABLE entries (base INTEGER NOT NULL DEFAULT 7,value INTEGER AS (9)) STRICT"
                )
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
        async with m.connect(config) as target:
            with assert_raises(m.PackageError):
                await target.prepare(followup)


@test(mark="slow")
async def native_generated_expression_drift_still_blocks_valid_followup() -> None:
    """An independent accepted-catalog guard catches later physical expression changes."""
    server = await load_fixture(provide_package_server())
    first = m.compile(_draft("mariadb", "AS (7)", "AS (7)"))
    async with m.connect(server.config()) as target:
        await target.apply(await target.prepare(first, schema_writers_excluded=True))
    await server.run_sql("ALTER TABLE entries MODIFY value BIGINT AS (9) VIRTUAL")
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


@test(mark="fast")
async def a_generated_column_label_is_not_check_removal_authority() -> None:
    """Expression/label binding doesn't manufacture named table CHECK ownership."""
    clause = 'CONSTRAINT "chosen" AS (7)'
    first = m.compile(_draft("sqlite", clause, clause))
    draft = m.Draft(
        revision="002",
        predecessor=first.digest,
        before=first.target,
        target=first.target,
        operations=(m.DropCheck(table_name="entries", check_name="chosen"),),
    )
    with assert_raises(m.PackageError):
        m.compile(draft)


@test(mark="fast")
async def native_expression_identifier_quotes_do_not_assume_ansi_quotes() -> None:
    """Native double quotes can be strings rather than references under the execution mode."""
    with assert_raises(m.PackageError) as error:
        m.compile(_draft("mariadb", "AS (`base` + 1)", 'AS ("base" + 1)'))
    assert "unsupported construction generation expression identifier quote" in str(
        error.exception
    )
