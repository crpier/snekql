# Direct dual-class descriptors

Question: can the dual application use `UserRow.balance` directly, without
`column(UserRow.balance)` or inference-saving temporary variables?

**Yes for the tested query expressions.** The [application](application.py) now
runs all sixteen advanced scenarios that way. Its query algorithms and compiled
SQL/ordered parameters still match the class-body application. Exact inferred
results and rejected callers are checked independently of function annotations.

This does not establish that every part of a dual-class interface is finished.
Model-source conversion and materialization remain separate work. A required FK
target declaration also retains a ty hole, described below.

## The actual spelling

```python
rows = await transaction.fetch_all(
    sqlite.select(
        UserRow.email,
        UserRow.balance.add(3),
        UserRow.nickname.coalesce("anonymous"),
    ).all()
)
assert_type(rows, list[tuple[str, int, str]])
```

There is no column conversion in this application. Native alias operations such
as `invitee.column(UserRow.inviter_id)` still exist: those bind a column to a SQL
source occurrence. They are native alias syntax, not the removed conversion.

Model operations still visibly use `table(UserRow)` and the existing SQLite
Transaction adapter. They have not been disguised as completed integration.

## What changed

- **Declaration metadata is separate from query access.** The shared experimental
  storage layer now has FieldDefinition and ForeignDefinition. Old descriptors
  retain their behavior. The new descriptors do not inherit an incompatible old
  `__get__` contract or suppress an override error.
- **Col and FKCol return native expression contracts directly.** Instance access
  remains an ordinary logical value. Owners retain the invariant native bridge
  coordinate, including sibling rows sharing an input base.
- **MariaDB has Col, FKCol, and JsonCol equivalents.** JSON methods retain their
  nullable scalar result and backend owner. MariaDB construction/insertion still
  uses its older adapter; new scalar queries execute through native Transaction.
- **The column itself becomes the canonical native descriptor.** A temporary
  construction lease lets the existing graph binder fill its native metadata.
  Publication and terminal failure remain controlled by the graph binding.
  Column identity is stable before and after binding.
- **Direct and callback FK references remain lazy.** Naming a row column does not
  bind a self/mutual graph. Composite FK targets also normalize declaration
  references without prematurely evaluating native metadata.

Read [columns.py](columns.py) for runtime identity/binding, then [sqlite.py](sqlite.py)
and [mariadb.py](mariadb.py) for the checked getters. The namespace constructors
remain bounded adapters, not copies of every native constructor option.

## Bugs found rather than assumed away

### A forwarding wrapper broke aliases

The first implementation passed basic SQL and type checks, but native
`alias.column` requires the exact object registered on its table. A proxy that
only forwards attributes fails that identity check.

The canonical descriptor integration fixes this. Regression tests include a
column saved before binding, aliases, nullable self-joins, native codec copies,
and two threads sharing one bound column. A graph that fails after partial column
assembly leaves those columns unusable.

### A missing class-access overload became Unknown

Initially, the getter only admitted complete row classes. ty could turn an input
class access into Unknown, allowing `select(User.balance)` without a diagnostic.

An explicit input-class overload now returns object. It makes no query promise
and safely covers a class parameter that may hold a row subclass. Actual input
classes return a non-query marker; instance field access stays precise. Direct
input-class queries are rejected statically and after type erasure at runtime.

### FK constructor inference still has a declaration hole

An inline required callback without an explicit default can conceal the wrong
FK target under this ty version. Such callback calls are now statically rejected,
as in native snekql. Deferred nullable/defaulted callbacks remain available;
immediate targets still support required fields.

With that overload arrangement, ty nevertheless accepts this required declaration:

```python
class Wrong(sqlite.Model):
    parent: sqlite.FKCol[PostRow, UserId] = sqlite.ForeignKey(UserRow.user_id)
```

Binding the corresponding complete row rejects the target mismatch. An ordinary
assignment of the factory result to the wrong FKCol target is rejected, as are
the tested explicitly defaulted wrong-target declarations. A class-body/native
control also accepts the malformed required declaration statically.

This is retained as a counterexample, not counted as a static guarantee. The
public query expressions have precise owners; that does not prove every
constructor/declaration relationship. No checker plugin or per-model helper was
introduced to hide this result.

## Evidence

- **156 isolated observations:** 79 capabilities, 57 rejections, 11 accepted
  counterexamples, nine unsupported contracts. These include shared native limits,
  not just new descriptor findings.
- **65 runtime tests**, including five real MariaDB tests.
- **16 matching application algorithms and SQL/parameter pairs**, with matching
  User/Post scaffolds.
- SQLite execution covers the paired advanced operations, byte/float projections,
  UUID/datetime/JSON codecs, deferred/self/mutual/composite FKs, descriptor identity,
  metadata freezing, failed binding, reentry, and one two-thread first-use control.
- MariaDB execution covers direct JSON extraction `[42, None]`, Decimal projection,
  alias JSON decoding with locking, and Decimal FK precision. A separate test
  retains the native-consumer/model-result mismatch.
- Exact callers include scalar, tuple, nullable, aggregate, expression, named,
  recursive, write, alias, subquery, and streaming results. Wrong domains, owners,
  roles, readiness and backend families retain rejection controls.
- The formerly erased inline scalar result is exactly `list[str]`. An inline
  integer-ID versus text subquery now rejects without binding either operand first.

The runtime run emits the expected native LexicalDatetimeWarning for the explicit
plain datetime-over-Text codec control. No warning was suppressed to claim success.

Reports: results.json and evidence.json. The checker requires clean controls,
challenge-located diagnostics, current application-expression callers and recorded
source hashes. Any/Unknown and runtime rejection are not static guarantees.

## Still not finished

- **Model source integration:** `table(UserRow)` remains. No assertion that native
  `select(UserRow)` already works.
- **Materialization:** a native Transaction can accept a translated model query
  while returning private native instances, contrary to its promised public row.
  SQLite still needs the earlier decoding adapter. MariaDB's new native queries
  here are scalar projections; its model-result mismatch is explicitly retained.
- **Constructor typing:** existing Python-default factory erasure, malformed row
  witnesses and missing generated refinements are not fixed by query descriptors.
- **Shared query limits:** named keyword schemas, right-hand eq_col ownership,
  erased result-only helpers and bulk homogeneity still need runtime validation.
  Native Decimal arithmetic and JSON extraction after `alias.column` remain
  unsupported in both controls. This study does not add those query features.
- **Operational coverage:** one concurrency control is not a concurrency audit.
  No performance study, complete codec matrix, full Transaction facade, or new
  streaming cancellation/early-exit audit was conducted.

The experiment still uses Any inside metadata/factory assembly, private native
interfaces and invariant phantom owners. It is evidence for direct descriptor
syntax, not a production-ready integration or a proof that no issues remain.

## Reproduce and review

```sh
bash scratchpad/dual_descriptors/run.sh
```

Review the application first, then the getter signatures and retained failures.
The important next integration problem is model sources/materialization, not
reintroducing explicit column conversions.

Regressions run after changing the shared experimental metadata layer:

- Earlier advanced comparison: 236 observations, 61 tests.
- Earlier parity study: 262 observations, 39 tests.
- Earlier application comparison: 163 and 225 observations, 22 source edits,
  280 tests including 13 MariaDB tests.
- Storage/finalization/backend/pairing/row-first runtime studies: 164 tests.
  Their individual historical typing inventories were not all rerun.
- Native fast suite: 1,127 tests. Full native integration suite was not run.
- Repository ty, Ruff and formatting pass.

Local, uncommitted research on `research/dual-native-descriptors`, based on
`56dbc32`. Historical issue #396 remains closed. Production files, dependencies,
checker plugins and published artifacts are unchanged.
