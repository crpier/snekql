"""A deferred target names its actual owner rather than inferring one from the field."""
from typing import assert_type, dataclass_transform
from snekql import mariadb, sqlite
from snekql.mariadb.model import ModelMeta
from deferred import deferred_fk

@dataclass_transform(field_specifiers=(mariadb.Integer, deferred_fk), kw_only_default=True)
class Meta(ModelMeta):
    pass

class Other[S=sqlite.Pending](sqlite.Model[S, "Other[sqlite.Fetched]"]):
    key: sqlite.Col[int] = sqlite.Integer(primary_key=True)

class Account[S=mariadb.Pending](mariadb.Model[S, "Account[mariadb.Fetched]"], metaclass=Meta):
    key: mariadb.GenCol[int] = mariadb.Integer(primary_key=True, auto_increment=True, default=mariadb.PENDING_GENERATION)
    parent: mariadb.FKCol[Account, int | None] = deferred_fk(lambda: Other.key, default=None)

assert_type(Account().parent, int | None)
Account.parent.references(Account.key)
