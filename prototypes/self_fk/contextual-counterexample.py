"""Contextual self-target inference accepts a target unrelated to the containing model."""
from typing import dataclass_transform
from snekql import sqlite
from snekql.sqlite.model import ModelMeta
from contextual import contextual_fk

@dataclass_transform(field_specifiers=(sqlite.Integer, contextual_fk), kw_only_default=True)
class Meta(ModelMeta):
    pass

class Other[S=sqlite.Pending](sqlite.Model[S, "Other[sqlite.Fetched]"]):
    key: sqlite.Col[int] = sqlite.Integer(primary_key=True)

class Account[S=sqlite.Pending](sqlite.Model[S, "Account[sqlite.Fetched]"], metaclass=Meta):
    key: sqlite.Col[int] = sqlite.Integer(primary_key=True, default=1)
    parent: sqlite.FKCol[Account, int | None] = contextual_fk(key, default=None)
    wrong: sqlite.FKCol[Other, int | None] = contextual_fk(key, default=None)
