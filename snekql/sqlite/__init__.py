"""SQLite backend namespace for snekql.

Import the whole SQLite surface from here: dialect-neutral builders,
predicates, runtime, and type helpers (shared via ``snekql._common``), plus
SQLite's write verbs, ``Model`` base, and column constructors. There is no flat
``snekql.*`` surface; pick a backend namespace and import everything from it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

from snekql._common import (
    PENDING_GENERATION,
    Aggregate,
    Assignment,
    Canonical,
    CanonicalDecimal,
    ChunkStream,
    ColumnRef,
    DatabaseClosedError,
    DatabaseCloseTimeoutError,
    DatabaseClosingError,
    DatabaseOperationTimeoutError,
    DatabaseRuntimeError,
    DoNothing,
    DoUpdate,
    Duration,
    ExecutionError,
    Fetched,
    FrozenModelError,
    Index,
    JoinOn,
    LexicalDatetimeWarning,
    LexicalDecimalWarning,
    LexicalDurationWarning,
    MigrationDeclarationError,
    MigrationError,
    MigrationHistoryError,
    MigrationLockError,
    MigrationLockTimeoutError,
    MigrationResult,
    ModelDeclarationError,
    ModelError,
    ModelValidationError,
    MultipleResultsError,
    NoResultError,
    OrderBy,
    OrderPreserving,
    Pending,
    PendingGeneration,
    PoolTimeoutError,
    Predicate,
    QueryCompilationError,
    QueryConstructionError,
    QueryError,
    ResultCardinalityError,
    Scalar,
    SchemaDriftIssue,
    SchemaError,
    SchemaPolicy,
    SchemaVerificationError,
    SchemaVerificationResult,
    SnekqlError,
    SnekqlWarning,
    TransactionClosedError,
    TransactionMode,
    TransactionNotStartedError,
    TransactionReuseError,
    TransactionStateError,
    UtcDatetime,
    ZonedDatetime,
    ZonedDatetimeError,
    exists,
    not_exists,
    scalar,
)
from snekql._common import (
    Select as _RuntimeSelect,
)
from snekql._common import (
    Write as _RuntimeWrite,
)
from snekql.query import _Select, _Write
from snekql.runtime import Database as _Database
from snekql.runtime import Transaction as _Transaction

# Importing the dialect module registers the SQLite query Dialect so a built
# SQLite query can render its own SQL for inspection (see _query_dialect).
from snekql.sqlite import _dialect_sql as _dialect_sql
from snekql.sqlite._schema_ddl import scaffold_sqlite_ddl as scaffold
from snekql.sqlite.config import Config
from snekql.sqlite.model import Col, FKCol, GenCol, Model
from snekql.sqlite.verbs import delete, insert, select, update
from snekql.storage import (
    Blob,
    CurrentTimestamp,
    ForeignKey,
    Integer,
    Real,
    Text,
)

if TYPE_CHECKING:
    Database = _Database[Literal["sqlite"]]
    type Select[RowT] = _Select[Literal["sqlite"], RowT]
    Transaction = _Transaction[Literal["sqlite"]]
    type Write[ResultT] = _Write[Literal["sqlite"], ResultT]
else:
    Database = _Database
    Select = _RuntimeSelect
    Transaction = _Transaction
    Write = _RuntimeWrite

__all__ = [
    "PENDING_GENERATION",
    "Aggregate",
    "Assignment",
    "Blob",
    "Canonical",
    "CanonicalDecimal",
    "ChunkStream",
    "Col",
    "ColumnRef",
    "Config",
    "CurrentTimestamp",
    "Database",
    "DatabaseCloseTimeoutError",
    "DatabaseClosedError",
    "DatabaseClosingError",
    "DatabaseOperationTimeoutError",
    "DatabaseRuntimeError",
    "DoNothing",
    "DoUpdate",
    "Duration",
    "ExecutionError",
    "FKCol",
    "Fetched",
    "ForeignKey",
    "FrozenModelError",
    "GenCol",
    "Index",
    "Integer",
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
    "Model",
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
    "Real",
    "ResultCardinalityError",
    "Scalar",
    "SchemaDriftIssue",
    "SchemaError",
    "SchemaPolicy",
    "SchemaVerificationError",
    "SchemaVerificationResult",
    "Select",
    "SnekqlError",
    "SnekqlWarning",
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
    "delete",
    "exists",
    "insert",
    "not_exists",
    "scaffold",
    "scalar",
    "select",
    "update",
]
