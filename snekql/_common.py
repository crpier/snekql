"""Dialect-neutral public symbols shared by both backend namespaces.

These are the parts of the API that behave identically regardless of backend:
the neutral query builders, predicates, the column base types and model type
helpers, runtime handles, errors, and logging. Each backend namespace re-exports
everything here alongside its own write verbs, dialect-specific column
constructors, and ``Model`` base, so an application imports its whole surface
from a single namespace. There is no flat top-level symbol surface by design
(see ADR 0004).

This aggregator imports only dialect-neutral core modules; it must not import a
Backend Namespace, so it stays compatible with the dialect-blindness invariant.
"""

from __future__ import annotations

from snekql._migrations import MigrationResult
from snekql.errors import (
    DatabaseClosedError,
    DatabaseCloseTimeoutError,
    DatabaseClosingError,
    DatabaseRuntimeError,
    ExecutionError,
    FrozenModelError,
    LexicalDatetimeWarning,
    LexicalDecimalWarning,
    LexicalDurationWarning,
    MigrationDeclarationError,
    MigrationError,
    MigrationHistoryError,
    MigrationLockError,
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
    SnekqlWarning,
    TransactionClosedError,
    TransactionNotStartedError,
    TransactionReuseError,
    TransactionStateError,
)
from snekql.expressions import (
    Aggregate,
    Assignment,
    ColumnRef,
    DoNothing,
    DoUpdate,
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
    Pending,
)
from snekql.query import (
    Select,
    Write,
    exists,
    not_exists,
    scalar,
    select,
)
from snekql.runtime import ChunkStream, Database, Transaction, TransactionMode
from snekql.storage import (
    PENDING_GENERATION,
    Canonical,
    CanonicalDecimal,
    Duration,
    OrderPreserving,
    PendingGeneration,
    SchemaPolicy,
    UtcDatetime,
)

__all__ = [
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
    "ModelDeclarationError",
    "ModelError",
    "ModelValidationError",
    "MultipleResultsError",
    "NoResultError",
    "OrderBy",
    "OrderPreserving",
    "Pending",
    "PendingGeneration",
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
]
