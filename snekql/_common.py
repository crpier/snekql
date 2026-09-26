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

from snekql._compiled import CompiledQuery
from snekql._explain import ExplainResult
from snekql._migrations import MigrationResult, MigrationStatus
from snekql._schema_verification import (
    SchemaDriftIssue,
    SchemaVerificationFact,
    SchemaVerificationResult,
)
from snekql.constraints import CheckConstraint, ForeignKeyConstraint
from snekql.defaults import LiteralDefault
from snekql.errors import (
    DatabaseClosedError,
    DatabaseCloseTimeoutError,
    DatabaseClosingError,
    DatabaseFailure,
    DatabaseOperationTimeoutError,
    DatabaseRuntimeError,
    DatetimeError,
    ExecutionError,
    FailureCategory,
    FrozenModelError,
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
    RawResultShapeError,
    RawResultValidationError,
    ResultCardinalityError,
    SchemaError,
    SchemaVerificationError,
    SnekqlError,
    SnekqlWarning,
    TransactionClosedError,
    TransactionNotStartedError,
    TransactionReuseError,
    TransactionStateError,
    ZonedDatetimeError,
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
    FKCol,
    GenCol,
    Pending,
    Row,
)
from snekql.query import (
    Write,
    exists,
    not_exists,
    scalar,
    select,
)
from snekql.runtime import (
    ChunkStream,
    CommitOutcome,
    Database,
    IsolationLevel,
    Transaction,
    TransactionMode,
)
from snekql.storage import (
    PENDING_GENERATION,
    Canonical,
    CanonicalDecimal,
    Duration,
    LocalDatetime,
    OrderPreserving,
    PendingGeneration,
    SchemaPolicy,
    UtcDatetime,
    ZonedDatetime,
)
from snekql.telemetry import Observer, PoolStats, TelemetryEvent

__all__ = [
    "PENDING_GENERATION",
    "Aggregate",
    "Assignment",
    "Canonical",
    "CanonicalDecimal",
    "CheckConstraint",
    "ChunkStream",
    "Col",
    "ColumnRef",
    "CommitOutcome",
    "CompiledQuery",
    "Database",
    "DatabaseCloseTimeoutError",
    "DatabaseClosedError",
    "DatabaseClosingError",
    "DatabaseFailure",
    "DatabaseOperationTimeoutError",
    "DatabaseRuntimeError",
    "DatetimeError",
    "DoNothing",
    "DoUpdate",
    "Duration",
    "ExecutionError",
    "ExplainResult",
    "FKCol",
    "FailureCategory",
    "ForeignKeyConstraint",
    "FrozenModelError",
    "GenCol",
    "Index",
    "IsolationLevel",
    "JoinOn",
    "LexicalDecimalWarning",
    "LexicalDurationWarning",
    "LiteralDefault",
    "LocalDatetime",
    "MigrationDeclarationError",
    "MigrationError",
    "MigrationHistoryError",
    "MigrationLockError",
    "MigrationLockTimeoutError",
    "MigrationResult",
    "MigrationStatus",
    "ModelDeclarationError",
    "ModelError",
    "ModelValidationError",
    "MultipleResultsError",
    "NoResultError",
    "Observer",
    "OrderBy",
    "OrderPreserving",
    "Pending",
    "PendingGeneration",
    "PoolStats",
    "PoolTimeoutError",
    "Predicate",
    "QueryCompilationError",
    "QueryConstructionError",
    "QueryError",
    "RawResultShapeError",
    "RawResultValidationError",
    "ResultCardinalityError",
    "Row",
    "Scalar",
    "SchemaDriftIssue",
    "SchemaError",
    "SchemaPolicy",
    "SchemaVerificationError",
    "SchemaVerificationFact",
    "SchemaVerificationResult",
    "SnekqlError",
    "SnekqlWarning",
    "TelemetryEvent",
    "Transaction",
    "TransactionClosedError",
    "TransactionMode",
    "TransactionNotStartedError",
    "TransactionReuseError",
    "TransactionStateError",
    "UtcDatetime",
    "Write",
    "ZonedDatetime",
    "ZonedDatetimeError",
    "exists",
    "not_exists",
    "scalar",
    "select",
]
