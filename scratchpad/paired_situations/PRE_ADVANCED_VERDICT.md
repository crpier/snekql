> Historical assessment before the advanced paired application. Superseded by VERDICT.md.

> Subsequent direction: nesting is dropped. Dual versus current-native typing
> research continues in [dual_typing_parity](../dual_typing_parity/README.md).
> The earlier overall preference below is not a settled interface decision.

# Dual classes versus class-body results

## Verdict

**I prefer class-body results overall for the stated priorities, narrowly.**
Queries and their checked contracts matter most here. Direct fetched construction
is a minor concern. With that weighting, keeping one model declaration and the
native query interface is more valuable than separating the value classes.

The input-first dual design is substantially more appealing than nesting at this
scale. It eliminates most repeated annotations and shares methods naturally.
I would choose it over the nested version. But I do not see enough improvement in
ordinary query typing to justify replacing the existing model/query integration.

This is a design recommendation, not approval to ship the witness-only shim.
Existing nominal generic helpers still require migration, and native query-source
holes deserve attention. Keep the original lifecycle-generic API as the production
baseline until those adoption questions are resolved.

The earlier constructor-led preference for nesting is archived in
[NESTED_VERDICT.md](NESTED_VERDICT.md). It is not the current recommendation.

## What the dual example improves

Read [dual.py](dual.py) beside [body.py](body.py), in the same twelve-section order.
The input-first spelling uses User for input/storage and UserRow for complete
values and query sources. These are the earlier dual-class names, not new column
vocabulary. Both files use Col, FKCol, and JsonCol.

### Fields and foreign keys are mostly declared once

```python
class Post(sqlite.Model):
    __row__: ClassVar[type[PostRow]]
    post_id: sqlite.Col[PostId | sqlite.Omitted] = sqlite.Integer(
        primary_key=True, auto_increment=True, default=sqlite.OMIT
    )
    author_id: sqlite.FKCol[UserRow, UserId] = sqlite.ForeignKey(UserRow.user_id)
    title: sqlite.Col[str] = sqlite.Text()


class PostRow(Post, sqlite.Row):
    table_name = "posts"
    post_id: sqlite.Col[PostId]
```

The FK is not repeated. PostRow inherits it, along with title and its constructor
requirement. Only the generated identity needs a narrower annotation.

The twenty-field Order has twenty input annotations plus three row refinements.
Nested has twenty plus twenty. Class-body has twenty. These counts exclude the
result witnesses. A new ordinary nullable field needs one declaration in dual,
not matching annotations in two independent classes.

### Behavior is cleaner than in either other example

Order defines total and is_paid once. OrderRow inherits them and adds receipt_key.
An Order parameter can accept either input or row values. No duplicated methods,
shared-method mixin, or explicit lifecycle-union self annotation is needed.

This is the dual design's strongest advantage in these examples, once direct
complete construction is given little weight.

## Queries: what the evidence actually establishes

### Ordinary checked queries are precise in both

```python
# Dual
sqlite.select(UserRow.email).join(
    PostRow, on=PostRow.author_id.references(UserRow.user_id)
).all()

# Class-body
sqlite.select(User.email).join(Post, on=Post.author_id.references(User.user_id)).all()
```

Both produce exactly list[str]. Both also retain exact model, generated-ID,
nullable-scalar, and MariaDB JSON-expression results in the tested calls.

The independent callers reject wrong predicate owners, wrong nominal IDs, wrong
value types, wrong FK target owners/columns, unrelated join predicates, wrong
conflict targets/assignments, unscoped execution, and backend mixing in both.
There is no Any or Unknown accepted as an exact result in those positive probes.

The UserRow suffix is a naming choice. Naming the classes UserInput and User would
shorten dual query expressions without changing their typing. I am not treating
suffix length as an inherent weakness of two classes.

### Dual has a real source-selection advantage

Dual rejects using the input class, an input column, an input predicate on a row
query, or an input instance as a query source.

Body accepts these two invalid source forms statically and rejects them at runtime:

```python
sqlite.select(User(email="A"))
sqlite.select(User[Fetched])
```

Both failures also occur with the original native declaration. They are inherited
query-source typing holes, not effects of moving the result witness into the body.
They matter more to this comparison than the fetched-constructor hole does.
They should be fixed; nothing here establishes that a single-class design requires
them. The usual sqlite.select(User) spelling remains precise and executes correctly.

### Generic insertion need not lose precision with class-body models

The existing Model[Pending, Read]-based helper still infers Any for body models.
Dual needs a different Paired[Read] helper because it is not a native Model.
Comparing the new dual helper only against the old body helper would be unfair.

A new tested alternative in body.py uses native InsertableModel:

```python
def insert_via_protocol[Owner: sqlite.Model[Any, Any], Read: sqlite.Model[Any, Any]](
    pending: InsertableModel[Literal["sqlite"], Owner, Read],
) -> sqlite.Write[Read]:
    return sqlite.insert(pending).returning()
```

It returns the exact Counter[Fetched] through execution and rejects fetched inputs
and another backend. This protocol comes from snekql.query, not the backend's
curated public namespace. A supported public helper annotation still needs an API
decision, and old nominal helpers do not repair themselves.

Result-oriented Select[Result] and Write[Result] helpers stay exact without knowing
model declaration details. Dual's current Write alias covers only INSERT RETURNING.
Body's native Write contract also covers other native write commands.

### The dual adapter does not have query parity

The same eight representative SQL/parameter comparisons match across all three
approaches. That is bounded evidence, not equivalence of the query interfaces.

In this adapter:

- Tuple projections, model-pair results, left joins, typed UPDATE, and typed DELETE
  are unsupported. Earlier dual-query research is broader; these limits are not
  proof that a dual-class design cannot support them.
- select(UserRow).join(PostRow, ...) returns only UserRow. Native model joins return
  a tuple containing both selected and joined models. Both result annotations are
  honest, but the superficially similar calls have different semantics.
- PATCH and deletion in dual.py use the explicit dual_gaps.py native bridge.
  Its string field names are unchecked. Body uses typed native assignments and
  UPDATE RETURNING directly.
- Optional lookup uses a primary-key-filtered fetch_all instead of native optional
  cardinality. This is not a general fetch-one replacement.

These gaps rule out adopting this prototype as-is. They do not decide the design
verdict by themselves. Even assuming equivalent query implementations, I slightly
prefer having one authoritative declaration used throughout construction, FKs,
and queries. Dual is competitive, but its query-typing benefits here are narrower
than a claim of generally safer queries.

## Other tradeoffs

- Both attribute uses reach storage directly. From an OrderRow type,
  dual first reaches the three refinements and receipt_key; following Order reaches
  the storage and shared methods. The actual ty definition requests confirm this.
- Dual needs a refinement when adding a generated field. Forgetting
  it passes declaration checking but fails schema binding, with Omitted still
  visible in the inherited attribute type. Ordinary field changes are simpler.
- Stale literal defaults are caught statically by native/body Column
  Type constructors. Dual's prototype constructors return Col[Any], so this check
  is missing; construction rejects the bad value. This is adapter typing debt.
- Dual executes the local self/mutual declarations in this study.
  Body's tested mutual FKCol spelling rejects at declaration. This is a bounded
  native binding limitation, not a universal claim about lifecycle generics.
- All seven common scaffolds match. Dual's Decimal-FK precision repair
  comes from an earlier adapter, not from class inheritance. Its Decimal FK join
  also executes against MariaDB. Nullable-datetime SQL NULL still fails in both.
- UserRow is a User, so dual permits inserting a complete row.
  Body rejects fetched values as insertion inputs. This is an intentional contract
  difference, not a claim that a populated value proves database existence.
- Dual requires generated values and rejects sentinels;
  inherited Python defaults can still supply ordinary fields. Body retains its
  native hole. We give this little weight and could provide a generic runtime-
  checked complete-value helper without changing the declaration design.

General model inheritance and constructor-fixture convenience do not drive the
recommendation. Behavior-heavy applications with many input/row-neutral helpers
could reasonably prefer dual. For this query-builder library, my next investment
would be class-body adoption compatibility and native query-source typing, rather
than another model/query adapter redesign.
