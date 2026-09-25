# Dual-class typing and native feature parity

Local, uncommitted research on `research/dual-typing-parity`, from `56dbc32`.
Historical context is issue #396, still closed. No production edits, dependencies,
checker plugins, commits, or publication. CPython 3.14.2 and ty 0.0.77.

The comparison is input-first User/UserRow against the current native
Model[State, ReadModel], not the class-body result-witness shim. Nesting is dropped.
Queries carry the most weight. Direct fetched construction remains secondary.

## Conclusion

**Dual classes remain a viable candidate.** I found no typing barrier preventing
the investigated native query features from working with dual models. Reusing
native query types and compilation was enough to demonstrate most missing
operations without building another query implementation.

The significant contract conflict is narrower: **UserRow cannot remain a subtype
of User while a parameter annotated User statically excludes UserRow.** That
includes an input-accepting insertion helper. Native lifecycle types can reject
fetched-row insertion; the inherited dual design currently accepts it. Keeping
that exclusion would require another operation-specific contract, a changed class
relationship, or a runtime check. Returning Never from an overload does not by
itself prohibit calling it.

This is not a full feature-parity certification. [MATRIX.md](MATRIX.md) distinguishes
executed reuse, existing capabilities, incomplete adapters, and uninvestigated
integration. The bridge has explicit counterexamples and is not a proposed public
interface.

## What gets easier or stronger

### State-neutral methods and generic value helpers

```python
# Dual: both User and UserRow satisfy this annotation.
def label(user: User) -> str:
    return user.nickname or user.email


# Current: bare User means User[Pending].
def label(user: User[Pending] | User[Fetched]) -> str:
    return user.nickname or user.email
```

An ordinary unannotated self works in the dual input class, inherited by the row.
The tested native generic class cannot read even its ordinary email descriptor
through plain self under ty. Its explicit union-self method works.

A generic helper bounded by the dual input type can read those attributes and
accept rows. The tested native User[State]-style constrained state helper
cannot access the descriptors. That is a current descriptor/checker limitation,
not proof that lifecycle generics could never support it. A read-only structural
Contact protocol works with both designs and is included as a counterweight.

### Runtime narrowing corresponds to distinct value classes

```python
if isinstance(value, UserRow):
    assert_type(value.user_id, UserId)
```

The dual check works. The corresponding native isinstance(value, User[Fetched])
is accepted by this ty version but raises TypeError at runtime. An unspecialized
User check cannot distinguish its two lifecycle states. A separate native state
guard could provide that operation, but ordinary Python class discrimination does
not provide it today.

A complete dual row is not evidence that the database contains that row.

### Sources and values are harder to confuse

The existing dual adapter rejects input classes, input columns, and row instances
as SELECT sources. Current native select accepts instances and specialized model
classes statically, then rejects them at runtime. These checks can also be improved
in the native interface; separate classes are not the only possible repair.

Both reject the tested wrong IDs, FK targets, predicate owners, and backend families.
Ordinary scalar/model results are precise in both.

### A row witness gets a useful runtime backstop

Both designs accept an incorrect result-class declaration under ty. The dual pair
validator rejects an unrelated row before insertion. Current native Model[S, Read]
can declare another model as Read, then return its own instances while the caller
sees the other model type. This has a runtime counterexample in test_limits.py.
Neither design gets a static proof that the declared result link is truthful.

### Complete construction and freezing

Dual requires generated identities when constructing a row and rejects the
omission sentinel there. Current fetched specialization retains the known hole.
Dual also rejects instance assignment under ty; native instances reject it only
at runtime. These are useful differences, but they do not decide the query design.
Inherited Python defaults still make some ordinary row fields optional.

## What dual does not automatically improve

- Owner scope, Backend Family, Query Readiness, nullable joins, and result cardinality
  still need query types. Two value classes do not encode any of these by themselves.
- Named Pydantic projection keywords still have runtime label/domain checks. Merely
  using UserRow does not make arbitrary **bindings statically field-checked.
- Native eq_col tracks only its left owner in the tested calls. Reusing that interface
  preserves the accepted unjoined-right-column counterexample.
- Result-only native Select[Result] helper annotations erase source relationships.
  Direct Transaction calls reject an unjoined projection, but a helper using that
  erased annotation can accept it. The bridge's direct consumer deliberately keeps
  the native scope/reference equality rather than accepting an erased alias.
- Mixed-model bulk input passes checking in both tested signatures; native construction
  rejects it. Equal-looking column types do not prove one table owns a batch.
- Static types do not prove row existence, authorization, SQL-name uniqueness,
  schema agreement, FK candidate keys, or validation of arbitrary runtime input.

## Native query reuse experiment

[bridge.py](bridge.py) binds the existing dual storage declaration to its private
native counterpart. A hidden owner type retains the public row identity through
native query types. The study adds a native Table marker to its row base because
current native result bounds require it. Applications do not hand-author another
schema, and the input/row field declarations still use Col and FKCol.

```python
users = bridge.table(UserRow)
email = bridge.column(UserRow.email)

rows = await bridge_transaction.fetch_all(sqlite.select(users).where(email.eq("Ada")))
assert_type(rows, list[UserRow])
```

The explicit table/column conversions expose the experiment's translation. They
are not a proposed replacement for select(UserRow) and UserRow.email.

The bridge executes model, scalar, tuple, named, joined, optional, bulk, write,
and streamed results. Runtime tests verify actual UserRow/PostRow instances, not
just matching field values. Aliases, arithmetic, CASE, COALESCE, grouping/HAVING,
correlated EXISTS, CTEs, UNION ALL, and recursive CTEs use native operators.
Two matched model scaffolds and 14 SQL/ordered-parameter pairs agree with current
native declarations.

Important failures remain:

1. A native Transaction also accepts the bridge's native query carriers, but returns
   private native objects instead of dual rows. This is an accepted typing/runtime
   mismatch. Production must integrate row materialization into the execution plan
   or enforce a distinct consumer contract. Documentation alone is not a sound fix.
2. Owner identity needs explicit invariance and a source witness. An earlier bare
   type[Row] factory allowed widening the owner to the row base. The corrected
   factory rejects that widening in an isolated caller.
3. Inlining generic column conversion into some native overloads infers Any. Bound
   local columns preserve exact types and reject wrong subquery domains. Both the
   inline failure and its clean bound-column control are retained.
4. The bridge uses a study-global native-to-public class map, phantom casts, and
   double model validation. It is SQLite-only and does not establish concurrency,
   lifecycle cleanup, performance, or complete codec parity.
5. The stream preserves exact batch elements but exposes an async context-manager
   contract, not native ChunkStream nominal identity. Unchecked read/write flags
   return object instead of claiming validated dual rows. Unchecked stream flags,
   raw-statement overloads, and full Transaction configuration are not wrapped.

One smaller observation: single native INSERT RETURNING of the nominal generated
UserId infers int in this control, even with the column prebound. SELECT and UPDATE
RETURNING preserve UserId. The bridge's bound column preserves UserId for insertion
as well. This is an observed descriptor/inference difference, not a claim that only
dual classes could fix the native overload.

## Fixable declaration debt

The old dual Column Type factories return Col[Any], so an invalid Python literal
default can escape ty. [strict_columns.py](strict_columns.py) proves a supplied
Python default can retain its type: wrong literal/default domains reject, valid
nullable defaults and omitted required-field checks work, and runtime construction
still uses existing storage capture.

This is a deliberately small Text experiment. SQL-default markers, factories,
all Column Types, and backend combinations need their own overload work. It is
not a replacement namespace.

Generated fields still need row refinements. Forgetting one passes declaration
checking and fails binding, with Omitted still visible in its inherited type.
Input-class constructor helpers can accept a row subclass that requires more
arguments, then fail constructing it. This is a Python subclass-constructor issue;
we do not elevate general inheritance or fixture convenience into a main criterion.

## Additional query capabilities already demonstrated

The earlier [dual query study](../dual_queries/README.md) was rerun on this baseline.
Its separate query design supports nullable-role tuple projections, ten-slot
variadic projections, and checked positional Python result mapping. The current
native interface deliberately rejects projection LEFT JOIN and more than eight
positional fields. It supports wide named projections, whose keyword bindings are
runtime-checked, and callers can always use checked Python construction after fetch.

Those are possible query-interface improvements with dual models, not benefits
that require dual declarations. The earlier query adapter has different join and
conflict semantics and lacks backend propagation. Do not combine its capability
list with this bridge and call the result one finished implementation.

## Evidence and reproduction

```sh
bash scratchpad/dual_typing_parity/run.sh
```

- **262 isolated typing observations**, with clean controls, exact type assertions,
  challenge-file/line checks, versions, diagnostics, and source hashes in results.json.
  **124 capabilities, 87 rejections, 26 counterexamples, 25 unsupported contracts.**
  These are bounded observations, not a score or a universal safety proof.
- **39 runtime tests** in this study, including actual SQLite and failure controls.
- Matching two-model scaffold and **14 SQL/parameter pairs** in evidence.json.
- Earlier paired tour: 163 original + 225 dual/body observations, 22 source edits,
  and 280 runtime tests including 13 real MariaDB tests. Nesting remains only as a
  historical regression fixture, not a candidate.
- Earlier dual queries: 158 observations/53 tests, plus 91 feature observations/41
  tests. Earlier recursive study: 60 observations/24 tests.
- Native fast suite: **1,127 passed**. No full native integration suite was run.

Start with current.py and dual.py for declarations, helpers.py for shared behavior,
MATRIX.md for coverage, and test_advanced.py for executed query reuse. cases.json
contains the independent callers; check.py regenerates results.json.

## Next decision

Choose whether inserting a complete row should be accepted. If yes, inherited
input-first dual classes are consistent with that policy. If no, settle the
insert-only contract before expanding the implementation.

Then investigate direct native materialization of dual rows and descriptor
integration. The results favor keeping the native query machinery rather than
maintaining a second query builder. They do not yet choose a production model
interface or promise that every existing helper can migrate unchanged.
