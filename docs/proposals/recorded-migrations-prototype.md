# Recorded-state migration prototype (#477)

Status: **experimental, incomplete, not ready for production or merge**.

This implements the first vertical slices of the design discussed in #475,
replacing the function-only direction in draft #476. The prototype lives in
`snekql.experimental.migrations`; existing migration interfaces are unchanged.
Artifact format 2 is provisional. It replaces the unpublished format-1 prototype;
old packages must be regenerated, and old experimental ledgers have no automatic
upgrade path. Do not delete a real database or its history to work around this. No compatibility or adoption path from another
migration history format is promised.

## The four interfaces

1. `generate(revision, models, backend=..., previous=...)` produces an immutable,
   editable `Draft` against the previous package's recorded managed state.
2. `compile(draft)` checks the route and produces a `Package`. `dump()` and
   `Package.load()` round-trip state, structured changes, frozen SQL, encoded
   scalar bindings, transaction flags, deferred table contractions and a content digest. `package.check(draft)`
   verifies that a supplied current draft still matches its committed artifact.
3. `target.prepare(package)` observes the target without creating history and
   returns an inspectable `Prepared` plan. MariaDB requires the caller to assert
   `schema_writers_excluded=True`; advisory locking cannot enforce that promise.
4. `target.apply(prepared)` checks history and observations under coordination.
   `target.status()` exposes completion or uncertain progress and the number of
   acknowledged execution steps (a SQLite rebuild contains several statements). It is not application readiness verification.

These are library calls, not a new CLI, directory-discovery convention or
application initialization mechanism. Query-only models never acquire migration
ownership merely by being defined. Passing models to `generate` explicitly
selects the desired managed scope. Missing previously managed tables produce an
unresolved deletion-versus-relinquishment decision, not DROP statements.

## Initial creation

```python
from typing import ClassVar

from snekql import sqlite
from snekql.experimental import migrations


class Entry[S = sqlite.Pending](sqlite.Model[S]):
    __row_type__: ClassVar[sqlite.ReadType[Entry[sqlite.Row]]]
    id: sqlite.Col[int] = sqlite.Integer(primary_key=True)
    title: sqlite.Col[str] = sqlite.Text()


first = migrations.compile(
    migrations.generate("001_entries", [Entry], backend="sqlite")
)
# Persist first.dump() as the reviewed deployment artifact.
# Deployment loads this text; it does not import Entry.
```

Explicit application from an async caller:

```python
async with migrations.connect(config) as target:
    plan = await target.prepare(first)
    print(plan.statements)
    result = await target.apply(plan)
    progress = await target.status()
```

The dedicated migration connection does not create tables on entry. It is not a
pooled application Database. For MariaDB, use `mariadb` models, `backend="mariadb"`
and its Config, and pass `schema_writers_excluded=True` to `prepare` only when the
caller has actually arranged exclusion of other schema writers.

## Explicit SQLite adoption

For an existing SQLite table, choose adoption **instead of** the proposed initial
creation. This is an alternative to the initial-creation example above:

```python
adoption = migrations.compile(
    migrations.generate("001_existing", [Entry], backend="sqlite").adopt("entry")
)
async with migrations.connect(config) as target:
    plan = await target.prepare(adoption)  # Read-only; does not stamp history.
    assert plan.statements == ()
    await target.apply(plan)  # Revalidates under the SQLite writer lock.
```

`Draft.adopt(*table_names)` replaces exactly one proposed creation per distinct
name with `AdoptTable`; missing or duplicate choices are rejected. Names alone
are not evidence. Preparation requires an actual table, matching column and
constraint declarations, table storage options, and declared indexes. Extra
columns, defaults, constraints, indexes and triggers on the adopted table stop
this first slice—even with `preserve_unmanaged=True`. Diagnostics identify the
mismatch category and affected column/constraint names without printing default
values. No table is created as a fallback when adoption fails.

This is a bounded declaration comparison, not a general SQL equivalence parser:
ordinary bare/quoted column-name spellings and column ordering are supported;
unknown renderings or other equivalent declaration arrangements may be rejected.
Virtual tables remain unsupported. MariaDB adoption is explicitly rejected during
compilation until a backend-specific proof is implemented.

Application checks the claim and the reviewed catalog again before recording
history. Adoption emits no application SQL by itself; it can precede supported
SQLite data changes in the same atomic package. A failed backfill rolls back both
data work and the ownership record. Later revisions can expand or contract the
adopted table through the usual recorded-state workflow. Declare the **existing**
structure for adoption; do not present a future desired shape and assume missing
columns will be created. A later revision can explicitly re-adopt a relinquished
matching table, but same-route ownership cycles are rejected.

Adoption does not validate existing rows against Python codecs or application
rules, certify readiness, import another tool's history, or coordinate an external
schema owner. Arrange any cross-system cutover separately. It also does not disable
subsequent catalog-drift checks. Query models remain independent of migration
ownership; applications can continue querying without adopting their tables.

## Draft first, then write the backfill

After adding an unconstrained nullable `note` column to the desired model (shown
here as `EntryWithNote`), generate against the first package. Neither package
needs to have been applied to generate the next one:

```python
draft = migrations.generate(
    "002_note", [EntryWithNote], backend="sqlite", previous=first
)
draft = draft.then(migrations.Checkpoint(name="backfill"))
source = migrations.contract_source(draft, point="backfill", table="entry")
```

The returned source declares a static `Historical` query model and a
`CONTRACT_DIGEST`. Save it as a developer-owned module, for example
`backfill_contract.py`. It carries no application imports, methods, Python-side
defaults or validation hooks. It is a query contract, not a schema-creation model.
Only supported built-in scalar contracts are emitted; custom codecs and names
that cannot be represented safely are rejected rather than mapped to guessed
Python types.

Then author the data change using those declarations:

```python
from backfill_contract import CONTRACT_DIGEST, Historical

change = migrations.DataChange.from_query(
    sqlite.update(Historical)
    .set(Historical.note.to("reviewed"))
    .where(Historical.note.is_null()),
    checkpoint="backfill",
    contract_digest=CONTRACT_DIGEST,
)
completed = draft.then(change)
second = migrations.compile(completed)
```

The resulting package contains the encoded parameters and SQL, not the query
object or the generated module. An integration test deletes the generated module
and draft, then deploys the JSON packages in another process. Moving the checkpoint
or changing its schema makes the old contract digest invalid during compilation.
The digest is author-supplied provenance, not proof that arbitrary SQL references
only that contract. Typed query authoring remains important.

Packages are trusted executable inputs and may contain sensitive bound values.
Their hashes detect accidental changes; they are not signatures or a sandbox.
Do not modify generated SQL, fingerprints or state by hand. Recompile the draft.
A deployed package alone cannot detect edits to a separate authoring file it has
not been given. CI can explicitly supply the current draft to `package.check(draft)`;
file discovery and general authoring-file freshness checks remain unimplemented.

## Explicit whole-table relinquishment

Omitting a previously managed table remains an unresolved decision. To stop
managing it **without deleting or rebuilding it**, resolve that named decision:

```python
# Following the completed second package above; retain other managed models in
# this list when only one table is being relinquished.
handoff = migrations.compile(
    migrations.generate("003_handoff", [], backend="sqlite", previous=second).resolve(
        migrations.RelinquishTable(table_name="entry")
    )
)
assert handoff.statements == ()
# Prepare/review/apply normally. This still records a migration, not a silent stamp.
```

`RelinquishTable` removes the table from subsequent **managed** state snapshots
without emitting application SQL. It leaves the physical table, indexes,
constraints, triggers, dependent views and rows alone. Application query models
remain usable; they do not need to disappear when migration ownership ends.
Earlier historical query declarations remain available. New generated managed
contracts omit the relinquished table, and a backfill cannot be moved across the
handoff while retaining its old checkpoint digest.

Relinquishment does not mean deletion. Later managed operations on that table
are rejected, and a CREATE cannot reclaim it within the same route. A later
revision that includes it again encounters the existing-object adoption guard.
SQLite adoption/re-adoption is available only for the bounded matching-table case
above. MariaDB adoption, column-level relinquishment, DROP TABLE, registering a
new external owner and coordinating another migration system are **not implemented**.
This is a journaled end to this chain's managed claim, not a cross-system transfer.

Review `plan.package.draft.operations` and the before/target states, not just
`plan.statements`: empty SQL can still represent an ownership change. The change
takes effect as a completed package; zero execution statements do not imply completion. SQLite records it atomically. MariaDB can retain an uncertain
zero-step package if the completion receipt fails; inspect and explicitly finish
it through recovery rather than stamping history or replaying user SQL.

The whole-catalog drift guard remains in place. Relinquishment does not silently
ignore later external changes or certify dependencies/readiness after those
changes. SQLite's existing explicit `preserve_unmanaged=True` review can validate
remaining managed facts; this is not a new general scoped-drift policy. Review and
coordination requirements apply even to a package containing only relinquishment.

## Explicit contraction and preservation

After backfilling `role`, generate a final model without `is_admin` and with
non-nullable `role`. Missing columns do **not** authorize deletion:

```python
draft = migrations.generate(
    "003_role_required",
    [AccountWithRequiredRole],
    backend="sqlite",
    previous=expanded_and_backfilled,
)
contracted = migrations.compile(
    draft.resolve(
        migrations.DropColumn(table_name="account", column_name="is_admin"),
    )
)
```

Generation proposes `RequireNotNull`; `resolve` authorizes only the named removal.
Other unresolved decisions remain unresolved. Compilation checks the exact final
state, and named query contracts interpret both operations. Adjacent contractions
of one table are grouped. MariaDB emits one ALTER; SQLite records a deferred
contraction (`None` in `package.statements`, with details in `package.contractions`).
The executable SQL is available in `prepared.statements` after target observation.
`prepared.steps` also exposes required-column checks, row-count checks, sequence
preservation, and trigger validation. Re-preparing a completed package returns no
execution steps.

SQLite preparation retains observed definitions rather than reconstructing the
whole table from application models. By default, unexpected catalog changes still
stop preparation. The explicit `preserve_unmanaged=True` option accepts additional
unmanaged structure only after checking every recorded managed column, table
constraint, storage suffix, and index. It does not authorize changes to managed
definitions or adopt existing tables. Rebuilds preserve extra/generated columns,
ordinary hidden row identity where accessible, indexes, triggers, dependent views,
and AUTOINCREMENT high-water state. Single-quoted trigger event columns
(`UPDATE OF 'column'`) and qualified fields such as `NEW.'column'` are recognized
as dependencies rather than string literals. Genuine literal labels remain
unchanged. Keyword-like trigger/index names are not interpreted as SQL grammar;
this includes preserving a unique index named `"on"` across same-package creation
and rebuilding. These are bounded recognizers, not complete SQL dependency
resolution; transaction-time checks and the documented unsupported cases remain
important. Checks and collations stay in their original
column/table definitions. STRICT and recorded WITHOUT ROWID storage are retained;
the latter is exercised using an explicitly authored physical snapshot, not a new
model-generator option.

Foreign-key enforcement is disabled **before** the writer transaction and restored
on exit. This prevents DROP TABLE from cascading into referencing rows. Required
values and copy row counts are checked, and foreign keys, views and trigger
programs are validated before commit. Sequence values are read under the writer
lock, not frozen at preparation time. Unknown or conflicting dependencies stop
execution or roll it back. Dependency scanning is conservative, not a general SQL
parser: references to removed columns and wildcard-dependent views/triggers need
explicit resolution. Complex SQL, custom functions, virtual tables, and other
schema features need further characterization before production use.

An explicit route can also combine nullable addition, checkpoint, typed backfills,
required enforcement and removal in one SQLite package. Preparation projects the
earlier structured steps without executing them. Separate expand/backfill/contract
revisions remain useful for application rollout compatibility; completing a
migration does not establish application readiness.

## Bounded MariaDB recovery

Save the original prepared plan before application, for example with
`plan.model_dump_json(indent=2)`; it contains sensitive values just like the package.
The journal binds progress to that plan. After a failure:

```python
assessment = await target.inspect_recovery(plan, schema_writers_excluded=True)
print(assessment.disposition, assessment.explanation)
# Review the evidence and repair any application-data precondition if appropriate.
if assessment.disposition in {"retry_remaining", "finish"}:
    await target.resume(assessment, schema_writers_excluded=True)
```

The caller must actually exclude external schema writers during both assessment
and continuation. Recovery rechecks the evidence under the advisory lock; stale
assessments and edited/different prepared plans are rejected. A different connection
address is a different target identity, even if it ultimately reaches the same data.

Each acknowledgement now records the observed catalog. If the catalog still matches
the last acknowledgement, acknowledged work is skipped and remaining work can be
retried under the supported engine assumptions. A typed UPDATE and its receipt
commit in the same InnoDB transaction. Execution and recovery refuse transactional
data work with non-InnoDB base tables, triggers or stored routines in the database.
Packages remain trusted inputs: this is a claim about supported transactional
database effects, not arbitrary SQL, external functions or exactly-once external
side effects.

### Explicit structural reconciliation

An unacknowledged change is not automatically retryable. Recovery can now report
`reconcile_structural` for **exactly the next grouped required/drop-column
contraction**, when projecting that transition onto the last acknowledged observed
catalog matches the entire current observed catalog. This is more evidence than
matching the desired model or an arbitrary endpoint. Unchanged objects, column
attributes, defaults, indexes and table options must also match. CREATE, ADD,
arbitrary SQL and typed data changes do not receive this proof.

```python
assessment = await target.inspect_recovery(plan, schema_writers_excluded=True)
# These expose (kind, name, SHOW CREATE SQL) records for review.
print(assessment.before_catalog, assessment.observed_catalog)
if assessment.disposition == "reconcile_structural":
    assessment = await target.reconcile(
        assessment,
        reason="Reviewed the exact contracted schema after receipt failure",
        schema_writers_excluded=True,
    )
# Acceptance records evidence only; it does not execute remaining package steps.
if assessment.disposition in {"retry_remaining", "finish"}:
    await target.resume(assessment, schema_writers_excluded=True)
```

`reconcile` requires a nonempty review reason and rechecks the evidence under the
advisory lock. It atomically advances **one** step and appends a durable acceptance
containing its step number, reason, before/after catalog snapshots and digests,
and rendering profile. Each `Progress` returned by `await target.status()` exposes
`reconciliations`, distinguishing these acceptances from ordinary execution
acknowledgements. It is
acceptance of a supported structural postcondition, **not proof that arbitrary
application data transformations ran**, an authenticated reviewer identity, or
permission to skip arbitrary steps. Forged dispositions, stale reviews, and
concurrent duplicate acceptance are rejected. After a lost connection, inspect
status/evidence again instead of repeating an old acceptance request.

Acknowledged observations retain the server version, session SQL mode, and
SHOW CREATE quoting setting. A changed rendering profile blocks recovery rather
than treating identical SQL text under different interpretation rules as proof.
Structural reconciliation currently declines NO_BACKSLASH_ESCAPES rendering.
AUTO_INCREMENT normalization omits only the actual unquoted table-option counter;
matching text in comments/defaults remains significant. The ledger stores complete
observations and acceptance evidence (LONGTEXT on MariaDB); older experimental
ledger layouts are explicitly rejected, with no automatic conversion.

The schema proof remains deliberately bounded and uses the migration account's
visible catalog. Complete metadata visibility is an operational prerequisite, not
a privilege audit implemented by this prototype. Non-InnoDB tables, visible
triggers and stored routines still block this recovery path. Unknown renderings,
unsupported transitions and additional drift stay `ambiguous`; there is no
force-accept override. Never delete history or replay uncertain DDL to bypass it.

Native tests cover non-idempotent data recovery, a receipt fault after committed
contraction, unrelated/comment/type drift, changed rendering profiles, competing
reconcilers, and owned-server SIGKILL/restart both while acceptance is blocked on
a journal row lock and after acceptance commits but before package completion.
These exercise rollback and durable acceptance separately. They do not establish
arbitrary in-flight crash behavior or hardware power-loss durability.

### Cancellation and connection lifetime

Cancelling an in-flight MariaDB protocol operation invalidates that `Target`.
Cancellation remains cancellation: cleanup does not replace it with an error from
attempting rollback or advisory-lock release on a broken socket. The connection
is discarded, and subsequent calls reject the closed target. This also applies to
read-only inspection, not just execution/reconciliation. Open a new target and
inspect durable progress before deciding what to do next.

Closing the socket is **not** a server-side statement-cancellation guarantee or
proof that work did not commit. A blocked server operation may finish before the
server notices disconnection and releases its session/advisory locks. DDL or a
commit already sent can still take effect; never infer retry safety from the
cancellation exception. Native tests cover asyncio task cancellation and AnyIO
scope cancellation while acceptance is row-lock blocked, plus cancellation of a
blocked read-only status query. They verify fresh-session inspection and recovery,
not every cancellation/commit window or repeated cancellation during cleanup.

## SQLite identifier handling during comparison and rebuilding

SQLite comparisons fold ASCII letters only: an unquoted reference to `straße`
is not a reference to `strasse`, while `STRAßE` still refers to `straße`. The
bounded adoption/preservation/endpoint comparison retains that distinction.
SQLite bare identifier tokens also retain non-ASCII combining marks, spaces and
symbols rather than splitting them into apparent SQL keywords.

Rebuild classification must preserve data as well as declarations. A column whose
name resembles `CHECK` under Unicode casefold is still a column, and a default
literal resembling `AS` is not generated-column syntax. Even the valid literal
`DEFAULT GENERATED` does not make a column generated: recognition requires the
actual top-level `AS(expression)` clause. Regression tests verify that existing
values survive, rather than being replaced by NULL or defaults during copying.

These fixes do not introduce general SQL equivalence, Unicode normalization of
names, or a new MariaDB identifier-comparison policy. Shared keyword recognition
is ASCII-only; MariaDB identifier-reference comparison and its lexer mode retain
their existing behavior. The overall prototype remains bounded and experimental.

## SQLite engine-checked copy contracts

Prepared rebuild steps record their ordinary copied columns and explicitly
removed columns. Immediately before each rebuild's DDL, under the SQLite writer
transaction, the runner reads `pragma_table_xinfo` and requires every ordinary
source column except authorized removals to appear exactly once in that copy
contract. Generated columns must not appear in the ordinary copy list; both
virtual and stored generated columns remain supported. Unknown hidden-column
classifications, missing columns or a mismatched copy classification stop with
`PackageError`, rather than trusting the same SQL recognizer twice.

This check uses the live source after earlier package steps, not a stale row or
column snapshot taken during preparation. It supplements row-count, dependency,
storage/identity and endpoint checks. By itself the metadata check does not
verify copied values; the separate comparison below checks retained SQL values,
not arbitrary SQL semantics. A valid but unrecognized spelling (such as a leading
BOM retained inside CREATE TABLE text) can therefore require an explicit adapter
instead of being guessed. The whole SQLite package rolls back on rejection.

Older serialized SQLite rebuild plans without the copy contract must be
re-prepared and reviewed. Empty copy metadata is omitted from serialization, so
non-rebuild plans—including MariaDB plans—retain their existing canonical shape
and recovery identity. No ledger or execution-package format upgrade is implied.

## SQLite retained-value comparison

After inserting into the rebuild staging table, and before dropping the source,
the runner compares retained source and destination values inside the same writer
transaction. `typeof` distinguishes SQLite storage classes and explicit BINARY
collation prevents a declared NOCASE collation from hiding text changes. The
projection includes hidden row identity where accessible, or the retained primary
key of a WITHOUT ROWID table. These identities make rows distinct; combined with
the existing equal-row-count check, one-way set difference detects changed or
missing rows without collapsing duplicate application values.

Stored generated values are included, not just ordinary copied columns. A rebuild
must not silently refresh old stored values under a changed expression. Tests
use isolated legacy-schema fixtures to demonstrate both affinity conversion of
text `001` into integer `1` and a stored `A` becoming `a` despite NOCASE. Those
fixtures edit their own schema text solely to reproduce legacy states; this is
not a recommended application migration procedure.

A mismatch raises `PackageError` and rolls back the whole package. The check does
not stringify or hash application values, and errors do not include row contents.
Positive coverage includes NULLs, blobs, embedded-NUL text, large integers,
precise reals, generated values, and hidden identity with a shadowed rowid alias.

Numeric values use SQLite equality, not bitwise floating-point equivalence.
This adds a source/destination scan and SQL set comparison; large or wide tables
remain subject to SQLite statement and resource limits, with failures rolling
back rather than bypassing validation. It checks current SQLite value semantics,
not physical file encoding, historical application behavior, arbitrary external
functions, hardware power-loss durability, or application readiness. It does not
repair earlier committed data loss or introduce MariaDB value verification.

## SQLite managed endpoint validation

Before writing completion evidence or committing, SQLite observes the resulting
catalog and checks the recorded managed endpoint. Managed tables, column/table
constraint declarations, storage options and declared indexes must be present
and match the bounded comparison, including recorded occurrences of repeated
constraint declarations. Unmanaged extras remain outside that claim,
and relinquished tables are not silently re-adopted. The same managed-fact
comparison is used for preservation review and endpoint checking.

Successful SQL calls alone are insufficient. For example, `CREATE INDEX IF NOT
EXISTS` can succeed without creating the intended index if its name is occupied
on another table. Endpoint validation rejects that result. It recognizes that
`IF NOT EXISTS` is an execution guard, not a persistent index property, while
still checking ownership, uniqueness and the indexed declaration.

A mismatch raises `PackageError` identifying a managed-schema postcondition
failure. The entire SQLite package rolls back, including schema/data work and
new history records; earlier committed history remains intact. Existing tests
also exercise successful adoption, contraction, unmanaged preservation and
relinquishment with this check enabled.

This is not general SQL equivalence, row/codec validation, a complete dependency
proof, or application readiness certification. Construction statements remain
trusted executable inputs, not a SQL sandbox. It does not retroactively repair
or re-certify already completed experimental packages. MariaDB does not yet have
this endpoint guard: its implicit-commit DDL needs a separate evidence/recovery
policy, not a promise of SQLite-style rollback.

## Current execution behavior

- SQLite uses a writer transaction for the entire package, including progress
  and completion, including prepared rebuilds.
- MariaDB records `started` durably before operations. DDL can commit implicitly.
  Each typed UPDATE and its acknowledgement run in one transaction; this is not
  a single transaction spanning several UPDATEs or DDL.
- An acknowledgement is persisted after each successful execution step. DDL may have
  committed before an acknowledgement was written. `acknowledged_steps` is a
  lower bound on acknowledged work, not proof later work had no effect. Explicit
  structural acceptances also advance this count and remain separately auditable.
- Incomplete MariaDB progress blocks further application, including requests to
  reapply an earlier completed revision. Only explicitly reviewed, proven recovery
  can resume. Exact supported contraction postconditions can be explicitly
  reconciled; other ambiguous DDL remains blocked.
- Competing runners reread history after obtaining SQLite writer coordination or
  MariaDB advisory coordination. The predecessor is an execution-package digest,
  so packages generated from divergent predecessors cannot silently form forks.
- Preparations are bound to a target identity and observed catalog digest.
  Separate SQLite `:memory:` connections have different identities.
- The predecessor's managed-state digest is checked independently of its revision
  and execution identity, so an edited draft cannot invent its starting contract.
  The last accepted observed catalog is recorded separately from that declarative
  managed state. Re-preparing after drift does not silently accept it. Matching
  untracked tables require explicit adoption. The bounded SQLite path above is
  supported; matching names alone never authorize it, and MariaDB adoption remains
  unsupported.

The catalog guard is deliberately conservative: it currently includes unrelated
objects in the observed catalog too. SQLite reads schema records; MariaDB reads
SHOW CREATE output for tables/views, excluding changing AUTO_INCREMENT counters.
This is not complete MariaDB trigger/routine/privilege observation. It is not a
full reconstruction blueprint. Schema-writer exclusion is a caller responsibility
on MariaDB, including the period between preparation and application.

## Implemented versus still required

| Scenario | Current evidence / limitation |
| --- | --- |
| Greenfield creation | Executed on SQLite and MariaDB, including repeat application |
| Consecutive unapplied revisions | Generated against recorded state without a database |
| Nullable addition | Executes while preserving populated rows |
| Typed intermediate backfill | Generated source type-checks; typed UPDATE and scalar bindings execute on both engines; is_admin-to-nullable-role expand/backfill tested |
| Route edited after backfill authoring | Stale checkpoint digest rejected |
| Historical application modules removed | JSON-only deployment works in a fresh process |
| Package corruption / unknown version | Rejected; no format-upgrade implementation yet |
| Competing runners | Native tests show one execution and one already-applied outcome |
| Interrupted MariaDB DDL | Skip acknowledged work after restart; exact contraction postconditions require explicit durable reconciliation; other changed DDL remains ambiguous |
| Whole-table relinquishment | Explicit metadata-only change; physical objects/data and query mapping remain intact |
| SQLite adoption / re-adoption | Explicit matching-table claim, rechecked under the writer lock; extensions/triggers and unknown renderings are rejected |
| MariaDB adoption / cross-system transfer | Not implemented; SQLite adoption does not certify another backend or another manager's history |
| SQLite preservation-sensitive rebuild | Bounded observed-definition rebuild; referencing rows, extras, generated columns, index/trigger/view behavior, storage and sequence state tested |
| Required-column enforcement and explicit column removal | Executed on both engines; populated full SQLite expand/backfill/contract route tested; rename and dependent-object changes remain unsupported |
| Long resumable backfill | Unimplemented; only individual bounded UPDATE operations |
| General custom SQL / Python | Unimplemented; typed UPDATE output only |
| Historical codec/compiler evolution | Scalar-only declarations; reader revalidates version-2 operations; no long-term compatibility promise |
| Source freshness / collaboration tooling | No file-management or automatic semantic rebase interface |

The dedicated connection currently uses path/credentials/TLS and SQLite busy
wait configuration, not the complete application runtime pool, telemetry,
deadline, durability and cancellation policy. In-flight server loss and repeated
cancellation cleanup require additional work before this can replace the mature
runtime. A complete partial-ownership/preservation representation must replace
the conservative catalog guard before brownfield support is claimed.

## Validation

Tests live in `tests/experimental/`. Use `snektest`, real backend servers, and
`ty`; tests do not substitute mock SQL engines. Native process-kill tests own
separate data directories and never kill the session-wide shared server.

```sh
PYTHON_CONTEXT_AWARE_WARNINGS=1 uv run snektest tests/experimental
uv run ty check
uv run ruff check .
uv run ruff format --check .
```

Do not run two suite invocations concurrently if both use the existing shared
`tests.helpers.provide_mariadb_server` data directory.
