"""Immutable structured output from Query Compilation."""

from dataclasses import dataclass

from snekql._telemetry import fingerprint_sql, format_bound_params
from snekql.model import BackendFamily


@dataclass(frozen=True, slots=True, repr=False)
class CompiledQuery:
    """Inspection-only SQL with ordered, dialect-encoded bound parameters.

    Compile a built query with `query.compile()`. The result does not carry
    execution or row-decoding policy and cannot be passed to a Transaction.
    Fields are frozen; `params` is a tuple of the actual encoded bindings.
    Text formatting redacts bindings, but does not sanitize SQL identifiers
    or literals supplied by custom dialect expressions.

    >>> compiled = CompiledQuery(backend="sqlite", params=(42,), sql="SELECT ?")
    >>> compiled.params
    (42,)
    >>> repr(compiled)
    "CompiledQuery(backend='sqlite', params=<redacted:1>, sql='SELECT ?')"
    """

    backend: BackendFamily
    params: tuple[object, ...]
    sql: str

    def __repr__(self) -> str:
        return (
            f"CompiledQuery(backend={self.backend!r}, "
            f"params={format_bound_params(self.params, 'redacted')}, sql={self.sql!r})"
        )

    @property
    def fingerprint(self) -> str:
        """Identify exact backend SQL independently of bound parameter values.

        No SQL or parameter values appear in the result. Different SQL shapes
        can still create unbounded distinct fingerprints; metric adapters need
        an explicit allowlist or must omit this label. This is not encryption
        for values embedded in custom SQL. Compilation changes can change IDs.
        """
        return fingerprint_sql(self.backend, self.sql)
