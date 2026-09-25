# Dual metadata finalization

Local continuation of the model-interface research associated with issue #396.
Baseline: main `56dbc32`, after callable FK binding landed in #411.
Production and earlier research implementations are unchanged.

## Findings

The earlier explicit `Schema(...)` phase is **not required by dual classes**.
Inputs can validate from their own declarations before a table exists. SQL metadata
can bind lazily when a query or scaffold first needs it.

A two-phase graph finalizer also supports mutually referencing tables, provided
column storage ultimately comes from concrete declarations. A relationship cycle
and a storage-derivation cycle are different problems.

This study found and corrected two prototype defects:

- Finalizing an extended table first could make the base input use the extension's
  defaults. Input construction must not borrow whichever table binding came first.
- Caching an entire compilation graph on every member accidentally made
  `Schema(Parent)` include an unrelated child after `Schema(Child)`. Each schema
  now selects only its roots and their outbound dependencies.

These are fixes to research code, not defects attributed to production snekql.

## Start here

- [examples.py](examples.py): Department and Employee refer to one another.
- [tour.py](tour.py): commands constructed before schema access, native
  migrate/verify, and an FK cascade followed by fetched-model materialization.
- [interface.py](interface.py): independent constructor validation and lazy
  two-phase graph binding. Reuses the earlier storage declarations and small query
  adapter rather than designing another query language.
- [current.py](current.py), [test_current.py](test_current.py): current-main controls.
- [test_mariadb.py](test_mariadb.py): actual MariaDB execution and its DDL limitation.

```sh
bash scratchpad/dual_finalization/run.sh
# SQLite tour alone:
uv run python -m scratchpad.dual_finalization.tour
```

Tour output:

```text
[('Research', 20)]
```

The complete runner needs the existing MariaDB tools and drivers. The temporary
server uses `.git/dual-finalization/mariadb` and a local Unix socket, with no TCP
listener. Tests manage its lifetime.

## Declaration shape

The full models use familiar fields, defaults, generated IDs, and local FKs:

```python
class NewDepartment(Record):
    id: Field[int | Omitted] = stored(
        sqlite.Integer(primary_key=True, auto_increment=True), default=OMIT
    )
    name: Field[str] = stored(sqlite.Text())
    manager_id: ForeignField[Employee, int | None] = foreign(
        lambda: Employee.id,
        default=None,
        on_update="CASCADE",
        on_delete="SET NULL",
    )


class Department(NewDepartment, ReadRow):
    table_name = "departments"
    id: Field[int] = required()
    create = insert_using(NewDepartment)
```

Employee has the opposite FK to Department. Neither input constructor needs the
other table's metadata. Both generated ID refinements preserve their original
storage declarations.

```python
command = Department.create(name="Research")
query = select(Department).all()
```

The command validates values without resolving foreign callbacks. The query binds
metadata on first use. `Schema(Department)` is a read-only selection of definitions
for scaffold/verify and this study's execution bridge. It does not configure the
input constructor or mutate a table registry.

`stored(...)` remains adapter spelling, not a proposed public wrapper around every
Column Type constructor. Likewise, the MariaDB study uses
`class Input(Record, backend="mariadb")`; a production Backend Namespace should
supply that family without another public model coordinate.

## Metadata ownership and phases

### At declaration

The input's logical annotations, defaults, and immutable storage declarations are
its own facts. Refinement removes Omitted and changes constructor presence while
retaining the storage declaration. Local nullable/primary-key assertions are
checked without traversing relationships.

Table names, field maps, schema policies, and backend selection freeze before first
metadata use. Each Fetched Model has one Definition plus a separate memoized
binding state. Schema selections share that definition, not a mutable registration
slot on the input.

### At value construction

Each class validates against its own logical contract and defaults. A base input
cannot inherit an extended table's defaults through registration order.

This adapter mirrors native strict logical validation, including bool-as-int
handling, the JSON payload marker, and the native NULL shortcut. A control caught
a subtle difference: running Pydantic directly on None invokes an AfterValidator,
where native nullable-column construction bypasses that validator. The adapter now
preserves native behavior rather than silently changing it.

Fetched constructors still require refined generated fields. SQL insertion may omit
them. Client factories run once for a command and do not run again during
materialization.

### At first SQL metadata use

The finalizer:

1. Resolves the reachable relationship graph, memoizing each target callback.
2. Resolves column storage dependencies independently of table dependencies.
3. Creates unpublished native models with columns, indexes, and CHECKs.
4. Binds physical FKs after all target columns and candidate keys exist.
5. Runs native scaffold validation before publishing the completed graph.

This uses private `ModelMeta._bind_foreign_keys` and assigns normalized constraints
to unpublished native classes. It does not replace native FK validation or edit
production code. A production implementation needs a supported internal finalizer,
not this private-class adapter technique.

Schemas retain native descriptor identity across repeated selections. Parents do
not acquire reverse dependencies merely because a child was finalized first.
Acyclic dependency ordering puts referenced tables first in scaffold output.

## Relationship cycles

| Case | Result |
| --- | --- |
| A FK to B.id, B FK to A.id, both IDs concrete | Metadata finalizes; SQLite migration/verify and cascade execute |
| Composite FKs in both directions | SQLite migration/verify and same-parent-row enforcement execute |
| A column derives storage from B's FK, which derives from A's FK | Rejected: no concrete storage root |
| MariaDB acyclic graph selected from its child | Scaffold creates dependencies first and verifies |
| MariaDB cyclic graph, unchanged CREATE-only scaffold | Migration rejects the forward FK |
| MariaDB cyclic graph, reviewed CREATE plus ALTER migration | Verification and update cascade execute |

The MariaDB distinction matters. Supporting the metadata graph does not make a
CREATE-only scaffold an automatic migration planner. The study does not disable
FK checks, generate ALTER statements, or silently omit a physical constraint.

## Failure and concurrency behavior

The adapter reuses main's synchronous `_OnceBinding` coordinator:

- A failed target callback is not retried on the next metadata access.
- A failed graph publishes no partially finalized dependent model.
- A valid independent dependency remains usable after its invalid child fails.
- Reentrant metadata use fails. Even if the callback catches that error and returns
  a column, the outer graph must not publish success.
- Concurrent first use in two worker threads resolves the callback once and yields
  the same scaffold.
- Reassigning a callback's captured variable after binding does not retarget the FK.

The swallowed-reentry case initially passed incorrectly. The adapter now records
failed binding accesses and checks every participating binding before publication.
Callbacks are still required to be pure. These tests do not make callbacks a
sandbox, establish general asynchronous safety, or cover every thread/interrupt
interleaving.

## What current main already does

Main added callable FK targets after the previous study. The native control now
constructs a nullable self-FK model and scaffolds it without a public registration
step. Lazy target binding is therefore **not a dual-class advantage**.

The tested original declaration spelling for a mutually referencing pair fails
while creating the first class because its FK annotation names a table that does
not exist yet. The graph adapter can defer that target-model check. This does not
prove every possible native cyclic-schema spelling is impossible.

Main could adopt graph finalization independently of dual classes. Dual classes
remain valuable for their constructor contracts, not because SQL requires two
Python classes or because lazy binding is unique to them.

The native `Current[sqlite.Fetched]()` control still type-checks its ID as int while
holding PENDING_GENERATION at runtime. The dual Fetched Model rejects missing
refined generated fields.

## Remaining costs and limitations

- **Typing is not complete declaration validation.** Required FK initializers can
  accept an inconsistent target annotation under ty; wrong refinements and bad
  default domains can also type-check. Runtime guards are still necessary.
- **Backend witnesses are not fully propagated.** A mixed-family Schema type-checks
  but rejects at runtime. This study did not solve the backend-owned descriptor
  interface or specialized public JSON columns.
- **The small query adapter is unchanged.** Its bare-class join can accept an
  unavailable predicate owner through inference widening. Native construction
  rejects that query. Do not replace production query signatures with this adapter.
- **Some declaration errors move later.** Local logical/nullability rules can be
  checked immediately. Target-dependent rules and some storage/default checks wait
  for metadata use. Inputs are value contracts, not proof of a valid database schema.
- **Failed first use is terminal.** Accessing SQL metadata before a forward target
  exists can permanently fail that definition. Value construction deliberately
  avoids triggering that binding.
- **Validation needs a shared implementation.** This prototype mirrors a small part
  of native logical validation and creates TypeAdapters during construction. A real
  redesign should extract/reuse one value-contract implementation. No performance
  claim follows from this adapter.
- **No general inheritance proof.** The registration-order fix demonstrates one
  controlled template-extension case, not arbitrary multiple inheritance or policy
  merging.
- **Private/erased bridge.** Native model generation, private helpers, and Any remain
  research mechanisms. Class metadata can still be bypassed deliberately through
  low-level Python operations. This is not a production hardening audit.

## Recommendation

Keep the input contract independent of table registration. Freeze declarations
when classes are created; bind target-dependent metadata once on first use.
Separate table dependency traversal from column storage derivation.

A public finalization command is not needed just to obtain honest dual
constructors. A schema collection can remain a selection used by explicit schema
operations. If dual classes proceed, the useful internal work is a shared logical
value contract and an immutable table definition with controlled binding state.

Do not conflate that work with a new query language, an automatic migration planner,
or proof of complete production parity.

## Evidence

- **33 isolated ty observations:** 13 capabilities, 13 rejections, seven accepted
  counterexamples. Every challenge has an independently checked clean control.
- `results.json` records source hashes, checker version, and actual diagnostics.
- Red-test logs and the old registration-order counterexample are under
  `.git/dual-finalization/`.
- Python 3.14.2, ty 0.0.77, MariaDB 12.3.2. No new dependencies.

Final validation:

- **31 research tests pass**, including three actual MariaDB cases and the
  two-thread first-use check.
- **1,127 existing fast tests** and **five native callable-FK SQLite runtime
  cases** pass on the new baseline.
- Earlier runners pass unchanged: **57 + 123 + 60 + 158 + 91 typing observations**
  and **58 + 42 + 24 + 53 + 41 research tests**.
- Repository ty, Ruff lint/format, and diff checks pass. **545 files formatted**.
- No full repository integration suite or performance suite was run.

Everything remains local and uncommitted. No issue, PR, or production change was
published for this continuation.
