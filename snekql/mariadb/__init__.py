"""MariaDB backend namespace for snekql.

Import the whole MariaDB surface from here: dialect-neutral builders,
predicates, runtime, and type helpers (shared via ``snekql._common``), plus
MariaDB's write verbs, ``Model`` base, and column constructors (including the
JSON column and its path operators). There is no flat ``snekql.*`` surface; pick
a backend namespace and import everything from it.
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
lazy from snekql.expressions import Aggregate as _AggregateType
lazy from snekql.expressions import ColumnRef as _ColumnRef
lazy from snekql.expressions import Predicate as _Predicate
lazy from snekql.expressions import Scalar as _ScalarType
lazy from snekql.mariadb._dialect_sql import MARIADB_QUERY_DIALECT
lazy from snekql.mariadb._raw import RawStatement, raw
lazy from snekql.mariadb.config import Config, TLSConfig
lazy from snekql.mariadb.functions import case, literal
lazy from snekql.mariadb.model import Col, FKCol, GenCol, JsonCol, Model, complete
lazy from snekql.mariadb.recursive import Cte, NamedOperand, recursive_cte
lazy from snekql.mariadb.schema import scaffold_mariadb_ddl as scaffold
lazy from snekql.mariadb.storage import (
    Blob,
    Boolean,
    CurrentTimestamp,
    Date,
    DateTime,
    Decimal,
    ForeignKey,
    Integer,
    Json,
    LongText,
    Real,
    Text,
    Uuid,
)
lazy from snekql.mariadb.verbs import (
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
lazy from snekql.model import ReadType, is_complete
lazy from snekql.query import _Write
lazy from snekql.runtime import Database as _Database
lazy from snekql.runtime import Transaction as _Transaction

# Resolve the dialect explicitly: lazy imports do not run registration side effects.
register_query_dialect("mariadb", MARIADB_QUERY_DIALECT)

if TYPE_CHECKING:
    _OwnerT = TypeVar("_OwnerT")
    _ValueT = TypeVar("_ValueT")
    _CompareT = TypeVar("_CompareT", default=_ValueT)
    Scalar = _ScalarType[_OwnerT, _ValueT, _CompareT, Literal["mariadb"]]
    Predicate = _Predicate[_OwnerT, Literal["mariadb"]]
    Aggregate = _AggregateType[_OwnerT, _ValueT, _CompareT, Literal["mariadb"]]
    ColumnRef = _ColumnRef[_OwnerT, _ValueT, Literal["mariadb"]]
    Database = _Database[Literal["mariadb"]]
    Transaction = _Transaction[Literal["mariadb"]]
    type Write[ResultT] = _Write[Literal["mariadb"], ResultT]
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
    "Boolean",
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
    "Date",
    "DateTime",
    "DatetimeError",
    "Decimal",
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
    "Json",
    "JsonCol",
    "LexicalDecimalWarning",
    "LexicalDurationWarning",
    "LiteralDefault",
    "LocalDatetime",
    "LongText",
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
    "TLSConfig",
    "TelemetryEvent",
    "Text",
    "Transaction",
    "TransactionClosedError",
    "TransactionMode",
    "TransactionNotStartedError",
    "TransactionReuseError",
    "TransactionStateError",
    "UtcDatetime",
    "Uuid",
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
