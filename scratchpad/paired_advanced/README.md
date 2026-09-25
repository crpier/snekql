# Advanced class-body versus dual comparison

> Follow-up: [direct dual descriptors](../dual_descriptors/README.md) remove the
> explicit column conversions in all sixteen examples, with canonical identity
> and independent typing/runtime checks. The bridge version below remains intact.

An extension of [the twelve-situation comparison](../paired_situations/README.md).
Read [body.py](body.py) beside [dual.py](dual.py), sections 13 through 28.
Nesting is dropped. The original twelve situations remain unchanged.

This SQLite application adds balances and referral links to User/Post. Both
versions declare identical storage and operate on identical seeded accounts and
posts. This is a separate runnable continuation, not a migration of the earlier
example database. Class-body means the witness-only shim, not the original native
two-coordinate declaration and not the constructor-hardening experiment.

## Does this change the comparison?

**It removes missing advanced queries as a design-level argument against dual.**
Both versions express the same sixteen application algorithms. Their SQL and
ordered parameters match, and they produce the same business results. The model
results differ as intended: User[Fetched] versus UserRow.

The earlier preference for class-body now needs to stand on one declaration and
lower native-integration work, not on better query expressions. Dual's value-helper
and class-narrowing advantages remain useful, but do not make its SQL generally
more precise. If those advantages already appeal to you, the advanced examples
supply no new reason to reject dual.

Read [REVIEW.md](REVIEW.md) for the short code comparison and remaining decisions.
The [updated overall assessment](../paired_situations/VERDICT.md) keeps adoption
cost separate from the interface you might prefer after integration.

## Matched applications

| Section | Operation | Result shape |
| --- | --- | --- |
| 13 | Authors with their posts | Pairs of complete User and Post values |
| 14 | Accounts including those without posts | User with Post or None |
| 15 | Referrers through two aliases of User | User with inviter User or None |
| 16 | GROUP BY and HAVING | BalanceGroup application results |
| 17 | Arithmetic, COALESCE, CASE, DISTINCT, ordered pagination | Four-field scalar tuples |
| 18 | Correlated EXISTS | Complete users with posts |
| 19 | Scalar subquery | Email with nullable reference balance |
| 20 | Named CTE and typed label lookup | AccountSummary application results |
| 21 | UNION ALL followed by named CTE ordering | AccountSummary application results |
| 22 | Recursive traversal of stored referral links | ReferralStep application results |
| 23 | Bulk input and RETURNING | List of complete users |
| 24 | Typed arithmetic UPDATE RETURNING | List of complete users |
| 25 | Typed DELETE RETURNING | List of deleted complete users |
| 26 | Conflict update of attempted nickname only | One complete user, original balance preserved |
| 27 | Optional account lookup | Complete user or None |
| 28 | Streaming | Batches of complete users |

The recursive example traverses Linus → Grace → Ada. Separate tests check missing
seeds, depth truncation, and a stored cycle. UNION ALL revisits a cyclic node until
the explicit depth bound; it does not promise cycle elimination. A committed
UPDATE is read back through the application lookup. Validated raw SQL is also
executed against both layouts, independently of table-model materialization.

## What the newer research does and does not transfer

### Wrong result witnesses are checked in both

The original native Model[State, OtherReadModel] counterexample does **not** carry
over unchanged. The body shim validates that ReadType names its own fetched
specialization. It rejects an unrelated witness during declaration. Dual rejects
an unrelated pair when it binds/inserts. Both erroneous declarations still pass
ty. This is runtime validation on both sides, not a dual-only safety improvement.

### Shared helpers favor dual's spelling, not exclusive capability

The dual input-bound generic helper can read ordinary fields directly. The tested
body state-generic helper cannot. A union-bound type variable still fails direct
descriptor access under this ty version.

But helpers.py gives body a working alternative: a union-bound type variable
preserves the exact input/fetched return type, while a shared read-only Contact
protocol handles attribute access. Its result remains exactly User[Fetched].
Both generic insertion helpers also retain their exact complete result type.
The old Model[Pending, Read] insertion helper still yields Any for the body shim.

### Static class narrowing is genuinely simpler with dual

UserRow is an ordinary class and an input subtype. isinstance(value, UserRow)
narrows its generated identity to UserId. isinstance(value, User[Fetched]) is
accepted by this ty version but raises TypeError. A native state guard would be
another interface, not the ordinary class check.

This does not establish database provenance or existence.

### Defaults are fixable adapter debt

Body's native Column Type catches a stale Python literal default. The existing
dual factory does not. The typed Text experiment rejects it and preserves valid
nullable defaults and required fields. That experiment remains partial. It is not
silently substituted for all constructors in dual.py.

### Most query limits are shared

Independent callers retain wrong scope/role/domain/readiness/backend rejections,
wide named results, and known holes. Named keyword binding, eq_col's right owner,
erased result-only helpers, and mixed-table bulk inputs still need runtime checks.
Neither layout makes those problems disappear.

Both reject more than eight positional fields and projection LEFT JOIN through
this native query interface. Older dual query experiments demonstrate alternative
contracts for those operations. They are not implemented here or exclusive to
input-first models.

Both also reject the tested nonnullable-left / nullable-CTE-right eq_col spelling.
Reversing operands makes the referral query type-check and execute without a cast.
That is shared descriptor friction, not a difference in declaration layout.

## The dual implementation is still a bridge

The application imports Transaction from the research bridge. Tests own a native
transaction and adapt it once at entry. The class-body application uses the native
Transaction directly.

Dual also has explicit table()/column() bindings. Prebinding is necessary because
some inline conversions infer Any. These bindings are visible so the example is
honest. They are integration machinery, not a proposed extra task for every query
author. evidence.py removes only those bindings, row-source renaming and insertion
alias differences before comparing the query algorithms.

A plain native Transaction accepts a bridge query but returns private native
objects, not the promised UserRow. That failure is retained with exact caller
typing and actual runtime evidence. Production adoption needs materialization
integration or an enforced consumer distinction. It is not solved by hiding an
import or documenting the right wrapper.

No new MariaDB bridge, complete codec audit, concurrency study, performance claim,
or complete native Transaction facade is included. Streaming is tested with full
iteration; early termination and cancellation were not added to this study.

## Run and inspect

```sh
PYTHON_CONTEXT_AWARE_WARNINGS=1 uv run python -m scratchpad.paired_advanced.tour
bash scratchpad/paired_advanced/run.sh
```

The tour prints matching values and shows User versus UserRow after UPDATE.

Evidence:

- **236 isolated typing observations**: 134 capabilities, 71 rejections,
  22 accepted counterexamples, nine unsupported contracts.
- **61 runtime tests**, including both applications, real SQLite, and failure controls.
- **16 matching application algorithms and SQL/ordered-parameter pairs**.
- Matching User/Post scaffolds.
- Actual expression callers are checked before function annotations could hide Any.
  The runner rejects stale application callers, requires clean controls, locates
  diagnostics in the challenge, and records versions and source hashes.
- Earlier comparison rerun: 163 original and 225 dual/body observations,
  22 source edits, 280 tests including 13 real MariaDB tests. Nesting is only a
  historical regression fixture.
- Earlier parity study rerun: 262 observations and 39 tests.
- Native fast suite: 1,127 passed. Repository ty, Ruff and formatting pass.

Reports are results.json and evidence.json. These counts overlap earlier research;
they are not independent discoveries or a score favoring either design.

All work stays local and uncommitted on research/paired-advanced-queries, based on
56dbc32. Historical issue #396 remains closed. No production change, dependency,
checker plugin, commit, or publication.
