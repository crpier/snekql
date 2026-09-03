"""Dialect-bound query codec used by Backend Runtime Adapters.

Bundles the shared compile, plan, and materialize seams behind one object
resolved from the query-dialect registry. The core stays dialect-blind (ADR
0004): this module only consults the registry that each Backend Namespace
populates on import. Legacy select paths still use the direct methods while they
migrate incrementally to plans.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Literal, overload

from snekql._query_compile import (
    compile_select_sql_for_dialect,
    compile_write_sql_for_dialect,
)
from snekql._query_dialect import QueryDialect, query_dialect_for_backend
from snekql._query_materialize import (
    materialize_select_row_for_backend,
    materialize_write_returning_rows_for_backend,
)
from snekql._query_plan import (
    SelectCardinality,
    SelectPlan,
    WritePlan,
    compile_select_plan_for_dialect,
    compile_write_plan_for_dialect,
)
from snekql._query_state import DeleteState, InsertState, UpdateState
from snekql.errors import QueryCompilationError
from snekql.query import AnySelectQuery, _QueryShape, _WriteShape
from snekql.storage import StorageBackend


@dataclass(frozen=True)
class DialectQueryCodec:
    """Compile and materialize queries for one backend family's Dialect."""

    backend: StorageBackend
    dialect: QueryDialect

    @classmethod
    def for_backend(cls, backend: StorageBackend) -> DialectQueryCodec:
        """Resolve a codec from the registry for a backend family.

        Raises ``QueryCompilationError`` when no Dialect is registered for the
        family, which means its Backend Namespace was never imported.
        """

        return cls(backend=backend, dialect=query_dialect_for_backend(backend))

    def compile_select_sql(
        self,
        query: AnySelectQuery,
    ) -> tuple[str, tuple[object, ...]]:
        """Compile a select query into parameterized backend SQL."""

        return compile_select_sql_for_dialect(query.state, self.dialect)

    def compile_write_sql(self, query: object) -> tuple[str, tuple[object, ...]]:
        """Compile a write query into parameterized backend SQL."""

        return compile_write_sql_for_dialect(query, self.dialect)

    @overload
    def compile_select_plan[ResultT](
        self,
        query: _QueryShape[Any, Any, Any, ResultT],
        *,
        cardinality: SelectCardinality,
        validate: Literal[True] = True,
    ) -> SelectPlan[ResultT]: ...

    @overload
    def compile_select_plan[ResultT](
        self,
        query: _QueryShape[Any, Any, Any, ResultT],
        *,
        cardinality: SelectCardinality,
        validate: Literal[False],
    ) -> SelectPlan[object]: ...

    @overload
    def compile_select_plan[ResultT](
        self,
        query: _QueryShape[Any, Any, Any, ResultT],
        *,
        cardinality: SelectCardinality,
        validate: bool,
    ) -> SelectPlan[object]: ...

    def compile_select_plan(
        self,
        query: object,
        *,
        cardinality: SelectCardinality,
        validate: bool = True,
    ) -> SelectPlan[object]:
        """Compile a select and capture its execution policy in one plan."""

        return compile_select_plan_for_dialect(
            query,
            self.dialect,
            cardinality=cardinality,
            validate=validate,
        )

    @overload
    def compile_write_plan[ResultT](
        self,
        query: _WriteShape[Any, ResultT],
        *,
        validate: Literal[True] = True,
    ) -> WritePlan[ResultT]: ...

    @overload
    def compile_write_plan[ResultT](
        self,
        query: _WriteShape[Any, ResultT],
        *,
        validate: Literal[False],
    ) -> WritePlan[object]: ...

    @overload
    def compile_write_plan[ResultT](
        self,
        query: _WriteShape[Any, ResultT],
        *,
        validate: bool,
    ) -> WritePlan[object]: ...

    def compile_write_plan(
        self,
        query: object,
        *,
        validate: bool = True,
    ) -> WritePlan[object]:
        """Compile a write and capture its execution policy in one plan."""

        return compile_write_plan_for_dialect(
            query,
            self.dialect,
            default_backend=self.backend,
            validate=validate,
        )

    def materialize_select_row(
        self,
        query: AnySelectQuery,
        row: Sequence[object],
        *,
        validate: bool = True,
    ) -> object:
        """Decode one result row according to a select query."""

        return materialize_select_row_for_backend(
            query.state,
            row,
            backend=self.backend,
            validate=validate,
        )

    def materialize_write_rows(
        self,
        query: object,
        rows: Sequence[Sequence[object]],
        *,
        validate: bool = True,
    ) -> list[object]:
        """Decode ``RETURNING`` rows from a write query."""

        state = getattr(query, "state", None)
        if not isinstance(state, InsertState | UpdateState | DeleteState):
            msg = "materialize requires a returning write query"
            raise QueryCompilationError(msg)
        return materialize_write_returning_rows_for_backend(
            state,
            rows,
            backend=self.backend,
            validate=validate,
        )
