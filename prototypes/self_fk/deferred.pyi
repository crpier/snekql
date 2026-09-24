"""Signature-only proposal, not an implemented public API."""
from collections.abc import Callable
from snekql.model import Table, Pending, Fetched
from snekql.storage import Attr, FKAttr, _UnboundOwner

def deferred_fk[Target, Write, Value, Set, Compare](
    target: Callable[[], Attr[Table[Pending], Table[Fetched], Target, Write, Value, Set, Compare]],
    *, default: None,
) -> FKAttr[Table[Pending], Table[Fetched], _UnboundOwner, Value | None, Value | None, Target]: ...
