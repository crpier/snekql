# Named UNION and UNION ALL

Use UNION when rows from two queries should form one result. `union_all` keeps
duplicates; `union` removes them using the database's equality rules.

Both backends support these methods on completed [named projections](results.md).
The inputs must use the same result-model class and compatible fields. The
combined query runs as one SQL statement.

## Combine named results

```python
from typing import ClassVar

from pydantic import BaseModel

from snekql import sqlite


class Event[S = sqlite.Pending](sqlite.Model[S]):
    __row_type__: ClassVar[sqlite.ReadType[Event[sqlite.Row]]]
    id: sqlite.Col[int] = sqlite.Integer(primary_key=True)
    archived: sqlite.Col[bool] = sqlite.Integer()


class EventIdentity(BaseModel):
    id: int


event_id = Event.id.label("id")
current = (
    sqlite.select(Event)
    .where(Event.archived.eq(False))
    .project(EventIdentity, id=event_id)
)
archived = (
    sqlite.select(Event)
    .where(Event.archived.eq(True))
    .project(EventIdentity, id=Event.id.label("id"))
)
combined = current.union_all(archived)
page = combined.order_by(combined.column(event_id).asc()).limit(50).offset(100)
# await transaction.fetch_all(page) returns list[EventIdentity].
```

`.union_all()` preserves duplicate rows. `.union()` removes duplicates using the
database's equality rules, including NULL and collation semantics. Neither
operation uses Python model equality or promises an order without final ordering.

Both operands must have the same backend and the exact same result-model class.
Neither operand requires `.all()` or `.where(...)`. Subclasses are different result contracts. Scalar, tuple,
table-model and write operands are not supported. Use `.project(...)` to make
an explicit named operand, including when reading an existing CTE.

Fields are matched by name and emitted in result-model field order, regardless
of binding insertion order. There is no eight-field limit for named operands.
Only a label actually bound in the left operand can address a combined output.
Equal spelling, a fresh label, or a right-hand token is not sufficient.

## The left output contract governs nullability

The combined output keeps the left token's type. A nullable right output cannot
widen a required left output. Construction raises `QueryConstructionError`
before database I/O, even if the Pydantic result annotation permits `None`.
A nullable left output can accept a compatible required right output.

```python
from typing import ClassVar


class MaybeEvent[S = sqlite.Pending](sqlite.Model[S]):
    __row_type__: ClassVar[sqlite.ReadType[MaybeEvent[sqlite.Row]]]
    id: sqlite.Col[int | None] = sqlite.Integer()


class OptionalIdentity(BaseModel):
    id: int | None


maybe_id = MaybeEvent.id.label("id")
optional = sqlite.select(MaybeEvent).project(OptionalIdentity, id=maybe_id)
required = sqlite.select(Event).project(OptionalIdentity, id=Event.id.label("id"))
accepted = optional.union_all(required)
# accepted.column(maybe_id) retains int | None.
# required.union_all(optional) raises QueryConstructionError.
```

The contract comes from SQL expressions, including contextual LEFT-join null
extension and scalar-subquery nullability. Changing only a result annotation
cannot make a required token optional. Reversing operands can therefore change
contract acceptance, independently of SQL set semantics.

This restriction is deliberate. Current completed-query types do not retain
arbitrary per-field right-hand nullability for static inference. Runtime guards
remain necessary for nullability and codec compatibility, exact model identity,
and callers whose helper annotations erase information.

## Codecs and result validation

A matching result class is not a compatibility proof. Every output must have a
known compatible logical domain, wire representation and decode policy. Source
annotation validators, JSON markers, decimal policies and declared text policies
are retained in that comparison. UUID TEXT and BLOB outputs are not interchangeable.
Unknown dialect-expression policies are rejected rather than guessed.

MIN/MAX outputs retain their source wire and decode policies, so their differing
operation names alone do not make them incompatible. SUM/AVG retain separate
provenance because their SQL result types can differ from their source types.

Compatibility is conservative. Different expression provenance can be rejected
although a particular database might accept it, including a native-column output
paired with an arithmetic output. The library does not insert numeric casts or
choose an arbitrary decoder. Compatible operands use the established left
output decoder.

Input result-model validators do not run inside the SQL operation. Source values
are decoded and the final named row validates strictly when fetched. Disabling
source validation with `validate=False` does not disable final named-result
validation. Eager, optional and chunked fetches keep the existing runtime rules.

## Ordering, grouping and relational boundaries

Final ordering accepts direct combined output columns only, not operand columns,
aggregates or computed ordering expressions. Final LIMIT/OFFSET apply to the
whole result. Ordering references from a different compound object are rejected.
Use `.cte()` before further filtering, joining or SQL output computation.
A standalone `select(combined.column(token))` is rejected at compilation; it
cannot read a compound output independently of its defining query:


```python
class CombinedEvents:
    pass


events = combined.cte(CombinedEvents, name="combined_events")
query = sqlite.select(events).where(events.column(event_id).gt(10))
```

Mixed operators retain their binary expression-tree grouping:

```python
left_grouped = current.union(archived).union_all(current)
right_grouped = current.union(archived.union_all(current))
```

Those expressions can return different multiplicities. Compilation uses derived
queries to preserve grouping on both backends; it does not flatten the tree.

Operand-local ORDER BY, LIMIT/OFFSET and locking SELECTs are rejected. If a bound
belongs inside an operand, make that boundary explicit:

```python
class RecentEvents:
    pass


recent = (
    current.order_by(Event.id.desc()).limit(20).cte(RecentEvents, name="recent_events")
)
bounded = sqlite.select(recent).project(
    EventIdentity, id=recent.column(event_id).label("id")
)
with_archive = bounded.union_all(archived)
```

CTE dependencies are emitted once before the statement. Parameters follow SQL
text order. Combined CTEs preserve the private row-presence output needed to
distinguish unmatched LEFT joins from matched all-NULL rows. That presence
output does not participate in duplicate removal.

INTERSECT, EXCEPT and window builders remain separate work. Use [raw reporting](reporting.md) for those SQL operations. There is no
optimizer materialization or evaluation-count guarantee.

For native recursion, see [typed recursive CTEs](recursive-ctes.md).

[All guides](README.md)
