"""Public API contract tests for snekql.

snekql has no flat top-level surface: the package root only re-exports the two
backend namespace handles, and every symbol -- the dialect-neutral verbs as well
as each backend's ``Model`` and column constructors -- is imported from
``snekql.sqlite`` or ``snekql.mariadb`` (see ADR 0004 / issue #138).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import FrozenInstanceError
from inspect import isclass
from typing import Any, cast

from snektest import assert_raises, test
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
_NEUTRAL_NAMES = frozenset(
    {
        "PENDING_GENERATION",
        "Aggregate",
        "Assignment",
        "Canonical",
        "CanonicalDecimal",
        "ChunkStream",
        "Col",
        "ColumnRef",
        "Database",
        "DatabaseCloseTimeoutError",
        "DatabaseClosedError",
        "DatabaseClosingError",
        "DatabaseRuntimeError",
        "DoNothing",
        "DoUpdate",
        "Duration",
        "ExecutionError",
        "FKCol",
        "Fetched",
        "FrozenModelError",
        "GenCol",
        "Index",
        "JoinOn",
        "LexicalDatetimeWarning",
        "LexicalDecimalWarning",
        "LexicalDurationWarning",
        "MigrationDeclarationError",
        "MigrationError",
        "MigrationHistoryError",
        "MigrationLockError",
        "MigrationLockTimeoutError",
        "MigrationResult",
        "PendingGeneration",
        "ModelDeclarationError",
        "ModelError",
        "ModelValidationError",
        "MultipleResultsError",
        "NoResultError",
        "OrderBy",
        "OrderPreserving",
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
        "Select",
        "SnekqlError",
        "SnekqlWarning",
        "Transaction",
        "TransactionClosedError",
        "TransactionMode",
        "TransactionNotStartedError",
        "TransactionReuseError",
        "TransactionStateError",
        "UtcDatetime",
        "Write",
        "exists",
        "not_exists",
        "scalar",
        "select",
    },
)
# Write verbs are owned by each backend namespace so their docstrings can
# describe driver-specific write semantics while preserving the same query API.
_WRITE_VERB_NAMES = frozenset({"delete", "insert", "update"})
# Dialect-specific symbols shared by both backends: each backend's ``Model``
# base, ``Config``, ``scaffold`` (bound to that backend's DDL dialect), and the
# four storage-primitive column constructors.
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
        "scaffold",
    },
)
# SQLite collapses to the four storage classes; MariaDB additionally exposes its
# native column types (``Boolean``/``DateTime``/``Json``/``Uuid``) and the JSON
# column attribute type.
_MARIADB_ONLY_NAMES = frozenset(
    {"Boolean", "DateTime", "Decimal", "Json", "JsonCol", "Uuid"},
)
_SQLITE_EXPECTED = _NEUTRAL_NAMES | _WRITE_VERB_NAMES | _DIALECT_NAMES
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
def backend_namespaces_hide_implementation_types() -> None:
    """Descriptors, metaclasses, and state-specific query classes stay internal."""

    hidden_names = (
        "Attr",
        "DeleteQuery",
        "DeleteReturningQuery",
        "DeleteReturningTupleQuery",
        "DeleteReturningValueQuery",
        "FKAttr",
        "InsertManyQuery",
        "InsertManyReturningQuery",
        "InsertManyReturningTupleQuery",
        "InsertManyReturningValueQuery",
        "InsertQuery",
        "InsertReturningQuery",
        "InsertReturningTupleQuery",
        "InsertReturningValueQuery",
        "JoinModelQuery",
        "ModelMeta",
        "Migration",
        "MigrationRecord",
        "SelectModelQuery",
        "SelectTupleQuery",
        "SelectValueQuery",
        "Table",
        "UpdateQuery",
        "UpdateReturningQuery",
        "UpdateReturningTupleQuery",
        "UpdateReturningValueQuery",
    )
    for namespace in (sqlite, mariadb):
        for name in hidden_names:
            assert_not_in(name, namespace.__all__)
            assert not hasattr(namespace, name)
    assert not hasattr(mariadb, "JsonAttr")


@test()
def result_oriented_query_annotations_are_not_constructors() -> None:
    """Select and Write name results without exposing constructible query states."""

    for namespace in (sqlite, mariadb):
        assert not callable(namespace.Select)
        assert not callable(namespace.Write)


@test()
def storage_declarations_are_functions() -> None:
    """Field specifiers are callable functions rather than constructor classes."""

    constructors = (
        sqlite.Blob,
        sqlite.ForeignKey,
        sqlite.Integer,
        sqlite.Real,
        sqlite.Text,
        mariadb.Blob,
        mariadb.Boolean,
        mariadb.DateTime,
        mariadb.Decimal,
        mariadb.ForeignKey,
        mariadb.Integer,
        mariadb.Json,
        mariadb.Real,
        mariadb.Text,
        mariadb.Uuid,
    )
    for constructor in constructors:
        assert callable(constructor)
        assert not isclass(constructor)


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

    class AttributeUser[S = sqlite.Pending](
        sqlite.Model[S, "AttributeUser[sqlite.Fetched]"]
    ):
        """Table model for descriptor smoke checks."""

        email: AttributeUser.Col[str] = sqlite.Text(nullable=False)

    assert_isinstance(AttributeUser.email, sqlite.ColumnRef)
    assert_isinstance(AttributeUser.email.eq("alice@example.com"), sqlite.Predicate)
    assert_isinstance(AttributeUser.email.asc(), sqlite.OrderBy)
    assert_isinstance(AttributeUser.email.to("new@example.com"), sqlite.Assignment)
    assert_isinstance(AttributeUser.email.to_inserted(), sqlite.Assignment)


@test()
def backend_namespaces_diverge_on_dialect_specific_names() -> None:
    """The two namespaces share neutral symbols but own distinct dialect ones."""

    # Neutral symbols are the very same objects in both namespaces.
    assert_is(sqlite.select, mariadb.select)
    assert_is(sqlite.ColumnRef, mariadb.ColumnRef)
    assert_is(sqlite.Predicate, mariadb.Predicate)
    assert_is(sqlite.Select, mariadb.Select)
    assert_is(sqlite.Write, mariadb.Write)

    # The Model base differs per backend; the native MariaDB column types
    # (JSON, Boolean, DateTime, Uuid) have no SQLite counterpart.
    assert sqlite.Model is not mariadb.Model
    assert_in("Json", mariadb.__all__)
    assert_not_in("Json", sqlite.__all__)
    assert_in("Uuid", mariadb.__all__)
    assert_not_in("Uuid", sqlite.__all__)
    assert_not_in("JsonAttr", mariadb.__all__)

    class SqliteUser[S = sqlite.Pending](sqlite.Model[S, "SqliteUser[sqlite.Fetched]"]):
        """SQLite table model declared through the SQLite namespace."""

        email: SqliteUser.Col[str] = sqlite.Text(nullable=False)

    assert_isinstance(SqliteUser.email, sqlite.ColumnRef)
    assert_isinstance(SqliteUser.email.eq("alice@example.com"), sqlite.Predicate)


@test()
def mutation_query_chain_methods_return_query_objects() -> None:
    """Public update/delete chain methods keep returning mutation query objects."""

    class MutationUser[S = sqlite.Pending](
        sqlite.Model[S, "MutationUser[sqlite.Fetched]"]
    ):
        """Table model for mutation chain smoke checks."""

        email: MutationUser.Col[str] = sqlite.Text(nullable=False)
        status: MutationUser.Col[str] = sqlite.Text(nullable=False)

    assignment = MutationUser.status.to("disabled")
    predicate = MutationUser.email.eq("alice@example.com")

    update_query = sqlite.update(MutationUser)
    delete_query = sqlite.delete(MutationUser)

    assert_is(type(update_query.set(assignment)), type(update_query))
    assert_is(type(update_query.where(predicate)), type(update_query))
    assert_is(type(update_query.all()), type(update_query))
    assert_is(type(delete_query.where(predicate)), type(delete_query))
    assert_is(type(delete_query.all()), type(delete_query))
    insert_query = sqlite.insert(
        MutationUser(email="alice@example.com", status="active")
    )
    assert_is(
        type(
            insert_query.on_conflict(
                MutationUser.email,
                action=sqlite.DoUpdate(MutationUser.status.to_inserted()),
            )
        ),
        type(insert_query),
    )


@test()
def select_query_chain_methods_return_query_objects() -> None:
    """Public select chain methods keep returning select query objects."""

    class ChainUser[S = sqlite.Pending](sqlite.Model[S, "ChainUser[sqlite.Fetched]"]):
        """Table model for select chain smoke checks."""

    query = sqlite.select(ChainUser)

    assert_is(type(query.all()), type(query))
    assert_is(type(query.limit(10)), type(query))
    assert_is(type(query.offset(5)), type(query))


@test()
def write_verbs_diverge_with_backend_specific_docstrings() -> None:
    """insert/update/delete are per-backend verbs that document each driver's writes."""

    # The write verbs are distinct objects per backend, unlike neutral ``select``.
    assert sqlite.insert is not mariadb.insert
    assert sqlite.update is not mariadb.update
    assert sqlite.delete is not mariadb.delete
    assert_is(sqlite.select, mariadb.select)

    # The docstrings name the backend and explain its affected-row count.
    assert_in("SQLite", sqlite.insert.__doc__ or "")
    assert_in("MariaDB", mariadb.insert.__doc__ or "")
    assert_in("matched", sqlite.update.__doc__ or "")
    assert_in("CLIENT_FOUND_ROWS", mariadb.update.__doc__ or "")


@test()
def public_symbols_have_specific_docstrings() -> None:
    """Public markers, errors, constructors, and runtime types explain intent."""

    documented_classes = (
        sqlite.Assignment,
        sqlite.Blob,
        sqlite.ColumnRef,
        sqlite.CurrentTimestamp,
        sqlite.Database,
        sqlite.DatabaseClosedError,
        sqlite.DatabaseCloseTimeoutError,
        sqlite.DatabaseClosingError,
        sqlite.DatabaseRuntimeError,
        sqlite.DoNothing,
        sqlite.DoUpdate,
        sqlite.ExecutionError,
        sqlite.Fetched,
        sqlite.FrozenModelError,
        sqlite.Index,
        sqlite.Integer,
        sqlite.MigrationError,
        sqlite.MigrationDeclarationError,
        sqlite.MigrationHistoryError,
        sqlite.MigrationLockError,
        sqlite.MigrationLockTimeoutError,
        sqlite.MigrationResult,
        sqlite.PendingGeneration,
        sqlite.Model,
        sqlite.ModelDeclarationError,
        sqlite.ModelError,
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
        sqlite.SnekqlError,
        sqlite.Text,
        sqlite.Transaction,
        sqlite.TransactionClosedError,
        sqlite.TransactionNotStartedError,
        sqlite.TransactionReuseError,
        sqlite.TransactionStateError,
    )

    for documented_class in documented_classes:
        _assert_has_specific_docstring(documented_class)


@test()
def pending_generation_sentinel_has_stable_singleton_behavior() -> None:
    """PENDING_GENERATION is the only pending value apps compare with."""

    assert_is(sqlite.PendingGeneration(), sqlite.PENDING_GENERATION)
    assert_eq(repr(sqlite.PENDING_GENERATION), "PENDING_GENERATION")


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
        sqlite.MigrationDeclarationError("package-originated failure"),
        sqlite.MigrationHistoryError("package-originated failure"),
        sqlite.MigrationLockError("package-originated failure"),
        sqlite.MigrationLockTimeoutError("package-originated failure"),
        sqlite.ModelDeclarationError("package-originated failure"),
        sqlite.ModelValidationError("package-originated failure"),
        sqlite.PoolTimeoutError("package-originated failure"),
        sqlite.QueryCompilationError("package-originated failure"),
        sqlite.QueryConstructionError("package-originated failure"),
        sqlite.SchemaVerificationError("package-originated failure"),
        sqlite.TransactionClosedError("package-originated failure"),
        sqlite.TransactionNotStartedError("package-originated failure"),
        sqlite.TransactionReuseError("package-originated failure"),
        sqlite.TransactionStateError("package-originated failure"),
    )

    catches: tuple[Callable[[], None], ...] = tuple(
        lambda error=error: _catch_as_snekql_error(error) for error in errors
    )

    for catch in catches:
        catch()


@test()
def migration_result_is_an_immutable_public_value() -> None:
    """Migration outcomes carry ordered tuples and cannot be mutated."""

    result = sqlite.MigrationResult(
        applied=("002",),
        already_applied=("001",),
        legacy_adopted=False,
    )

    with assert_raises(FrozenInstanceError):
        cast("Any", result).applied = ()


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


@test()
def execution_error_folds_cause_into_str() -> None:
    """A chained cause is visible in ``str()`` without inspecting __cause__."""

    error = sqlite.ExecutionError(
        "write failed",
        sql="INSERT INTO memories DEFAULT VALUES",
        params=(),
    )
    # ``raise ExecutionError(...) from cause`` sets ``__cause__`` to exactly this.
    error.__cause__ = ValueError("no such table: memories")

    rendered = str(error)

    assert_in("write failed", rendered)
    assert_in("cause=ValueError: no such table: memories", rendered)


@test()
def execution_error_without_cause_omits_cause_text() -> None:
    """A bare ExecutionError renders no cause fragment."""

    error = sqlite.ExecutionError("write failed", sql="SELECT 1", params=())

    assert_not_in("cause=", str(error))
