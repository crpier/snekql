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


class TransactionStateError(DatabaseRuntimeError):
    """Base class for Transaction lifecycle misuse.

    A ``Transaction`` is single-use: enter it exactly once with ``async with``,
    run queries while it is open, and let the block exit close it. Using it out
    of that order -- before entering, after closing, or entering it more than
    once -- raises a subclass of this error. Catch this base to treat every
    lifecycle misuse uniformly.
    """


class TransactionClosedError(TransactionStateError):
    """Raised when a Transaction is used after it has closed."""


class TransactionNotStartedError(TransactionStateError):
    """Raised when a Transaction runs a query before it has been entered."""


class TransactionReuseError(TransactionStateError):
    """Raised when a Transaction is entered more than once.

    A ``Transaction`` is not re-entrant and cannot be restarted: re-entering one
    that is still open, or one that has already been used and closed, raises this
    error. Create a fresh ``db.transaction()`` for each unit of work.
    """


class PoolTimeoutError(DatabaseRuntimeError):
    """Raised when acquiring a database connection exceeds the timeout."""


class DatabaseCloseTimeoutError(DatabaseRuntimeError):
    """Raised when Database.close cannot finish before its timeout."""


class DatabaseClosingError(DatabaseRuntimeError):
    """Raised when new work starts while Database.close is in progress."""


class NoResultError(DatabaseRuntimeError):
    """Raised when ``fetch_one`` finds no row for a select that must match one.

    ``fetch_one`` carries an exactly-one contract; absence is an error rather
    than a ``None`` return, which keeps a returned ``None`` for a single-value
    select unambiguously meaning SQL ``NULL``. Use ``fetch_at_most_one`` (model,
    tuple, and join selects) when a missing row is expected.
    """


class MultipleResultsError(DatabaseRuntimeError):
    """Raised when ``fetch_one``/``fetch_at_most_one`` match more than one row.

    Both methods cap cardinality at one. Select ``first of N`` explicitly with
    ``.limit(1)`` when more than one row is acceptable.
    """


class ExecutionError(DatabaseRuntimeError):
    """Database execution failure with query context.

    >>> error = ExecutionError("failed", sql="SELECT ?", params=(1,))
    >>> error.sql
    'SELECT ?'

    When raised with ``raise ExecutionError(...) from cause`` the underlying
    error is folded into ``str()`` so the cause is visible without inspecting
    ``__cause__`` or the traceback.
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
        text = f"{message} sql={self.sql!r} params={self.params!r}"
        cause = self.__cause__
        if cause is not None:
            text += f" cause={type(cause).__name__}: {cause}"
        return text


class SchemaError(SnekqlError):
    """Base class for schema creation and verification failures."""


class SchemaVerificationError(SchemaError):
    """Raised when an existing database table drifts from model DDL."""


class MigrationError(SnekqlError):
    """Raised when a hand-authored migration body fails to apply.

    The message names the failing migration; previously-applied migrations stay
    recorded in the Migration History so a fixed retry resumes from the failure.
    """


class MigrationLockTimeoutError(SnekqlError):
    """Raised when the migration advisory lock cannot be acquired in time.

    A concurrent instance held the lock for the full acquire timeout. The losing
    instance applied nothing; retrying after the holder finishes observes the
    completed Migration History and applies only what is still pending.
    """
