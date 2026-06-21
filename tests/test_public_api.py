"""Public API contract tests for snekql.

snekql has no flat top-level surface: the package root only re-exports the two
backend namespace handles, and every symbol -- the dialect-neutral verbs as well
as each backend's ``Model`` and column constructors -- is imported from
``snekql.sqlite`` or ``snekql.mariadb`` (see ADR 0004 / issue #138).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import cast

from snektest import test
from snektest.assertions import (
    assert_eq,
    assert_in,
    assert_is,
    assert_isinstance,
    assert_ne,
    assert_not_in,
)

import snekql
from snekql import mariadb, sqlite
from snekql.testing import mariadb as testing_mariadb

# The dialect-neutral symbols every backend namespace re-exports identically.
_COMMON_NAMES = frozenset(
    {
        "MISSING",
        "Aggregate",
        "Assignment",
        "Attr",
        "Col",
        "Database",
        "DatabaseCloseTimeoutError",
        "DatabaseClosedError",
        "DatabaseClosingError",
        "DatabaseRuntimeError",
        "DeleteQuery",
        "ExecutionError",
        "FKAttr",
        "FKCol",
        "Fetched",
        "FrozenModelError",
        "GenCol",
        "Index",
        "InsertManyQuery",
        "InsertManyReturningQuery",
        "InsertManyReturningTupleQuery",
        "InsertManyReturningValueQuery",
        "InsertQuery",
        "InsertReturningQuery",
        "InsertReturningTupleQuery",
        "InsertReturningValueQuery",
        "JoinModelQuery",
        "JoinOn",
        "MigrationError",
        "MigrationLockTimeoutError",
        "Missing",
        "ModelDeclarationError",
        "ModelError",
        "ModelMeta",
        "ModelValidationError",
        "OrderBy",
        "Pending",
        "PoolTimeoutError",
        "Predicate",
        "QueryCompilationError",
        "QueryConstructionError",
        "QueryError",
        "Scalar",
        "SchemaError",
        "SchemaPolicy",
        "SchemaVerificationError",
        "SelectModelQuery",
        "SelectTupleQuery",
        "SelectValueQuery",
        "SnekqlError",
        "Table",
        "Transaction",
        "TransactionClosedError",
        "UpdateQuery",
        "delete",
        "exists",
        "insert",
        "not_exists",
        "scalar",
        "select",
        "update",
    },
)
# Dialect-specific symbols shared by both backends: each backend's ``Model``
# base, ``Config``, and the four storage-primitive column constructors.
_DIALECT_NAMES = frozenset(
    {
        "Blob",
        "Config",
        "CurrentTimestamp",
        "ForeignKey",
        "Integer",
        "Model",
        "Real",
        "Text",
    },
)
# SQLite collapses to the four storage classes; MariaDB additionally exposes its
# native column types (``Boolean``/``DateTime``/``Json``/``Uuid``) and the JSON
# column attribute type.
_MARIADB_ONLY_NAMES = frozenset(
    {"Boolean", "DateTime", "Json", "JsonAttr", "Uuid"},
)
_SQLITE_EXPECTED = _COMMON_NAMES | _DIALECT_NAMES
_MARIADB_EXPECTED = _SQLITE_EXPECTED | _MARIADB_ONLY_NAMES


def _assert_has_specific_docstring(value: object) -> None:
    docstring = getattr(value, "__doc__", None)
    assert_ne(docstring, None)
    assert_ne(docstring, "")
    assert_ne(docstring, object.__doc__)


def _catch_as_snekql_error(error: sqlite.SnekqlError) -> None:
    try:
        raise error
    except sqlite.SnekqlError as caught_error:
        assert_is(caught_error, error)


@test()
def package_root_only_exposes_backend_namespaces() -> None:
    """The package root carries no flat surface, only the namespace handles."""

    assert_eq(tuple(snekql.__all__), ("mariadb", "sqlite"))
    assert_not_in("select", snekql.__all__)
    assert not hasattr(snekql, "select")
    assert not hasattr(snekql, "Model")


@test()
def backend_namespaces_export_canonical_names() -> None:
    """Each backend namespace curates the neutral plus its dialect-specific names."""

    assert_eq(frozenset(sqlite.__all__), _SQLITE_EXPECTED)
    assert_eq(frozenset(mariadb.__all__), _MARIADB_EXPECTED)
    for name in sqlite.__all__:
        assert_in(name, sqlite.__all__)
        assert_is(getattr(sqlite, name), getattr(sqlite, name))
    for name in mariadb.__all__:
        assert_is(getattr(mariadb, name), getattr(mariadb, name))


@test()
def testing_mariadb_namespace_exports_test_server_names() -> None:
    """The testing namespace exposes MariaDB test-server support directly."""

    assert_eq(
        tuple(testing_mariadb.__all__),
        (
            "MariaDBAuth",
            "MariaDBCommandResult",
            "MariaDBTransport",
            "TemporaryMariaDBServer",
            "TemporaryMariaDBServerError",
            "temporary_mariadb_server",
        ),
    )
    assert_in("mariadb", __import__("snekql.testing").testing.__all__)
    assert_in("temporary_mariadb_server", testing_mariadb.__all__)
    assert_isinstance(
        testing_mariadb.TemporaryMariaDBServerError("failure"),
        sqlite.SnekqlError,
    )
    assert "testing" not in snekql.__all__


@test()
def query_factory_functions_reject_empty_selects() -> None:
    """Selecting no model or fields is package-originated query misuse."""

    select_fn = cast("Callable[..., object]", sqlite.select)

    try:
        _ = select_fn()
    except sqlite.QueryConstructionError:
        return

    msg = "select() should reject empty selection"
    raise AssertionError(msg)


@test()
def column_declarations_produce_query_attributes() -> None:
    """Column declarations leave public descriptors on table model classes."""

    class AttributeUser(sqlite.Model[sqlite.Pending, "AttributeUser[sqlite.Fetched]"]):
        """Table model for descriptor smoke checks."""

        email: AttributeUser.Col[str] = sqlite.Text(nullable=False)

    assert_isinstance(AttributeUser.email, sqlite.Attr)
    assert_isinstance(AttributeUser.email.eq("alice@example.com"), sqlite.Predicate)
    assert_isinstance(AttributeUser.email.asc(), sqlite.OrderBy)
    assert_isinstance(AttributeUser.email.to("new@example.com"), sqlite.Assignment)


@test()
def backend_namespaces_diverge_on_dialect_specific_names() -> None:
    """The two namespaces share neutral symbols but own distinct dialect ones."""

    # Neutral symbols are the very same objects in both namespaces.
    assert_is(sqlite.select, mariadb.select)
    assert_is(sqlite.Attr, mariadb.Attr)
    assert_is(sqlite.Predicate, mariadb.Predicate)

    # The Model base differs per backend; the native MariaDB column types
    # (JSON, Boolean, DateTime, Uuid) have no SQLite counterpart.
    assert sqlite.Model is not mariadb.Model
    assert_in("Json", mariadb.__all__)
    assert_not_in("Json", sqlite.__all__)
    assert_in("Uuid", mariadb.__all__)
    assert_not_in("Uuid", sqlite.__all__)
    assert_in("JsonAttr", mariadb.__all__)
    assert_not_in("JsonAttr", sqlite.__all__)

    class SqliteUser(sqlite.Model[sqlite.Pending, "SqliteUser[sqlite.Fetched]"]):
        """SQLite table model declared through the SQLite namespace."""

        email: SqliteUser.Col[str] = sqlite.Text(nullable=False)

    assert_isinstance(SqliteUser.email, sqlite.Attr)
    assert_isinstance(SqliteUser.email.eq("alice@example.com"), sqlite.Predicate)


@test()
def mutation_query_chain_methods_return_query_objects() -> None:
    """Public update/delete chain methods keep returning mutation query objects."""

    class MutationUser(sqlite.Model[sqlite.Pending, "MutationUser[sqlite.Fetched]"]):
        """Table model for mutation chain smoke checks."""

        email: MutationUser.Col[str] = sqlite.Text(nullable=False)
        status: MutationUser.Col[str] = sqlite.Text(nullable=False)

    assignment = MutationUser.status.to("disabled")
    predicate = MutationUser.email.eq("alice@example.com")

    update_query = sqlite.update(MutationUser)
    delete_query = sqlite.delete(MutationUser)

    assert_isinstance(update_query.set(assignment), sqlite.UpdateQuery)
    assert_isinstance(update_query.where(predicate), sqlite.UpdateQuery)
    assert_isinstance(update_query.all(), sqlite.UpdateQuery)
    assert_isinstance(delete_query.where(predicate), sqlite.DeleteQuery)
    assert_isinstance(delete_query.all(), sqlite.DeleteQuery)


@test()
def select_query_chain_methods_return_query_objects() -> None:
    """Public select chain methods keep returning select query objects."""

    class ChainUser(sqlite.Model[sqlite.Pending, "ChainUser[sqlite.Fetched]"]):
        """Table model for select chain smoke checks."""

    query = sqlite.select(ChainUser)

    assert_isinstance(query.all(), sqlite.SelectModelQuery)
    assert_isinstance(query.limit(10), sqlite.SelectModelQuery)
    assert_isinstance(query.offset(5), sqlite.SelectModelQuery)


@test()
def query_factory_functions_return_public_query_objects() -> None:
    """Query builder entry points return stable public query classes."""

    class QueryUser(sqlite.Model[sqlite.Pending, "QueryUser[sqlite.Fetched]"]):
        """Table model for query factory smoke checks."""

    row = object.__new__(QueryUser)

    assert_isinstance(sqlite.select(QueryUser), sqlite.SelectModelQuery)
    assert_isinstance(sqlite.insert(row), sqlite.InsertQuery)
    assert_isinstance(sqlite.update(QueryUser), sqlite.UpdateQuery)
    assert_isinstance(sqlite.delete(QueryUser), sqlite.DeleteQuery)


@test()
def public_classes_have_specific_docstrings() -> None:
    """Public marker, error, column, query, and runtime classes explain intent."""

    documented_classes = (
        sqlite.Assignment,
        sqlite.Attr,
        sqlite.Blob,
        sqlite.CurrentTimestamp,
        sqlite.Database,
        sqlite.DatabaseClosedError,
        sqlite.DatabaseCloseTimeoutError,
        sqlite.DatabaseClosingError,
        sqlite.DatabaseRuntimeError,
        sqlite.DeleteQuery,
        sqlite.ExecutionError,
        sqlite.Fetched,
        sqlite.FrozenModelError,
        sqlite.Index,
        sqlite.InsertQuery,
        sqlite.Integer,
        sqlite.MigrationError,
        sqlite.MigrationLockTimeoutError,
        sqlite.Missing,
        sqlite.Model,
        sqlite.ModelDeclarationError,
        sqlite.ModelError,
        sqlite.ModelMeta,
        sqlite.ModelValidationError,
        sqlite.OrderBy,
        sqlite.Pending,
        sqlite.PoolTimeoutError,
        sqlite.Predicate,
        sqlite.QueryCompilationError,
        sqlite.QueryConstructionError,
        sqlite.QueryError,
        sqlite.Real,
        sqlite.SchemaError,
        sqlite.SchemaVerificationError,
        sqlite.SelectModelQuery,
        sqlite.SelectTupleQuery,
        sqlite.SelectValueQuery,
        sqlite.SnekqlError,
        sqlite.Table,
        sqlite.Text,
        sqlite.Transaction,
        sqlite.TransactionClosedError,
        sqlite.UpdateQuery,
    )

    for documented_class in documented_classes:
        _assert_has_specific_docstring(documented_class)


@test()
def missing_sentinel_has_stable_singleton_behavior() -> None:
    """MISSING is the only Missing value applications need to compare with."""

    assert_is(sqlite.Missing(), sqlite.MISSING)
    assert_eq(repr(sqlite.MISSING), "MISSING")


@test()
def public_error_hierarchy_is_rooted_at_snekql_error() -> None:
    """All intentional public errors can be caught as SnekqlError."""

    errors = (
        sqlite.DatabaseClosedError("package-originated failure"),
        sqlite.DatabaseCloseTimeoutError("package-originated failure"),
        sqlite.DatabaseClosingError("package-originated failure"),
        sqlite.ExecutionError(
            "package-originated failure",
            sql="SELECT ?",
            params=(1,),
        ),
        sqlite.FrozenModelError("package-originated failure"),
        sqlite.MigrationError("package-originated failure"),
        sqlite.MigrationLockTimeoutError("package-originated failure"),
        sqlite.ModelDeclarationError("package-originated failure"),
        sqlite.ModelValidationError("package-originated failure"),
        sqlite.PoolTimeoutError("package-originated failure"),
        sqlite.QueryCompilationError("package-originated failure"),
        sqlite.QueryConstructionError("package-originated failure"),
        sqlite.SchemaVerificationError("package-originated failure"),
        sqlite.TransactionClosedError("package-originated failure"),
    )

    catches: tuple[Callable[[], None], ...] = tuple(
        lambda error=error: _catch_as_snekql_error(error) for error in errors
    )

    for catch in catches:
        catch()


@test()
def execution_error_preserves_sql_and_params() -> None:
    """Execution failures expose query context through the public exception."""

    error = sqlite.ExecutionError(
        "insert failed",
        sql='INSERT INTO "user" ("email") VALUES (?)',
        params=("alice@example.com",),
    )

    assert_eq(error.sql, 'INSERT INTO "user" ("email") VALUES (?)')
    assert_eq(error.params, ("alice@example.com",))
    assert_in("insert failed", str(error))
    assert_in('INSERT INTO "user"', str(error))
    assert_in("alice@example.com", str(error))
