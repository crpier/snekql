# Recorded migrations: versioned original prepared evidence (#477)

Status: experimental implementation checkpoint, **not production/merge/release approval**.
Follows the [supported-scope proposal](recorded-migrations-supported-scope.md). This is a bounded
execution/recovery-contract slice, not another catalog-parser expansion or a completed compiler
independence claim. Query mapping remains independent of ownership; consumer guides deferred.

## The interface and its meaning

`Prepared.dump()` exports a canonical JSON integrity envelope; `Prepared.load(text)` validates
it without opening a target or re-lowering its steps. Callers retain the ORIGINAL evidence
before native apply and load it in replacement workers before inspect/resume. No CLI, storage
manager, source discovery or general compatibility framework is added.

The first envelope has exactly `version`, `prepared` and `digest`. Version is the explicit JSON
integer 1, not a Pydantic default/coercion. The payload includes explicit execution_epoch=1,
package, original target/catalog identities, ordered execution steps and preservation choice.
The catalog observation is represented by its digest here; full native observation/rendering
and reconciliation evidence remains in the database ledger. This file is not a ledger backup.
The envelope digest is SHA-256 over canonical UTF-8 JSON of version+prepared (sorted keys,
compact separators, non-ASCII preserved), excluding digest itself. This detects changes;
trusted publishers can author another valid artifact. It is not authentication or encryption.

Execution epoch and wire version have different jobs: wire version selects decoding;
execution epoch selects permitted interpretation. New plans include epoch in their existing
ledger-bound plan digest. No column/layout conversion, package-format change, historical
package regeneration or rewriting of completed receipts follows. Only epoch 1/version 1 is
implemented; incompatible epochs/versions stop, with no automatic conversion. Raw unversioned
Pydantic JSON is not accepted as this persistence interface. Retain old incomplete evidence;
do not reconstruct a plan against an uncertain endpoint to bypass refusal.

The reader shares existing package decoding budgets: 8 MiB UTF-8 including whitespace,
64 JSON containers of nesting and 100,000 structural units, with duplicate decoded object
members rejected throughout. It checks explicit version/epoch before nested package admission,
verifies envelope integrity, validates the supplied nested package through Package.load before Pydantic plan coercion,
and refuses field omission/coercion that changes the plan's canonical representation. These
are bounded input guarantees, not whole-program resource bounds or a SQL sandbox.

Loader validation does NOT authorize execution on another target. Ordinary apply still checks
target/history/catalog/steps under existing coordination; native inspection requires the
original plan hash retained in the ledger. Unsupported epoch values also refuse at apply and
recovery admission, not merely at file import. Stronger existing safety gates remain in force.

## Actual deferred-contraction and replacement-worker journey

`test_migration_prepared_evidence.py` uses real initial/current query models and committed
framework-evolution 001/002/003 packages, with the actual generated historical typed UPDATE
already frozen by that archived writer. No fabricated states, receipt rows or declaration patches.

1. Deploy original accounts; insert two rows through ordinary typed application queries.
2. Deploy committed role expansion/backfill; independently add unowned note/default storage.
3. Prepare original deferred required-role/drop-flag rebuild with preservation explicitly on.
4. Save dump, round-trip it unchanged, and close the original migration connection.
5. A real fresh model/author-free worker loads and applies it without preparing a replacement.
   Its rendered source passes ty and inherits normal/forced-lazy mode explicitly.
6. Query current logical roles and preserved notes through ordinary typed application mapping.
   Frozen package body/digest remain unchanged, and only the new completion is added.

The committed `fixtures/prepared-evidence/sqlite-role-contraction.json` is an actual first-writer
export from that journey. It retains original deferred SQL/copy metadata, observations and
preservation choice. Its target ID is not portable; the regression loads/dumps literal bytes,
not applies that target-bound fixture elsewhere. Do not regenerate historical evidence.

Reader refusals cover incompatible/coerced/missing version/epoch, raw unversioned JSON,
changed execution/catalog/preservation data, duplicate members and input budgets. Independent
resealing demonstrates that a checksum cannot bypass nested package-version admission or
silently insert omitted step policies. Valid exported evidence still refuses a different target
without history creation. These are explicit persistence-interface checks, not new SQL proofs.

## Actual native restart and original-plan correlation

The existing real role-interruption worker now saves `plan.dump()` and resumes with
`Prepared.load`, not raw Pydantic serialization. Same three actual release revisions, generated
historical imports/typed authoring, committed packages and deleted author directory.

The real row2 lock still observes a partially modified native first UPDATE; kill only the owned
client, observe rollback and durable uncertainty, then kill/restart the OWNED server AFTER
client rollback. Replacement operators load unchanged versioned original evidence and assess
before either resumes. Winner applies; loser refuses and reassesses completed status. An
independent terminal apply is already_applied; current typed application use succeeds.

A different but internally valid/re-exported preservation choice is rejected by native recovery
because its plan identity is not the ORIGINAL ledger-bound plan; status stays unchanged. File
integrity alone cannot certify which plan was applied. No receipt editing, forced acceptance,
endpoint stamping or automatic replay. This remains a client-backfill-death/server-after-rollback
case, not server death during COMMIT/DDL, WAL death or a general lost-receipt proof.

## TDD, evidence and remaining scope

The feature RED is actual `Prepared.dump` absence after preparing the role contraction. Earlier
insert/insert_many call-signature corrections are author/test-program errors, not product runtime
defects; lint/format corrections likewise are not defect evidence. Positive replacement-worker
and refusal regressions exercise the approved package/prepare/apply/status/recovery/query seams.

Evidence root `.snektest/477-prepared-evidence/` retains separate real SQLite/native traces,
original envelope bytes, operator programs, actual row/lock observations and validation reports.
No new environment-matrix or full-suite claim follows from those selected traces.

**G1 remains open:** Package.load recompiles recorded drafts using today's compiler, and ordinary
apply rechecks current deferred lowering. Current packages have no independent explicit compiler
execution epoch. Prepared epoch admission prevents accepting a different declared plan epoch;
it does not provide historical compiler dispatch, generic downgrade fencing or future old-emission
independence. Existing 67 historical package fixtures keep their exact bodies/digests. This slice
implements the versioned-original-evidence foundation of G2 without pretending that metadata
alone finishes G1 or all cross-version recovery policy.

**Other open work:** caller storage must provide permissions, atomic/durable publication and
backup; no host/volume-loss portability is promised. Per-I/O deadlines, unsafe-connection/session/
config policy, finite maintained-version qualification, WAL and selected native receipt-loss
windows, historical-source ergonomics and final interface/ADR/release approval remain. Epoch
changes must preserve supported interpretation or refuse explicitly; no old-evidence conversion
or retrospective stronger certificate is introduced. Entire prototype remains draft/incomplete.

## Completed local validation

- 873 normal +873 forced-lazy experimental tests; 1,784 fast tests; 18 targeted normal +18
forced-lazy, including real role-process interruption/restart. All reports exited 0, with zero
failures/errors/fixture or session teardown failures. Normal/lazy native runs were sequential
with distinct external TMPDIRs and context-aware warnings; source stayed unchanged.
- Whole-tree ty/ruff/format640/diff checks pass. Actual rendered replacement-worker and typed
role authoring programs pass ty; child processes explicitly inherit forced-lazy mode.
- Actual SQLite/native traces retain original bytes, target/ledger correlation refusals,
observed modified-row wait, restart, competing outcomes and current application rows. Owned
servers/runners are finished; unrelated services/settings were not changed.
- All 67 prior experimental package JSON fixtures remain byte-identical. One new literal
Prepared-envelope reference is retained; it is not a converted/regenerated historical package.

Local environment: CPython 3.15.0, SQLite 3.53.1, MariaDB 13.0.2, Pydantic 2.14.0, aiosqlite 0.22.1,
aiomysql 0.3.2/PyMySQL 1.2.0 on Linux/default asyncio. These completed experimental suites are
not a new local full-suite, maintained-version matrix or exact-head GitHub CI success claim.
