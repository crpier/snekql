"""Materialization: decode database rows into a select query's result shape.

The read-side counterpart to Query Compilation. Every function here operates on
query state plus a backend tag; like compilation, it depends only on the shared
query state, never on the Query Builder classes.
"""

lazy from collections.abc import Callable, Sequence
lazy from dataclasses import dataclass

lazy from snekql._materialization_shape import (
    JoinedRowShape,
    SourceDecoders,
    SourceRowShape,
)
lazy from snekql._model_materialization import decode_model_values
lazy from snekql._named_projection import NamedProjection
lazy from snekql._query_state import (
    InsertState,
    Selectable,
    SelectState,
    WriteState,
)
lazy from snekql._value_decode import resolve_projection_decoder
lazy from snekql.model import require_model_columns
lazy from snekql.storage import StorageBackend


def _materialize_insert_returning_fields(
    fields: tuple[Selectable, ...],
    rows: Sequence[Sequence[object]],
    *,
    backend: StorageBackend,
    validate: bool,
    projection: NamedProjection | None = None,
) -> list[object]:
    """Decode RETURNING rows for an explicit column projection.

    Mirrors a projection select: one projected column yields a decoded scalar per
    row, several yield a tuple per row, both through the shared selectable decode.
    """

    decoders = tuple(
        resolve_projection_decoder(
            field, nullable_models=frozenset(), backend=backend, validate=validate
        )
        for field in fields
    )
    materialized: list[object] = []
    if len(fields) == 1:
        decode = decoders[0]
        for row in rows:
            assert len(row) == 1, (  # noqa: S101
                "returning row shape did not match the projection"
            )
            value = decode(row[0])
            materialized.append(
                projection.materialize((value,)) if projection is not None else value
            )
        return materialized
    for row in rows:
        assert len(row) == len(fields), (  # noqa: S101
            "returning row shape did not match the projection"
        )
        decoded = tuple(
            decode(value) for decode, value in zip(decoders, row, strict=True)
        )
        materialized.append(
            projection.materialize(decoded) if projection is not None else decoded
        )
    return materialized


@dataclass(frozen=True, slots=True)
class SelectMaterialization:
    """Capture a select's source shape and validation policy once per plan.

    Row spans, projection decoders and nullable owners are execution-local
    facts, not work to repeat for every buffered or streamed row.
    """

    # Consumption facts followed by source shape facts.
    backend: StorageBackend
    state: SelectState
    validate: bool
    joined: JoinedRowShape | None
    decoders: tuple[Callable[[object], object], ...]
    source: SourceRowShape | None
    joined_decoders: tuple[SourceDecoders, ...]

    @classmethod
    def for_state(
        cls, state: SelectState, *, backend: StorageBackend, validate: bool
    ) -> SelectMaterialization:
        """Resolve whole-source shapes separately from fixed projections."""
        joined = (
            JoinedRowShape.for_sources(state.model, state.joins)
            if state.returns_model and state.joins
            else None
        )
        source = (
            SourceRowShape.for_source(state.model)
            if state.returns_model and not state.joins
            else None
        )
        nullable_models = frozenset(
            join.model for join in state.joins if join.join_type == "LEFT"
        )
        decoders = (
            tuple(
                resolve_projection_decoder(
                    column,
                    nullable_models=nullable_models,
                    backend=backend,
                    validate=validate,
                )
                for column in state.fields
            )
            if not state.returns_model
            else ()
        )
        return cls(
            state=state,
            backend=backend,
            validate=validate,
            joined=joined,
            joined_decoders=joined.resolve_decoders(backend=backend, validate=validate)
            if joined is not None
            else (),
            source=source,
            decoders=decoders,
        )

    def materialize(self, row: Sequence[object]) -> object:
        """Decode the result without reconstructing source widths or presence."""
        assert len(row) == len(self.state.fields), (  # noqa: S101
            "database row shape did not match select query"
        )
        if self.joined is not None:
            return self.joined.materialize(
                row,
                backend=self.backend,
                validate=self.validate,
                decoders=self.joined_decoders,
            )
        if self.source is not None:
            return self.source.materialize(
                row, backend=self.backend, validate=self.validate
            )
        if len(self.decoders) == 1:
            value = self.decoders[0](row[0])
            return (
                self.state.named_projection.materialize((value,))
                if self.state.named_projection is not None
                else value
            )
        decoded_values = tuple(
            decode(value) for decode, value in zip(self.decoders, row, strict=True)
        )
        if self.state.named_projection is not None:
            return self.state.named_projection.materialize(decoded_values)
        return decoded_values


def materialize_select_row_for_backend(
    state: SelectState,
    row: Sequence[object],
    *,
    backend: StorageBackend,
    validate: bool = True,
) -> object:
    """Decode a standalone row; execution plans retain the resolved decoder."""
    return SelectMaterialization.for_state(
        state, backend=backend, validate=validate
    ).materialize(row)


def materialize_write_returning_rows_for_backend(
    state: WriteState,
    rows: Sequence[Sequence[object]],
    *,
    backend: StorageBackend,
    validate: bool = True,
) -> list[object]:
    """Materialize ``RETURNING`` rows from a write into the query result shape.

    A whole-row ``returning()`` projects every column in model declaration order,
    so each database row decodes through the full model exactly like a model
    select. An explicit projection mirrors a projection select.
    """

    model_class = state.model() if isinstance(state, InsertState) else state.model
    returning_fields = state.returning_fields
    if returning_fields:
        return _materialize_insert_returning_fields(
            returning_fields,
            rows,
            backend=backend,
            validate=validate,
            projection=state.named_projection,
        )
    if model_class is None:
        return []
    columns = require_model_columns(model_class)
    materialized: list[object] = []
    for row in rows:
        assert len(row) == len(columns), (  # noqa: S101
            "returning row shape did not match the written model"
        )
        materialized.append(
            decode_model_values(
                model_class, columns, row, backend=backend, validate=validate
            ),
        )
    return materialized
