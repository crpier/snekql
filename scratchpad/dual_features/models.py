"""Small dual-class contracts used by the feature experiments."""

from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Annotated, ClassVar, Self
from uuid import UUID

from annotated_types import Ge

from scratchpad.dual_features.records import (
    OMIT,
    Field,
    Omitted,
    Record,
    field,
    insert_using,
    required,
)

if TYPE_CHECKING:
    from scratchpad.dual_queries.interface import Item, Occurrence
    from scratchpad.dual_queries.relationships import ForeignKeyConstraint


class ReadRow(Record):
    """Explicit eligibility for table reads, independent of insert inheritance."""

    table_name: ClassVar[str]
    __foreign_keys__: ClassVar[tuple[ForeignKeyConstraint, ...]] = ()

    @classmethod
    def __source__(cls) -> Occurrence[Self, Self]:
        """Pin the class identity for inference without another application base."""
        from scratchpad.dual_features.runtime import source
        from scratchpad.dual_queries.interface import Occurrence

        return Occurrence(source(cls))

    @classmethod
    def __selection__(cls) -> Item[Self, Self]:
        """Selecting a read class materializes that class, not its input base."""
        from scratchpad.dual_features.runtime import source
        from scratchpad.dual_queries.interface import Item

        table = source(cls)
        return Item(table, table.row())


class NewAccount(Record):
    id: Field[int | Omitted] = field(default=OMIT)
    name: Field[str] = field()
    code: Field[str] = field()


class Account(NewAccount, ReadRow):
    table_name = "accounts"
    id: Field[int] = required()
    create = insert_using(NewAccount)


class NewEntry(Record):
    id: Field[int | Omitted] = field(default=OMIT)
    account_id: Field[int | None] = field(default=None)
    note: Field[str] = field()


class Entry(NewEntry, ReadRow):
    table_name = "entries"
    id: Field[int] = required()
    create = insert_using(NewEntry)


class NewOther(Record):
    id: Field[int | Omitted] = field(default=OMIT)
    name: Field[str] = field()


class Other(NewOther, ReadRow):
    table_name = "others"
    id: Field[int] = required()
    create = insert_using(NewOther)


class NewDocument(Record):
    id: Field[UUID] = field()
    happened_at: Field[datetime] = field()
    amount: Field[Annotated[Decimal, Ge(0)]] = field()


class Document(NewDocument, ReadRow):
    table_name = "documents"
    create = insert_using(NewDocument)
