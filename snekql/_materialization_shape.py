"""Materialization-owned source payloads, presence witnesses, and joined spans.

Query Builder and Query Compilation consume the same source interpretation that
Execution Plans retain for decoding. No backend namespace or runtime is needed.
"""

lazy from collections.abc import Sequence
lazy from dataclasses import dataclass
lazy from typing import Any

lazy from snekql._aliases import _AliasRelation
lazy from snekql._cte import _CteOutput, _CtePresence, _CteRelation
lazy from snekql._dialect_expr import CompileCtx
lazy from snekql._model_materialization import decode_model_row
lazy from snekql._named_projection import NamedProjection
lazy from snekql._query_state import JoinSpec, Selectable
lazy from snekql._value_decode import _decode_selectable
lazy from snekql.errors import QueryCompilationError
lazy from snekql.model import Table, require_model_columns, require_model_table_name
lazy from snekql.storage import StorageBackend


@dataclass(frozen=True, slots=True)
class _TablePresence:
    """A derived table's marker distinguishes a matched all-NULL payload."""

    source: type[Table[Any]]
    name: str

    def __owner_model__(self) -> type[Table[Any]]:
        return self.source

    def __compile_sql__(self, ctx: CompileCtx) -> tuple[str, tuple[object, ...]]:
        owner = ctx.quote_identifier(require_model_table_name(self.source))
        return f"{owner}.{ctx.quote_identifier(self.name)}", ()


@dataclass(frozen=True, slots=True)
class SourceRowShape:
    """One source's visible payload and optional hidden presence witness.

    Presence is separate from the payload: a real all-NULL row remains a row,
    and adding its witness cannot change model field names or named bindings.
    """

    # SQL payload and presence precede the decoded row contract.
    payload: tuple[Selectable, ...]
    presence: _TablePresence | _CtePresence | None
    column_names: tuple[str, ...]
    projection: NamedProjection | None
    row_model: type[Table[Any]] | None

    @classmethod
    def for_source(
        cls, source: type[Table[Any]], *, presence: bool = False
    ) -> SourceRowShape:
        """Resolve source policy once, including aliases and query-only rows."""
        if issubclass(source, _CteRelation):
            projection = source.definition.state.named_projection
            if projection is None:
                msg = "CTE row requires a named result contract"
                raise QueryCompilationError(msg)
            return cls(
                payload=tuple(
                    _CteOutput[Any, Any, Any](position=position, relation=source)
                    for position in range(len(source.definition.layout.slots))
                ),
                presence=_CtePresence(source) if presence else None,
                column_names=(),
                row_model=None,
                projection=projection,
            )
        columns = require_model_columns(source)
        marker: _TablePresence | None = None
        if presence and all(column.nullable for column in columns.values()):
            names = {name.casefold() for name in columns}
            marker_name = "__snekql_present"
            while marker_name.casefold() in names:
                marker_name += "_"
            marker = _TablePresence(source, marker_name)
        return cls(
            payload=tuple(columns.values()),
            presence=marker,
            column_names=tuple(columns),
            row_model=source.source_model
            if issubclass(source, _AliasRelation)
            else source,
            projection=None,
        )

    @property
    def fields(self) -> tuple[Selectable, ...]:
        """SQL fields include the witness only after the visible payload."""
        return (
            (*self.payload, self.presence)
            if self.presence is not None
            else self.payload
        )

    @property
    def presence_name(self) -> str | None:
        """Only physical sources need an extra derived-table SELECT."""
        return self.presence.name if isinstance(self.presence, _TablePresence) else None

    @property
    def width(self) -> int:
        """The witness contributes one SQL field, never a decoded field."""
        return len(self.payload) + int(self.presence is not None)

    def materialize(
        self,
        row: Sequence[object],
        *,
        backend: StorageBackend,
        validate: bool,
        nullable: bool = False,
    ) -> object:
        """Decode exactly this source's span, never exposing its witness."""
        if nullable:
            absent = (
                row[-1] is None
                if self.presence is not None
                else all(value is None for value in row)
            )
            if absent:
                return None
        payload = row[: len(self.payload)]
        if self.projection is not None:
            return self.projection.materialize(
                tuple(
                    _decode_selectable(field, value, backend=backend, validate=validate)
                    for field, value in zip(self.payload, payload, strict=True)
                )
            )
        if self.row_model is None:
            msg = "source row lost its model contract"
            raise QueryCompilationError(msg)
        return decode_model_row(
            self.row_model,
            dict(zip(self.column_names, payload, strict=True)),
            backend=backend,
            validate=validate,
        )


@dataclass(frozen=True, slots=True)
class _RowSpan:
    """A source's fixed position and null-extension policy in one joined row."""

    nullable: bool
    offset: int
    shape: SourceRowShape


@dataclass(frozen=True, slots=True)
class JoinedRowShape:
    """The ordered fields and spans shared by SQL emission and row decoding."""

    fields: tuple[Selectable, ...]
    spans: tuple[_RowSpan, ...]

    @classmethod
    def for_sources(
        cls, model: type[Table[Any]], joins: tuple[JoinSpec, ...]
    ) -> JoinedRowShape:
        """Concentrate expansion, hidden fields, and offsets in one interpretation."""
        fields: list[Selectable] = []
        spans: list[_RowSpan] = []
        for source, nullable in (
            (model, False),
            *((join.model, join.join_type == "LEFT") for join in joins),
        ):
            shape = SourceRowShape.for_source(source, presence=True)
            spans.append(_RowSpan(shape=shape, offset=len(fields), nullable=nullable))
            fields.extend(shape.fields)
        return cls(fields=tuple(fields), spans=tuple(spans))

    def materialize(
        self, row: Sequence[object], *, backend: StorageBackend, validate: bool
    ) -> tuple[object, ...]:
        """Split joined rows using the same spans that expanded the SQL fields."""
        return tuple(
            span.shape.materialize(
                row[span.offset : span.offset + span.shape.width],
                backend=backend,
                validate=validate,
                nullable=span.nullable,
            )
            for span in self.spans
        )
