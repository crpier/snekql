"""Table-level foreign-key declarations independent of column value construction."""

from dataclasses import dataclass
from typing import Any

from snekql.errors import ModelDeclarationError
from snekql.expressions import Predicate
from snekql.storage import Attr, ReferentialAction, _DeferredFKAttr


@dataclass(frozen=True, init=False)
class ForeignKeyConstraint[OwnerT, TargetT]:
    """Declare an ordered foreign key without deriving local column storage.

    Within a model body:

    ```python
    __foreign_keys__ = [ForeignKeyConstraint(
        tenant_id, account_id,
        references=(Account.tenant_id, Account.id), on_delete="CASCADE",
    )]
    ```
    """

    columns: tuple[Attr[Any, Any, OwnerT, Any, Any], ...]
    references: tuple[Attr[Any, Any, TargetT, Any, Any], ...]
    on_delete: ReferentialAction | None
    on_update: ReferentialAction | None

    def __init__(
        self,
        *columns: Attr[Any, Any, OwnerT, Any, Any],
        references: tuple[Attr[Any, Any, TargetT, Any, Any], ...],
        on_delete: ReferentialAction | None = None,
        on_update: ReferentialAction | None = None,
    ) -> None:
        if (
            not isinstance(references, tuple)
            or not columns
            or len(columns) != len(references)
        ):
            msg = "foreign key requires equally sized nonempty column tuples"
            raise ModelDeclarationError(msg)
        for members in (columns, references):
            seen: set[int] = set()
            for column in members:
                if not isinstance(column, Attr):
                    msg = "foreign key members must be column descriptors"
                    raise ModelDeclarationError(msg)
                if not isinstance(column, _DeferredFKAttr) and not column.keyable:
                    msg = "column storage does not support foreign keys"
                    raise ModelDeclarationError(msg)
                if id(column) in seen:
                    msg = "foreign key cannot repeat a column within either tuple"
                    raise ModelDeclarationError(msg)
                seen.add(id(column))
        for action in (on_delete, on_update):
            if action is not None and action not in (
                "CASCADE",
                "RESTRICT",
                "SET NULL",
                "NO ACTION",
            ):
                msg = "unsupported foreign-key referential action"
                raise ModelDeclarationError(msg)
        object.__setattr__(self, "columns", columns)
        object.__setattr__(self, "references", references)
        object.__setattr__(self, "on_delete", on_delete)
        object.__setattr__(self, "on_update", on_update)


@dataclass(frozen=True)
class CheckConstraint[OwnerT]:
    """Declare a named table CHECK using local column predicates.

    Return declarations from a synchronous `__checks__` classmethod:

    ```python
    @classmethod
    def __checks__(cls):
        return [CheckConstraint(cls.balance.gte(0), name="ck_balance")]
    ```

    The method runs once during model creation, or on first binding for models
    with callable foreign keys. SQL NULL passes unless excluded.
    """

    predicate: Predicate[OwnerT]
    name: str
