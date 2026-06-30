"""Property and table-driven tests for identifier validation (issue #65).

``ModelMeta._is_sql_identifier`` is the gate every table, column, and index
name passes through before it ever reaches a backend's ``quote_identifier``.
The quoting layer (``test_identifier_quoting_properties.py``) and the
compilers (``test_schema_compile_properties.py``,
``test_query_compilation_properties.py``) already pin that quoting cannot be
broken out of and that bound values stay parameterized -- for *whatever*
string reaches them. What neither covers is the validation boundary itself:
that a hostile name supplied where a table/column/index name is expected is
rejected with a domain error before it ever reaches a compiler, and that an
unusual-but-legal name (a reserved keyword, a very long name, a name with
non-ASCII letters) is accepted and survives the full declaration -> schema-DDL
/ query-compile pipeline safely for both backends.
"""

from __future__ import annotations

from typing import Any, cast

from hypothesis import settings
from hypothesis import strategies as st
from snektest import assert_eq, assert_raises, assert_true, test, test_hypothesis

from snekql.mariadb import scaffold as scaffold_mariadb_ddl
from snekql.mariadb.identifiers import quote_identifier as quote_mariadb
from snekql.mariadb.query import compile_mariadb_select_sql
from snekql.sqlite import Index, Integer, Model, ModelDeclarationError, select
from snekql.sqlite import scaffold as scaffold_sqlite_ddl
from snekql.sqlite.identifiers import quote_identifier as quote_sqlite
from snekql.sqlite.query import compile_sqlite_select_sql

# Characters with established meaning in SQL syntax: quote/backtick
# delimiters, statement separators, comment markers, NUL, and whitespace
# (including look-alike/invisible Unicode whitespace and a bidi-override code
# point, spelled as escapes rather than raw bytes so the source stays plain
# ASCII and a stray RTL-override character can't scramble the file's
# rendering). None of these is alphanumeric or "_", so any non-empty string
# drawn from this alphabet alone already falls outside the identifier
# charset whitelist -- the inputs most likely to expose a gap in the gate.
_DANGEROUS_CHARS = [
    '"',
    "`",
    "'",
    ";",
    "-",
    "/",
    "*",
    "(",
    ")",
    "=",
    "<",
    ">",
    "\\",
    ",",
    " ",
    "\n",
    "\t",
    "\r",
    "\x00",
    "\u00a0",  # no-break space
    "\u2028",  # line separator
    "\u3000",  # ideographic space
    "\u200b",  # zero-width space
    "\u202e",  # right-to-left override
]
_hostile_identifiers = st.text(
    alphabet=st.sampled_from(_DANGEROUS_CHARS),
    min_size=1,
    max_size=16,
)

# Concrete payload shapes a fuzzer drawing from a pure "dangerous" alphabet
# would not produce on its own: real words mixed with the syntax that turns a
# quoted name into multiple statements.
_INJECTION_PAYLOADS = (
    'x"; DROP TABLE users; --',
    "x`; DROP TABLE users; --",
    "x' OR '1'='1",
    'x" OR "1"="1',
    "x`--",
    'x"--',
    "x/*comment*/",
    "x;DELETE FROM x",
    "x\x00y",
    "x\nDROP TABLE x",
    "x DROP TABLE x",
    "",
    "1x",
    "x\u2028y",
    "x\u00a0y",
    "x\u202ey",
    "select * from x",
)

# Names that are awkward to look at but legal under the charset whitelist:
# reserved keywords in several cases, a bare/leading underscore, a very long
# name, and non-ASCII letters (the whitelist's alpha/alnum check is
# Unicode-aware, so these are accepted today).
_AWKWARD_VALID_IDENTIFIERS = (
    "select",
    "SELECT",
    "Select",
    "table",
    "TABLE",
    "order",
    "group",
    "index",
    "from",
    "where",
    "drop",
    "insert",
    "delete",
    "update",
    "primary",
    "key",
    "_",
    "_leading",
    "a",
    "A1",
    "x" * 200,
    "café",
    "naïve",
    "日本語",
    "Ω",
    "Москва",
)


def _model_with_table_name(
    table_name: str, *, backend: str = "sqlite"
) -> type[Model[Any, Any]]:
    return cast(
        "type[Model[Any, Any]]",
        type(
            "T",
            (Model,),
            {
                "__tablename__": table_name,
                "__snekql_backend__": backend,
                "id": Integer(primary_key=True, auto_increment=True, nullable=False),
            },
        ),
    )


def _model_with_column_name(
    column_name: str, *, backend: str = "sqlite"
) -> type[Model[Any, Any]]:
    # The annotation is read from the literal ``Model`` base, not the
    # dynamically built subclass: ``_extract_logical_type`` only inspects the
    # generic alias's own name/args, never which class produced it, so this
    # is a faithful stand-in for a normal ``some_model.Col[int]`` annotation
    # and lets predicate compilation encode a real value through it.
    return cast(
        "type[Model[Any, Any]]",
        type(
            "T",
            (Model,),
            {
                "__annotations__": {column_name: Model.Col[int]},
                "__snekql_backend__": backend,
                "id": Integer(primary_key=True, auto_increment=True, nullable=False),
                column_name: Integer(nullable=False),
            },
        ),
    )


def _model_with_index_name(
    index_name: str, *, backend: str = "sqlite"
) -> type[Model[Any, Any]]:
    column = Integer(nullable=False)
    return cast(
        "type[Model[Any, Any]]",
        type(
            "T",
            (Model,),
            {
                "__snekql_backend__": backend,
                "id": Integer(primary_key=True, auto_increment=True, nullable=False),
                "value": column,
                "__indexes__": [Index(column, name=index_name)],
            },
        ),
    )


@settings(deadline=None)
@test_hypothesis(_hostile_identifiers, mark="fast")
def hostile_table_names_are_rejected(name: str) -> None:
    """A name built only from SQL-meaningful characters can't become a table."""

    with assert_raises(ModelDeclarationError):
        _ = _model_with_table_name(name)


@settings(deadline=None)
@test_hypothesis(_hostile_identifiers, mark="fast")
def hostile_column_names_are_rejected(name: str) -> None:
    """A name built only from SQL-meaningful characters can't become a column."""

    with assert_raises(ModelDeclarationError):
        _ = _model_with_column_name(name)


@settings(deadline=None)
@test_hypothesis(_hostile_identifiers, mark="fast")
def hostile_index_names_are_rejected(name: str) -> None:
    """A name built only from SQL-meaningful characters can't become an index."""

    with assert_raises(ModelDeclarationError):
        _ = _model_with_index_name(name)


@test(mark="fast")
def classic_injection_payloads_are_rejected_in_every_position() -> None:
    """Concrete breakout-shaped payloads are rejected as table, column, and
    index names alike, with a domain error rather than reaching a compiler."""

    for payload in _INJECTION_PAYLOADS:
        with assert_raises(ModelDeclarationError):
            _ = _model_with_table_name(payload)
        with assert_raises(ModelDeclarationError):
            _ = _model_with_column_name(payload)
        with assert_raises(ModelDeclarationError):
            _ = _model_with_index_name(payload)


@test(mark="fast")
def hostile_identifiers_are_rejected_identically_for_both_backends() -> None:
    """Identifier validation runs before any backend dialect is consulted, so a
    hostile name is rejected the same way whether the model targets SQLite or
    MariaDB -- there is no backend-specific charset carve-out to fuzz around."""

    for payload in _INJECTION_PAYLOADS:
        with assert_raises(ModelDeclarationError):
            _ = _model_with_table_name(payload, backend="sqlite")
        with assert_raises(ModelDeclarationError):
            _ = _model_with_table_name(payload, backend="mariadb")


@test(mark="fast")
def awkward_but_valid_table_names_compile_safely_for_both_backends() -> None:
    """Reserved keywords, very long names, and non-ASCII letters all declare
    and scaffold to DDL carrying the table name only in its quoted form."""

    for name in _AWKWARD_VALID_IDENTIFIERS:
        model = _model_with_table_name(name)

        sqlite_ddl = scaffold_sqlite_ddl([model])
        assert_true(quote_sqlite(name) in sqlite_ddl)

        mariadb_ddl = scaffold_mariadb_ddl([model])
        assert_true(quote_mariadb(name) in mariadb_ddl)


@test(mark="fast")
def awkward_but_valid_index_names_compile_safely_for_both_backends() -> None:
    """An explicit index name that is a reserved keyword or non-ASCII still
    scaffolds to a CREATE INDEX statement carrying it only in quoted form."""

    for name in _AWKWARD_VALID_IDENTIFIERS:
        model = _model_with_index_name(name)

        sqlite_ddl = scaffold_sqlite_ddl([model])
        assert_true(quote_sqlite(name) in sqlite_ddl)

        mariadb_ddl = scaffold_mariadb_ddl([model])
        assert_true(quote_mariadb(name) in mariadb_ddl)


@test(mark="fast")
def awkward_but_valid_column_names_compile_safely_with_parameterized_values() -> None:
    """A reserved-keyword or non-ASCII column name reaches DDL only quoted, and
    a predicate against it still binds its value as a single placeholder --
    the column name and the bound value never share the same SQL token."""

    for name in _AWKWARD_VALID_IDENTIFIERS:
        model = _model_with_column_name(name)

        sqlite_ddl = scaffold_sqlite_ddl([model])
        assert_true(quote_sqlite(name) in sqlite_ddl)

        mariadb_ddl = scaffold_mariadb_ddl([model])
        assert_true(quote_mariadb(name) in mariadb_ddl)

        predicate = getattr(model, name).eq(1)

        sqlite_sql, sqlite_params = compile_sqlite_select_sql(
            select(model).where(predicate)
        )
        assert_true(quote_sqlite(name) in sqlite_sql)
        assert_eq(sqlite_sql.count("?"), 1)
        assert_eq(sqlite_params, (1,))

        mariadb_sql, mariadb_params = compile_mariadb_select_sql(
            select(model).where(predicate)
        )
        assert_true(quote_mariadb(name) in mariadb_sql)
        assert_eq(mariadb_sql.count("%s"), 1)
        assert_eq(mariadb_params, (1,))
