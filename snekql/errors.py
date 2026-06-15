"""Intentional package-originated exception hierarchy for snekql."""

from __future__ import annotations


class SnekqlError(Exception):
    """Base class for all intentional package-originated exceptions.

    >>> isinstance(ModelDeclarationError("bad model"), SnekqlError)
    True
    """


class ModelError(SnekqlError):
    """Base class for table model declaration and validation failures."""


class ModelDeclarationError(ModelError):
    """Raised when a table model class violates snekql declaration rules."""


class ModelValidationError(ModelError):
    """Raised when pending or fetched table model values fail validation."""


class FrozenModelError(ModelError):
    """Raised when code attempts to mutate an immutable table model instance."""


class QueryError(SnekqlError):
    """Base class for query builder construction and compilation failures."""


class QueryConstructionError(QueryError):
    """Raised when query builder methods are used in an invalid sequence."""


class QueryCompilationError(QueryError):
    """Raised when a built query cannot be compiled into valid SQLite SQL."""


class DatabaseRuntimeError(SnekqlError):
    """Base class for Database and Transaction execution failures."""


class DatabaseClosedError(DatabaseRuntimeError):
    """Raised when a closed Database is used for new work."""


class TransactionClosedError(DatabaseRuntimeError):
    """Raised when a Transaction is used after it has closed."""


class PoolTimeoutError(DatabaseRuntimeError):
    """Raised when acquiring a database connection exceeds the timeout."""


class DatabaseCloseTimeoutError(DatabaseRuntimeError):
    """Raised when Database.close cannot finish before its timeout."""


class DatabaseClosingError(DatabaseRuntimeError):
    """Raised when new work starts while Database.close is in progress."""


class ExecutionError(DatabaseRuntimeError):
    """Database execution failure with query context.

    >>> error = ExecutionError("failed", sql="SELECT ?", params=(1,))
    >>> error.sql
    'SELECT ?'
    """

    sql: str
    params: tuple[object, ...]

    def __init__(
        self,
        message: str,
        *,
        sql: str,
        params: tuple[object, ...],
    ) -> None:
        super().__init__(message)
        self.sql: str = sql
        self.params: tuple[object, ...] = params

    def __str__(self) -> str:
        message = super().__str__()
        return f"{message} sql={self.sql!r} params={self.params!r}"


class SchemaError(SnekqlError):
    """Base class for schema creation and verification failures."""


class SchemaVerificationError(SchemaError):
    """Raised when an existing database table drifts from model DDL."""


class MigrationError(SnekqlError):
    """Raised when a hand-authored migration body fails to apply.

    The message names the failing migration; previously-applied migrations stay
    recorded in the Migration History so a fixed retry resumes from the failure.
    """
