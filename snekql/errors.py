"""Intentional package-originated exception hierarchy for snekql."""

from __future__ import annotations


class SnekqlError(Exception):
    """Base class for all intentional package-originated exceptions.

    >>> isinstance(ModelDeclarationError("bad model"), SnekqlError)
    True
    """

    pass


class ModelError(SnekqlError):
    """Base class for table model declaration and validation failures."""

    pass


class ModelDeclarationError(ModelError):
    """Raised when a table model class violates snekql declaration rules."""

    pass


class ModelValidationError(ModelError):
    """Raised when pending or fetched table model values fail validation."""

    pass


class FrozenModelError(ModelError):
    """Raised when code attempts to mutate an immutable table model instance."""

    pass


class QueryError(SnekqlError):
    """Base class for query builder construction and compilation failures."""

    pass


class QueryConstructionError(QueryError):
    """Raised when query builder methods are used in an invalid sequence."""

    pass


class QueryCompilationError(QueryError):
    """Raised when a built query cannot be compiled into valid SQLite SQL."""

    pass


class DatabaseRuntimeError(SnekqlError):
    """Base class for Database and Transaction execution failures."""

    pass


class DatabaseClosedError(DatabaseRuntimeError):
    """Raised when a closed Database is used for new work."""

    pass


class TransactionClosedError(DatabaseRuntimeError):
    """Raised when a Transaction is used after it has closed."""

    pass


class PoolTimeoutError(DatabaseRuntimeError):
    """Raised when acquiring a database connection exceeds the timeout."""

    pass


class DatabaseCloseTimeoutError(DatabaseRuntimeError):
    """Raised when Database.close cannot finish before its timeout."""

    pass


class DatabaseClosingError(DatabaseRuntimeError):
    """Raised when new work starts while Database.close is in progress."""

    pass


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

    pass


class SchemaVerificationError(SchemaError):
    """Raised when an existing database table drifts from model DDL."""

    pass
