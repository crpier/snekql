"""Materialization-owned source payloads, presence witnesses, and joined spans.

Query Builder and Query Compilation consume the same source interpretation that
Execution Plans retain for decoding. No backend namespace or runtime is needed.
"""

lazy from collections.abc import Callable, Mapping, Sequence
lazy from dataclasses import dataclass
lazy from typing import Any

lazy from snekql._aliases import _AliasRelation
lazy from snekql._cte import _CteOutput, _CtePresence, _CteRelation
lazy from snekql._dialect_expr import CompileCtx
lazy from snekql._model_materialization import decode_model_row, decode_model_values
lazy from snekql._named_projection import NamedProjection
lazy from snekql._query_state import JoinSpec, Selectable
lazy from snekql._value_decode import _decode_selectable, resolve_projection_decoder
lazy from snekql.errors import QueryCompilationError
lazy from snekql.model import Table, require_model_columns, require_model_table_name
lazy from snekql.storage import Attr, StorageBackend

type SourceDecoders = tuple[Callable[[object], object], ...]


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
    model_columns: Mapping[str, Attr[Any, Any, Any, Any, Any]] | None

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
                model_columns=None,
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
        row_model = (
            source.source_model if issubclass(source, _AliasRelation) else source
        )
        model_columns = (
            require_model_columns(row_model) if row_model is not source else columns
        )
        # A reordered alias retains the general name-based materialization path.
        if row_model is not source and tuple(model_columns) != tuple(columns):
            model_columns = None
        return cls(
            payload=tuple(columns.values()),
            presence=marker,
            column_names=tuple(columns),
            row_model=row_model,
            model_columns=model_columns,
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
        decoders: SourceDecoders = (),
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
                    decode(value)
                    for decode, value in zip(decoders, payload, strict=True)
                )
                if decoders
                else tuple(
                    _decode_selectable(field, value, backend=backend, validate=validate)
                    for field, value in zip(self.payload, payload, strict=True)
                )
            )
        if self.row_model is None:
            msg = "source row lost its model contract"
            raise QueryCompilationError(msg)
        if self.model_columns is not None:
            return decode_model_values(
                self.row_model,
                self.model_columns,
                payload,
                backend=backend,
                validate=validate,
            )
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
    stop: int
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
            offset = len(fields)
            fields.extend(shape.fields)
            spans.append(
                _RowSpan(
                    shape=shape, offset=offset, stop=len(fields), nullable=nullable
                )
            )
        return cls(fields=tuple(fields), spans=tuple(spans))

    def resolve_decoders(
        self, *, backend: StorageBackend, validate: bool
    ) -> tuple[SourceDecoders, ...]:
        """Bind named-source wire decoders without changing SQL spans or presence."""
        if not any(span.shape.projection is not None for span in self.spans):
            return ()
        return tuple(
            tuple(
                resolve_projection_decoder(
                    field,
                    nullable_models=frozenset(),
                    backend=backend,
                    validate=validate,
                )
                for field in span.shape.payload
            )
            if span.shape.projection is not None
            else ()
            for span in self.spans
        )

    def materialize(
        self,
        row: Sequence[object],
        *,
        backend: StorageBackend,
        validate: bool,
        decoders: tuple[SourceDecoders, ...] = (),
    ) -> tuple[object, ...]:
        """Split joined rows using the same spans that expanded the SQL fields."""
        return tuple(
            span.shape.materialize(
                row[span.offset : span.stop],
                backend=backend,
                validate=validate,
                nullable=span.nullable,
                decoders=decoders[index] if decoders else (),
            )
            for index, span in enumerate(self.spans)
        )
