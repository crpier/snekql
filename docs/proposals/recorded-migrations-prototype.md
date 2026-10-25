# Recorded-state migration prototype (#477)

Status: **experimental, incomplete, not ready for production or merge**.

This implements the first vertical slices of the design discussed in #475,
replacing the function-only direction in draft #476. The prototype lives in
`snekql.experimental.migrations`; existing migration interfaces are unchanged.
Artifact formats 2 through 8 are provisional. Format 3 adds explicit default
transitions; format 4 adds required-to-nullable relaxation and format 5 adds
named index creation on both backends. Format 6 adds explicit index removal and
bounded replacement; format 7 adds named table CHECKs and format 8 explicitly
removes/replaces them.
Unchanged operation sets retain their existing format. Format 1 remains
unsupported, and old experimental ledgers have no automatic upgrade path. Do not delete a real database or its history to work around this. No compatibility or adoption path from another
migration history format is promised.

## Proposed promotion scope

The [supported-scope proposal](recorded-migrations-supported-scope.md) consolidates the completed
workflow evidence into a finite candidate: selected Linux/CPython/SQLite/maintained MariaDB
qualification, strict SQLite adoption, explicit writer exclusion and bounded recovery.
It recommends execution-contract epochs covering compilation AND deferred preparation, durable
versioned original-plan persistence, runtime deadline/session integration and targeted remaining
qualification before promotion. These are recommendations/gates, not implemented guarantees.
[Proposed ADR 0023](../adr/0023-recorded-migration-ownership-and-execution.md) reconciles existing
decisions without silently superseding them. Consumer interfaces/guides and release remain deferred;
query mapping stays independent of ownership. The next priority is execution/recovery contracts,
not automatic parser expansion. Earlier checkpoint statements below retain their historical scope.

The [prepared-evidence follow-through](recorded-migrations-prepared-evidence-review.md) adds
bounded `Prepared.dump/load` with wire version1 and explicit execution_epoch1 in new plans.
The ORIGINAL plan can cross worker/process/server restart without re-preparation; incompatible
or corrupt persistence refuses, and ledger correlation still distinguishes the applied plan
from a different internally valid file. Historical packages/complete receipts are unchanged.
Package compiler-epoch separation, runtime policies and qualification remain open; this is
not general compiler independence or a portable database backup.

## Workflow-first checkpoint

The [authoring-to-application review](recorded-migrations-workflow-review.md) exercises the
complete model-generated is_admin → role route, actual generated typed historical source,
route editing/freshness, model-free deployment and current typed application on both backends.
It records manual staged-draft composition as the next interface priority, not another parser
slice. Existing safety gates remain; finite scope and the other product objectives are incomplete.

The [combined ownership review](recorded-migrations-ownership-review.md) extends the SAME
role journey with query-only external mappings, strict adoption, preserving rebuild and
non-destructive handoff. Clean re-adoption works; preserved unmanaged additions still refuse
strict re-adoption, and old-flag dependencies block preparation. Partial adoption remains an
explicit scope/design choice, not permission implied by querying or preservation.

The [codec-evolution review](recorded-migrations-evolution-review.md) changes real application
serializer/validator behavior before historical deployment on both backends. Frozen old
bindings stay old; structural verification is not codec/data readiness; an explicit new
representation migration enables current typed reads. Opaque historical provenance remains
unrecorded, and genuine framework compiler/package/ledger evolution remains separate work.

The [framework evolution review](recorded-migrations-framework-evolution-review.md) uses actual
archived writers/readers/runtimes and nine/eleven-column ledgers, preserving supported old
receipts through new format5 index work and refusing unsupported layouts intact. It does not
prove future existing-operation emission ABI, automatic conversion or general downgrade safety.

The [role-recovery workflow review](recorded-migrations-recovery-workflow-review.md) uses real
child-process death/engine lock observations, native server restart, competing operators and
an unrelated application writer. SQLite DELETE rollback/retry differs from durable native
uncertainty/original-plan resume; WAL active death and broader windows remain explicit limits.

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

## Composing model-derived stages

`draft.then(*typed_changes).advance(final_models, removals=(...))` appends one complete
model-derived stage within the SAME revision/predecessor. No caller-constructed State/Draft,
intermediate package or synthetic revision is needed. Resolve existing draft decisions before
advancing; new explicit removals are stage-local via `removals`. Missing/unsupported choices
refuse without mutating the prior draft. Earlier checkpoints/data stay intact and both prefix
and composed route must compile. Defaulted nullable additions still require explicit
`defaulted_additions="leave_null"`. It performs no target IO or implicit ownership/adoption.

The [workflow review](recorded-migrations-workflow-review.md#staged-authoring-improvement)
records the interface and remaining authoring/product work. The original committed packages
remain byte-identical; no format or ledger change follows from this authoring method.

## Frozen input and compiler evolution

`Package.load()` now has a fixed experimental wire-input envelope: at most
8 MiB of UTF-8 (including whitespace), 64 nested JSON containers including the
root, and 100,000 structural units (container openings plus separators outside
strings). The size/structure checks precede JSON container allocation and model
validation. Escaped quotes, backslashes and punctuation inside strings do not
consume structural units. Duplicate decoded object keys are refused at every
level, including differently escaped spellings of the same key.

The version must be an explicit JSON integer `2`, `3`, `4`, `5`, `6`, `7` or `8`; omission, numeric
coercion, unknown versions and omitted operation kinds cannot select a reader/
compiler through defaults or union ordering. `DropCheck` selects format 8;
otherwise `AddCheck` selects format 7;
otherwise `DropIndex` selects format 6;
otherwise `CreateIndex` selects format 5;
otherwise `AllowNull` selects format 4;
otherwise `ChangeDefault` selects format 3, and old operation sets select format 2.
Formats 2–7 refuse `drop_check` and even empty `removed_checks` metadata.
Formats 2–6 refuse `add_check` and even empty `added_checks` metadata.
Formats 2/3/4/5 refuse `drop_index`; formats 2/3/4 refuse `create_index`. Format 2 refuses default operations/metadata. Formats 2/3 refuse relaxation
operations and even an empty `relaxed` contraction field. Empty new fields are
omitted from older routes, preserving their shapes and identities.
The format is a package capability, not a monotonically increasing history
counter: an unchanged operation set can still emit format 2 after a format-8
predecessor. The reader checks the compiler-selected format as part of integrity. The current reader still recompiles the
recorded draft and requires the frozen execution and digest to agree. These
checks do not authenticate publishers or make construction SQL a sandbox.

Three fixed fixtures exported by writer `8ae6024` exercise model-free creation,
nullable addition and required-column contraction through the current reader and SQLite deployment, retaining
literal digests, predecessor identity, rows and a server default. They are not
regenerated by tests. A future compiler change must preserve compatible frozen
execution, retain an explicit old-epoch reader/compiler, or explicitly refuse
that epoch. Do not regenerate old artifacts or rewrite receipts merely to make
a new compiler's output agree. No general historical-compiler or codec
compatibility promise follows from these three fixtures. A separate-process test
also deploys a format-2 creation followed by a format-3 default change without
importing authoring models. An isolated archived `368a44b` reader refuses format 3
explicitly; older readers are not silently granted the new operation.

A second fixed chain from writer `7932c4f` covers format-2 nullable creation and a
format-3 required/default composition. That writer could compile an explicitly
authored `RequireNotNull` + `ChangeDefault` route, but could not generate it
automatically. The current reader deploys its unchanged identities without the
writer's models; learning that generation route requires no new wire format or
compiler reinterpretation. These fixtures are not regenerated by tests.

Existing format-2 shapes and digests remain unchanged. The format marker is not a
verifier-version certificate: accepting an old artifact does not retrospectively
recertify completed history. Ledger-layout refusal and the no-automatic-upgrade
policy remain unchanged; history must not be deleted or stamped as a workaround.

These are **input-decoding limits**, not a whole-program resource guarantee.
Different JSON formatting can consume different wire budgets. The separate SQL
compilation envelope below does not make every in-memory object fit this wire
budget. There is no streaming input, caller limit override or ledger conversion.

### SQL compilation envelope

`compile` additionally admits at most **1 MiB UTF-8 per SQL source** and **4 MiB
aggregate SQL bytes**. Comments, whitespace and repeated occurrences count; shared
Python string objects do not get a discount. Counted input is:

- table construction SQL, index SQL and column definitions in both recorded
  before/target states;
- the same fields in CREATE/adoption operations, replacement/addition column
  definitions, and typed data-change SQL in operations.

This input is checked before semantic route validation and compiler edits, without
first copying the whole draft into a JSON-compatible dictionary. Each emitted
statement is then charged before retention. Each frozen contraction's before/after
table, index and column SQL is also charged before retention: deferred SQLite
rebuilds cannot evade the budget with `None` statement slots. The cumulative total
includes input and output occurrences. Native ALTER SQL is counted as well as its
frozen structural metadata. Within-budget artifacts retain their formats/digests.

Public tests cover exact boundaries, multibyte SQL, aggregate input and output,
intermediate operation SQL, nonexecuted source claims and repeated deferred
rebuilds. Oversized preparation refuses before application tables or history are
created. Fixed format-2/3 artifacts remain unchanged. An isolated `99e9193` writer
accepted a roughly 3 MiB wire artifact containing a SQL source one byte above the
new per-source limit; current loading explicitly refuses it. This is a narrower
admission policy, not an automatic artifact or ledger conversion. Do not rewrite
historical identities or delete history to work around refusal.

This bounds **SQL bytes**, not total compiler work or peak memory. Model generation,
historical declaration generation, already-allocated input objects, operation
counts, parameter values, other metadata (including identifier fields),
tokenizer/parser work, transient intermediate structures, observed catalogs, target-specific prepared SQL, ledger
IO, deadlines and total memory remain separate hardening work. Dumping can still
exceed the JSON envelope through non-SQL data or escaping. Construction SQL remains
trusted executable input, not a sandbox. No readiness or publisher-authenticity
claim follows from either budget.

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

## Native default absence

For a recorded MariaDB column without a DEFAULT clause, endpoint verification now
rejects a native scalar/clock default instead of treating absence as unclaimed.
For nullable columns, native declaration absence and native `DEFAULT NULL` are
accepted: MariaDB normalizes nullable omission to NULL, so this is an **effective
NULL-default claim**, not proof that a clause was explicitly absent in the user's
DDL. For required columns, a native DEFAULT clause does not satisfy absence.
Identity generation and automatic-update clauses remain separately checked facts.

Public native tests show inconsistent CREATE SQL cannot certify either nullable or
required absence: committed DDL remains, the receipt is uncertain, inspection is
ambiguous and resume cannot authorize finish. Ordinary and explicit-NULL nullable
construction still deploy and reapply; omitted nullable inserts produce NULL when
required values are provided. Subsequent out-of-band default drift prevents the
next reviewed revision's preparation without adding history.

This does not promise that omitting a required value always fails: SQL modes,
identity rules and application writes remain separate. It does not backfill data,
by itself prove construction/claim agreement before DDL or retrospectively certify
old completed receipts. Native alteration uses this bounded endpoint policy.

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

## Defaulted additions: explicit existing-row policy

Defaulted additions to an existing table remain unresolved unless generation is
called with `defaulted_additions="leave_null"`. That opt-in applies to new nullable
columns: add an unconstrained column **without** its default, then set the desired
default using `ChangeDefault`. It does not authorize required additions, other
constraints, or any backfill. Existing ordinary nullable additions and creation
behavior are unchanged. Required additions need an explicit nullable stage and
chosen data work before required enforcement.

The policy is frozen as existing ordered operations, not a deployment-time option:
`AddColumn` followed by `ChangeDefault`. Format 3 already represents that route;
no new operation, reader field or ledger conversion is introduced. An actual archived
`9795442` reader loads the new SQLite and MariaDB artifacts byte-for-byte unchanged,
and deploys the SQLite route without importing authoring models. Existing historical
fixture identities remain unchanged. This demonstrates that bounded compatibility,
not arbitrary compiler/codec evolution.

Old rows receive SQL NULL, not the scalar/text/clock default. Future omitted-value
writes after completion use the requested default; explicit NULL stays NULL. Integer,
encoded text (including DEFAULT/quotes/backslash/NUL/Unicode), explicit NULL and clock
routes cover both backends, including multiple added columns. A counterfactual that
puts DEFAULT 7 directly on native ADD fails the old-row assertion despite reaching
the expected endpoint schema: schema proof alone does not establish this data policy.

SQLite's ADD and subsequent rebuild share the writer transaction with later data
work. A conflicting UPDATE rolls back the column, rebuild and new receipt. After
explicit row correction, the original plan succeeds while preserving an unmanaged
blob/default, index, view and insert-trigger behavior; rebuilding does not fire the
application insert trigger.

MariaDB has separate durable ADD and default steps, **not an atomic multi-step schema
transition**. The policy concerns rows present at ADD, not a row snapshot at prepare.
Application inserts between ADD and SET DEFAULT may also receive NULL; schema-writer
exclusion is not an application-write pause. Rollout compatibility remains the caller's
responsibility. A lost default receipt after acknowledged ADD remains ambiguous and
cannot authorize resume. A test explicitly restores the default-free acknowledged
schema, then resumes only the default step without repeating ADD. That operator
restoration is not automatic repair or a general recovery recipe.

This addition policy does not enable fill-with-default, a required-addition shortcut
or new default-aware structural reconciliation. Relaxation has its own operation below.

## MariaDB default alterations

`generate` and explicit `ChangeDefault` now support setting, changing and removing
bounded native defaults. Compilation validates the existing finite literal/clock
language and requires every non-default declaration byte and recorded column fact
to remain unchanged. SQL lexer comments in column sources are refused: extracting
a line-comment-bearing default into a comma-separated ALTER could swallow later
clauses. This is distinct from a SQL `COMMENT 'text'` column attribute, which is
not a lexer comment. Arbitrary expression equivalence remains unsupported.

Default-only groups emit `ALTER TABLE ... ALTER COLUMN ... SET DEFAULT ...` or
`DROP DEFAULT`, not a whole-column MODIFY. Existing rows and explicit NULLs are not
backfilled. Future omitted-value inserts are tested separately. Nullable explicit
NULL and removal have distinct recorded operations, while native endpoint proof
accepts their effective NULL equivalence. Required absence does not promise omitted
writes fail in every SQL mode; a strict-session test demonstrates removal under
that explicit policy.

Generation can combine nullable-to-required enforcement with a default transition.
That group uses the existing required-column MODIFY route with the final definition,
not a second default clause for the same column. Existing NULLs refuse before new
history/DDL; an explicit data correction allows retrying the original reviewed
plan. This is not default-driven backfill; nullable relaxation is a separate operation.

Frozen routes cover integer set/change/remove, NULL, encoded text with quotes,
backslashes/NUL/Unicode, and parameterized DATETIME clocks. A separate process
loads only packages and connectivity, deploys the chain and relinquishes ownership
without deleting the table or importing authoring models. Format 3 already carries
the operation and contraction metadata; old operation sets retain format 2. An
actual archived `a650a3b` reader refuses native format-3 default transitions with its
SQLite-only capability error. Existing fixed SQLite artifacts retain identity.

Acknowledged native ALTER work can precede a failed transactional UPDATE. Reconnected
recovery refuses catalog drift, and after explicit data correction resumes only
unacknowledged work; a prior non-idempotent increment is not replayed. **Lost default
DDL receipts remain ambiguous.** The older full-catalog contraction projection
proves require/drop only and now refuses any contraction carrying default changes.
A regression demonstrates that matching only NOT NULL must not authorize acceptance
of the wrong default. Even a correct changed endpoint is not automatically a receipt
or a supported structural reconciliation. Default-aware structural reconciliation
remains work; there is no implicit repair, replay authorization from partial evidence,
ledger conversion or retrospective certification.

## SQLite default-only alterations

`generate` now recognizes an existing column whose only change is its SQL DEFAULT
clause and emits `ChangeDefault(table_name=..., column=...)`. The replacement
`ColumnState` is frozen authoring input, not a live model. It can set, change or
remove a default. Compilation requires unchanged non-default declaration text,
name, storage, nullability and query-type claims; duplicate, empty or unbalanced
DEFAULT clauses are refused. Scalar/signed and parenthesized expressions are
recognized through token spans, not arbitrary expression equivalence.

The operation joins the existing grouped SQLite rebuild machinery. Preparation
replaces only the selected managed definition, retains observed unmanaged
structure, and checks the recorded source. Execution checks copied values and
identities before dropping the source, verifies the complete recorded endpoint,
and commits schema/data/history atomically. A default change is not a backfill:
existing values, including SQL NULLs, are copied unchanged. Removing a default is
an explicit **declaration-absence claim** in SQLite, not an inference from a
nullable column's omitted-value behavior. MariaDB uses the bounded effective-default policy above and the targeted
alteration route below.

Public routes cover ordinary integer set/change/remove, explicit NULL versus
absence, signed defaults and encoded text with quotes, punctuation, NUL and
Unicode. They verify future omitted-value inserts separately from preserved old
rows. Another route preserves an unmanaged blob column/default, index, view and
insert trigger; copying does not fire the application insert trigger. A later
typed data-step failure rolls the default rebuild, data and new receipt back;
reconnecting and retrying the original plan after application-data correction
then succeeds. These are not power-loss or every interruption-window proofs.

The operation changes a SQL declaration; it does not override engine identity
allocation or prove clock, codec or session semantics. Generation can also compose
SQLite nullable-to-required enforcement followed by a default set/change/remove.
These existing operations share one checked rebuild; the default never repairs
existing NULLs implicitly. NULLs cause refusal without schema/data/history changes;
after explicit application-data correction the original plan can be retried.
Alternatively, an explicitly authored checkpoint and typed backfill can precede
the generated operations in the same atomic package. Tests distinguish that
chosen data-fill policy from preservation of existing non-NULL values and future
insertion defaults. Separate routes above cover native defaults and explicit
nullable defaulted additions; relaxation is described below. No ledger upgrade or
retrospective recertification is introduced. User guides remain deferred.

## Named index additions

`CreateIndex(table_name=..., sql=...)` creates a new named index on an already
managed table. Generation derives appended ordinary index declarations. Removal
and replacement require the separate authorization below; arbitrary reordering of
existing recorded declarations remains unresolved. The
operation does not rebuild rows or infer ownership of an existing physical index.

The bounded grammar is unconditional `CREATE [UNIQUE] INDEX`, quoted names, the
exact recorded owner, and a nonempty comma-separated list of whole managed columns.
Existing recorded indexes must also fit this grammar for addition. Expressions,
prefix lengths, explicit directions/collations, predicates, options, conditional
`IF NOT EXISTS`, lexer comments and extra statements require an adapter. ASCII-case
colliding recorded names are refused. This is not a full SQL parser or universal
preflight: engine name collisions, permissions, data and engine limits may still
refuse execution. Unconditional CREATE cannot silently adopt an existing index.

SQLite unique-index failure on existing duplicates rolls back the receipt and
leaves rows unchanged; explicit data correction permits the original prepared-plan
retry. An explicitly ordered index-then-relaxation route projects the new index
through the existing rebuild, retaining an unmanaged BLOB/default/index/view/trigger
without firing the insert trigger during copying. This is not new deletion authority.

Native endpoint checks prove the listed index facts. Missing-index drift blocks a
subsequent route. An acknowledged CREATE followed by a failed typed UPDATE resumes
the UPDATE after explicit data correction, not CREATE. A lost CREATE receipt remains
ambiguous even when the correct index is present: no replay, implicit adoption or
structural reconciliation is authorized. Application writes are not paused by schema
writer exclusion; concurrent writes and engine-specific build behavior remain caller
rollout concerns, not an atomic native package promise.

**Format 5** introduces `create_index`, with no new contraction field or ledger
layout. Formats 2/3/4 explicitly refuse the operation. Actual archived reader
`c27bf4d` refuses both new backend artifacts; current reading retains the preceding
format-4 artifacts byte-for-byte and the fixed format-2/3 identities. A model-free
SQLite child deploys format 2 then 5, preserves old rows/defaults and demonstrates
unique enforcement. No general compatibility or retrospective certification claim.

Explicit removal/replacement adds separate authorization and negative postconditions
below. Named CHECK additions and explicit bounded removal/replacement are supported separately.

## Explicit index removal and replacement

Generation leaves an index-removal decision unresolved. Authorize it with
`draft.resolve(DropIndex(table_name=..., index_name=...))`; compilation cannot
silently remove uniqueness or infer authority from a missing target declaration.
The exact name must identify one explicitly recorded bounded secondary index, not
an unowned/implicit index or primary-key constraint. Index deletions are placed
before dependent generated alterations; column deletions retain their separate
explicit decision. Editing a route still requires regenerating checkpoint contracts.

Replacement composes an authorized DROP with ordinary CREATE, including a same-name
uniqueness change. The finite declaration grammar remains that of CreateIndex.
The current ordering is surviving recorded declarations followed by new declarations;
replacing an earlier index among several may therefore require explicit declaration
reordering/review, otherwise generation remains unresolved. This is not a general
index-diff, reorder or constraint-rewrite facility.

Preparation conservatively checks observed catalog SQL, before/target table sources
and intermediate CreateTable/AdoptTable sources. Possible FK-adjacent table and
stored-object index-name dependencies require an adapter. A newly created child
cannot evade this check by relinquishing ownership before dropping its parent's
index. SQLite legacy single-quoted REFERENCES and INDEXED BY views are covered.
Native removal additionally requires `foreign_key_checks=1` and no visible opaque
application triggers/routines; it does not silently change session policy. These
checks recur at application/recovery boundaries. This is not a complete dependency
graph, cross-schema/application-query proof, privilege audit or SQL sandbox.

SQLite DROP projection removes the index from subsequent rebuild planning rather
than recreating it. An explicit negative endpoint check proves absence before commit;
positive subset verification alone is insufficient. A failing same-name unique
replacement rolls back DROP, CREATE and receipt, restoring the old nonunique index
and rows. Explicit data correction permits original-plan retry.

Native DROP is an acknowledged progress step separate from CREATE. If a replacement
unique build fails, the old index remains gone: there is a real construction gap,
not rollback/atomic replacement. Explicit duplicate-data correction permits CREATE
retry without replaying DROP. Application writes are not paused by schema-writer
exclusion. Lost DROP receipts remain ambiguous even with a correct absent endpoint;
there is no index-specific structural reconciliation or automatic repair.

Negative endpoint claims require removed indexes to be absent, or, for recorded
same-name replacements, the existing positive index verifier to prove the new
contract. Native completion and recovery finish both apply this rule. Unrelated
indexes retain their existing grammar (including native prefix indexes). A skipped-
DROP counterfactual previously falsely completed on both engines; it now rolls back
SQLite or leaves native uncertainty and refuses recovery finish. Whole-catalog drift
checks remain; this does not establish a general negative-ownership policy.

**Format 6** carries `drop_index`. Formats 2–5 refuse it; an actual archived `6c15088`
reader refuses both new backend artifacts. Fixed format-2/3 fixtures and preceding
format-4/5 artifacts retain identity. A model-free SQLite child deploys format 2→6,
retaining rows/defaults and allowing duplicates after explicit uniqueness removal.
No ledger-layout change, conversion, retrospective certification or user guide.

## Named table CHECK additions

`AddCheck(table_name=..., definition=...)` adds one named table constraint to an
already managed table. Generation derives appended named table CHECK declarations;
removing/replacing old CHECKs requires the explicit decisions described below.
Reordering and changing inline column constraints remain unresolved. Names must be new among recorded constraints, expressions may
reference only managed columns, and comments, suffixes and extra statements refuse.
SQLite preparation also checks names in the observed definition, so preservation
cannot accidentally reuse an unmanaged constraint name.

The expression language and parse/normalization work envelope reuse the existing
finite general CHECK verifier: bounded comparisons, NULL/IN/BETWEEN and Boolean
composition, not arbitrary functions/arithmetic or the separate JSON alias exemption.
Every new definition occurrence—including the repeated `added_checks` frozen
metadata—is charged to the existing SQL byte envelope. This is not a total lexer,
generation, memory, data-scan or IO budget.

Each addition is a separate structural step. SQLite performs a checked rebuild,
validating copied rows through the new constraint while preserving values/identity,
unmanaged BLOB/default/index/view/trigger and avoiding insert-trigger replay. Invalid
old rows roll back schema/data/receipt; explicit correction permits original-plan
retry. A later conflicting typed UPDATE also rolls the CHECK back atomically.
Historical checkpoints describe the new schema without generating CHECK ownership
into the query-only model.

Native execution uses ALTER TABLE ADD CONSTRAINT and requires
`@@SESSION.check_constraint_checks=1`. SQLite requires
`PRAGMA ignore_check_constraints=0`. Preparation, application steps, completion and
recovery refuse a disabled profile rather than changing session policy. A real
native RED/counterfactual otherwise completed over invalid old rows with checking
turned off. Validation here is engine validation during ALTER/copy, not a perpetual
row audit, application-write pause or guarantee about future application sessions.
Initial/legacy CHECK declaration verification is not retrospectively upgraded into
an enforcement/data certificate.

Rejected native ALTER leaves uncertain progress; when the catalog matches the last
acknowledgement, explicit data correction permits retry. An acknowledged CHECK plus
later failed transactional UPDATE resumes only the UPDATE. Lost CHECK receipts stay
ambiguous even when the correct constraint exists. The require/drop projection is
not CHECK-aware and cannot authorize structural reconciliation; no automatic repair.
Native effects survive later refusal, unlike SQLite's package rollback.

**Format 7** adds `add_check` and `added_checks` contraction metadata. Empty metadata
is omitted for older routes, and formats 2–6 explicitly refuse the new vocabulary.
Actual archived reader `10863c4` refuses the new backend artifacts. Preceding
format-4/5/6 artifacts stay byte-identical and fixed format-2/3 identities remain.
A model-free SQLite child deploys format 2→7, preserves rows/defaults and rejects an
invalid subsequent insert. No ledger conversion, general compatibility promise or
user guide. Explicit removal/replacement is described below; broader approved
hardening remains incomplete.

## SQLite explicit referenced-member observation

Pending preparation and live completion now extend ordinary parent-table observation with
explicit referenced-member presence. Read physical declarations from the relevant parent
CREATE TABLE SQL in the projected/live catalog, not from imported models or query aliases.
Inline claimed references and explicit single/composite table-FK full-column lists use
SQLite ASCII identifier folding and decoded identifier quotes. A declared rowid-named column
is retained; undeclared rowid/_rowid_/oid aliases, constraint labels, default literals and
Unicode casefold guesses are not physical columns. Unknown table-FK member expressions,
string roles/options/malformed lists require adapters even with equal construction bytes.

Before/target/intermediate CREATE/SQLite ADOPT requirements survive handoff; matching existing
child DDL is not member-readiness proof. Parent ownership is not inferred, opaque inline
references on extra SQL child fields remain unclaimed, constrained ADD remains unsupported.
Projected same-package parent creation must actually declare explicit referenced members;
old both-order positives remain. Implicit table-FK member lists retain base-table observation
ONLY: this gate does not resolve implicit parent keys or widen inline-reference admission.
No local/parent arity, uniqueness/key/index eligibility, affinity/type/collation, data/current
or future enforcement-session/codec/query-readiness/full FK/resource/recovery guarantee.
Native path unchanged. Existing stale-plan/accepted-catalog drift guards remain independent.

Actual archived `7b20272` format2 writer/reader/runtime completed real MATCHING FK DDL with an
ordinary parent but absent explicit member; child writes failed with foreign_keys=1. This is
a member-readiness gap, NOT missing/mismatched-FK construction or orphan acceptance. SAME
frozen artifact retains literal body/digest/load on old/current runtimes and valid/NULL child
writes plus orphan rejection when the parent declares the member. Pending prepare refuses
missing members read-only pre-effects. Isolated copied member-validator-only omission at
both call sites reproduces old context with ordinary-parent/construction/catalog guards
retained. Copied preparation-only bypass retains archived ordinary-parent proof and current
endpoint member proof: child+ledger roll back, external parent remains. Working sources are
not mutated during native suites. No format/digest/ledger/receipt conversion, repair/revocation/
retrospective certification; old complete/already-applied receipts remain earlier execution
evidence, not new parent/readiness certificates.

Remaining key/index/type/collation/implicit-key/constraint/namespace/FK/combined workflow/
interruption/resource/compiler/package/codec/ledger/release-scope queue open; points1–4
incomplete, trusted SQL unsandboxed, guides deferred, draft/not production/merge-ready.

## SQLite referenced-parent ordinary-table observation

Pending SQLite preparation now requires observed or explicitly planned ordinary parent
base tables for claimed inline REFERENCES and table-level FOREIGN KEY declarations. Pure
preparation projects the existing catalog through supported steps, then checks final
projected parent presence; live endpoint validation repeats the parent check before phase
completion. An isolated preparation-only bypass demonstrates the endpoint gate rolling
back child DDL AND history; omitting only the new validator at both call sites reproduces
the old completed-but-unusable context. No working-source mutation during native suites.

Ordinary parent proof means a main catalog table entry with ordinary CREATE TABLE SQL,
not a view or CREATE VIRTUAL TABLE entry (SQLite catalogs virtual tables as type table).
Only relevant parent definitions are parsed; unrelated opaque objects are not adopted or
certified. Name lookup uses SQLite ASCII identifier folding, not Unicode casefold. This is
not exhaustive virtual-module/shadow-object/namespace/privilege/type/parent-key/index/
collation/uniqueness or data proof. Missing/incompatible parent keys remain separate work.
Native parent observation remains unchanged. No resource/total-memory/IO/deadline guarantee.

Before/target/intermediate CREATE/SQLite ADOPT claimed tables retain their reference-parent
requirements after relinquishment; strict adoption matching child DDL is not missing-parent
certification. Declaring a reference does not adopt its parent. Extra SQL child fields'
own opaque references remain outside this claimed-parent gate, trusted/unclaimed. Supported
explicit same-package parent creation works with parent first OR child first, because proof
is final projection, not every-step readiness: preceding DML can still fail/roll back before
its parent exists. Constrained FK ADD remains unsupported; no operation/adoption/destruction
permission is added. External ordinary parents may remain wholly unowned/non-STRICT.

Actual archivedb106fd1 writer/reader/runtime emitted/loaded/completed real format2 with real
matching FK DDL but a missing external parent, and rejected attempted child writes. This is
a referenced-parent readiness gap, NOT a missing/mismatched-FK construction contradiction.
The SAME fixed artifact retains literal dump/digest/model-free load and succeeds with an
observed ordinary parent, valid/NULL children and orphan rejection. Missing/view/virtual
parents now refuse pending prepare pre-schema/history. Compiler/package identity remains
separate from target observations; no artifact/digest/ledger/receipt conversion, retrospective
repair/revocation/certification. Existing complete status/already-applied receipts are prior
execution evidence, not a new parent/readiness certificate.

Parent replacement after prepare still invalidates apply under existing catalog revalidation;
post-completion parent removal still blocks followup through accepted-catalog drift. Bounded
presence proof does not certify all current/future foreign_keys/defer_foreign_keys sessions,
application/trigger/data/codec/query readiness, parent member/key/index/type/collation/full FK
compatibility or a recovery shortcut. Remaining attributes/constraints/namespaces/FK/combined
workflows/interruption/resources/compiler/package/codec/ledger/release-scope queue open;
points1–4 incomplete, trusted SQL unsandboxed, draft/guides deferred, not production/merge-ready.

## SQLite inline REFERENCES construction agreement

Compile/load binds managed SQLite column REFERENCES presence/absence, one explicit
unqualified target table and referenced member, bounded immediate ON DELETE/UPDATE actions
and this clause's optional CONSTRAINT label against corresponding executable columns.
Known identifier quote styles/ASCII identifier and keyword case normalize; action clause
ordering and omitted/default NO ACTION normalize. SQLite NO ACTION remains DISTINCT from
RESTRICT; native immediate-action normalization is not imported. Label presence/spelling/
case bind, known label quotes normalize. Following known column-constraint boundaries own
their own identity; a REFERENCES label never becomes table DropCheck authority.

Finite action vocabulary is CASCADE/RESTRICT/NO ACTION. Implicit parent-key resolution,
composite inline targets, qualified targets, string-role names, expressions/sort/prefix
members, multiple REFERENCES/duplicate actions, MATCH/DEFERRABLE/NOT DEFERRABLE/INITIALLY,
SET NULL/DEFAULT and unknown own suffix/actions require adapters even matching bytes. SET
forms and broader ordinary-default/nullability/action role integration remain deferred,
not silently certified by this gate. Compiler-generated table-level FKs are outside this
inline gate; this is not complete SQLite FK syntax or SQL/DDL validity solving.

Before/target/intermediate CREATE/SQLite ADOPT claims survive relinquishment; standalone
ADD/ChangeDefault language admission is independent of final ownership and operation
permission. Extra executable SQL fields' own references, including unknown timing forms,
remain trusted/unclaimed, not owned child columns or implicit parent adoption. Native
handling remains unchanged. No new FK alteration/destruction API, native adoption or
referenced parent existence/key/index/type/collation/namespace/privilege proof. Query/model
mapping and parent ownership remain separate; declaring a reference doesn't adopt a parent.

Actual archived51e4b74 writer/reader/runtime emitted/loaded/completed real format2 recording
REFERENCES parents(id) but constructing no FK, then accepted orphan999 with foreign_keys1:
genuine SQLite false completion. Literal load/typed prepare now refuse pre-schema/history;
truthful companion retains dump/digest/model-free parent/NULL-child/valid-child writes and
orphan rejection. Isolated copied current-source table-gate-only bypass reproduces false
completion with other guards active, no worktree mutation during native suites. No format/
digest/ledger/receipt conversion, retrospective repair/revocation/certification or recovery
shortcut. Missing parents or incompatible parent keys remain separate readiness work.

Live CASCADE parent-key update and parent deletion retain child propagation/deletion;
independent accepted-catalog drift still blocks followup after physical action changes.
These bounded cases do not promise all future foreign_keys/defer_foreign_keys sessions,
application writes/data/trigger/privilege/codec/query readiness, arbitrary FK equivalence,
resource/deadline/total-memory coverage or full referenced-parent compatibility. Remaining
attributes/constraints/namespaces/FK/combined workflows/interruption/resources/compiler/
package/codec/ledger/release-scope queue open; points1–4 incomplete, trusted SQL unsandboxed,
draft/guides deferred, not production/merge-ready.

## SQLite inline CHECK construction agreement

Compile/load binds managed SQLite column CHECK bodies bidirectionally to the corresponding
executable column, including order/multiplicity and each own optional CONSTRAINT label.
Labels bind presence/spelling/case; known label quote styles normalize. Body significant token
kinds/order/punctuation/string values bind, with ASCII keyword/member case and known quoted
identifier styles cosmetic. Bare vs quoted roles, additional parentheses, operator aliases,
reordered/combined/algebraically equivalent predicates are not inferred equivalent. Known
finite terms must still agree by token signature; the AST is admission/resource/reference
validation, not the comparison/equivalence authority.

Reuse existing finite CHECK grammar and4096-token/32-parenthesis/64-tree/4096-weighted-work
admission envelope used for CHECK additions. Unsupported functions/constant or bare-column
bodies/nested COLLATE/unknown suffix or inline CHECK ON CONFLICT/name roles require adapters
even equal bytes. Following known constraint boundaries remain separate from this CHECK's
identity/policy; this is not complete SQL syntax/DDL-validity solving. Referenced members
must be declared table columns, avoiding SQLite double-quoted missing-name/string fallback;
known extra SQL members may be referenced without creating ownership. Standalone ADD/
ChangeDefault has only the payload's own member scope, so other references need adapters.
No total IO/deadline/parser/memory bound, SQL sandbox or generated-query/codec certificate.

Before/target/intermediate CREATE/SQLite ADOPT claims survive relinquishment. Extra SQL
columns' own opaque CHECKs and opaque table-level CHECKs are outside this managed inline
gate, executable/unclaimed rather than silently certified. Existing native CHECK handling
remains unchanged and separate; this does not make native redundant-claim/namespace proof
complete. Named inline CHECKs do not gain named table DropCheck authority. No new CHECK
alteration/removal API, implicit adoption or authority from matching bytes.

Actual archived2efa8f4 writer/reader/runtime emitted/loaded/completed real format2 with
CHECK(value>=0) metadata but absent construction, then accepted default7 AND forbidden-1:
genuine SQLite false completion. Literal load/typed prepare now refuse pre-schema/history;
truthful companion retains dump/digest/model-free default7/negative-write rejection.
Isolated copied current-source table-gate-only bypass reproduces false completion with all
other guards active, no worktree mutation during native suites. No format/digest/ledger/
receipt conversion, retrospective repair/revocation/certification or recovery shortcut.

Live nullable CHECK(value>=0) accepts SQL NULL/zero/positive, rejects negative: not a hidden
NOT NULL/general constraint solver. Explicit adoption→handoff→re-adoption preserves checked
DDL/rows/enforcement; default-changing preserving rebuild retains the owned finite CHECK and
an opaque unmanaged length CHECK, existing rows/defaults and both rejection domains. Later
physical CHECK change still blocked by independent accepted-catalog drift. These bounded
probes do not certify all current/future sessions (including ignore_check_constraints),
application writes/data/privileges/codec/query readiness or arbitrary expression equivalence.
Remaining native/other attributes/constraints/namespaces/FK/combined interruption/resources/
compiler/package/codec/ledger/release-scope queue open; points1–4 incomplete, trusted SQL
unsandboxed, draft/guides deferred, not production/merge-ready.

## Native automatic ON UPDATE construction agreement

Compile/load binds managed native ON UPDATE presence/absence and existing temporal precision
against corresponding executable columns. Reuse the bounded DATETIME/TIMESTAMP
CURRENT_TIMESTAMP language: omitted/empty function precision inherits the column precision,
explicit0–6 must match, known keyword case normalizes. Unknown functions/positions/suffixes/
duplicate clauses/conflicting precision require adapters even with matching bytes. Default,
storage/nullability/visibility/generation/clock semantics remain separate; SQLite unchanged.
Before/target/intermediate CREATE claims survive relinquishment; standalone ADD/ChangeDefault
language admission remains independent of final ownership/operation permission. No new
ON UPDATE alteration/ADD permission, native adoption or destructive authority. Extra SQL
automatic-update fields remain executable/unclaimed, not recorded ownership.

FK ON DELETE/UPDATE actions are read by the bounded FK-reference parser, not promoted to
column timestamp attributes. For native bounded REFERENCES tails, SET NULL belongs to the
referential action, not another ordinary nullability clause. Tail actions must parse exactly;
later ordinary clauses/unknown action roles fail closed, not blind REFERENCES suppression.
Known CASCADE/RESTRICT/NO ACTION/SET NULL public compile identities retained, existing native
inline default-action positive retained, separate parent/child ON UPDATE SET NULL behavior
proven. Not complete FK column/index/type/collation/engine/session compatibility proof;
SQLite reference ordering/language remains unchanged.

Actual archived692e316 writer/reader/runtime emitted/loaded/prepared real format2 recording
an automatic-update column but constructing an ordinary temporal column. It committed DDL,
then refused completion and remained UNCERTAIN/AMBIGUOUS: NOT false completion. Current
literal load/typed prepare refuse before schema/history; truthful companion retains literal
dump/digest/model-free deployment. Isolated copied-source table-gate bypass preserves late
refusal/committed effects/uncertainty with other guards active; no worktree mutation during
native suites. No format/digest/ledger/receipt conversion or retrospective repair/certification.

Live deterministic session-clock probes distinguish initial NULL default from changed-write
clock assignment and explicit unchanged-column suppression; ordinary columns remain NULL.
Independent accepted-catalog drift still blocks followup after removal of a completed column's
physical ON UPDATE clause. These bounded probes do not certify exact wall clock/monotonicity/
timezones/precision accuracy/all update forms/triggers/privileges/future-session/data/codec/
query readiness. No clock/server policy mutation or native recovery shortcut. Temporal legacy
implicit defaults remain subject to independent observation, not inferred from absence.
Remaining attributes/constraints/namespaces/FK/workflows/interruption/resource/compiler/package/
codec/ledger evolution/release-scope queue stays open. Points1–4 incomplete, trusted SQL
unsandboxed, draft/guides deferred, not production/merge-ready.

## Generated-column kind and finite expression construction agreement

Compile/load binds managed generated presence/absence, physical virtual/stored kind and a
finite expression signature, separately from type/nullability/default/visibility/identity.
SQLite default VIRTUAL/optional GENERATED ALWAYS normalize; native existing STORED/PERSISTENT
aliases remain known. SQLite generated-constraint labels bind presence/spelling/case, with
known identifier quotes cosmetic; labels do not grant DROP CHECK authority. Unknown/multiple
prefix/mode/suffix/name-role forms require adapters even with equal bytes.

Finite scalar language: signed64 decimal constants (at most19 digits), single-quoted strings,
NULL, a quoted reference to a declared table member, that reference plus one signed integer,
and native CAST(integer AS SIGNED). Whole-expression parentheses/known keyword case and
known identifier quote/case normalize. Native references require backticks rather than
assuming ANSI_QUOTES/MSSQL modes; unquoted references are adapter-only to avoid reserved/
function/numeric role guesses. Unknown functions, arbitrary expressions, reversed/algebraic
rewrites and missing members require adapters. Quoted references may target extra declared
SQL columns without manufacturing ownership. Standalone admission has no table member scope,
so member-dependent expressions require adapters there; no new ADD/alter-generated permission.
Expression input is limited to64 tokens before wrapper normalization; no recursion/evaluation
or unbounded integer conversion. This is not a total parser/IO/work/memory bound.

Before/target/intermediate CREATE/SQLite ADOPT claims survive relinquishment. Extra executable
generated fields remain trusted SQL without becoming recorded columns. Their expression
language is not automatically claimed/certified by this managed gate. Quoted names/literals/
nested AS/CAST mentions do not manufacture clauses. Native unsupported generation positions
and modes now refuse compile rather than preparation; existing visibility/generation-kind/
other attribute/live-catalog guards remain independent.

Actual archived6af49f5 writers/readers/runtimes emitted/loaded/completed real format2 on BOTH
SQLite and MariaDB recording AS7 VIRTUAL but constructing AS8 VIRTUAL, then returned value8
under ordinary base7 insertion. These are genuine false completions, not just earlier late
refusals. Literal load/typed prepare now refuse before effects/history; truthful AS7 companions
retain literal dump/digest/model-free base7/value7. Isolated copied-source table-gate bypasses
reproduce both current false completions without worktree mutation during native suites.
No format/digest/ledger/receipt conversion, retrospective repair/revocation/certification.

Live VIRTUAL/STORED/native PERSISTENT quoted-member-plus-integer cases retain default-derived
and updated values. Independent accepted-catalog drift guards still block followup after
physical expression changes. Finite construction agreement is not arbitrary equivalence,
complete live expression/index/FK proof, dependency/cycle/type/DDL-validity solving, generated
query-field writability/codec compatibility, all session/data/locale/overflow/readiness proof
or native recovery shortcut. ON UPDATE/other attributes/constraints/namespaces/FK/combined
workflows/interruption/resources/compiler/package/codec/ledger queue remain open. Trusted
SQL unsandboxed; points1–4 incomplete, draft/guides deferred, not production/merge-ready.

## Native column visibility construction agreement

Compile/load binds managed native column visibility independently of named queryability,
key/storage/nullability/generator agreement. Before/target/intermediate CREATE claims survive
relinquishment; standalone ADD/ChangeDefault language admission is independent of final
ownership/operation permission. No native adoption/visibility alteration operation is added.
Extra SQL invisible fields do not create recorded column/index/destructive authority.

Reuse the existing bounded native visibility recognizer: implicit ordinary visibility and
INVISIBLE, known keyword case, literal/default/comment/expression role separation. Explicit
VISIBLE, repeated/conflicting flags and unparsed roles remain adapter-only, now at compile
rather than preparation; not a cross-version claim about server syntax. SQLite remains
unchanged. Generated-column meaning/expression identity stays separate and unfinished.

Actual archived566229c writer/reader/runtime emitted/loaded/prepared real format2 ordinary
visible metadata/INVISIBLE construction, committed DDL then refused UNCERTAIN/AMBIGUOUS:
**not native false completion**. Current literal load/typed prepare refuse before effects/
history. Truthful old invisible companion retains dump/digest/model-free wildcard omission,
positional default7 and explicit named access. Isolated copied-source table-gate bypass
retains late live catalog refusal/uncertainty and other admission/recovery guards, leaving
working sources unmutated during native suites. No conversion/digest/ledger/receipt rewriting,
retrospective repair/revocation/history recertification or native recovery shortcut.

Live ordinary visibility preserves wildcard/positional behavior, invisible columns remain
explicitly addressable. Accepted-catalog drift still blocks followup after physical visibility
changes. Visibility is not access control/privilege enforcement, column deletion, logical
codec compatibility, arbitrary query projection ABI or data/readiness certification. Existing
invisible generated/auto-increment and physical `_rowid` positives remain independent.
Other generated/ON UPDATE/attribute/constraint/namespace/index/FK compatibility, combined
workflows/interruption/resources/compiler/package/codec/ledger queue remain open. Trusted
SQL unsandboxed, points1–4 incomplete, draft/guides deferred; not production/merge-ready.

## Native AUTO_INCREMENT construction agreement

Compile/load binds managed native AUTO_INCREMENT presence/absence independently of key/
nullability/storage agreement. Before/target and intermediate CREATE payload claims survive
relinquishment; standalone ADD/ChangeDefault language admission is independent of final
ownership/operation permission. Native adoption is not added. Extra executable generators
or supporting unique indexes do not create recorded column/index/destructive authority.

Reuse the existing bounded native attribute-prefix recognizer; known keyword case normalizes.
Duplicate attributes now require adapters even with equal bytes. Unsupported positions need
adapters, not a general DDL-parser/equivalence fallback. Identifier/default/comment/literal
mentions do not manufacture attributes. SQLite rowid/AUTOINCREMENT key policy remains
separate and unchanged. DEFAULT and other attribute admission remain independent.

Actual archived9b4b442 writer/reader/runtime emitted/loaded/prepared real format2 recording
AUTO_INCREMENT but constructing a plain primary key, committed DDL then refused UNCERTAIN/
AMBIGUOUS recovery: **not native false completion**. Current literal load/typed prepare now
refuse before effects/history. Truthful old companion retains literal dump/digest/model-free
generation/default7; known fresh-session empty/NULL inserts allocate distinct ids, ordinary
counter advancement does not invalidate a valid follow-up. Isolated copied-source table-gate
bypass preserves old late catalog refusal/uncertainty, not false completion, leaving working
sources untouched during native suites. No conversion/digest/ledger/receipt rewriting,
retrospective repair/revocation or history recertification.

Live accepted-catalog drift guard still blocks valid followup after removing the physical
generator. Constructor admission does not replace catalog/recovery checks or guarantee exact
next counters, contiguous/no-gap/non-reuse sequences, ranges/exhaustion, zero-input sql_mode,
server offsets/increments or future-session semantics. No policy mutation or new recovery
shortcut. Other generated/visibility/ON UPDATE/attribute agreement, constraints/namespaces/
indexes/FK compatibility, combined workflows/interruption/resources/compiler/package/codec/
ledger queue remain open. Trusted SQL unsandboxed; points1–4 incomplete, draft/guides deferred.

## Column collation construction agreement

Compile/load binds each managed ColumnState collation to construction. SQLite's bounded
language is BINARY/NOCASE/RTRIM, ASCII-case-insensitive names/known identifier quotes and
implicit BINARY. Optional explicit COLLATE constraint labels bind presence/spelling/case;
only quote style normalizes. Following labels are separate. Unknown custom/duplicate/
string-role/suffix forms require adapters even with equal bytes. Quoted names/literals and
nested expression COLLATE mentions do not manufacture a column collation claim. Expression
semantics remain separate, not automatically certified by column agreement.

Native binding reuses the existing bounded type-prefix utf8mb4/JSON-implied-bin declaration
contract. Named collation equality is not server availability/equivalence proof; supported
backend catalogs still matter. Unknown omitted native collation does not normalize to an
explicit name using assumed table/server defaults. JSON/known LONGTEXT binary-collation
storage alias behavior remains separately guarded. Charset inheritance/equivalence and
arbitrary syntax/custom collations are not added here. Existing native unsupported-position
refusal moves to compile rather than waiting for preparation. Native collation expression
admission remains conservative; this does not broaden that language.

Before/target/intermediate CREATE/ADOPT claims survive relinquishment; standalone ADD/
ChangeDefault admission is independent of final ownership/operation permission. Extra SQL
collated fields do not create recorded ownership. No new destructive/namespace authority.

Actual archived8e7c243 writer/reader/runtime completed NOCASE metadata/BINARY construction,
then accepted default 'Case' plus 'case' under UNIQUE. Real format2 literal now refuses load/
typed prepare before effects/history. Truthful old NOCASE companion retains dump/digest/
model-free default/case-only duplicate rejection. Isolated copied-source table-gate bypass
reproduces current false completion, leaving working sources unmutated during native suites.
Archived native bin/general_ci contradiction prepared and committed DDL, then refused with
uncertain effects/ambiguous recovery: **not native false completion**, now pre-DDL refusal.
No conversion/digest/ledger/receipt rewriting, retrospective repair/revocation/certification.

Live SQLite built-ins distinguish case/trailing-space duplicate behavior. Known native bin/
general_ci positives retain case behavior; post-completion physical collation drift still
blocks a valid followup via the independent accepted-catalog guard. Constructor admission
is not full live collation/index/FK/data/session/codec/readiness proof. SQLite built-in names
are not a certificate against externally registered overrides; native names are not locale/
Unicode/version/registry guarantees. Failed transactions exit before subsequent queries.
Remaining attribute/constraint policies/identity, charset/generated/other facts, namespaces/
indexes/FK compatibility, combined workflows/interruption/resources/compiler/package/codec/
ledger queue stay open. Trusted SQL unsandboxed, points1–4 incomplete, draft/guides deferred.

## Explicit inline primary-key label agreement

Compile/load also binds each managed inline key's optional explicit SQLite constraint
label, separately from its direction/conflict/AUTOINCREMENT and effective nullability.
Known identifier quoting normalizes, including escaped quotes/keyword-looking identifiers;
label presence/spelling/case do not. Following NOT NULL/UNIQUE labels belong to those
clauses, not the PK. Unsupported string-role names need adapters even with equal bytes.
Native named inline PK forms require adapters rather than inference about syntax support,
retained/ignored names or the physical PRIMARY index. This is not a claim that every
native server rejects the syntax.

Before/target/intermediate CREATE/ADOPT claims survive relinquishment. Standalone ADD/
ChangeDefault label roles are admitted even with no final ownership. Extra SQL named keys
do not create recorded columns/indexes. A PK symbol does not authorize DROP CHECK/INDEX.
No table-level key relocation/index/constraint namespace equivalence is inferred.

Actual archivede1d3ef0 writer/reader/runtime emitted/loaded a format2 package, reported
complete with ColumnState label "recorded" but constructed/catalog label "other". This is
an identity contradiction, **not evidence of lost uniqueness or changed write behavior**.
Current load/typed prepare refuse that literal before effects/history; truthful old
companion retains dump/digest/model-free default7 insertion and duplicate-key rejection.
An isolated copied-source comparison omitting only label reproduces the contradiction,
without working-source mutation during native suites. Live named SQLite keys retain
ordinary/DESC enforcement, default7 and AUTOINCREMENT non-reuse after deletion. Existing
key-nullability/direction/policy/catalog guards remain independent. No native runtime
false-completion claim, new format/ledger/receipt conversion, retrospective repair/revocation
or history recertification.

Remaining NULL/CHECK/FK/other constraint policies/identity, collation/generated/other
attributes, whole key/index/namespace/FK compatibility, unexpected objects/drift and combined
workflow/interruption/resource/compiler/package/codec/ledger queue remain open. SQL stays
trusted/unsandboxed, points1–4 incomplete, draft/guides deferred; not production/merge-ready.

## Explicit NOT NULL clause construction agreement

Compile/load binds each managed explicit NOT NULL declaration to construction: presence,
SQLite own ON CONFLICT policy and optional explicit constraint label. Before/target and
intermediate CREATE/ADOPT remain claims after relinquishment. Standalone ADD/ChangeDefault
terms need independent admission even with empty final ownership. Extra SQL declarations
do not create ColumnState authority. A NOT NULL label is not a named table CHECK and does
not grant DROP CHECK permission.

Effective key-implied requiredness is separate: equal nullable flags do not prove explicit
clause identity or policy. Extra/omitted NOT NULL clauses require adapters even when a PK
already prevents stored NULL. Known omitted SQLite ABORT and label quote style normalize;
label presence/spelling/case do not. Following UNIQUE/PK policy belongs to that constraint,
not NOT NULL. Unknown/multiple forms need adapters even when matching bytes. Native plain
NOT NULL is supported; named native forms/SQLite-style conflict policies require adapters,
not cross-version syntax/name guesses. This does not assert all servers reject the syntax.

Actual archived `86464d6` writer/reader/runtime completed NOT NULL IGNORE metadata with
REPLACE construction, then a NULL write inserted id42/default7 where the recorded policy
should skip the row. Its real format2 artifact now refuses load/typed preparation before
effects/history. An isolated copied-source table-gate bypass reproduces current false
completion without working-source mutation during native suites. The truthful old IGNORE
companion retains literal dump/digest and model-free NULL-write skipping. No format/ledger/
receipt conversion, retrospective repair/revocation or history recertification. This is a
SQLite false-completion case; no new native false-completion claim.

Live public-transaction cases distinguish IGNORE skipping, REPLACE default7 substitution,
and rejection for implicit/explicit ABORT, FAIL and ROLLBACK. REPLACE without a non-NULL
default (absent or explicit NULL) rejects instead of inventing values. These cases do not
establish all multi-statement FAIL/ABORT/ROLLBACK semantics. Failed writes leave their
transaction before later queries. A native canonical positive deploys; a separate strict
consumer session rejects NULL, not a claim about every future session's coercion policy.

Existing declaration/key-nullability/catalog/recovery guards remain independent; this is
not full live NOT NULL/CHECK/constraint catalog proof. Explicit NULL labels, CHECK/FK/other
constraint definitions/namespaces, collation/identity/generated/other attribute agreement,
index/FK compatibility, session/data enforcement, logical codecs/readiness and combined
workflow/interruption/resource/compiler/package/codec/ledger evolution remain open. SQL is
trusted executable input, not sandboxed; points1–4 incomplete, still draft/guides deferred.

## Managed inline UNIQUE construction agreement

Compile/load binds each managed column's inline UNIQUE declaration to its construction
including absence in either direction. Before/target/intermediate CREATE/ADOPT remain
claims after relinquishment. Standalone ADD/ChangeDefault definitions need bounded UNIQUE
admission independently of final ownership. Extra SQL declarations do not create ColumnState
or separate-index ownership. A table-level UNIQUE or separate index is not automatically
substituted for an inline claim, even when it looks logically equivalent.

SQLite signatures preserve the UNIQUE clause's own ON CONFLICT policy and optional explicit
constraint label. Only known omitted ABORT normalizes to explicit ABORT; label quote style
can normalize, but label presence/spelling (including case) cannot disappear or fold.
Following NOT NULL policies/labels are not attributed to UNIQUE. Multiple clauses, unknown
suffixes/policies and unsupported identifier roles require adapters even with equal bytes.
Native ordinary UNIQUE and optional UNIQUE KEY spelling are supported; named native inline
forms need explicit adapters rather than cross-version syntax/name guessing. That refusal
is not a claim that every server rejects the syntax. Native implicit index names are not a
stable claimed ABI or separately recorded DROP INDEX authority.

Actual archived `fd5f36e` writers/readers/runtimes completed INTEGER/BIGINT inline UNIQUE
metadata with construction omitting UNIQUE on both SQLite and native, then stored duplicate
default7 values under distinct ids42/43. These were genuine false completions on both
backends, not native late-refusal examples. Real format2 artifacts now refuse load/typed
preparation before DDL/history; isolated copied-source table-gate bypasses reproduce current
behavior without working-source mutation during native suites. Valid old companions retain
literal dumps/digests and model-free default7 deployment rejecting a second equal value.
No wire/ledger/receipt conversion, retrospective revocation/repair or history recertification.

Live SQLite rejecting policies (implicit/explicit ABORT, FAIL, ROLLBACK) preserve the
previously committed row under the public transaction boundary; IGNORE skips the duplicate
and REPLACE replaces the old row. This does not claim a complete FAIL-vs-ABORT/ROLLBACK
multi-statement failure ABI. Nullable UNIQUE remains separate from NOT NULL and permits
multiple NULL values. Native canonical/KEY positives reject duplicates. Failed writes leave
their transaction before further queries. Existing native catalog/recovery guards remain
unchanged: construction agreement is not a new complete live UNIQUE catalog proof.

Full table-key/index/constraint equivalence, other column constraints and their policies,
constraint namespace/identity beyond this declaration label, native implicit names, collation/
NULL/index-family/version compatibility, FK/reference compatibility, data/session enforcement
(including unique_checks), logical codecs and readiness remain separate. Constraint naming
never grants unrecorded index-removal authority. SQL is trusted executable input, not a
sandbox. Remaining claim/workflow/interruption/resource/compiler/package/codec/ledger queue
open; points1–4 incomplete, still draft and guides deferred.

## Bounded declaration/key-implied nullability

Compile/load now compares each managed primary-key member's recorded nullable flag
with the effective declaration/key rules, independently in its frozen definition and
construction declaration. Before/target/intermediate CREATE/ADOPT remain claims after
relinquishment. Extra SQL declarations/members do not manufacture ColumnState ownership.

SQLite plain rowid tables preserve nullable non-INTEGER keys unless explicitly NOT NULL.
INT is not INTEGER: only exactly INTEGER with a single inline non-DESC key aliases the
rowid. The historical inline INTEGER PRIMARY KEY DESC exception remains nullable outside
STRICT/explicit NOT NULL. A single table-level INTEGER key aliases rowid even with DESC;
a composite INTEGER member does not. Accepting NULL input and allocating a non-NULL rowid
is not nullable stored key data. Known STRICT, WITHOUT ROWID, and their comma-separated
combinations require key members; both orders are covered. Native supported primary-key
members are required even when the definition omits NOT NULL. Other constraints are not
an alternative basis for inferring the flag.

Bounded table-key membership accepts one ordered full-column list, quoted identifiers,
optional known direction, and SQLite's finite key ON CONFLICT clause. Expressions,
prefixes, duplicate/unknown members, multiple keys, unsupported policies/options require
adapters. Membership admission is not complete table-key/constraint/index equivalence,
constraint naming or authorization to alter/drop keys. Native PK/index/catalog checks
remain independent and unchanged; earlier native prefix refusal is not a runtime defect.

An actual archived `9eb468e` writer/reader/runtime completed a non-STRICT TEXT PRIMARY KEY
with required metadata, then stored two NULL keys. Its real format2 artifact now refuses
load/typed preparation; isolated copied-source table-gate bypass reproduces current false
completion without mutating working sources during native suites. A truthful old nullable
companion retains literal dump/digest and model-free NULL-bearing deployment. An actual
archived native nullable table-key package prepared/executed DDL then refused, preserving
uncertain effects/ambiguous recovery: not native false completion. It now refuses before
DDL/history; a truthful required counterpart deploys without converting the old identity.

Live SQLite cases distinguish nullable TEXT/INT/inline-DESC and non-STRICT composite keys,
INTEGER rowid allocation (including table-level DESC), explicit requiredness, STRICT and
WITHOUT ROWID modes. Rejected writes exit their transaction before subsequent queries.
Native inline/table-level required positives deploy; invalid old typed packages leave no
DDL/history. No format/ledger/receipt conversion, retrospective repair or schema-history
recertification. Historical completion is not a readiness certificate.

This binds declaration/key-implied nullability, not the full admissible-value domain:
CHECK/FK/trigger/default/session behavior, logical annotations, codecs, data and application
readiness remain separate. SQL is trusted executable input, not sandboxed. Whole key and
constraint definitions/names, UNIQUE and other conflict policies, namespace/index/FK
compatibility, combined workflows/interruption, remaining resources and genuine compiler/
package/codec/ledger evolution remain open. Points1–4 incomplete; draft, guides deferred.

## Inline primary-key declaration agreement before execution

Compile/load now binds managed inline PRIMARY KEY declarations to corresponding
construction declarations, including absence in either direction. Before/target and
intermediate CREATE/ADOPT claims remain checked after relinquishment. Standalone
ADD/ChangeDefault definitions also need bounded key-clause admission. Extra SQL columns
do not manufacture ColumnState claims. This is not complete table-level key inference.

SQLite key signatures retain ASC/DESC direction, the key's own ON CONFLICT policy and
AUTOINCREMENT. Omitted direction/conflict normalize only to known ASC/ABORT defaults;
explicit DESC or another policy cannot be erased behind a matching PRIMARY KEY marker.
Following NOT NULL/UNIQUE conflict policies are not mistaken for the key's own policy.
Known matching explicit ASC/ABORT, DESC, IGNORE and AUTOINCREMENT cases actually execute:
DESC keeps a distinct hidden rowid, IGNORE preserves the original duplicate row, and
AUTOINCREMENT retains never-reuse behavior after deleting the greatest id. This does
not certify every rowid/nullability mode or all conflict/constraint interactions.

Native ordinary inline keys bind presence. Direction clauses or unknown key suffixes
require adapters rather than relying on server/version behavior. Native AUTO_INCREMENT,
nullability, key order/index metadata and other attributes retain their existing separate
catalog checks; this gate does not replace them. Known missing/hidden/moved inline-key
construction examples now refuse before DDL/history instead of leaving effects before
endpoint refusal. Those native examples were not false completion. Independent physical
key drift still blocks a valid follow-up under the existing accepted-catalog guard.

An actual archived `6806ca6` SQLite writer/reader/runtime completed an INTEGER PRIMARY
KEY definition with no constructed key, then accepted duplicate42 and NULL ids. Its
fixed real format2 artifact now refuses load/typed preparation. An isolated copied-source
table-gate bypass reproduces current false completion without worktree mutation during
native suites. The valid companion's literal dump/digest and id42/default7 deployment
remain. No wire vocabulary/format/ledger conversion, receipt rewriting, retrospective
revocation or automatic repair. Historical completion is not schema recertification.

Quoted/default/string/expression mentions are not inline declarations. Multiple clauses
or unsupported key-policy forms require adapters even when matching bytes. Inline/table
key relocation is not silently treated as equivalent; rowid and naming differences need
separate proof. Table-level member/order/expression/prefix policy, effective key
nullability, key/constraint names, NOT NULL/UNIQUE conflict policy, namespace, index/FK
compatibility, codecs and readiness remain separate. SQL is trusted executable input,
not a sandbox. The remaining claim/workflow/interruption/resource/evolution queue is
open; points1–4 incomplete, still draft and guides deferred.

## Historical query-source admission

Historical query declarations are a separate generation seam, not a deployment or
schema-readiness certificate. `contract_source` now checks the default primitive
proposed by ColumnState.storage against the recorded physical definition. It does not
infer a codec from the SQL family. SQLite's admitted default primitive declarations
are INTEGER/TEXT/REAL/BLOB; INT/ANY or contradictory hints need an adapter here even
when their physical packages remain supported. Native candidates are the default
BIGINT/VARCHAR(255)/DOUBLE/BLOB primitives, using existing understood type-signature
aliases. Parameterized/wider text, native Boolean/datetime/decimal/JSON and other
non-default policies cannot be reconstructed merely because their coarse hint is
INTEGER/TEXT/REAL/BLOB. This is intentionally narrower than physical deployment.

An actual archived `6e6b0b1` generator took native VARCHAR(512)/logical str/TEXT hint
and emitted default Text(): an original-model 300-character update compiled, but the
historical declaration rejected it under the default 255-character codec policy.
The fixed real format2 package still loads byte-identically and deploys; an explicit
query adapter writes/reads 300 characters on the owned native server. Automatic
historical generation now refuses with an explicit codec/name adapter diagnostic.
An isolated copied-source primitive-gate bypass reproduces the current lossy output
without worktree mutation during native suites. This was a query-generation defect,
not a migration false-completion/recovery defect; target guards are unchanged.

Fresh model generation now distinguishes genuine builtin scalar unions from other
generic origins. Annotated metadata and native JSON payloads such as list[int] or
dict[str,int] remain opaque (`query_type=None`), rather than becoming int or str|int.
Opaque nullable union members also stay opaque without hashing their metadata; the
archived generator blocked an otherwise legal physical model with an unhashable-dict
TypeError. Physical generation/loading/deployment do not require an automatic query
declaration. Historical source emits only finite builtin int/str/float/bytes/bool/None
names/unions, normalizing safe whitespace/repeated atoms instead of replaying raw annotation text.
It never evaluates a recorded annotation. Known generated framework/type-name shadows,
dunder fields and non-ASCII field spellings need name adapters, avoiding Python name
normalization/shadowing guesses. This is not full model-namespace/SQL validation.

Default-primitive positives on both backends retain scalar, nullable and mixed-union
declarations, independently typecheck/import without authoring-model imports, and
compile typed updates. Valid old physical artifacts retain bytes/digests; no format,
ledger, receipt or metadata conversion. Fresh drafts with formerly misrepresented
opaque annotations intentionally record None; old erased provenance cannot be inferred
or repaired retrospectively. An old recorded scalar claim is not evidence of the
original model's validation hooks, custom codecs or logical-type provenance.

This is bounded generation admission, not durable codec ABI/provenance, value/JSON-shape
compatibility, original-hook reconstruction, full namespace validation, a native-family
codec map or application-readiness proof. The source is a query-only declaration, not a
reconstruction blueprint. Trusted SQL/model generation remains executable, unsandboxed
input. Resource limits for generation and genuine compiler/package/codec/ledger
evolution remain open, alongside key/constraint/FK, ownership/workflow/interruption
proofs. Points1–4 remain incomplete; still draft and user guides deferred.

## Bounded default declaration agreement before execution

Compile/load now compares each managed frozen column default with the corresponding
construction declaration, including absence. Before/target and intermediate CREATE/
ADOPT claims remain checked after relinquishment. Standalone ADD/ChangeDefault terms
also need admission even when no final table remains. Extra construction columns do
not manufacture ColumnState claims; existing table-SQL/backend endpoint checks still
apply independently. A matching expression's bytes are not, by themselves, proof.

SQLite compares bounded integer/Boolean/text/NULL literal terms, including generated
UTF-8 hex CAST forms and cosmetic literal parentheses, plus the compiler's TEXT clock
expression. Token keyword case can normalize; literal strings/clock format and modifier
strings cannot be indiscriminately folded. Absence is distinct from explicit DEFAULT
NULL. Arithmetic, arbitrary functions, floating-point or other unknown default terms
require an adapter, even if definition and construction contain identical text. The
whole term is checked, not just a leading scalar. No SQL evaluation is used for proof.

Native comparison reuses existing bounded declaration-default signatures: supported
scalar/encoded-text literals and compiler DATETIME/text clocks. Nullable omission and
explicit NULL retain the existing effective-NULL contract in either representation;
this does not prove clause spelling or omitted-write behavior. Required absence cannot
hide an explicit default. Ambiguous/default-NULL/unsupported forms formerly refused at
preparation now fail compilation too, including intermediate claims with empty targets.
Known mismatches move from late endpoint refusal to pre-DDL/no-history refusal. Native
catalog, drift, uncertain-progress and recovery guards remain necessary and unchanged;
these native examples were not false completion.

An actual archived `9cf8fd9` writer/reader/runtime completed SQLite DEFAULT 7 metadata
with DEFAULT 8 construction; an omitted-value insert stored 8. Its fixed real format2
artifact now refuses load/typed preparation. An isolated copied-source table-gate bypass
reproduces current SQLite false completion without mutating working source during native
suites. Valid companion digest/dump and model-free id42/default7 remain unchanged.
Generated encoded Unicode/NUL, explicit NULL and cosmetic clock-case forms execute too.
Prior package vocabularies/identities remain; no new format, ledger conversion or
receipt rewriting. Historical completions are not retrospectively revoked or repaired.

This is default declaration agreement, not arbitrary SQL/attribute/key equivalence,
a complete default-value domain/constraint-fit proof, Python constructor defaults,
ColumnState.storage-hint/query/codec certification, clock/timezone correctness,
future-session enforcement or general application readiness. Construction SQL remains
trusted executable input, not a sandbox. The remaining metadata/key/constraint/FK,
ownership/workflow/interruption/resource/evolution queue stays open; points1–4 are
incomplete and this PR remains draft. User guides remain deferred.

## Physical definition/construction storage agreement before execution

Compile/load now compares each managed column's physical definition type against its
construction declaration, bound by the already-checked column name. Before/target and
intermediate CREATE/ADOPT payloads remain checked even after relinquishment. ADD/default
payload type prefixes are admitted independently, so an empty final target cannot hide
an unsupported claimed intermediate type. This is positive managed-column admission;
extra SQL declarations do not manufacture ColumnState claims, and existing table-SQL/
backend-specific endpoint claims still independently apply.

SQLite admits finite STRICT type names INT/INTEGER/REAL/TEXT/BLOB/ANY, comparing keyword
case but not collapsing affinity. INT remains distinct from INTEGER because affinity
cannot establish INTEGER PRIMARY KEY rowid type identity. Type parameters/multiword
modifiers and other type names require an adapter. This does not prove rowid/key mode
semantics or stored-value/codec equivalence for every table. Both case variants of all
six admitted names execute and retain integer/real/text/BLOB/ANY values.

Native comparison reuses the existing bounded physical-type signature: understood
family aliases, normalized implicit parameters and irrelevant integer display widths,
while retaining meaningful lengths, decimal/temporal precision and signedness. JSON's
LONGTEXT alias is storage only; validity/collation remain separate. Unknown declaration
or construction types/modifiers refuse at compile/load, rather than waiting for target-
only preparation admission; this also covers intermediate claimed ENUM plus relinquishment.
Existing known alias/parameter positives still execute model-free. The signature is
not full attribute/tail equivalence, global engine behavior or a codec proof; native
catalog/postcondition checks remain necessary and unchanged.

An actual archived `5c4a655` SQLite writer/reader/runtime completed an INTEGER column
definition with TEXT construction and stored 'not integer' as text. Its fixed real
format2 artifact now refuses load/prepare, including typed in-memory Package objects.
Native known type/parameter/signedness mismatches and unsupported constructor probes
now refuse before DDL/history instead of leaving effects before endpoint refusal.
Already-unsupported declaration/type-conversion forms move their existing pre-effect
refusal from preparation to compilation. These native examples were not false completion.
An isolated copied-source gate bypass reproduces current SQLite false completion;
working source is never mutated during native suites.

No wire vocabulary/version/ledger conversion or receipt rewriting. Valid old companion
literal digest/dump and model-free id42/default7 remain; prior backend2/7/8 and fixed2/3
identities retain. Historical completions are not retrospectively revoked or repaired.

**This binds physical definitions, not the coarse ColumnState.storage hint or Python
query/codec annotations.** Native datetime/decimal/JSON representations cannot be mapped
to a universal runtime codec by guessing from their type family. Those contracts,
default/other attribute agreement, full key/constraint/index/namespace/privilege/negative-
ownership/drift/FK compatibility and workflow/resource/compiler/codec/ledger proofs
remain separate. Trusted construction SQL is executable input, not a sandbox; source
admission does not prove every SQL effect or all unlisted declarations.

## Ordinary-column nullability agreement before execution

Compilation/loading binds ordinary ColumnState.nullable flags to both their frozen
column definitions and corresponding construction declarations, in both directions.
Top-level NOT NULL means required; explicit NULL or absence of a nullability clause
means nullable. DEFAULT NULL, parenthesized expressions/CHECKs, quoted literals and
identifier contents are not nullability clauses. Multiple clauses require an adapter,
rather than selecting an arbitrary winner. This is a bounded declaration check, not
arbitrary expression equivalence or a claim that CHECK/default effects cannot reject
NULL independently.

Before/target and intermediate CREATE/ADOPT claims remain checked even if later
relinquished. ADD COLUMN and ChangeDefault payloads independently bind their own
flags/definitions before projection, so relinquishment cannot hide inconsistent
nullable ADD metadata with required executable SQL. Existing contraction/edit guards
remain active; this grants no additional alteration authority or implicit backfill.

**Primary-key members remain separate.** Inline keys and potential table-key members
are excluded from this ordinary-column check; membership spelling is not a key-proof
or a promise about primary-key nullability on every SQLite/native table mode. A
constraint's name is not a member and cannot exempt an unrelated ordinary column.
Existing native key/catalog checks are unchanged. Positive routes on both backends
retain table-level primary-key operation while an ordinary nullable column accepts
explicit NULL and future omission uses default7. Do not generalize this slice into
all-column physical nullability or a future application-session enforcement certificate.

An actual archived `adb59a6` SQLite compiler/reader/runtime completed a package with
required metadata/definition but nullable construction SQL, then accepted NULL. The
fixed real format2 artifact now refuses compile/load/preparation, including typed
in-memory Package objects. Native opposing nullability mismatch tests now refuse
before DDL/history rather than only after committed effects. Runtime endpoint guards
are unchanged. An isolated copied-source gate bypass reproduces current-runtime
false completion without mutating working source during native suites.

No format/vocabulary/ledger conversion. The valid archived companion preserves bytes/
digest and model-free deployment retains id42/default7. Previously valid backend2/7/8
and fixed2/3 identities remain. No receipt rewriting or automatic revocation/repair
of historical completions: status is history, not retrospective schema certification.
Storage/default agreement, complete key/constraint/index/namespace/privilege/negative
ownership/drift/FK compatibility and remaining workflow/resource/compiler/codec/ledger
proofs stay separate. Trusted construction SQL is not sandboxed.

## Positive managed-column coverage before execution

Compilation/loading now requires exactly one actual column declaration for every
recorded `ColumnState.name` in each frozen construction SQL body. Before/target
snapshots and intermediate CREATE/ADOPT payloads remain checked even if later
relinquished. CHECK/constraint names, expressions, string literals, comments and
native pseudo-column query aliases cannot supply a missing physical declaration.
Duplicate or ASCII-case-colliding declarations for a managed name refuse. The
bounded identifier reader accepts bare/identifier-quoted declarations; single-quoted
column spellings require an adapter even where an engine would accept them.

Order and ASCII case differences do not erase presence. This does not claim full
native Unicode/case equivalence: SQLite distinct Unicode names remain distinct.
Extra construction declarations do not manufacture extra ColumnState authority;
trying to DropColumn an extra unrecorded column still refuses. Existing table-SQL
and backend-specific endpoint declarations remain independently applicable, so this
is not a blanket statement that extra SQL has no claims/effects or is unowned.

An actual archived `86f6ab1` SQLite deployment completed a package whose SQL created
only id but whose ColumnState still claimed id/value. PRAGMA table_info confirmed
only id. SQLite's existing table-SQL endpoint check agreed with construction SQL,
not the contradictory column metadata. New load/compile/preparation refuse this
fixed historical artifact before effects. The native missing-column and `_rowid`
alias tests now assert pre-construction refusal/no history, replacing late native
refusal; independent legacy setup still proves that `_rowid` queryability is not
physical declaration. Runtime endpoint guards are unchanged.

No format/vocabulary/ledger conversion. Valid old artifacts keep bytes/digests;
unsupported historical claim mismatches explicitly refuse instead of rewriting
receipts. Already-completed historical receipts are not automatically revoked or
repaired; status remains history, not retrospective schema certification.
Real archived valid/invalid format2 fixtures, model-free valid deployment
with id42/default7, and an isolated copied-source gate-bypass counterfactual retain
the evidence. Gate bypass again falsely completes the inconsistent old SQLite
artifact; no working-source mutation during native suites.

This is **positive managed-column presence**, not complete body/all-effects proof,
reverse ownership inference or full declaration/physical-claim agreement. Storage/defaults and broader key nullability,
indexes/constraints, native namespaces/privilege visibility,
unexpected objects/negative ownership/drift and FK compatibility need separate
proof/refusal. SQL remains trusted executable input, not sandboxed.

## Construction header authority before execution

Compilation/loading now binds each frozen construction header to its recorded exact
table name, before/target snapshots and intermediate CREATE/ADOPT included even if
later relinquished. Only unqualified ordinary `CREATE TABLE <identifier> (` is
admitted. Bare or quoted owner tokens are accepted; keyword case and ordinary
whitespace do not matter. Quoted identifier contents (including keyword-like text,
escaped quotes and punctuation) are not interpreted as grammar.

Views, temporary/virtual tables, IF NOT EXISTS, schema-qualified names, CREATE AS /
LIKE and commented headers require an explicit adapter. This does not infer ownership
from an existing object, broaden adoption, or allow TEMP to shadow a persistent table.
Owner spelling must exactly agree; native catalog resolution/normalization is still
proved independently at execution, not assumed from Python folding. The existing
native lower-case-table-names route remains a separate endpoint test.

Earlier wrong-owner/view probes reached native DDL before endpoint refusal, leaving
committed effects. They now assert compiler refusal with no objects/history; SQLite's
wrong-owner route similarly refuses before execution rather than depending on rollback.
The endpoint guards are unchanged. This moves a knowable construction-authority error
earlier, not evidence that old endpoint checking falsely completed those examples.

No new vocabulary/version: valid format2–8 artifacts retain identities. Actual archived
`2b596f5` compiler/reader accepted a format2 package constructing `unowned` while
recording/quoting `entries`; the fixed artifact now explicitly refuses at load. Its
valid companion retains bytes/digest and deploys model-free with id42. An isolated
copied-source counterfactual bypasses this gate and reproduces acceptance without
mutating working sources during native suites. No digest/receipt rewriting or ledger
conversion.

**Not full construction/claim agreement or a SQL sandbox.** The header check does not
prove body grammar, all SQL effects, column coverage/storage/nullability/default
agreement, indexes/constraints, Unicode/native namespace behavior, privileges or
unexpected-object/FK compatibility. Reviewed SQL remains trusted executable input;
unsupported authority forms need explicit proof/refusal, not automatic repair.

## Identifier claim bindings before execution

Compilation (also invoked by package loading) rejects a table `quoted_name` that
is not one complete quoted identifier naming exactly `TableState.name`. Comments,
SQL tails, strings and unquoted names are not accepted in that executable fragment.
Every `ColumnState.name` must exactly name the first identifier in its definition.
Empty identifiers and duplicate/ASCII-case-colliding table or column claims refuse
rather than silently collapsing under dictionary projection. This conservative
collision rule does not promise equivalence for every native identifier namespace,
Unicode case behavior or deployment-specific table-name policy.

The checks include before/target snapshots, intermediate CreateTable/AdoptTable
payloads even if later relinquished, and AddColumn/ChangeDefault definitions. An
otherwise-unused bad executable name cannot be certified on initial creation for
later use by an alteration. This is not a SQL sandbox: reviewed construction SQL
remains trusted executable input, and these identifier bindings do **not** prove
complete declaration agreement, physical
nullability/storage/default consistency, index/constraint binding, publisher
authentication or general construction/claim agreement. Header binding is now checked
as described above; remaining facts need separate proof
or pre-effect refusal in subsequent work.

No new wire vocabulary/version: valid packages retain format2–8 identities. Fixed
artifacts from real writer `3456c05` preserve one valid format2 dump and explicitly
refuse another that the old writer/reader accepted with `quoted_name="unowned"`
while constructing `entries`. Loading does not rewrite its digest or receipt. A
counterfactual in an isolated copied source tree bypasses the gate and reproduces
acceptance; the working source is not mutated during native suites. Reader
tightening is explicit refusal, not general backwards compatibility or conversion.

## Explicit named CHECK removal and bounded replacement

`DropCheck(table_name=..., check_name=...)` authorizes exactly one recorded bounded
named table CHECK. Omission or changed declaration produces an unresolved decision;
`draft.resolve(DropCheck(...))` supplies exact-name authority before dependent changes.
No implicit removal of inline/unnamed/JSON-alias/unowned constraints, primary/unique
keys or foreign keys. Ambiguous recorded names refuse. Only surviving-then-new
ordering is derived; arbitrary constraint reordering remains unsupported.

SQLite removes the identified declaration through the observed-definition rebuild,
retaining other constraints, values/defaults and unmanaged BLOB/index/view/trigger.
A later nullable rebuild cannot resurrect the removed rule. Same-name replacement
composes DROP with AddCheck: invalid old data rolls the entire SQLite package back,
including its receipt and old CHECK. Explicit data correction allows original-plan
retry without copying through insert triggers.

Native ALTER TABLE DROP CONSTRAINT is **not intrinsically CHECK-specific**. A real
owned-server probe found that an implicitly named FK sharing the CHECK name was
removed instead, leaving the CHECK behind. Endpoint refusal alone was too late.
Preparation now refuses observed ambiguous constraint types, and every DROP rechecks
`information_schema.TABLE_CONSTRAINTS` for exactly one CHECK before executing.
Missing metadata is never permission to DROP. Constraints created earlier in the
package are checked when materialized; refusal can leave those earlier authorized
CREATEs committed/acknowledged, but does not execute the unsafe DROP. Recovery also
refuses such an unverifiable next step rather than offering it as retryable. Tests
learn actual native implicit names, not version-dependent naming guesses.

An acknowledged native DROP followed by rejected ADD leaves a real constraint gap.
Data correction permits ADD-only retry, not replaying DROP. Lost DROP receipts stay
ambiguous even if the old CHECK is absent; no CHECK-aware structural reconciliation
or automatic repair. The native boundary is not an atomic replacement/rollout.

Explicit removal adds a negative endpoint claim: the old named CHECK must be absent
and its physical owner available, even after relinquishment. Same-name replacements
are excluded from the absence set and verified positively in the managed target.
Skipped-DROP counterfactuals previously falsely completed on both backends after
relinquishment. SQLite now rolls back, while native uncertainty remains and recovery
finish refuses. These are name-scoped claims, not a promise that no other constraint
restricts the same values. General unexpected-object, privilege-visibility and
cross-schema/application dependency guarantees remain separate.

**Format 8** carries `drop_check` and `removed_checks`; formats 2–7 refuse either,
even empty metadata. Older routes omit the field and keep identities. Archived
`84574ce` refuses new backend artifacts; format4/5/6/7 artifacts remain byte-identical
and fixed format2/3 fixtures pass. Model-free SQLite format2→7→8 deployment preserves
42/default7 and accepts -1 after removal. No ledger conversion or retrospective
certificate. SQLite removal/relinquishment/readoption and native removal/relinquishment
are covered, not all mixed ownership workflows.

The bounded common-change slices now include these CHECK routes. Broader
construction/claim authority, negative-ownership/drift and FK compatibility,
workflow/interruption coverage, resource bounds and compiler/codec/ledger evolution
remain open. No production-readiness, merge/release authorization or user guides.

## Required-to-nullable relaxation

`AllowNull(table_name=..., column_name=...)` removes an ordinary recorded NOT NULL
constraint; generation derives it for supported required-to-nullable changes.
It changes nullability and the historical query type, not storage, default, or
existing values. A separate `ChangeDefault` can compose with it. SQL NULL inserts
are exercised after application, independently of old rows and omitted defaults.
Other constraints, triggers and application policies are not bypassed by relaxing
the declared NOT NULL fact.

This is bounded to an explicit, unnamed NOT NULL in an ordinary column declaration.
Keys/auto-increment, generated clauses, inline UNIQUE/FK/CHECK or named constraints,
recorded table-tail references to the column, and lexer comments require an adapter.
Lexer comments are distinct from a SQL COMMENT attribute. The implementation is
not a general constraint rewrite/equivalence engine. Opposing nullability operations
on one column require a checkpoint rather than collapsing into an ambiguous group.
A later explicit DropColumn does not emit MODIFY for the removed column.

SQLite uses the observed-definition rebuild and existing copied-value/identity
checks. A later conflicting UPDATE rolls back relaxation, default change and receipt;
explicit row correction permits the original-plan retry. Native groups use MODIFY
with the final definition, including a composed default removal, without a redundant
ALTER DEFAULT clause for the same column. These tests preserve scalar values,
retain/change/remove defaults and permit subsequent NULL writes in the tested routes.

**Format 4** adds `allow_null` and the `relaxed` contraction metadata. Empty metadata
is omitted for older routes. Formats 2/3 explicitly refuse the new vocabulary; an
actual archived `5b2b891` reader refuses both new backend artifacts as unsupported
version 4. A separate model-free SQLite process deploys format 2 then format 4.
Existing frozen formats 2/3 retain their identities; no automatic conversion or
ledger-layout change is introduced.

Lost native relaxation receipts remain ambiguous. The older require/drop catalog
projection cannot certify relaxation: a counterfactual removing its new guard
incorrectly offered reconciliation after a column drop while the retained column
was still NOT NULL. Even a correct changed endpoint is not a receipt or a newly
supported structural reconciliation. This slice adds no native repair or total
interruption/resource guarantee.

## MariaDB managed table and column checks

Before recording a new completion, MariaDB requires every table in the target
managed scope to resolve to an observed base table. A missing table or a view with
the right name does not satisfy that claim. This does not restrict query-only
model mappings to views; mapping and ownership remain separate.

The runner asks the server to resolve each declared name with SHOW CREATE TABLE
and matches its normalized definition to the observed base-table catalog. It does
not implement identifier folding in Python: on a lower-case-table-names server,
SHOW's name column can echo the requested spelling while the definition contains
the physical name. Existing AUTO_INCREMENT counter normalization is reused so
ordinary inserts do not change structural identity.

Once a claimed base table resolves, the runner reads its physical column names
with SHOW FULL COLUMNS and asks MariaDB to resolve the declared names against a
constant derived-table namespace containing exactly those observed names.
The probe returns one row of constant metadata-row keys, binding the observed
nullability, type and collation metadata by name without selecting application data. This avoids reimplementing native identifier case rules or
parsing localized driver messages.
It also prevents the native `_rowid` pseudo-column from satisfying a physical
column claim merely because a primary key exists. Real physical columns with
that spelling, including INVISIBLE columns omitted by SELECT *, remain supported.

Escaped identifiers and different physical name casing remain supported. Metadata
must be visible to the migration connection; unrelated server errors propagate
rather than being mislabeled as missing columns. This is not a data SELECT or an
application-permission check.

Each resolved nullability flag must exactly match the recorded column: an absent
NOT NULL attribute and an unrequested NOT NULL attribute both reject completion.
Flags bind by server-resolved names, not physical column order; differing casing,
invisible columns and implicit primary-key NOT NULL metadata remain supported.
Missing, unsupported or ambiguous metadata stops rather than being guessed.

This checks the server's nullable/not-null attribute, not equivalence through CHECK
constraints, defaults, expressions or SQL modes, and it does not inspect stored
values. Storage types are also compared using a bounded declaration-prefix grammar:
recognized aliases, non-ZEROFILL integer display widths and implicit parameters
normalize, while storage families, character/binary lengths, decimal precision and
scale, temporal precision and signedness must match. Unsupported recorded types or
modifiers fail preparation before DDL; unsupported observed types block completion
and finish recovery. ZEROFILL, enum/set, mode-dependent REAL and binary-charset
conversion declarations require explicit support rather than guesses. The understood
character-set/collation modifier syntax is restricted to emitted utf8mb4 forms;
this is not a general SQL parser or a collation-equivalence engine.

Explicit supported type-prefix collations must now match SHOW FULL COLUMNS metadata.
JSON also requires its implicit utf8mb4_bin collation unless the supported prefix
explicitly overrides it. Names are compared in canonical spelling; unimplemented
alias equivalence is not inferred. Bare character types without a recorded collation
do not acquire a claim on deployment-dependent defaults. Additional COLLATE syntax
outside the supported prefix, including expression uses, stops preparation rather
than being guessed; quoted defaults/comments are not mistaken for declarations.

AUTO_INCREMENT must also match the name-bound EXTRA metadata in both directions.
A primary key alone does not prove a generator, and an unrequested generator does
not satisfy a nongenerating column claim. Recognition is bounded to the understood
attribute prefix; ambiguous occurrences after unparsed attributes fail preparation.
Column names, quoted literals and nested expressions do not become generator claims.
This does not verify counter values, gaplessness, allocation policy, triggers or
sequence-backed defaults; ordinary inserts may advance the counter without drift.

Primary keys are checked separately from uniqueness and AUTO_INCREMENT. Inline
column claims and ordinary CREATE TABLE table-level primary-key declarations
resolve to an ordered list of physical column names through the same server-bound
namespace. SHOW INDEX must report exactly that primary key (or no key if none is
claimed), with full ascending columns. Missing keys, keys on different columns and
unrequested keys block completion and finish. Composite keys preserve declared
member order, not column order; escaped names and native name casing are supported.
Prefix lengths, descending/expression keys, unsupported options and conflicting
primary-key declarations require explicit support rather than normalization guesses.
This adds verification, not general primary-key alteration authoring or secondary
index/foreign-key equivalence checking.

JSON aliases also require a recognized CHECK (JSON_VALID(column)) in the
server-resolved SHOW CREATE TABLE definition. Both inline and named table checks
are understood, with harmless outer parentheses. Check references bind through the
same physical-column namespace; a check on a different column is not proof. Quoted
comments, constants such as JSON_VALID('true'), weakened OR expressions and
unrecognized equivalent expressions do not certify the contract. Unsupported native
rendering is no evidence of a required check.

Explicit literal ENGINE options are compared to the already server-resolved SHOW
CREATE TABLE definition. Case-insensitive engine names and the known HEAP/MEMORY
and MERGE/MRG_MyISAM aliases normalize; quoted literals are supported. Column names,
comment text and nested partition options are not table-engine declarations. Missing
ENGINE options make no fixed claim about deployment defaults. Duplicate options,
expressions and ENGINE=DEFAULT require explicit support; the latter is not accepted
as an omission. Substitution in either direction and hidden/unsupported engine
metadata block completion and finish. NO_TABLE_OPTIONS can therefore leave committed
DDL uncertain rather than allowing completion without engine evidence. This proves
engine identity, not row format, encryption, engine capabilities, data durability or
transactional recovery eligibility; existing InnoDB recovery prerequisites remain.

Explicit secondary indexes in TableState.indexes also require matching native
SHOW INDEX facts: ordered column members, exact prefix lengths, uniqueness,
ascending direction, BTREE type and non-ignored state. IF NOT EXISTS is only an
execution guard; an occupied name with another shape does not certify completion.
Column references bind through the native physical-column namespace, independently
of primary-key and JSON-check references. Index names currently require exact
observed spelling, and ON-table names must match the recorded table spelling;
identifier alias equivalence for those names is not inferred. Expression/descending
indexes, FULLTEXT/SPATIAL, extra options and other unsupported declarations fail
preparation. Unlisted and inline-only secondary indexes remain outside this check.
Prefix/full-column equivalence beyond exact native metadata is not guessed.

Recorded columns also require matching ordinary, virtual-generated or
stored-generated kinds from SHOW FULL COLUMNS EXTRA metadata. The bounded
AS(expression) clause supports optional GENERATED ALWAYS, implicit/explicit VIRTUAL
and STORED/PERSISTENT aliases. Quoted names/literals and nested expression AS words
are not generation attributes. Ambiguous positions or conflicting storage kinds
fail preparation. Comparison uses the same native column-name binding as other
column facts, not physical order. This does not compare generating expressions,
audit generated values or prove all write/enforcement behavior.

Column visibility must also match the native INVISIBLE flag in either direction;
physical name resolution alone does not establish wildcard/positional visibility.
The bounded declaration reader distinguishes an INVISIBLE attribute from quoted
names, literals and parenthesized expressions. Simple literal or parenthesized
defaults are supported before the flag; unparsed attribute positions, repeated
flags and explicit VISIBLE syntax require explicit support. Absent INVISIBLE
records ordinary visibility. Comma-separated native EXTRA attributes retain each
fact, including generated/auto-increment columns that are also invisible. This
checks visibility metadata, not privileges, query results or all write behavior.

Automatic temporal updates are also checked independently of defaults. Bounded
DATETIME/TIMESTAMP ON UPDATE CURRENT_TIMESTAMP clauses require matching native
EXTRA metadata; absent and unrequested clauses differ in either direction, including
precision zero. Omitted arguments and empty parentheses inherit column precision;
explicit precision must match it. Native metadata is read separately from other
comma-delimited attributes. Literal/comment text and nested expressions are not
clauses. Other function spellings, arbitrary expressions, ambiguous attribute roles
and unsupported precision require explicit support. This does not verify defaults,
clock/timezone semantics, actual timestamp values or general write behavior.

Explicit DEFAULT NULL claims on nullable columns now require SQL-NULL native
default metadata. Bare and parenthesized NULL are recognized; implicit NULL on a
nullable column is equivalent for this bounded check. A non-NULL scalar, including
the string 'NULL', cannot satisfy it. Nonnullable NULL claims, duplicate defaults
and ambiguous NULL attribute positions fail preparation. Generated integer/Boolean and UTF-8 text literal defaults, plus the compiler's
DATETIME and text CurrentTimestamp forms, now receive a bounded endpoint check too.
Comparison uses quoted SHOW CREATE column definitions bound through native column
metadata, not ambiguous SHOW COLUMNS default text. NULL, the string 'NULL', and a
literal spelling of a clock expression remain distinct; text comparisons do not
borrow case-insensitive column collations. Known UTF-8 hex CONVERT renderings and
parentheses normalize without evaluating SQL. Unsupported default expressions or
storage combinations now fail preparation instead of remaining unclaimed.
Clock/timezone/value semantics remain outside
this check. Adding a defaulted column or changing a default is still not a newly
supported migration operation merely because initial creation verifies it.

MariaDB CHECK creation now supports the compiler's finite expression language:
comparisons, NULL predicates, membership, BETWEEN, NOT and ordered boolean
composition with encoded integer/Boolean/text literals. Quoted native definitions
are compared through bounded expression trees; only known NOT/association and
singleton-IN renderings normalize. Declared names and expression multiplicity are
retained. Unknown expressions still fail preparation; this is not arbitrary SQL
or logical equivalence. Redundant recorded column CHECKs must be present in the
construction SQL with matching expressions, counts and explicit names.

The existing JSON_VALID proof remains a separate exemption for recorded JSON
columns; its constraint names and multiplicity are still not claimed. Other-column, constant or
weakened JSON predicates remain rejected. SQLite CHECK comparison is unchanged.
Native expression rewrites that cannot prove the recorded tree block completion
and recovery finish, leaving committed effects and uncertain history. The native
HIGH_NOT_PRECEDENCE scenario exercises this through application and reopened
recovery; removing the endpoint guard makes the test fail.

The new non-JSON CHECK expressions are limited to 4,096 tokens, 32 inner
parenthesis levels and 64 parsed tree levels before recursive normalization.
A 4,096-unit weighted traversal budget additionally doubles subtree weight under
NOT, conservatively refusing repeated-negation workloads before normalization.
These are experimental
expression limits, not whole-artifact size, database-operation deadline or memory
limits: tokenizing the complete DDL, catalog observation and other package work
remain outside this resource bound, as does the pre-existing JSON predicate
recognizer. Matching CHECK definitions does not prove
session enforcement, privileges, existing data correctness or deployment readiness.

Foreign-key definitions are compared against the already server-resolved SHOW CREATE
TABLE definition. Ordinary table-level declarations and simple inline references
from recorded ColumnState definitions contribute ordered local/referenced members,
unqualified target tables, actions and multiplicity. Native generated constraint
names are not relationship identity. Immediate NO ACTION/RESTRICT and omitted
actions normalize; CASCADE and SET NULL are supported. Missing, unexpected and
mismatched relationships block completion and finish, including engines that
accept but discard foreign-key syntax. Identifiers currently require exact
observed spelling; native alias equivalence is not inferred. Cross-schema targets,
MATCH, SET DEFAULT, unsupported members/options and inline action syntax need
explicit support. This does not audit existing rows, constraint names or session
enforcement such as foreign_key_checks.

Referenced targets must also resolve to definitions in the same observed BASE TABLE
catalog before completion or finish. A dangling relationship or a view with the
referenced name is not sufficient, even when foreign_key_checks=0 allowed its
creation. Checking an unmanaged parent does not acquire ownership. Existing
AUTO_INCREMENT-counter normalization allows ordinary parent inserts without schema
drift. Referenced storage must also be provably InnoDB in that server-resolved
metadata; a present MyISAM/MEMORY parent or hidden/unsupported engine rendering is
not sufficient. This condition applies to referenced parents, not unrelated
unmanaged tables, and does not acquire ownership. NO_TABLE_OPTIONS can therefore
leave completion/finish uncertain even with correct actual InnoDB storage. This is
base-table availability and bounded engine identity, not independent referenced-
column/index/type compatibility, engine-property verification, data auditing or
session-policy proof.

Known unsupported native rendering: MariaDB 12.2.2 can emit an unescaped backtick
in SHOW CREATE foreign-key column names. Malformed base-table catalog SQL raises
PackageError naming the object, rather than leaking a tokenizer SchemaError or
guessing repaired SQL. Preparation creates no history. If malformed metadata is
observed after committed DDL, history stays uncertain, application cannot replay
it, and recovery inspection itself raises PackageError: no Recovery disposition
can be justified from an unreadable catalog. status() remains available. An
isolated native 12.2.2 test exercises these refusals; the escaped-name test still
requires completion on engines rendering valid SQL. The test recognizes the
specific malformed native output, not a version skip or blanket expected failure.
This is supported refusal, not support for executing/recovering that schema on
the affected renderer. No automatic SQL repair or server/session-mode change is
performed, and upgrading a server does not itself authorize recovery.

These remain bounded **presence, object-kind, nullability, storage-type, recorded
collation, AUTO_INCREMENT, primary-key, JSON-check-definition, engine-identity,
listed-secondary-index, generation-kind, visibility, automatic-temporal-update,
foreign-key-definition and supported-default checks**, not full native schema
verification. JSON constraint presence/shape is not an audit of stored
values or a guarantee that application sessions leave check_constraint_checks enabled.
Application JSON shape/codec compatibility also remains separate. General omitted-write behavior, charset-only declarations without a recorded
collation, other unclaimed constraints, unlisted index facts, engine properties, codecs and values remain unverified. Construction SQL remains
trusted executable input, not a sandbox.

Unlike SQLite, rejected completion cannot roll back already committed MariaDB
DDL. The actual object and acknowledged steps remain, progress stays uncertain,
and the error warns that committed effects may remain. An otherwise all-steps-
acknowledged recovery also checks this guard before offering `finish`; a failed
table, column-name, nullability, storage-type, collation, AUTO_INCREMENT, primary-key, JSON-check, engine, listed-secondary-index, generation-kind, visibility, automatic-update or foreign-key claim
yields `ambiguous`, and resume cannot bypass it. There is no automatic repair, cleanup, force-completion or history rewriting.
Earlier records already
marked complete are not re-certified by this change. Empty relinquished scope
does not re-adopt old tables.

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
unsupported transitions and additional drift stay `ambiguous` when observations
can be collected. Unreadable catalog SQL instead prevents inspection with
PackageError as described above; there is no
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

Retained columns are compared in bounded batches instead of doubling the entire
table width in one SELECT. Every batch repeats the complete hidden or natural
identity, so unchanged value sets cannot conceal values moving between rows.
Wide rowid and WITHOUT ROWID fixtures retain all 1,000 unmanaged extra columns;
a late-column generated-value swap is rejected even though its value set is
unchanged. The runner reads the full primary key from SQLite metadata rather
than guessing it from the SQL recognizer.

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
This adds a source/destination scan and SQL set comparison per batch. It bounds
ordinary projection growth, not total work: large tables and very wide composite
identities remain subject to SQLite statement and resource limits, with failures
rolling back rather than bypassing validation. It checks current SQLite value semantics,
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
| Nullable addition | Ordinary additions supported; nullable defaulted additions require explicit `defaulted_additions="leave_null"`, preserving old NULLs rather than backfilling |
| Default changes | SQLite rebuilds and bounded native SET/DROP DEFAULT; required composition and acknowledged native recovery tested; lost native default receipts remain ambiguous |
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
| Required-to-nullable relaxation | Bounded AllowNull on both engines, default composition and SQLite rollback; coupled constraints refused and lost native receipts remain ambiguous |
| Required-column enforcement and explicit column removal | Executed on both engines; populated full SQLite expand/backfill/contract route tested; rename and dependent-object changes remain unsupported |
| Long resumable backfill | Unimplemented; only individual bounded UPDATE operations |
| General custom SQL / Python | Unimplemented; typed UPDATE output only |
| Historical codec/compiler evolution | Formats 2/3/4/5/6/7/8 checked against their operation vocabulary; fixed old-writer creation/addition/contraction fixtures retain identity; no general codec or long-term compatibility promise |
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

## Hardening gates before production integration

These are remaining engineering gates, not a release announcement or an expanded
support promise. Use these gates to select further verification work rather than
extending individual checks indefinitely. The
[contract inventory](recorded-migrations-contract-inventory.md) maps the generated
physical facts to actual verification, rejection and remaining gaps; it proposes
generated defaults and CHECKs as the next priorities, not arbitrary SQL equivalence:

1. **Native compatibility:** complete the current-revision backend matrix. Treat
   known malformed metadata as an explicit refusal contract; do not equate a
   green refusal test with support for that schema on that server.
2. **Bound the initial contract:** inventory the physical facts generated by the
   existing model API against the verifier. For each fact, record verified forms,
   preparation-time rejections and still-unclaimed semantics. Decide which
   unclaimed forms must be rejected before a production proposal. Ordinary
   literal defaults and general constraints are immediate gaps; arbitrary SQL
   equivalence is not the target.
3. **Bound ownership and recovery:** retain SQLite-only adoption unless MariaDB
   adoption receives its own proof. Exercise complete create/backfill/contract,
   relinquish/re-adopt and interrupted native deployment routes; neither an
   unreadable catalog nor an uncertain receipt permits automatic replay.
4. **Deployment compatibility:** specify compiler/package compatibility and
   history-evolution policy, deployment without model imports, coordination
   prerequisites and resource limits. No silent experimental-ledger upgrade.
5. **Readiness review:** complete broad validation and review the public API and
   module boundaries before production integration. Schema completion remains
   distinct from data/application readiness. User-guide work remains deferred.

### Executable model-free route coverage

A separate-process native test now loads frozen packages without importing the
application model module. It creates a table with an integer default, inserts a
row omitting that field, adds an unconstrained nullable column, backfills it,
requires it, and confirms the original default still works for another insert.
It then commits one non-idempotent increment, encounters a transactional key
conflict, reconnects after an explicit application-data repair, resumes only the
unacknowledged work, and relinquishes ownership without deleting the data. The
final count proves the acknowledged increment was not replayed.

This is one bounded route, not a claim that all recovery windows, deployment
versions or power-loss cases are covered. Defaulted nullable additions remain
unsupported; the test deliberately does not extend that operation. Existing
SQLite adoption/relinquishment/re-adoption coverage remains separate. Compiler
and ledger evolution policies, broader adoption and resource limits are still
open hardening gates.
