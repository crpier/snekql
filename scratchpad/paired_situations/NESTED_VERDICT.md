> Historical two-way impressions. The query-weighted recommendation in
> [VERDICT.md](VERDICT.md) supersedes this conclusion.

# Impressions and verdict

## My preference

**Fetched-first nesting remains my preferred direction for a larger model-interface
redesign. Class-body results remain the better small declaration improvement.**

Those are different recommendations. The class-body approach changes much less
and retains the existing query interface. The nested prototype demonstrates a
better separation of input and complete-value construction, but is not ready to
replace the native interface as it stands.

Model inheritance does not affect this recommendation. Explicitly rejecting
unsupported inheritance is sufficient for the current library priorities.

## What felt better with nesting

### Complete construction is honest

This is the most important difference:

```python
Counter(counter_id=42, count=3)  # A complete Python value.
Counter.Pending()  # Both values may be omitted for insertion.
```

The complete constructor rejects missing or omitted generated values, both
statically and after erasure. Pending is not a subtype of Counter. Even a fully
populated Pending cannot accidentally satisfy a complete-row parameter.

The class-body model still accepts `Counter[Fetched](count=3)` while exposing
counter_id as an int whose runtime value is PENDING_GENERATION. Its result witness
does not change the native constructor. This is an inherited problem, but it is
still present in the application comparison.

Direct Counter construction is intentionally allowed without database access. It
proves a complete value, not that the counter exists in a database.

### Complete values read more naturally

```python
async def create_user(...) -> User: ...
def receipt_destination(order: Order) -> str: ...
```

The frequently used complete value gets the short name. The exceptional insert
contract is visibly `User.Pending`. I prefer that distribution of names in
application functions and helpers.

Navigation is good, but it is not an exclusive nested win here. Actual ty requests
land on authoritative storage declarations in both files. Nesting fixes the older
input-first dual-class navigation problem; class-body generics already keep their
storage in one place.

### SQL defaults stay separate from complete construction

The nested declaration makes the choice explicit: storage may generate count,
Pending may omit it, and Counter still requires its concrete value.

Its stricter complete constructor also requires Python-defaulted fields explicitly.
The body constructor can legitimately fill those with real Python defaults. I do
not count every such omission as an unsoundness. The serious problem is accepting
a generated sentinel behind a complete annotation.

## Where nesting cost more

### The second field list is real maintenance

Order has twenty storage fields and twenty Pending annotations. An added field
or nominal-type change must update both contracts. Deliberately stale Pending
edits pass ty but fail when the outer class is declared.

The second declaration is useful for input optionality, but many lines merely
repeat the same logical type. I would not pretend the repetition disappears
because storage options are declared once.

Runtime declaration validation makes this manageable. It does not make it as
statically local as one field list. A production design should surface those
errors predictably before application work starts.

### Shared methods need a choice

The example deliberately uses simple delegation rather than introducing another
class hierarchy:

```python
# Present on both Order and Order.Pending:
def total(self) -> Decimal:
    return invoice_total(self)
```

The implementation is shared, but the two methods are still declared separately.
`is_paid` also repeats. The complete-only receipt_key has a natural home on Order.

The body approach writes each method once, although methods using ordinary fields
need the tested explicit Pending-or-Fetched self annotation. That is ceremony,
but often less ceremony than deciding how two independent classes share behavior.

If models accumulate substantial common behavior, this advantage becomes more
important. If they mostly declare data and feed explicit queries, I prefer the
nested naming and constructor contracts.

### One newly visible default-typing weakness

Change the allowed status values to remove draft, but leave the default unchanged:

```python
# Nested Pending:
status: sqlite.Col[Status] = sqlite.default("draft")

# Body:
status: sqlite.Col[Status] = sqlite.Text(default="draft")
```

The body declaration produces a static assignment diagnostic. The nested
prototype's default helper returns Any and misses the disagreement. Construction
rejects it in both approaches.

This is a concrete defect in the current nested helper, not a necessary property
of independent classes. It deserves attention before production extraction. We
kept the counterexample rather than silently strengthening the helper during the
comparison.

### The native query interface is still ahead of the adapter

Body uses native optional lookup, UPDATE, DELETE, RETURNING, and native Write
annotations. Nested currently needs a bounded fetch_all implementation for the
primary-key lookup and explicit native bridges for UPDATE/DELETE.

The string field names in those bridges lose assignment checking. They are visible
in the review file because hiding them would make the nested prototype look more
complete than it is. They are implementation work, not evidence against the basic
class layout, but that work should not be ignored.

## What class-body results do well

The same native fields, queries, codecs, transactions, and application contracts
continue to work. Order's storage fields are declared once. Native MariaDB operators
remain available without inventing another descriptor vocabulary.

The witness lives in an ordinary class-body annotation. Both minimal and full
consumers lint without a Fetched import exception. No constructor overloads or
replacement runtime are required for this change.

That makes it a plausible incremental improvement, independent of whether the
library ever adopts separate input classes.

## What class-body results do not solve

It keeps lifecycle-generic naming and state-dependent descriptor annotations.
It does not harden complete construction, fix `.construct()`, or make specialized
classes valid native query sources.

The current shim also has a material compatibility problem:

```python
def insert_generic[Read: sqlite.Model[Any, Any]](
    pending: sqlite.Model[Pending, Read],
) -> sqlite.Write[Read]: ...
```

This original nominal helper remains precise with original models. With the
class-body shim, its result becomes Any. The concrete witness cannot recover the
result parameter after upcasting to the inherited native `Model[State, Any]`.
Query-oriented helpers still retain exact results.

Nested also requires helper migration. It does not accept the old nominal helper;
its new Paired contract explicitly expresses the input-to-row relation. Its tested
helper is precise, but its Write alias is only the adapter's INSERT RETURNING subset.
Neither variant gets a blanket generic-helper compatibility claim.

## How I interpret the FK and backend findings

Both approaches execute direct and self FKs. The nested adapter executes the tested
mutual FK spelling, while the body variant inherits native early rejection of the
forward FKCol annotation. That is not proof that native models cannot represent
cyclic constraints using other declarations.

The adapter's preservation of Decimal-FK precision predates nesting. Conversely,
both variants hit the native nullable-datetime SQL-default restriction. These are
storage/binding implementation findings, not arguments that indentation fixes SQL.

Their common declarations produce matching Scaffold, and eight representative
compiled SQL/parameter pairs match. Native storage and codecs remain the foundation
of both approaches.

## Decision I would make

For the long-term model interface, I would continue with **explicit-link fetched-first
nesting**, prioritizing:

1. Preserving the truthful complete and input constructors.
2. Tightening default-helper typing and keeping declaration-agreement checks early.
3. Bringing typed native query operations to the row/input interface without the
   current string-based bridges.

For a smaller near-term change, I would keep **class-body results** as an independent
option, but resolve the generic-helper compatibility story before treating the
witness-only shim as a drop-in replacement.

I would not select by line count or by how many current prototype features happen
to work. The deciding trade is simpler, trustworthy complete values versus the
maintenance and behavior-sharing costs of two contracts. With the stated library
priorities, I still think the complete-value side is worth paying for.
