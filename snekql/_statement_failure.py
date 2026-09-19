"""Adapter evidence that a constraint failure completed without interrupted IO."""

from snekql.errors import DatabaseRuntimeError


class StatementConstraintError(DatabaseRuntimeError):
    """A completed constraint error that still requires savepoint rollback.

    Adapters emit this only for recognized server errors after any cursor cleanup
    succeeds. It does not prove that the savepoint still exists. Query Runtime
    must block further work until rollback and release both succeed.
    """

    def __init__(self, original: Exception) -> None:
        super().__init__("statement failed a recognized constraint")
        self.original: Exception = original
