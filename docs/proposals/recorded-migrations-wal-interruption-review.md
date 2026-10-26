# Recorded migrations: actual WAL backfill process death (#477)

Status: **bounded local G4 failure-window checkpoint**, not maintained-environment matrix or
G5/release approval. Follows [retained cleanup](recorded-migrations-retained-cleanup-review.md).

## Public journey and why this is WAL evidence

`test_migration_wal_interruption.py`, normal/FULL cases, uses the visible role authoring programs:
actual generate/checkpoint/generated historical typed UPDATE/advance/compile, ty check,
byte comparison to literal001/002/003 and removal of authoring sources. Mapping remains separate
from ownership; the deployment worker imports no current/historical application declarations.
No artifact/declaration-state fabrication or new public/runtime/format/layout selector.

Caller applies001, seeds typed-compatible flags1/2, applies002 and arranges real external audit
policy before preparation. A retained SQL trigger on row1's user-role UPDATE inserts65,536
512-byte audit payload records and records actual UPDATE-session synchronous. Audit/workload
objects remain UNOWNED; initial audit sentinel is retained. This is real SQLite SQL, not a
migration callback/UDF/mock or injected driver behavior. It creates a measurable spill window,
not a product requirement for this audit volume or an application-readiness proof.

Prepare003 with explicit preservation on THIS database, then caller writes ORIGINAL envelope
with restrictive permissions/file fsync/atomic rename/directory fsync BEFORE execution. This is
local evidence retention across client death, not power-loss/backup/authentication certification.
Checkpoint/TRUNCATE the actual WAL, pin an independent reader's old snapshot, start unchanged
frozen ORIGINAL work in a real model-free process. No migration step is intercepted.

After actual WAL growth, controller SIGSTOPs its OWN writer and confirms every real Linux
thread stopped. Read stable WAL bytes and validate actual header/frame salts/checksums before
interpreting only local leaf records matching the visible audit schema: rowid/piece, account1,
512 zero bytes, and actual NORMAL1/FULL2. Require positive audit records, no valid COMMIT frame
and an early spill below half the planned payload volume. Ignore an interrupted incomplete tail,
never invent completion/commit markers or accept a checksum-invalid page as data evidence.

This positively proves frozen role UPDATE-trigger execution/uncommitted physical spill, NOT a
writer merely waiting in BEGIN. It is not an instruction-pointer assertion or chosen COMMIT-call
boundary: a pending apply/absence of client output alone would not have proved active data work.
The reader and another fresh observer still see NULL roles/old receipts/only sentinel audit row.
Kill/reap the actual stopped client with SIGKILL, with no cooperative rollback or normal cleanup
BEFORE kill. Keep database/WAL/readers rather than substitute a copied target.

## Restart and unchanged original application

Fresh independent connection reads WAL mode/integrity/NULL roles, ALL own earlier001/002 columns
and only original sentinel: spilled uncommitted audit/role/003 work is not accepted as completion.
Physical uncommitted bytes may remain in the WAL until reuse/checkpoint; rollback/logical rejection
is not file deletion, secure erasure or a claim that the captured bytes vanished at SIGKILL.
Public sorted status has001/002 complete and NO003. This SQLite atomic absence differs from native
uncertain-progress recovery; do not demand native inspect/resume or manufacture a failed receipt.

Fresh deployment process reloads SAME saved original on SAME database and applies once. The still-
pinned WAL reader continues to see old flags/NULL roles despite successful writer COMMIT; unlike
DELETE-mode reader blocking, this reader does not block writer completion. End reader snapshot
explicitly and observe exactly65,536 audit rows with actual requested synchronization plus old
sentinel/workload/schema definitions/ALL earlier own receipts unchanged. Public original apply
returns already_applied and sorted complete progress. Separate ordinary typed current app
verifies its mapping, reads1admin2user and inserts/reads3user. Original/package bytes unchanged.

## Qualification, not a manufactured runtime fix

Initial public run reached the final ordinary application correctly; the test's raw JSON-output
comparison mistakenly omitted stdout's newline. Correcting the observer to parse JSON yielded
one passing case on EXISTING runtime, then both policies passed. That formatting/setup error is
not a runtime RED. All production files remain unchanged against6877111; no fabricated defect,
production patch/error, archive comparison or retrospective receipt upgrade is claimed.

Known physical WAL effects + actual process death + independent fresh state + original reuse
are the seam. The finite checksum/leaf observer is test-only, not a new generic WAL-recovery or
catalog-verification implementation. No fsync bypass/server replacement/environment download,
new dependency or broad parser/capability operation is needed.

## Remaining scope

This selects local Linux/default asyncio/GIL CPython3.15.0, SQLite3.53.1/aiosqlite0.22.1 and owned
external disk-backed files, requested NORMAL/FULL. It does NOT qualify SQLite3.45.1, other filesystems/
OS/interpreters, power loss/host death/storage honesty/torn writes/ledger loss, every signal/transport,
native COMMIT/DDL outcomes or global loop shutdown/failed physical close. WAL readers are snapshot
observers, not writer exclusion/fencing or a business-readiness mechanism. Caller continues to
exclude incompatible/schema writers and retain original evidence.

At this local checkpoint G4 still needed the maintained finite environment/native DDL window.
The later [G4 qualification record](recorded-migrations-g4-qualification-review.md) now completes
that finite set: BOTH SQLite builds/normal-lazy/NORMAL-FULL WAL death, all four exact native LTS
builds/normal-lazy with actual ALTER OK loss, plus final broad validation. That is later evidence,
not a retrospective stronger certificate for these initial local runs. G3 lifetime adequacy and
G5 names/interface/ADR0023/coexistence/release approval remain open. Consumer guides deferred;
experimental/draft, not merge/release-ready. No merge/tag/publication or released migration/
initialization change.
