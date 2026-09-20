"""Identity-bearing output labels derived from existing SQL expressions."""

from dataclasses import dataclass

from snekql.errors import QueryConstructionError


@dataclass(frozen=True, slots=True, eq=False, repr=False)
class _OutputLabel[OwnerT, T, CompareT]:
    """Bind one expression by token identity, never by name-based type assertions."""

    name: str
    operand: object

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name or "\x00" in self.name:
            msg = "output labels require a nonempty string without NUL"
            raise QueryConstructionError(msg)

    def __owner_type__(self) -> OwnerT:
        """Typing-only witness for the expression's original query owner."""
        raise NotImplementedError

    def __value_type__(self) -> T:
        """Typing-only witness for the decoded SQL value, not a result validator."""
        raise NotImplementedError

    def __accepts_comparison__(self, value: CompareT, /) -> None:
        """Typing-only witness retaining the source's comparison domain."""
        raise NotImplementedError


class _NullExtendedLabel[OwnerT, T, CompareT](_OutputLabel[OwnerT, T, CompareT]):
    """An output whose owner becoming absent can introduce a SQL NULL."""

    __slots__ = ()
