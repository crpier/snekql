"""Default and nullable declaration variants for the callable proposal."""
from typing import assert_type, dataclass_transform
from snekql import sqlite as database
from snekql.sqlite.model import ModelMeta
from narrow_probe import foreign_key

@dataclass_transform(field_specifiers=(database.Integer, foreign_key), kw_only_default=True)
class Meta(ModelMeta):
    pass

class Other[S=database.Pending](database.Model[S, "Other[database.Fetched]"]):
    key: database.Col[int] = database.Integer(primary_key=True)

class Account[S=database.Pending](database.Model[S, "Account[database.Fetched]"], metaclass=Meta):
    key: database.GenCol[int] = database.Integer(primary_key=True, auto_increment=True, default=database.PENDING_GENERATION)
    required: database.FKCol[Other, int] = foreign_key(Other.key)
    nullable_required: database.FKCol[Account, int | None] = foreign_key(lambda: Account.key, nullable=True)
    null_default: database.FKCol[Account, int | None] = foreign_key(lambda: Account.key, default=None)
    value_default: database.FKCol[Account, int] = foreign_key(lambda: Account.key, default=1)
    nullable_value_default: database.FKCol[Account, int | None] = foreign_key(lambda: Account.key, nullable=True, default=1)

assert_type(Account(required=1, nullable_required=None).null_default, int | None)
assert_type(Account(required=1, nullable_required=None).value_default, int)
Account.null_default.references(Account.key)
