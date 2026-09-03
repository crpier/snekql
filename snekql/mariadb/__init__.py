"""MariaDB backend namespace for snekql.

Import the whole MariaDB surface from here: dialect-neutral builders,
predicates, runtime, and type helpers (shared via ``snekql._common``), plus
MariaDB's write verbs, ``Model`` base, and column constructors (including the
JSON column and its path operators). There is no flat ``snekql.*`` surface; pick
a backend namespace and import everything from it.
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
    SchemaError,
    SchemaPolicy,
    SchemaVerificationError,
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

# Importing the dialect module registers the MariaDB query Dialect so a built
# MariaDB query can render its own SQL for inspection (see _query_dialect).
from snekql.mariadb import _dialect_sql as _dialect_sql
from snekql.mariadb.config import Config
from snekql.mariadb.model import Col, FKCol, GenCol, JsonCol, Model
from snekql.mariadb.schema import scaffold_mariadb_ddl as scaffold
from snekql.mariadb.storage import (
    Blob,
    Boolean,
    CurrentTimestamp,
    DateTime,
    Decimal,
    ForeignKey,
    Integer,
    Json,
    Real,
    Text,
    Uuid,
)
from snekql.mariadb.verbs import delete, insert, select, update
from snekql.query import _Select, _Write
from snekql.runtime import Database as _Database
from snekql.runtime import Transaction as _Transaction

if TYPE_CHECKING:
    Database = _Database[Literal["mariadb"]]
    type Select[RowT] = _Select[Literal["mariadb"], RowT]
    Transaction = _Transaction[Literal["mariadb"]]
    type Write[ResultT] = _Write[Literal["mariadb"], ResultT]
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
    "Boolean",
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
    "DatabaseRuntimeError",
    "DateTime",
    "Decimal",
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
    "Json",
    "JsonCol",
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
    "SchemaError",
    "SchemaPolicy",
    "SchemaVerificationError",
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
    "Uuid",
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
