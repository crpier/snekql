"""Rejected signature experiment: target is chosen only by the annotation."""
from snekql.model import Table, Pending, Fetched
from snekql.storage import Attr, FKAttr, _UnboundOwner

def contextual_fk[Target, Write, Value, Set, Compare](
    target: Attr[Table[Pending], Table[Fetched], _UnboundOwner, Write, Value, Set, Compare],
    *, default: None,
) -> FKAttr[Table[Pending], Table[Fetched], _UnboundOwner, Value | None, Value | None, Target]: ...
