"""Public plan inspection results and private EXPLAIN compilation."""

from dataclasses import dataclass

from snekql._query_compile import compile_query_sql
from snekql._query_dialect import query_dialect_for_backend
from snekql._query_state import DeleteState, InsertState, SelectState, UpdateState
from snekql._raw import RawPlan
from snekql.errors import DatabaseRuntimeError, QueryCompilationError
from snekql.model import BackendFamily


@dataclass(frozen=True, slots=True, repr=False)
class ExplainResult:
    """Backend-native plan columns and rows, without model materialization.

    `await transaction.explain(query)` returns this result. Each tuple in
    `rows` follows `columns` order. Column names and cell values depend on
    the backend and server version; no portable optimizer schema is implied.
    Native cells can contain sensitive values. Text formatting shows counts
    only; accessing `rows` or `columns` is deliberate inspection.

    >>> plan = ExplainResult(backend="sqlite", columns=("detail",), rows=())
    >>> plan.rows
    ()
    >>> repr(plan)
    "ExplainResult(backend='sqlite', columns=1, rows=0)"
    """

    backend: BackendFamily
    columns: tuple[str, ...]
    rows: tuple[tuple[object, ...], ...]

    def __repr__(self) -> str:
        return (
            f"ExplainResult(backend={self.backend!r}, "
            f"columns={len(self.columns)}, rows={len(self.rows)})"
        )


def compile_explain_plan(
    query: object,
    *,
    backend: BackendFamily,
    analyze: bool,
) -> RawPlan:
    """Use native cursor metadata while keeping optimizer output out of logs."""

    compiled = compile_query_sql(query)
    if compiled.backend != backend:
        msg = (
            f"backend mismatch: expected {backend} query, "
            f"received {compiled.backend} query"
        )
        raise DatabaseRuntimeError(msg)
    state = getattr(query, "state", None)
    if not isinstance(state, (SelectState, InsertState, UpdateState, DeleteState)):
        msg = "EXPLAIN requires a built query"
        raise QueryCompilationError(msg)
    dialect = query_dialect_for_backend(backend)
    if dialect.explain_sql is None:
        msg = "EXPLAIN is not supported by this dialect"
        raise QueryCompilationError(msg)
    return RawPlan(
        adapter=None,
        backend=backend,
        operation="fetch_all",
        params=compiled.params,
        row_mode="tuple",
        requires_write_transaction=isinstance(state, SelectState)
        and state.lock_wait is not None,
        sql=dialect.explain_sql(
            state, compiled.sql, "analyze" if analyze else "explain"
        ),
    )
