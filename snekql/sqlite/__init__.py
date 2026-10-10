"""SQLite backend namespace for snekql.

Import the whole SQLite surface from here: dialect-neutral builders,
predicates, runtime, and type helpers (shared via ``snekql._common``), plus
SQLite's write verbs, ``Model`` base, and column constructors. There is no flat
``snekql.*`` surface; pick a backend namespace and import everything from it.
"""

lazy from typing import TYPE_CHECKING, Literal, TypeVar

lazy from snekql._common import (
    PENDING_GENERATION,
    Assignment,
    Canonical,
    CanonicalDecimal,
    CheckConstraint,
    ChunkStream,
    CommitOutcome,
    CompiledQuery,
    DatabaseClosedError,
    DatabaseCloseTimeoutError,
    DatabaseClosingError,
    DatabaseFailure,
    DatabaseOperationTimeoutError,
    DatabaseRuntimeError,
    DatetimeError,
    DoNothing,
    DoUpdate,
    Duration,
    ExecutionError,
    ExplainResult,
    FailureCategory,
    ForeignKeyConstraint,
    FrozenModelError,
    Index,
    IsolationLevel,
    JoinOn,
    LexicalDecimalWarning,
    LexicalDurationWarning,
    LiteralDefault,
    LocalDatetime,
    MigrationDeclarationError,
    MigrationError,
    MigrationHistoryError,
    MigrationLockError,
    MigrationLockTimeoutError,
    MigrationResult,
    MigrationStatus,
    ModelDeclarationError,
    ModelError,
    ModelValidationError,
    MultipleResultsError,
    NoResultError,
    Observer,
    OrderBy,
    OrderPreserving,
    Pending,
    PoolStats,
    PoolTimeoutError,
    QueryCompilationError,
    QueryConstructionError,
    QueryError,
    RawResultShapeError,
    RawResultValidationError,
    ResultCardinalityError,
    Row,
    SchemaDriftIssue,
    SchemaError,
    SchemaPolicy,
    SchemaVerificationError,
    SchemaVerificationFact,
    SchemaVerificationResult,
    SnekqlError,
    SnekqlWarning,
    TelemetryEvent,
    TransactionClosedError,
    TransactionMode,
    TransactionNotStartedError,
    TransactionReuseError,
    TransactionStateError,
    UtcDatetime,
    ZonedDatetime,
    ZonedDatetimeError,
)
lazy from snekql._common import (
    Write as _RuntimeWrite,
)
lazy from snekql._query_dialect import register_query_dialect
lazy from snekql._runtime_selection import register_default_backend_factory
lazy from snekql.expressions import Aggregate as _AggregateType
lazy from snekql.expressions import ColumnRef as _ColumnRef
lazy from snekql.expressions import Predicate as _Predicate
lazy from snekql.expressions import Scalar as _ScalarType
lazy from snekql.model import ReadType, is_complete
lazy from snekql.query import _Write
lazy from snekql.runtime import Database as _Database
lazy from snekql.runtime import Transaction as _Transaction
lazy from snekql.sqlite._dialect_sql import SQLITE_QUERY_DIALECT
lazy from snekql.sqlite._raw import RawStatement, raw
lazy from snekql.sqlite._schema_ddl import scaffold_sqlite_ddl as scaffold
lazy from snekql.sqlite.config import Config, _build_default_config
lazy from snekql.sqlite.functions import case, literal
lazy from snekql.sqlite.model import Col, FKCol, GenCol, Model, complete
lazy from snekql.sqlite.recursive import Cte, NamedOperand, recursive_cte
lazy from snekql.sqlite.verbs import (
    ClosedOptional,
    ClosedRead,
    OptionalRead,
    PendingInput,
    ReadQuery,
    alias,
    delete,
    exists,
    insert,
    insert_many,
    not_exists,
    ready,
    scalar,
    select,
    update,
)
lazy from snekql.storage import (
    Blob,
    CurrentTimestamp,
    ForeignKey,
    Integer,
    Real,
    Text,
)

# Resolve the dialect explicitly: lazy imports do not run registration side effects.
register_query_dialect("sqlite", SQLITE_QUERY_DIALECT)
register_default_backend_factory(_build_default_config)

if TYPE_CHECKING:
    _OwnerT = TypeVar("_OwnerT")
    _ValueT = TypeVar("_ValueT")
    _CompareT = TypeVar("_CompareT", default=_ValueT)
    Scalar = _ScalarType[_OwnerT, _ValueT, _CompareT, Literal["sqlite"]]
    Predicate = _Predicate[_OwnerT, Literal["sqlite"]]
    Aggregate = _AggregateType[_OwnerT, _ValueT, _CompareT, Literal["sqlite"]]
    ColumnRef = _ColumnRef[_OwnerT, _ValueT, Literal["sqlite"]]
    Database = _Database[Literal["sqlite"]]
    Transaction = _Transaction[Literal["sqlite"]]
    type Write[ResultT] = _Write[Literal["sqlite"], ResultT]
else:
    Scalar = _ScalarType
    Predicate = _Predicate
    Aggregate = _AggregateType
    ColumnRef = _ColumnRef
    Database = _Database
    Transaction = _Transaction
    Write = _RuntimeWrite


__all__ = [
    "PENDING_GENERATION",
    "Aggregate",
    "Assignment",
    "Blob",
    "Canonical",
    "CanonicalDecimal",
    "CheckConstraint",
    "ChunkStream",
    "ClosedOptional",
    "ClosedRead",
    "Col",
    "ColumnRef",
    "CommitOutcome",
    "CompiledQuery",
    "Config",
    "Cte",
    "CurrentTimestamp",
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
    "ForeignKey",
    "ForeignKeyConstraint",
    "FrozenModelError",
    "GenCol",
    "Index",
    "Integer",
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
    "Model",
    "ModelDeclarationError",
    "ModelError",
    "ModelValidationError",
    "MultipleResultsError",
    "NamedOperand",
    "NoResultError",
    "Observer",
    "OptionalRead",
    "OrderBy",
    "OrderPreserving",
    "Pending",
    "PendingInput",
    "PoolStats",
    "PoolTimeoutError",
    "Predicate",
    "QueryCompilationError",
    "QueryConstructionError",
    "QueryError",
    "RawResultShapeError",
    "RawResultValidationError",
    "RawStatement",
    "ReadQuery",
    "ReadType",
    "Real",
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
    "Text",
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
    "alias",
    "case",
    "complete",
    "delete",
    "exists",
    "insert",
    "insert_many",
    "is_complete",
    "literal",
    "not_exists",
    "raw",
    "ready",
    "recursive_cte",
    "scaffold",
    "scalar",
    "select",
    "update",
]
