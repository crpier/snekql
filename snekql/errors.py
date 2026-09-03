"""Intentional package-originated exception hierarchy for snekql."""

from __future__ import annotations

from typing import TYPE_CHECKING

from snekql._telemetry import ParameterVisibility, format_bound_params

if TYPE_CHECKING:
    from snekql._schema_verification import SchemaVerificationResult


class SnekqlError(Exception):
    """Base class for all intentional package-originated exceptions.

    >>> isinstance(ModelDeclarationError("bad model"), SnekqlError)
    True
    """


class SnekqlWarning(Warning):
    """Base class for package-originated warnings.

    >>> issubclass(LexicalDatetimeWarning, SnekqlWarning)
    True
    """


class LexicalDatetimeWarning(SnekqlWarning):
    """Warns that a SQLite Text datetime column compares lexically."""


class LexicalDecimalWarning(SnekqlWarning):
    """Warns that a Text decimal column compares lexically."""


class LexicalDurationWarning(SnekqlWarning):
    """Warns that a Text duration column compares lexically."""


class ZonedDatetimeError(SnekqlError):
    """Raised when a timezone cannot be preserved by `ZonedDatetime`.

    >>> issubclass(ZonedDatetimeError, SnekqlError)
    True
    """


class ModelError(SnekqlError):
    """Base class for table model declaration and validation failures."""


class ModelDeclarationError(ModelError):
    """Raised when a table model class violates snekql declaration rules."""


class ModelValidationError(ModelError):
    """Raised when pending or fetched table model values fail validation."""


class FrozenModelError(ModelError):
    """Raised when code mutates a model instance or finalized column metadata."""


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


class DatabaseOperationTimeoutError(DatabaseRuntimeError):
    """Raised when a transaction driver operation exceeds its deadline."""

    operation: str
    timeout: float

    def __init__(self, operation: str, timeout: float) -> None:
        self.operation = operation
        self.timeout = timeout
        super().__init__(f"database {operation} timed out after {timeout} seconds")


class DatabaseClosingError(DatabaseRuntimeError):
    """Raised when new work starts while Database.close is in progress."""


class ResultCardinalityError(DatabaseRuntimeError):
    """Raised when database rows violate an execution plan's cardinality."""


class NoResultError(ResultCardinalityError):
    """Raised when ``fetch_one`` finds no row for a select that must match one.

    ``fetch_one`` carries an exactly-one contract; absence is an error rather
    than a ``None`` return, which keeps a returned ``None`` for a single-value
    select unambiguously meaning SQL ``NULL``. Use ``fetch_at_most_one`` (model,
    tuple, and join selects) when a missing row is expected.
    """


class MultipleResultsError(ResultCardinalityError):
    """Raised when ``fetch_one``/``fetch_at_most_one`` match more than one row.

    Both methods cap cardinality at one. Select ``first of N`` explicitly with
    ``.limit(1)`` when more than one row is acceptable.
    """


class ExecutionError(DatabaseRuntimeError):
    """Database execution failure with query context.

    >>> error = ExecutionError("failed", sql="SELECT ?", params=(1,))
    >>> error.sql
    'SELECT ?'

    A chained driver's type is included in ``str()``. Its message is redacted
    with bound values unless parameter visibility explicitly opts into values.
    """

    sql: str
    params: tuple[object, ...]
    parameter_visibility: ParameterVisibility

    def __init__(
        self,
        message: str,
        *,
        sql: str,
        params: tuple[object, ...],
        parameter_visibility: ParameterVisibility = "redacted",
    ) -> None:
        super().__init__(message)
        self.sql: str = sql
        self.params: tuple[object, ...] = params
        self.parameter_visibility: ParameterVisibility = parameter_visibility

    def __str__(self) -> str:
        message = super().__str__()
        rendered_params = format_bound_params(self.params, self.parameter_visibility)
        text = f"{message} sql={self.sql!r} params={rendered_params}"
        cause = self.__cause__
        if cause is not None:
            text += f" cause={type(cause).__name__}"
            if self.parameter_visibility == "values":
                text += f": {cause}"
        return text


class SchemaError(SnekqlError):
    """Base class for schema creation and verification failures."""


class SchemaVerificationError(SchemaError):
    """Raised after strict verification collects all live-schema drift."""

    def __init__(
        self,
        message: str,
        *,
        result: SchemaVerificationResult,
    ) -> None:
        super().__init__(message)
        self.result: SchemaVerificationResult = result


class MigrationError(SnekqlError):
    """Raised when a hand-authored migration body fails to apply.

    The message names the failing migration; previously-applied migrations stay
    recorded in the Migration History so a fixed retry resumes from the failure.
    """


class MigrationDeclarationError(SnekqlError):
    """Raised before I/O when a Migration declaration is invalid."""


class MigrationHistoryError(SnekqlError):
    """Raised when Migration History is missing, divergent, or malformed."""


class MigrationLockError(SnekqlError):
    """Raised when migration lock ownership cannot be acquired or released."""


class MigrationLockTimeoutError(MigrationLockError):
    """Raised when backend migration coordination cannot acquire its lock in time.

    Another writer held SQLite's writer lock or MariaDB's advisory lock through
    the acquisition budget. The losing instance applied nothing; retrying after
    the holder finishes checks Migration History before applying pending work.
    """
