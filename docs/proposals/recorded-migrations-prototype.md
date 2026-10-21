# Recorded-state migration prototype (#477)

Status: **experimental, incomplete, not ready for production or merge**.

This implements the first vertical slices of the design discussed in #475,
replacing the function-only direction in draft #476. The prototype lives in
`snekql.experimental.migrations`; existing migration interfaces are unchanged.
Artifact format 1 is provisional. No compatibility or adoption path from another
migration history format is promised.

## The four interfaces

1. `generate(revision, models, backend=..., previous=...)` produces an immutable,
   editable `Draft` against the previous package's recorded managed state.
2. `compile(draft)` checks the route and produces a `Package`. `dump()` and
   `Package.load()` round-trip state, structured changes, frozen SQL, encoded
   scalar bindings, transaction flags and a content digest. `package.check(draft)`
   verifies that a supplied current draft still matches its committed artifact.
3. `target.prepare(package)` observes the target without creating history and
   returns an inspectable `Prepared` plan. MariaDB requires the caller to assert
   `schema_writers_excluded=True`; advisory locking cannot enforce that promise.
4. `target.apply(prepared)` checks history and observations under coordination.
   `target.status()` exposes completion or uncertain progress and the number of
   acknowledged statements. It is not application readiness verification.

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

## Current execution behavior

- SQLite uses a writer transaction for the entire package, including progress
  and completion. This prototype never rebuilds tables.
- MariaDB records `started` durably before operations. DDL can commit implicitly.
  Each typed UPDATE and its acknowledgement run in one transaction; this is not
  a single transaction spanning several UPDATEs or DDL.
- An acknowledgement is persisted after each successful statement. DDL may have
  committed before an acknowledgement was written. `acknowledged_steps` is a
  lower bound on recorded successful work, not proof later work had no effect.
- Incomplete MariaDB progress blocks further application, including requests to
  reapply an earlier completed revision. There is no automatic resume, repair or
  operator acknowledgement interface yet. Do not delete the ledger to retry.
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
| Interrupted MariaDB DDL | Partial progress blocks replay; evidence survives native server kill/restart |
| Brownfield ownership transfer | Unresolved/rejected, not implemented |
| SQLite preservation-sensitive rebuild | Unimplemented; alterations beyond supported nullable additions stop |
| Required-column enforcement, rename, DROP | Unimplemented; full is_admin-to-required-role contraction remains pending |
| Long resumable backfill | Unimplemented; only individual bounded UPDATE operations |
| General custom SQL / Python | Unimplemented; typed UPDATE output only |
| Historical codec/compiler evolution | Scalar-only declarations; reader revalidates version-1 operations; no long-term compatibility promise |
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
uv run snektest tests/experimental
uv run ty check
uv run ruff check .
uv run ruff format --check .
```

Do not run two suite invocations concurrently if both use the existing shared
`tests.helpers.provide_mariadb_server` data directory.
