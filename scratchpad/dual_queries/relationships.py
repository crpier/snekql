"""Target-aware reference binding and bounded FK declaration support."""

from annotationlib import Format, get_annotations
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Generic, Protocol, TypeVar, get_args

from scratchpad.dual_features.models import ReadRow
from scratchpad.dual_features.records import (
    Column,
    Field,
    ForeignColumn,
    ModelError,
    ReferentialAction,
)
from scratchpad.dual_features.runtime import (
    Expression,
    Predicate,
    composite,
    relationship,
)

Scope = TypeVar("Scope")
Row = TypeVar("Row")
Value_co = TypeVar("Value_co", covariant=True)


@dataclass(frozen=True)
class ReferenceTarget(Generic[Scope, Row, Value_co]):
    """Original column identity plus the possibly aliased, nullable SQL occurrence."""

    column: Column[Row, Any]
    expression: Expression[Scope, Any]
    decode: Callable[[object], Value_co]


class Referenced[Scope, Row, Value](Protocol):
    """Invariant original target identity survives aliasing independently of scope."""

    def __reference__(self) -> ReferenceTarget[Scope, Row, Value]: ...


def reference_predicate[Left, Right, Owner: ReadRow, Target: ReadRow](
    foreign: ForeignColumn[Owner, Target, Any],
    source: Expression[Left, Any],
    target: ReferenceTarget[Right, Target, Any],
) -> Predicate[Left | Right]:
    """Check declaration identity and domains before building an explicit equality."""
    expected = foreign.declaration.resolve()
    if expected.owner is not target.column.owner or expected.name != target.column.name:
        message = "Reference target does not match the declared model and column"
        raise ModelError(message)
    relationship(foreign, expected, enforced=foreign.declaration.enforced)
    return Predicate[Left | Right](
        f"{source.sql} = {target.expression.sql}",
        source.owners | target.expression.owners,
    )


@dataclass(frozen=True, init=False)
class ForeignKeyConstraint:
    """Class-local composite FK using class-body fields, like current snekql.

    Put `ForeignKeyConstraint(tenant_id, account_id, references=(Account.tenant_id,
    Account.id), on_update="CASCADE")` in the input class's `__foreign_keys__`.
    A deferred callable also works for forward/self target columns. Fields bind
    to the read class only when `foreign_keys(ReadClass)` finalizes the fragment.
    """

    columns: tuple[Field[Any] | Column[Any, Any], ...]
    references: (
        tuple[Column[Any, Any], ...] | Callable[[], tuple[Column[Any, Any], ...]]
    )
    on_update: ReferentialAction

    def __init__(
        self,
        first: Field[Any] | Column[Any, Any],
        second: Field[Any] | Column[Any, Any],
        *rest: Field[Any] | Column[Any, Any],
        references: tuple[Column[Any, Any], ...]
        | Callable[[], tuple[Column[Any, Any], ...]],
        on_update: ReferentialAction = "NO ACTION",
    ) -> None:
        object.__setattr__(self, "columns", (first, second, *rest))
        object.__setattr__(self, "references", references)
        object.__setattr__(self, "on_update", on_update)

    def ddl(self, owner: type[ReadRow]) -> str:
        """Validate every pair, then emit one composite constraint, not scalar FKs."""
        targets = (
            self.references if isinstance(self.references, tuple) else self.references()
        )
        if len(self.columns) != len(targets):
            message = "Composite FK source and target arities differ"
            raise ModelError(message)
        if self.on_update not in {
            "CASCADE",
            "RESTRICT",
            "NO ACTION",
            "SET NULL",
            "SET DEFAULT",
        }:
            message = "Unsupported foreign-key ON UPDATE action"
            raise ModelError(message)
        pairs = []
        for member, target in zip(self.columns, targets, strict=True):
            if isinstance(member, Field):
                belongs = any(
                    vars(base).get(member.name) is member for base in owner.__mro__
                )
            else:
                belongs = member.owner is owner
            if not belongs or member.name not in owner.specs:
                message = "Composite source column belongs to another model"
                raise ModelError(message)
            pairs.append(relationship(getattr(owner, member.name), target))
        return f"{composite(pairs[0], pairs[1], *pairs[2:]).ddl()} ON UPDATE {self.on_update}"


def foreign_keys(row: type[ReadRow]) -> tuple[str, ...]:
    """Resolve scalar FK declarations to DDL fragments after model definitions.

    Logical domains and declared target annotations are checked here. This is
    not a full schema planner: physical storage, indexes, actions versus NULL
    policy, and migration history remain outside the prototype.
    """
    declarations = {}
    for base in reversed(row.__mro__):
        declarations.update(get_annotations(base, format=Format.FORWARDREF))
    fragments: list[str] = []
    for name in row.specs:
        column = getattr(row, name)
        if not isinstance(column, ForeignColumn):
            continue
        target = column.declaration.resolve()
        annotated_target = get_args(declarations[name])[0]
        if annotated_target is not target.owner:
            message = "FK annotation and deferred target name different read models"
            raise ModelError(message)
        edge = relationship(column, target, enforced=column.declaration.enforced)
        if column.declaration.enforced:
            fragments.append(f"{edge.ddl()} ON UPDATE {column.declaration.on_update}")
    fragments.extend(constraint.ddl(row) for constraint in row.__foreign_keys__)
    return tuple(fragments)
