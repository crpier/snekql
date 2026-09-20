"""Schema verification exposes compared facts without certifying unchecked schema."""

from dataclasses import FrozenInstanceError
from datetime import datetime
from typing import ClassVar

from snektest import Param, assert_eq, assert_raises, load_fixture, test

from snekql import mariadb, sqlite
from tests.helpers import provide_mariadb_server


@test(mark="fast")
async def matching_column_exposes_a_matched_fact() -> None:
    """Verification reports the specific column property it compared."""

    class Entry[S = sqlite.Pending](sqlite.Model[S, "Entry[sqlite.Fetched]"]):
        __tablename__ = "fact_entry"
        value: sqlite.Col[str] = sqlite.Text()

    async with await sqlite.Database.initialize(
        sqlite.Config(database=":memory:")
    ) as database:
        await database.migrate(
            {"001": "CREATE TABLE fact_entry (value TEXT NOT NULL) STRICT"}
        )
        result = await database.verify([Entry])

    assert_eq(
        [
            (fact.table_name, fact.object_name, fact.status)
            for fact in result.facts
            if fact.kind == "column.nullable"
        ],
        [("fact_entry", "value", "matched")],
    )


@test(mark="fast")
async def column_properties_report_independent_statuses() -> None:
    """Drift in one property does not hide matching evidence for another."""

    class Entry[S = sqlite.Pending](sqlite.Model[S, "Entry[sqlite.Fetched]"]):
        __tablename__ = "fact_entry"
        value: sqlite.Col[str] = sqlite.Text(collation="NOCASE")

    async with await sqlite.Database.initialize(
        sqlite.Config(database=":memory:")
    ) as database:
        await database.migrate(
            {"001": "CREATE TABLE fact_entry (value TEXT NULL) STRICT"}
        )
        result = await database.verify([Entry], policy="warn")

    assert_eq(
        {
            fact.kind: fact.status
            for fact in result.facts
            if fact.object_name == "value"
        },
        {
            "column.presence": "matched",
            "column.type": "matched",
            "column.nullable": "drift",
            "column.primary_key": "matched",
            "column.auto_increment": "matched",
            "column.server_default": "matched",
            "column.collation": "drift",
        },
    )
    assert_eq(len(result.issues), 1)


@test(mark="fast")
async def index_properties_report_independent_statuses() -> None:
    """Column ordering and uniqueness are individual index facts."""

    class Entry[S = sqlite.Pending](sqlite.Model[S, "Entry[sqlite.Fetched]"]):
        __tablename__ = "fact_entry"
        value: sqlite.Col[str] = sqlite.Text()
        __indexes__: ClassVar = [sqlite.Index(value, name="fact_index", unique=True)]

    async with await sqlite.Database.initialize(
        sqlite.Config(database=":memory:")
    ) as database:
        await database.migrate(
            {
                "001": "CREATE TABLE fact_entry (value TEXT NOT NULL) STRICT; CREATE INDEX fact_index ON fact_entry(value)"
            }
        )
        result = await database.verify([Entry], policy="warn")

    assert_eq(
        {
            fact.kind: fact.status
            for fact in result.facts
            if fact.object_name == "fact_index"
        },
        {
            "index.presence": "matched",
            "index.columns": "matched",
            "index.unique": "drift",
            "index.partial": "matched",
        },
    )


@test(mark="fast")
async def table_presence_reports_drift_without_child_matches() -> None:
    """An absent table cannot provide evidence about its column properties."""

    class Entry[S = sqlite.Pending](sqlite.Model[S, "Entry[sqlite.Fetched]"]):
        value: sqlite.Col[str] = sqlite.Text()

    async with await sqlite.Database.initialize(
        sqlite.Config(database=":memory:")
    ) as database:
        result = await database.verify([Entry], policy="warn")

    assert_eq(
        [(fact.kind, fact.object_name, fact.status) for fact in result.facts],
        [("table.presence", None, "drift")],
    )


@test(mark="fast")
async def storage_options_are_compared_facts() -> None:
    """Non-STRICT storage remains drift and exposes its normalized evidence."""

    class Entry[S = sqlite.Pending](sqlite.Model[S, "Entry[sqlite.Fetched]"]):
        __tablename__ = "fact_entry"
        value: sqlite.Col[str] = sqlite.Text()

    async with await sqlite.Database.initialize(
        sqlite.Config(database=":memory:")
    ) as database:
        await database.migrate({"001": "CREATE TABLE fact_entry (value TEXT NOT NULL)"})
        result = await database.verify([Entry], policy="warn")

    assert_eq(
        [
            (fact.kind, fact.status)
            for fact in result.facts
            if fact.kind in {"table.presence", "table.storage_options"}
        ],
        [("table.presence", "matched"), ("table.storage_options", "drift")],
    )


@test(
    [
        Param(value="", name="absent"),
        Param(value=" ON DELETE CASCADE", name="changed-action"),
        Param(value=" ON DELETE RESTRICT", name="matching"),
    ],
    mark="fast",
)
async def scalar_foreign_key_relationships_have_facts(action: str) -> None:
    """A relationship's target and actions contribute to its comparison status."""

    class Parent[S = sqlite.Pending](sqlite.Model[S, "Parent[sqlite.Fetched]"]):
        __tablename__ = "fact_parent"
        id: sqlite.Col[int] = sqlite.Integer(primary_key=True)

    class Child[S = sqlite.Pending](sqlite.Model[S, "Child[sqlite.Fetched]"]):
        __tablename__ = "fact_child"
        parent_id: sqlite.FKCol[Parent, int] = sqlite.ForeignKey(
            Parent.id, on_delete="RESTRICT"
        )

    constraint = (
        f", FOREIGN KEY(parent_id) REFERENCES fact_parent(id){action}" if action else ""
    )
    async with await sqlite.Database.initialize(
        sqlite.Config(database=":memory:")
    ) as database:
        await database.migrate(
            {
                "001": f"CREATE TABLE fact_parent (id INTEGER PRIMARY KEY) STRICT; CREATE TABLE fact_child (parent_id INTEGER NOT NULL{constraint}) STRICT"
            }
        )
        result = await database.verify([Child], policy="warn")

    assert_eq(
        [
            (fact.object_name, fact.status)
            for fact in result.facts
            if fact.kind == "foreign_key.relationships"
        ],
        [("parent_id", "matched" if action == " ON DELETE RESTRICT" else "drift")],
    )


@test(
    [
        Param(value="", name="no-check"),
        Param(value=" CHECK(length(value) > 0)", name="check-present"),
    ],
    mark="fast",
)
async def unchecked_limits_do_not_claim_catalog_presence(check: str) -> None:
    """Strict success records uninspected CHECK scope with or without a live constraint."""

    class Entry[S = sqlite.Pending](sqlite.Model[S, "Entry[sqlite.Fetched]"]):
        __tablename__ = "fact_entry"
        value: sqlite.Col[str] = sqlite.Text()

    async with await sqlite.Database.initialize(
        sqlite.Config(database=":memory:")
    ) as database:
        await database.migrate(
            {"001": f"CREATE TABLE fact_entry (value TEXT NOT NULL{check}) STRICT"}
        )
        result = await database.verify([Entry])

    assert_eq(
        [
            (fact.object_name, fact.status, fact.detail)
            for fact in result.facts
            if fact.kind == "table.check_constraints"
        ],
        [
            (
                None,
                "unchecked",
                "CHECK verification covers declared names and supported expressions only; unmanaged checks, data, and enforcement settings are not certified",
            )
        ],
    )
    assert_eq(result.issues, ())


@test(mark="slow")
async def mariadb_json_backing_collation_is_unchecked() -> None:
    """Suppressed JSON catalog details must not appear as successful comparisons."""
    server = await load_fixture(provide_mariadb_server())

    class Entry[S = mariadb.Pending](mariadb.Model[S, "Entry[mariadb.Fetched]"]):
        __tablename__ = "fact_entry"
        payload: mariadb.Col[dict[str, int]] = mariadb.Json()

    async with await mariadb.Database.initialize(server.config()) as database:
        await database.migrate(
            {
                "001": "CREATE TABLE fact_entry (payload LONGTEXT CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci NOT NULL) ENGINE=InnoDB"
            }
        )
        result = await database.verify([Entry])

    assert_eq(
        [
            (fact.object_name, fact.status)
            for fact in result.facts
            if fact.kind == "column.collation"
        ],
        [("payload", "unchecked")],
    )
    assert_eq(
        [
            (fact.object_name, fact.status)
            for fact in result.facts
            if fact.kind == "column.json_check"
        ],
        [("payload", "unchecked")],
    )


@test(mark="slow")
async def mariadb_index_facts_do_not_certify_uninspected_partial_flags() -> None:
    """Missing backend metadata is not a successful partial-index comparison."""
    server = await load_fixture(provide_mariadb_server())

    class Entry[S = mariadb.Pending](mariadb.Model[S, "Entry[mariadb.Fetched]"]):
        __tablename__ = "fact_entry"
        value: mariadb.Col[str] = mariadb.Text()
        __indexes__: ClassVar = [mariadb.Index(value, name="fact_index")]

    async with await mariadb.Database.initialize(server.config()) as database:
        await database.migrate(
            {
                "001": "CREATE TABLE fact_entry (value VARCHAR(255) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin NOT NULL, INDEX fact_index (value)) ENGINE=InnoDB"
            }
        )
        result = await database.verify([Entry])

    assert_eq(
        {fact.kind for fact in result.facts if fact.object_name == "fact_index"},
        {
            "index.presence",
            "index.columns",
            "index.unique",
            "index.prefix_lengths",
            "index.type",
        },
    )


@test(mark="fast")
async def strict_errors_preserve_the_same_facts_as_warn_results() -> None:
    """Policy changes reporting, not the facts collected for every requested table."""

    class Entry[S = sqlite.Pending](sqlite.Model[S, "Entry[sqlite.Fetched]"]):
        __tablename__ = "fact_entry"
        value: sqlite.Col[str] = sqlite.Text()

    class Missing[S = sqlite.Pending](sqlite.Model[S, "Missing[sqlite.Fetched]"]):
        value: sqlite.Col[int] = sqlite.Integer()

    async with await sqlite.Database.initialize(
        sqlite.Config(database=":memory:")
    ) as database:
        await database.migrate(
            {"001": "CREATE TABLE fact_entry (value TEXT NULL) STRICT"}
        )
        warned = await database.verify([Entry, Missing], policy="warn")
        with assert_raises(sqlite.SchemaVerificationError) as error:
            await database.verify([Entry, Missing])

    assert_eq(error.exception.result, warned)
    assert_eq(warned.checked_tables, ("fact_entry", "missing"))


@test(mark="fast")
async def missing_columns_have_no_matched_property_facts() -> None:
    """Presence drift does not manufacture successful checks for absent columns."""

    class Entry[S = sqlite.Pending](sqlite.Model[S, "Entry[sqlite.Fetched]"]):
        __tablename__ = "fact_entry"
        value: sqlite.Col[str] = sqlite.Text()

    async with await sqlite.Database.initialize(
        sqlite.Config(database=":memory:")
    ) as database:
        await database.migrate(
            {"001": "CREATE TABLE fact_entry (unexpected TEXT NOT NULL) STRICT"}
        )
        result = await database.verify([Entry], policy="warn")

    assert_eq(
        [
            (fact.kind, fact.object_name, fact.status)
            for fact in result.facts
            if fact.kind.startswith("column.")
        ],
        [
            ("column.presence", "unexpected", "drift"),
            ("column.presence", "value", "drift"),
        ],
    )


@test(mark="fast")
async def missing_indexes_have_no_matched_property_facts() -> None:
    """An absent declared index and an extra live index each get presence drift only."""

    class Entry[S = sqlite.Pending](sqlite.Model[S, "Entry[sqlite.Fetched]"]):
        __tablename__ = "fact_entry"
        value: sqlite.Col[str] = sqlite.Text()
        __indexes__: ClassVar = [sqlite.Index(value, name="expected_index")]

    async with await sqlite.Database.initialize(
        sqlite.Config(database=":memory:")
    ) as database:
        await database.migrate(
            {
                "001": "CREATE TABLE fact_entry (value TEXT NOT NULL) STRICT; CREATE INDEX extra_index ON fact_entry(value)"
            }
        )
        result = await database.verify([Entry], policy="warn")

    assert_eq(
        [
            (fact.kind, fact.object_name, fact.status)
            for fact in result.facts
            if fact.kind.startswith("index.")
        ],
        [
            ("index.presence", "expected_index", "drift"),
            ("index.presence", "extra_index", "drift"),
        ],
    )


@test(mark="fast")
async def primary_key_membership_does_not_certify_order() -> None:
    """Reordered composite keys retain matched membership but explicit unchecked structure."""

    class Entry[S = sqlite.Pending](sqlite.Model[S, "Entry[sqlite.Fetched]"]):
        __tablename__ = "fact_entry"
        first: sqlite.Col[int] = sqlite.Integer(primary_key=True)
        second: sqlite.Col[int] = sqlite.Integer(primary_key=True)

    async with await sqlite.Database.initialize(
        sqlite.Config(database=":memory:")
    ) as database:
        await database.migrate(
            {
                "001": "CREATE TABLE fact_entry (first INTEGER NOT NULL, second INTEGER NOT NULL, PRIMARY KEY(second, first)) STRICT"
            }
        )
        result = await database.verify([Entry])

    assert_eq(
        [
            (fact.object_name, fact.status)
            for fact in result.facts
            if fact.kind == "column.primary_key"
        ],
        [("first", "matched"), ("second", "matched")],
    )
    assert_eq(
        [fact.status for fact in result.facts if fact.kind == "primary_key.structure"],
        ["unchecked"],
    )


@test(mark="fast")
async def scalar_relationship_matches_do_not_certify_composite_grouping() -> None:
    """A live composite FK can match flattened facts without proving scalar equivalence."""

    class Parent[S = sqlite.Pending](sqlite.Model[S, "Parent[sqlite.Fetched]"]):
        __tablename__ = "fact_parent"
        first: sqlite.Col[int] = sqlite.Integer(primary_key=True)
        second: sqlite.Col[int] = sqlite.Integer(unique=True)

    class Child[S = sqlite.Pending](sqlite.Model[S, "Child[sqlite.Fetched]"]):
        __tablename__ = "fact_child"
        first: sqlite.FKCol[Parent, int] = sqlite.ForeignKey(Parent.first)
        second: sqlite.FKCol[Parent, int] = sqlite.ForeignKey(Parent.second)

    async with await sqlite.Database.initialize(
        sqlite.Config(database=":memory:")
    ) as database:
        await database.migrate(
            {
                "001": "CREATE TABLE fact_parent (first INTEGER PRIMARY KEY, second INTEGER NOT NULL UNIQUE, UNIQUE(first, second)) STRICT; CREATE TABLE fact_child (first INTEGER NOT NULL, second INTEGER NOT NULL, FOREIGN KEY(first, second) REFERENCES fact_parent(first, second)) STRICT"
            }
        )
        with assert_raises(sqlite.SchemaVerificationError) as error:
            await database.verify([Child])
        result = error.exception.result

    assert_eq(
        [
            (fact.object_name, fact.status)
            for fact in result.facts
            if fact.kind == "foreign_key.relationships"
        ],
        [("first", "matched"), ("second", "matched")],
    )
    assert_eq(
        [fact.status for fact in result.facts if fact.kind == "foreign_keys.grouping"],
        ["drift"],
    )


@test(mark="slow")
async def maria_json_type_drift_is_not_overwritten_by_a_limitation() -> None:
    """Existing drift stays drift even when incompatible storage exposes a JSON-scope detail."""
    server = await load_fixture(provide_mariadb_server())

    class Entry[S = mariadb.Pending](mariadb.Model[S, "Entry[mariadb.Fetched]"]):
        __tablename__ = "fact_entry"
        payload: mariadb.Col[dict[str, int]] = mariadb.Json()

    async with await mariadb.Database.initialize(server.config()) as database:
        await database.migrate(
            {
                "001": "CREATE TABLE fact_entry (payload VARCHAR(255) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin NOT NULL) ENGINE=InnoDB"
            }
        )
        result = await database.verify([Entry], policy="warn")

    assert_eq(
        [fact.status for fact in result.facts if fact.kind == "column.collation"],
        ["drift"],
    )
    assert_eq(
        [fact.status for fact in result.facts if fact.kind == "column.type"], ["drift"]
    )


@test(mark="slow")
async def mariadb_facts_include_native_metadata() -> None:
    """Native precision, signedness, and collation are individually reported when inspected."""
    server = await load_fixture(provide_mariadb_server())

    class Entry[S = mariadb.Pending](mariadb.Model[S, "Entry[mariadb.Fetched]"]):
        __tablename__ = "fact_entry"
        amount: mariadb.Col[int] = mariadb.Integer()
        at: mariadb.Col[datetime] = mariadb.DateTime()
        name: mariadb.Col[str] = mariadb.Text(length=80, collation="utf8mb4_unicode_ci")

    async with await mariadb.Database.initialize(server.config()) as database:
        await database.migrate(
            {
                "001": "CREATE TABLE fact_entry (amount BIGINT UNSIGNED NOT NULL, at DATETIME(6) NOT NULL, name VARCHAR(80) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL) ENGINE=InnoDB"
            }
        )
        result = await database.verify([Entry], policy="warn")

    assert_eq(
        [
            (fact.object_name, fact.kind, fact.status)
            for fact in result.facts
            if fact.kind
            in {"column.unsigned", "column.datetime_precision", "column.collation"}
        ],
        [
            ("amount", "column.unsigned", "drift"),
            ("at", "column.datetime_precision", "drift"),
            ("name", "column.collation", "matched"),
        ],
    )


@test(mark="fast")
async def empty_verification_does_not_claim_any_facts() -> None:
    """An empty request certifies nothing about the database."""
    async with await sqlite.Database.initialize(
        sqlite.Config(database=":memory:")
    ) as database:
        result = await database.verify([])

    assert_eq(result.facts, ())


@test(mark="fast")
async def returned_facts_are_frozen_values() -> None:
    """The structured report and its entries remain immutable after verification."""

    class Entry[S = sqlite.Pending](sqlite.Model[S, "Entry[sqlite.Fetched]"]):
        value: sqlite.Col[str] = sqlite.Text()

    async with await sqlite.Database.initialize(
        sqlite.Config(database=":memory:")
    ) as database:
        result = await database.verify([Entry], policy="warn")

    with assert_raises(FrozenInstanceError):
        result.facts[0].status = "matched"  # ty: ignore[invalid-assignment]
    with assert_raises(FrozenInstanceError):
        result.facts = ()  # ty: ignore[invalid-assignment]


@test(mark="fast")
async def empty_foreign_key_comparison_reports_only_scalar_absence() -> None:
    """An empty scalar relationship comparison is evidence, not composite certification."""

    class Entry[S = sqlite.Pending](sqlite.Model[S, "Entry[sqlite.Fetched]"]):
        __tablename__ = "fact_entry"
        value: sqlite.Col[str] = sqlite.Text()

    async with await sqlite.Database.initialize(
        sqlite.Config(database=":memory:")
    ) as database:
        await database.migrate(
            {"001": "CREATE TABLE fact_entry (value TEXT NOT NULL) STRICT"}
        )
        result = await database.verify([Entry])

    assert_eq(
        [
            (fact.object_name, fact.status)
            for fact in result.facts
            if fact.kind == "foreign_key.relationships"
        ],
        [(None, "matched")],
    )


@test(mark="slow")
async def mariadb_strict_errors_preserve_the_same_facts_as_warn_results() -> None:
    """Native inspection reports the same complete evidence under either policy."""
    server = await load_fixture(provide_mariadb_server())

    class Entry[S = mariadb.Pending](mariadb.Model[S, "Entry[mariadb.Fetched]"]):
        __tablename__ = "fact_entry"
        value: mariadb.Col[str] = mariadb.Text()

    async with await mariadb.Database.initialize(server.config()) as database:
        await database.migrate(
            {
                "001": "CREATE TABLE fact_entry (value VARCHAR(255) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin NULL) ENGINE=InnoDB"
            }
        )
        warned = await database.verify([Entry], policy="warn")
        with assert_raises(mariadb.SchemaVerificationError) as error:
            await database.verify([Entry])

    assert_eq(error.exception.result, warned)


@test(mark="slow")
async def ignored_supporting_indexes_are_a_reported_limit() -> None:
    """A supporting index's uncertain origin remains unchecked, not certified absent."""
    server = await load_fixture(provide_mariadb_server())

    class Parent[S = mariadb.Pending](mariadb.Model[S, "Parent[mariadb.Fetched]"]):
        __tablename__ = "fact_parent"
        id: mariadb.Col[int] = mariadb.Integer(primary_key=True)

    class Child[S = mariadb.Pending](mariadb.Model[S, "Child[mariadb.Fetched]"]):
        __tablename__ = "fact_child"
        parent_id: mariadb.FKCol[Parent, int] = mariadb.ForeignKey(Parent.id)

    async with await mariadb.Database.initialize(server.config()) as database:
        await database.migrate(
            {
                "001": "CREATE TABLE fact_parent (id BIGINT NOT NULL PRIMARY KEY) ENGINE=InnoDB; CREATE TABLE fact_child (parent_id BIGINT NOT NULL, INDEX support(parent_id), FOREIGN KEY(parent_id) REFERENCES fact_parent(id)) ENGINE=InnoDB"
            }
        )
        result = await database.verify([Child])

    assert_eq(
        [
            fact.status
            for fact in result.facts
            if fact.kind == "indexes.fk_supporting_origin"
        ],
        ["unchecked"],
    )
    assert_eq([fact for fact in result.facts if fact.object_name == "support"], [])
