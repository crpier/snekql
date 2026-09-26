"""Backend-owned native constants without query-source ownership."""

from dataclasses import dataclass
from typing import ClassVar, Never

from snekql._dialect_expr import CompileCtx
from snekql._output_domain import OutputDomain
from snekql._output_label import _OutputLabel
from snekql._query_dialect import query_dialect_for_backend
from snekql._value_expression import _encode_native_literal
from snekql.errors import ModelValidationError, QueryConstructionError
from snekql.model import BackendFamily
from snekql.storage import StorageBackend


@dataclass(frozen=True, slots=True, repr=False)
class _IntegerLiteral[FamilyT: BackendFamily]:
    """A bound signed-64 integer whose domain does not depend on a FROM table."""

    value_type: ClassVar[type[int]] = int

    backend: FamilyT
    value: int

    def __expression_family_type__(self) -> FamilyT:
        """Typing-only family evidence for named projection inputs."""
        return self.backend

    def __owner_model__(self) -> Never:
        msg = "a literal cannot supply FROM; use select(Model).project(...)"
        raise QueryConstructionError(msg)

    def __compile_sql__(self, ctx: CompileCtx) -> tuple[str, tuple[object, ...]]:
        renderer = query_dialect_for_backend(self.backend).integer_literal_sql
        sql = ctx.placeholder if renderer is None else renderer(ctx.placeholder)
        return sql, (self.value,)

    def __decode_with_policy__(
        self, raw: object, *, backend: StorageBackend, validate: bool
    ) -> int:
        """Native SQL integer results require no source-column codec or coercion."""
        if backend != self.backend:
            msg = "literal decode backend differs from its declaration"
            raise QueryConstructionError(msg)
        if type(raw) is not int:
            msg = "integer literal returned a non-integer SQL value"
            raise ModelValidationError(msg)
        return raw

    def __encode_comparison__(self, value: object) -> object:
        """Reuse the native integer policy when a CTE rebinds this constant."""
        return _encode_native_literal(int, value)

    def __output_domain__(self) -> OutputDomain:
        return OutputDomain(int, nullable=False)

    def label(self, name: str) -> _OutputLabel[Never, int, int, FamilyT]:
        """Name a constant without introducing LEFT-join null extension."""
        return _OutputLabel[Never, int, int, FamilyT](name=name, operand=self)


def build_integer_literal[FamilyT: BackendFamily](
    value: object, *, backend: FamilyT
) -> _IntegerLiteral[FamilyT]:
    """Reject booleans, NULL and integers outside the native signed-64 domain."""
    if type(value) is not int:
        msg = "literal requires a native integer value"
        raise QueryConstructionError(msg)
    _encode_native_literal(int, value)
    return _IntegerLiteral(backend=backend, value=value)
