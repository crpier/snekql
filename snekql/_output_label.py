"""Identity-bearing output labels derived from existing SQL expressions."""

from dataclasses import dataclass
from typing import Any

from snekql.errors import QueryConstructionError


@dataclass(frozen=True, slots=True, eq=False, repr=False)
class _OutputLabel[OwnerT, T, CompareT, FamilyT = Any]:
    """Bind one expression by token identity, never by name-based type assertions."""

    name: str
    operand: object

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name or "\x00" in self.name:
            msg = "output labels require a nonempty string without NUL"
            raise QueryConstructionError(msg)

    def __expression_family_type__(self) -> FamilyT:
        """Typing-only evidence retained when an expression receives a name."""
        raise NotImplementedError

    def __owner_type__(self) -> OwnerT:
        """Typing-only witness for the expression's original query owner."""
        raise NotImplementedError

    def __value_type__(self) -> T:
        """Typing-only witness for the decoded SQL value, not a result validator."""
        raise NotImplementedError

    def __accepts_comparison__(self, value: CompareT, /) -> None:
        """Typing-only witness retaining the source's comparison domain."""
        raise NotImplementedError


class _NullExtendedLabel[OwnerT, T, CompareT, FamilyT = Any](
    _OutputLabel[OwnerT, T, CompareT, FamilyT]
):
    """An output whose owner becoming absent can introduce a SQL NULL."""

    __slots__ = ()

    def __null_extension_sensitive__(self) -> None:
        """Typing-only witness distinguishing column reads from stable aggregates."""
        raise NotImplementedError
