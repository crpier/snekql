"""Public API contract tests for snekql."""

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
)

import snekql
from snekql.testing import mariadb as testing_mariadb


def _assert_has_specific_docstring(value: object) -> None:
    docstring = getattr(value, "__doc__", None)
    assert_ne(docstring, None)
    assert_ne(docstring, "")
    assert_ne(docstring, object.__doc__)


def _catch_as_snekql_error(error: snekql.SnekqlError) -> None:
    try:
        raise error
    except snekql.SnekqlError as caught_error:
        assert_is(caught_error, error)


@test()
def public_contract_exports_canonical_names() -> None:
    """The package root explicitly curates canonical PRD names."""

    expected_names = (
        "MISSING",
        "Aggregate",
        "Assignment",
        "Attr",
        "Blob",
        "Boolean",
        "Col",
        "CurrentTimestamp",
        "Database",
        "DatabaseCloseTimeoutError",
        "DatabaseClosedError",
        "DatabaseClosingError",
        "DatabaseRuntimeError",
        "DateTime",
        "DeleteQuery",
        "ExecutionError",
        "FKAttr",
        "FKCol",
        "Fetched",
        "ForeignKey",
        "FrozenModelError",
        "GenCol",
        "Index",
        "InsertQuery",
        "Integer",
        "JoinModelQuery",
        "JoinOn",
        "Json",
        "MigrationError",
        "MigrationLockTimeoutError",
        "Missing",
        "Model",
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
        "Real",
        "Scalar",
        "SchemaError",
        "SchemaPolicy",
        "SchemaVerificationError",
        "SelectModelQuery",
        "SelectTupleQuery",
        "SelectValueQuery",
        "SnekqlError",
        "StructuredLogger",
        "Table",
        "Text",
        "Transaction",
        "TransactionClosedError",
        "UpdateQuery",
        "delete",
        "exists",
        "insert",
        "mariadb",
        "not_exists",
        "scalar",
        "select",
        "sqlite",
        "update",
    )

    assert_eq(tuple(snekql.__all__), expected_names)
    for name in expected_names:
        assert_in(name, snekql.__all__)
        assert_eq(getattr(snekql, name), getattr(snekql, name))


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
        snekql.SnekqlError,
    )
    assert "testing" not in snekql.__all__


@test()
def query_factory_functions_reject_empty_selects() -> None:
    """Selecting no model or fields is package-originated query misuse."""

    select_fn = cast("Callable[..., object]", snekql.select)

    try:
        _ = select_fn()
    except snekql.QueryConstructionError:
        return

    msg = "select() should reject empty selection"
    raise AssertionError(msg)


@test()
def column_declarations_produce_query_attributes() -> None:
    """Column declarations leave public descriptors on table model classes."""

    class AttributeUser(snekql.Model[snekql.Pending, "AttributeUser[snekql.Fetched]"]):
        """Table model for descriptor smoke checks."""

        email: AttributeUser.Col[str] = snekql.Text(nullable=False)

    assert_isinstance(AttributeUser.email, snekql.Attr)
    assert_isinstance(AttributeUser.email.eq("alice@example.com"), snekql.Predicate)
    assert_isinstance(AttributeUser.email.asc(), snekql.OrderBy)
    assert_isinstance(AttributeUser.email.to("new@example.com"), snekql.Assignment)


@test()
def sqlite_namespace_exports_backend_specific_names() -> None:
    """The SQLite namespace exposes the future backend-specific model shape."""

    assert_is(snekql.sqlite.Model, snekql.Model)
    assert_is(snekql.sqlite.Index, snekql.Index)
    assert_is(snekql.sqlite.Integer, snekql.Integer)
    assert_is(snekql.sqlite.Text, snekql.Text)
    assert_in("Config", snekql.sqlite.__all__)

    class SqliteUser(snekql.sqlite.Model[snekql.Pending, "SqliteUser[snekql.Fetched]"]):
        """SQLite table model declared through the SQLite namespace."""

        email: SqliteUser.Col[str] = snekql.sqlite.Text(nullable=False)

    assert_isinstance(SqliteUser.email, snekql.sqlite.Attr)
    assert_isinstance(SqliteUser.email.eq("alice@example.com"), snekql.Predicate)


@test()
def mutation_query_chain_methods_return_query_objects() -> None:
    """Public update/delete chain methods keep returning mutation query objects."""

    class MutationUser(snekql.Model[snekql.Pending, "MutationUser[snekql.Fetched]"]):
        """Table model for mutation chain smoke checks."""

        email: MutationUser.Col[str] = snekql.Text(nullable=False)
        status: MutationUser.Col[str] = snekql.Text(nullable=False)

    assignment = MutationUser.status.to("disabled")
    predicate = MutationUser.email.eq("alice@example.com")

    update_query = snekql.update(MutationUser)
    delete_query = snekql.delete(MutationUser)

    assert_isinstance(update_query.set(assignment), snekql.UpdateQuery)
    assert_isinstance(update_query.where(predicate), snekql.UpdateQuery)
    assert_isinstance(update_query.all(), snekql.UpdateQuery)
    assert_isinstance(delete_query.where(predicate), snekql.DeleteQuery)
    assert_isinstance(delete_query.all(), snekql.DeleteQuery)


@test()
def select_query_chain_methods_return_query_objects() -> None:
    """Public select chain methods keep returning select query objects."""

    class ChainUser(snekql.Model[snekql.Pending, "ChainUser[snekql.Fetched]"]):
        """Table model for select chain smoke checks."""

    query = snekql.select(ChainUser)

    assert_isinstance(query.all(), snekql.SelectModelQuery)
    assert_isinstance(query.limit(10), snekql.SelectModelQuery)
    assert_isinstance(query.offset(5), snekql.SelectModelQuery)


@test()
def query_factory_functions_return_public_query_objects() -> None:
    """Query builder entry points return stable public query classes."""

    class QueryUser(snekql.Model[snekql.Pending, "QueryUser[snekql.Fetched]"]):
        """Table model for query factory smoke checks."""

    row = object.__new__(QueryUser)

    assert_isinstance(snekql.select(QueryUser), snekql.SelectModelQuery)
    assert_isinstance(snekql.insert(row), snekql.InsertQuery)
    assert_isinstance(snekql.update(QueryUser), snekql.UpdateQuery)
    assert_isinstance(snekql.delete(QueryUser), snekql.DeleteQuery)


@test()
def public_classes_have_specific_docstrings() -> None:
    """Public marker, error, column, query, and runtime classes explain intent."""

    documented_classes = (
        snekql.Assignment,
        snekql.Attr,
        snekql.Blob,
        snekql.Boolean,
        snekql.CurrentTimestamp,
        snekql.Database,
        snekql.DatabaseClosedError,
        snekql.DatabaseCloseTimeoutError,
        snekql.DatabaseClosingError,
        snekql.DatabaseRuntimeError,
        snekql.DateTime,
        snekql.DeleteQuery,
        snekql.ExecutionError,
        snekql.Fetched,
        snekql.FrozenModelError,
        snekql.Index,
        snekql.InsertQuery,
        snekql.Integer,
        snekql.Json,
        snekql.MigrationError,
        snekql.MigrationLockTimeoutError,
        snekql.Missing,
        snekql.Model,
        snekql.ModelDeclarationError,
        snekql.ModelError,
        snekql.ModelMeta,
        snekql.ModelValidationError,
        snekql.OrderBy,
        snekql.Pending,
        snekql.PoolTimeoutError,
        snekql.Predicate,
        snekql.QueryCompilationError,
        snekql.QueryConstructionError,
        snekql.QueryError,
        snekql.Real,
        snekql.SchemaError,
        snekql.SchemaVerificationError,
        snekql.SelectModelQuery,
        snekql.SelectTupleQuery,
        snekql.SelectValueQuery,
        snekql.SnekqlError,
        snekql.Table,
        snekql.Text,
        snekql.Transaction,
        snekql.TransactionClosedError,
        snekql.UpdateQuery,
    )

    for documented_class in documented_classes:
        _assert_has_specific_docstring(documented_class)


@test()
def missing_sentinel_has_stable_singleton_behavior() -> None:
    """MISSING is the only Missing value applications need to compare with."""

    assert_is(snekql.Missing(), snekql.MISSING)
    assert_eq(repr(snekql.MISSING), "MISSING")


@test()
def public_error_hierarchy_is_rooted_at_snekql_error() -> None:
    """All intentional public errors can be caught as SnekqlError."""

    errors = (
        snekql.DatabaseClosedError("package-originated failure"),
        snekql.DatabaseCloseTimeoutError("package-originated failure"),
        snekql.DatabaseClosingError("package-originated failure"),
        snekql.ExecutionError(
            "package-originated failure",
            sql="SELECT ?",
            params=(1,),
        ),
        snekql.FrozenModelError("package-originated failure"),
        snekql.MigrationError("package-originated failure"),
        snekql.MigrationLockTimeoutError("package-originated failure"),
        snekql.ModelDeclarationError("package-originated failure"),
        snekql.ModelValidationError("package-originated failure"),
        snekql.PoolTimeoutError("package-originated failure"),
        snekql.QueryCompilationError("package-originated failure"),
        snekql.QueryConstructionError("package-originated failure"),
        snekql.SchemaVerificationError("package-originated failure"),
        snekql.TransactionClosedError("package-originated failure"),
    )

    catches: tuple[Callable[[], None], ...] = tuple(
        lambda error=error: _catch_as_snekql_error(error) for error in errors
    )

    for catch in catches:
        catch()


@test()
def execution_error_preserves_sql_and_params() -> None:
    """Execution failures expose query context through the public exception."""

    error = snekql.ExecutionError(
        "insert failed",
        sql='INSERT INTO "user" ("email") VALUES (?)',
        params=("alice@example.com",),
    )

    assert_eq(error.sql, 'INSERT INTO "user" ("email") VALUES (?)')
    assert_eq(error.params, ("alice@example.com",))
    assert_in("insert failed", str(error))
    assert_in('INSERT INTO "user"', str(error))
    assert_in("alice@example.com", str(error))
