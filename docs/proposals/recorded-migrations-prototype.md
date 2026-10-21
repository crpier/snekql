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
and AUTOINCREMENT high-water state. Checks and collations stay in their original
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
  untracked tables require explicit adoption; adoption is not implemented yet.

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
| Brownfield ownership transfer | Unresolved/rejected, not implemented |
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
