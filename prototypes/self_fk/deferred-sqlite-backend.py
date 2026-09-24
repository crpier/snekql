"""A deferred target names its actual owner rather than inferring one from the field."""
from typing import assert_type, dataclass_transform
from snekql import sqlite, mariadb
from snekql.sqlite.model import ModelMeta
from deferred import deferred_fk

@dataclass_transform(field_specifiers=(sqlite.Integer, deferred_fk), kw_only_default=True)
class Meta(ModelMeta):
    pass

class Other[S=mariadb.Pending](mariadb.Model[S, "Other[mariadb.Fetched]"]):
    key: mariadb.Col[int] = mariadb.Integer(primary_key=True)

class Account[S=sqlite.Pending](sqlite.Model[S, "Account[sqlite.Fetched]"], metaclass=Meta):
    key: sqlite.GenCol[int] = sqlite.Integer(primary_key=True, auto_increment=True, default=sqlite.PENDING_GENERATION)
    parent: sqlite.FKCol[Account, int | None] = deferred_fk(lambda: Other.key, default=None)

assert_type(Account().parent, int | None)
Account.parent.references(Account.key)
