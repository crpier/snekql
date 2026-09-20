"""Native LONGTEXT declarations preserve ordinary text semantics."""

import warnings
from decimal import Decimal

from snektest import Param, assert_eq, assert_in, assert_raises, load_fixture, test

from snekql import mariadb, sqlite
from tests.helpers import provide_mariadb_server


@test(mark="fast")
def scaffold_emits_native_long_text() -> None:
    """LongText is ordinary string storage, not the JSON alias or VARCHAR."""

    class Document[S = mariadb.Pending](mariadb.Model[S, "Document[mariadb.Fetched]"]):
        body: mariadb.Col[str] = mariadb.LongText()

    assert_in(
        "LONGTEXT CHARACTER SET utf8mb4 COLLATE utf8mb4_bin",
        mariadb.scaffold([Document]),
    )


@test(mark="slow")
async def matching_long_text_verifies() -> None:
    """Verification includes native type and text collation for LONGTEXT."""
    server = await load_fixture(provide_mariadb_server())

    class Document[S = mariadb.Pending](mariadb.Model[S, "Document[mariadb.Fetched]"]):
        __tablename__ = "long_document"
        body: mariadb.Col[str] = mariadb.LongText()

    async with await mariadb.Database.initialize(server.config()) as database:
        await database.migrate(
            {
                "001": "CREATE TABLE long_document (body LONGTEXT CHARACTER SET utf8mb4 COLLATE utf8mb4_bin NOT NULL) ENGINE=InnoDB"
            }
        )
        assert_eq((await database.verify([Document])).issues, ())


@test(mark="fast")
def long_text_cannot_be_a_physical_fk_target() -> None:
    """A long-text target cannot acquire a foreign key through derived storage."""

    class Document[S = mariadb.Pending](mariadb.Model[S, "Document[mariadb.Fetched]"]):
        body: mariadb.Col[str] = mariadb.LongText()

    with assert_raises(mariadb.ModelDeclarationError):
        mariadb.ForeignKey(Document.body)


@test(mark="fast")
def long_text_cannot_enter_a_compound_index() -> None:
    """Table-level Index cannot bypass the constructor's storage restriction."""

    class Document[S = mariadb.Pending](mariadb.Model[S, "Document[mariadb.Fetched]"]):
        body: mariadb.Col[str] = mariadb.LongText()
        tag: mariadb.Col[str] = mariadb.Text()

    with assert_raises(mariadb.ModelDeclarationError):
        mariadb.Index(Document.tag, Document.body)


@test(mark="slow")
async def long_text_supports_pattern_matching_and_large_values() -> None:
    """Ordinary text predicates and materialization work beyond VARCHAR/TEXT capacity."""
    server = await load_fixture(provide_mariadb_server())

    class Document[S = mariadb.Pending](mariadb.Model[S, "Document[mariadb.Fetched]"]):
        __tablename__ = "long_document"
        body: mariadb.Col[str] = mariadb.LongText()

    value = "prefix-" + "🐍" * 20000
    async with await mariadb.Database.initialize(server.config()) as database:
        await database.migrate(
            {
                "001": "CREATE TABLE long_document (body LONGTEXT CHARACTER SET utf8mb4 COLLATE utf8mb4_bin NOT NULL) ENGINE=InnoDB"
            }
        )
        async with database.transaction() as transaction:
            await transaction.execute(mariadb.insert(Document(body=value)))
        async with database.transaction() as transaction:
            received = await transaction.fetch_one(
                mariadb.select(Document.body).where(Document.body.like("prefix-%"))
            )
        assert_eq(received, value)


@test(
    [
        Param(value=("TEXT", "utf8mb4_bin"), name="text"),
        Param(value=("MEDIUMTEXT", "utf8mb4_bin"), name="mediumtext"),
        Param(value=("VARCHAR(512)", "utf8mb4_bin"), name="varchar"),
        Param(value=("LONGTEXT", "utf8mb4_general_ci"), name="collation"),
    ],
    mark="slow",
)
async def differing_native_storage_is_drift(declaration: tuple[str, str]) -> None:
    """Other string storage classes and collations do not silently match LONGTEXT."""
    server = await load_fixture(provide_mariadb_server())

    class Document[S = mariadb.Pending](mariadb.Model[S, "Document[mariadb.Fetched]"]):
        __tablename__ = "long_document"
        body: mariadb.Col[str] = mariadb.LongText()

    native_type, collation = declaration
    async with await mariadb.Database.initialize(server.config()) as database:
        await database.migrate(
            {
                "001": f"CREATE TABLE long_document (body {native_type} CHARACTER SET utf8mb4 COLLATE {collation} NOT NULL) ENGINE=InnoDB"
            }
        )
        with assert_raises(mariadb.SchemaVerificationError):
            await database.verify([Document])


@test(
    [
        Param(value="utf8mb4_bin", name="matching"),
        Param(value="utf8mb4_general_ci", name="drift"),
    ],
    mark="slow",
)
async def json_alias_scope_does_not_hide_long_text_collation(collation: str) -> None:
    """JSON's deliberately unchecked backing collation cannot mask a neighboring text column."""
    server = await load_fixture(provide_mariadb_server())

    class Document[S = mariadb.Pending](mariadb.Model[S, "Document[mariadb.Fetched]"]):
        __tablename__ = "long_document"
        body: mariadb.Col[str] = mariadb.LongText()
        payload: mariadb.Col[dict[str, int]] = mariadb.Json()

    async with await mariadb.Database.initialize(server.config()) as database:
        await database.migrate(
            {
                "001": f"CREATE TABLE long_document (body LONGTEXT CHARACTER SET utf8mb4 COLLATE {collation} NOT NULL, payload LONGTEXT CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci NOT NULL) ENGINE=InnoDB"
            }
        )
        if collation == "utf8mb4_bin":
            assert_eq((await database.verify([Document])).issues, ())
        else:
            with assert_raises(mariadb.SchemaVerificationError):
                await database.verify([Document])


@test(mark="fast")
def no_capacity_or_key_options_are_exposed() -> None:
    """Unsupported storage options fail at the constructor, not during DDL execution."""
    with assert_raises(TypeError):
        mariadb.LongText(length=255)  # ty: ignore[no-matching-overload]
    with assert_raises(TypeError):
        mariadb.LongText(primary_key=True)  # ty: ignore[no-matching-overload]
    with assert_raises(TypeError):
        mariadb.LongText(unique=True)  # ty: ignore[no-matching-overload]
    with assert_raises(TypeError):
        mariadb.LongText(index=True)  # ty: ignore[no-matching-overload]


@test(
    [Param(value="nonunique", name="nonunique"), Param(value="unique", name="unique")],
    mark="fast",
)
def standalone_indexes_are_rejected(kind: str) -> None:
    """Neither full-column regular nor unique indexes are supported for LongText."""

    class Document[S = mariadb.Pending](mariadb.Model[S, "Document[mariadb.Fetched]"]):
        body: mariadb.Col[str] = mariadb.LongText()

    with assert_raises(mariadb.ModelDeclarationError):
        mariadb.Index(Document.body, unique=kind == "unique")


@test(mark="slow")
async def nullable_long_text_keeps_python_default_semantics() -> None:
    """Missing Python values become NULL while explicit long strings remain unchanged."""
    server = await load_fixture(provide_mariadb_server())

    class Document[S = mariadb.Pending](mariadb.Model[S, "Document[mariadb.Fetched]"]):
        __tablename__ = "long_document"
        id: mariadb.Col[int] = mariadb.Integer(primary_key=True)
        body: mariadb.Col[str | None] = mariadb.LongText(default=None)

    async with await mariadb.Database.initialize(server.config()) as database:
        await database.migrate(
            {
                "001": "CREATE TABLE long_document (id BIGINT NOT NULL PRIMARY KEY, body LONGTEXT CHARACTER SET utf8mb4 COLLATE utf8mb4_bin NULL) ENGINE=InnoDB"
            }
        )
        await database.verify([Document])
        async with database.transaction() as transaction:
            await transaction.execute(mariadb.insert(Document(id=1)))
        async with database.transaction() as transaction:
            row = await transaction.fetch_one(
                mariadb.select(Document).where(Document.id.eq(1))
            )
        assert_eq(row.body, None)


@test(mark="fast")
def long_text_factory_defaults_are_not_sql_defaults() -> None:
    """LongText retains Text's Python construction defaults without truncation."""

    class Document[S = mariadb.Pending](mariadb.Model[S, "Document[mariadb.Fetched]"]):
        body: mariadb.Col[str] = mariadb.LongText(
            default_factory=lambda: "large" * 1000
        )

    assert_eq(Document().body, "large" * 1000)


@test(mark="fast")
def sqlite_does_not_expose_long_text() -> None:
    """SQLite TEXT already supplies its native large string storage."""
    assert_eq(hasattr(sqlite, "LongText"), False)


@test(mark="fast")
def long_text_keeps_lexical_decimal_warnings() -> None:
    """Native capacity does not make serialized decimal order numerically safe."""
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always", mariadb.LexicalDecimalWarning)

        class Price[S = mariadb.Pending](mariadb.Model[S, "Price[mariadb.Fetched]"]):
            amount: mariadb.Col[Decimal] = mariadb.LongText()

    assert_eq(len(caught), 1)
    assert_eq(caught[0].category, mariadb.LexicalDecimalWarning)
