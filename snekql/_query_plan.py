"""Private typed execution plans between Query Compilation and Query Runtime.

A plan lowers one built query into the complete instruction the runtime needs:
backend identity, SQL, parameters, result cardinality, and materialization policy.
The runtime executes that instruction without naming Query Builder classes.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Literal, cast

from snekql._query_compile import (
    compile_select_sql_for_dialect,
    compile_write_sql_for_dialect,
)
from snekql._query_dialect import QueryDialect
from snekql._query_materialize import (
    materialize_select_row_for_backend,
    materialize_write_returning_rows_for_backend,
)
from snekql._query_state import (
    DeleteState,
    InsertState,
    SelectState,
    UpdateState,
    WriteState,
)
from snekql._telemetry import QueryDiagnostics
from snekql.errors import (
    MultipleResultsError,
    NoResultError,
    QueryCompilationError,
    QueryConstructionError,
    ResultCardinalityError,
)
from snekql.model import BackendFamily, require_model_backend
from snekql.query import SelectValueQuery

type SelectCardinality = Literal["one", "one_or_none", "many"]
type WriteCardinality = Literal["none", "rowcount", "one", "many"]


@dataclass(frozen=True)
class SelectPlan[ResultT]:
    """One compiled select plus its row decoding and consumption policy."""

    sql: str
    params: tuple[object, ...]
    backend: BackendFamily
    cardinality: SelectCardinality
    _state: SelectState = field(repr=False)
    _validate: bool = field(repr=False)

    @property
    def diagnostics(self) -> QueryDiagnostics:
        """Builder selects retain their existing SQL and parameter diagnostics."""

        return QueryDiagnostics("select failed", self.params, self.sql)

    @property
    def fetch_limit(self) -> int | None:
        """Rows needed to distinguish zero, one, and excess results."""

        return None if self.cardinality == "many" else 2

    def materialize(self, rows: Sequence[Sequence[object]]) -> ResultT | None:
        """Materialize a capped result; many-row reads use `materialize_row`."""

        if not rows:
            if self.cardinality == "one_or_none":
                return None
            msg = "fetch_one found no row"
            raise NoResultError(msg)
        if len(rows) > 1:
            msg = f"fetch_{self.cardinality} found more than one row"
            raise MultipleResultsError(msg)
        return self.materialize_row(rows[0])

    def materialize_row(self, row: Sequence[object]) -> ResultT:
        """Decode a row using the validation policy captured at compilation."""

        result = materialize_select_row_for_backend(
            self._state,
            row,
            backend=self.backend,
            validate=self._validate,
        )
        return cast("ResultT", result)


@dataclass(frozen=True)
class WritePlan[ResultT]:
    """One compiled write plus its result cardinality and materialization policy."""

    sql: str | None
    params: tuple[object, ...]
    backend: BackendFamily
    cardinality: WriteCardinality
    _state: WriteState = field(repr=False)
    _validate: bool = field(repr=False)

    @property
    def diagnostics(self) -> QueryDiagnostics:
        """Builder writes retain their existing SQL and parameter diagnostics."""

        return QueryDiagnostics("write failed", self.params, self.sql or "")

    @property
    def fetch_limit(self) -> int | None:
        """Collect RETURNING rows; skip fetching for commands without rows."""

        return None if self.returns_rows else 0

    @property
    def returns_rows(self) -> bool:
        """Whether execution must collect RETURNING rows."""

        return self.cardinality in ("one", "many")

    def materialize(
        self,
        *,
        rowcount: int,
        rows: Sequence[Sequence[object]],
    ) -> ResultT:
        """Turn driver output into the result promised by this write plan."""

        if self.cardinality == "none":
            return cast("ResultT", None)
        if self.cardinality == "rowcount":
            return cast("ResultT", rowcount)
        materialized = materialize_write_returning_rows_for_backend(
            self._state,
            rows,
            backend=self.backend,
            validate=self._validate,
        )
        if self.cardinality == "many":
            return cast("ResultT", materialized)
        if len(materialized) != 1:
            msg = (
                "single-row RETURNING expected exactly one row; "
                f"received {len(materialized)}"
            )
            raise ResultCardinalityError(msg)
        return cast("ResultT", materialized[0])


def validate_select_consumption(
    query: object, *, cardinality: SelectCardinality
) -> None:
    """Reject an optional scalar read whose SQL NULL could mean an absent row."""

    if cardinality == "one_or_none" and isinstance(query, SelectValueQuery):
        msg = (
            "fetch_one_or_none cannot disambiguate a missing row from a SQL "
            "NULL value for a single-value select; use fetch_one, or "
            "fetch_all / a tuple select including a non-nullable column"
        )
        raise QueryConstructionError(msg)


def select_query_backend(query: object) -> BackendFamily:
    """Check select shape and family without compiling SQL or opening a cursor."""

    state = getattr(query, "state", None)
    if not isinstance(state, SelectState):
        msg = "fetch requires a select query"
        raise QueryCompilationError(msg)
    return require_model_backend(state.model)


def compile_select_plan_for_dialect(
    query: object,
    dialect: QueryDialect,
    *,
    cardinality: SelectCardinality,
    validate: bool = True,
) -> SelectPlan[object]:
    """Lower one select shape into a typed execution plan."""

    validate_select_consumption(query, cardinality=cardinality)
    state = getattr(query, "state", None)
    if not isinstance(state, SelectState):
        msg = "fetch requires a select query"
        raise QueryCompilationError(msg)
    sql, params = compile_select_sql_for_dialect(state, dialect)
    return SelectPlan(
        sql=sql,
        params=params,
        backend=require_model_backend(state.model),
        cardinality=cardinality,
        _state=state,
        _validate=validate,
    )


def compile_write_plan_for_dialect(
    query: object,
    dialect: QueryDialect,
    *,
    default_backend: BackendFamily,
    validate: bool = True,
) -> WritePlan[object]:
    """Lower one write shape into a typed execution plan.

    Empty bulk inserts remain backend-neutral no-ops, as before. Their plan uses
    the compiling adapter's backend because no row exists from which to recover
    model identity, and no SQL reaches that backend.
    """

    state = getattr(query, "state", None)
    if not isinstance(state, InsertState | UpdateState | DeleteState):
        msg = "execute requires a write query"
        raise QueryCompilationError(msg)
    if isinstance(state, InsertState) and not state.rows:
        cardinality: WriteCardinality = "many" if state.returning else "none"
        return WritePlan(
            sql=None,
            params=(),
            backend=default_backend,
            cardinality=cardinality,
            _state=state,
            _validate=validate,
        )
    if isinstance(state, InsertState):
        model = state.model()
        if model is None:
            msg = "insert plan lost its model"
            raise QueryCompilationError(msg)
        backend = require_model_backend(model)
        cardinality = ("many" if state.multi else "one") if state.returning else "none"
    else:
        backend = require_model_backend(state.model)
        cardinality = "many" if state.returning else "rowcount"
    sql, params = compile_write_sql_for_dialect(query, dialect)
    return WritePlan(
        sql=sql,
        params=params,
        backend=backend,
        cardinality=cardinality,
        _state=state,
        _validate=validate,
    )
