"""Dialect-neutral public symbols shared by both backend namespaces.

These are the parts of the API that behave identically regardless of backend:
the query verbs and builders, predicates, the column base types and model type
helpers, runtime handles, errors, and logging. Each backend namespace re-exports
everything here alongside its own dialect-specific column constructors and
``Model`` base, so an application imports its whole surface from a single
namespace. There is no flat top-level symbol surface by design (see ADR 0004).

This aggregator imports only dialect-neutral core modules; it must not import a
Backend Namespace, so it stays compatible with the dialect-blindness invariant.
"""

from __future__ import annotations

from snekql.errors import (
    DatabaseClosedError,
    DatabaseCloseTimeoutError,
    DatabaseClosingError,
    DatabaseRuntimeError,
    ExecutionError,
    FrozenModelError,
    MigrationError,
    MigrationLockTimeoutError,
    ModelDeclarationError,
    ModelError,
    ModelValidationError,
    MultipleResultsError,
    NoResultError,
    PoolTimeoutError,
    QueryCompilationError,
    QueryConstructionError,
    QueryError,
    SchemaError,
    SchemaVerificationError,
    SnekqlError,
    TransactionClosedError,
)
from snekql.expressions import (
    Aggregate,
    Assignment,
    JoinOn,
    OrderBy,
    Predicate,
    Scalar,
)
from snekql.indexes import Index
from snekql.model import (
    Col,
    Fetched,
    FKCol,
    GenCol,
    ModelMeta,
    Pending,
    Table,
)
from snekql.query import (
    DeleteQuery,
    InsertManyQuery,
    InsertManyReturningQuery,
    InsertManyReturningTupleQuery,
    InsertManyReturningValueQuery,
    InsertQuery,
    InsertReturningQuery,
    InsertReturningTupleQuery,
    InsertReturningValueQuery,
    JoinModelQuery,
    SelectModelQuery,
    SelectTupleQuery,
    SelectValueQuery,
    UpdateQuery,
    delete,
    exists,
    insert,
    not_exists,
    scalar,
    select,
    update,
)
from snekql.runtime import Database, Transaction
from snekql.storage import (
    MISSING,
    Attr,
    FKAttr,
    Missing,
    SchemaPolicy,
)

__all__ = [
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
    "MultipleResultsError",
    "NoResultError",
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
]
