# Real role-migration interruption and operator coordination (#477)

Engineering fixture, not consumer guide/release promise. Actual standalone processes and
observed engine locks; no injected exceptions, production-step callbacks, mocks, custom sleep
functions, edited ledger rows or hand-built migration states. No production-code changes.

## Actual authored route

Same visible Initial/Expanded/Account declarations and revised typed historical backfill as
the role journey. Three REAL release revisions:001 create,002 nullable role expansion,003
initialize roles/classify admins and advance to required role/drop old flag. Advance owns
stage composition; no synthetic intermediate revisions/packages or DTO stitching. Actual
historical.py is generated, statically imported, and the rendered programs ty checked.

Frozen format2 JSON in sqlite/ and mariadb/ is emitted by39ff0e0 production code. Compare
literal author dumps, then deploy COMMITTED bytes after deleting author directory. The runner
imports no models/historical/backfill/current application. Original Prepared JSON is saved
before apply, reused UNCHANGED across native process/server restart, not reconstructed from
observed endpoint or rewritten to match a fresh plan.

## SQLite DELETE-journal transaction death and retry race

Fresh experimental migration connection preserves default DELETE mode. A separate reader
holds an actual read transaction. A separate OS-process probe observes SQLITE_BUSY while the
active migrator holds its write journal and attempts exclusive access. Kill the migrator
(SIGKILL), release reader: hot-journal rollback leaves original flag rows/NULL role, durable001/
002 and NO003 receipt. Fresh public prepare/apply is appropriate; two operators prepared
before either applied converge to one applied/one already_applied. Current typed app separately
verifies, reads admin/user and inserts user.

This is NOT a WAL-mode active-backfill death experiment. Ordinary SQLite application runtime
uses WAL; the final app connection may switch mode AFTER this exercise. That does not turn
this DELETE-mode evidence into WAL proof. No claim about every possible kill instruction,
spill/cache/durability mode, power loss or filesystem behavior.

## Native partial backfill, server restart and two resumers

Own private InnoDB server only. A real external row lock holds account2; metadata observes
our first UPDATE in LOCK WAIT with trx_rows_modified>=1 (account1 already changed INSIDE the
uncommitted data transaction). An ordinary typed writer commits42 to unrelated unowned
InnoDB audit_log WHILE the migrator remains blocked. It does not participate in migration
advisory locking: this lock is neither fencing nor an application pause.

Kill only our migrator child; release blocker, observe its server connection disappear and
both roles roll back to NULL. The expanded002 schema stays committed;003 durable receipt is
uncertain with acknowledged0. Kill the OWNED server, restart same data/socket identity:
uncertainty and unrelated committed write survive. Ordinary prepare/apply refuses; operator
must inspect ORIGINAL Prepared evidence and explicitly resume retry_remaining. Two operators
assess before either resumes: one applies, other is refused because no unique incomplete
execution remains. Loser reports complete status and REASSESSES, not replays; separate fresh
terminal apply reports already_applied. Current app verifies/reads/inserts normally.

Kill was during transactional backfill; server kill was AFTER client disconnect/rollback,
with durable uncertainty. NOT a server-killed-in-COMMIT test or lost DDL-receipt/structural
reconciliation experiment. Final contraction executes normally during explicit resume.

## TDD and scope

Operator-program REDs: native inspect_recovery on SQLite is refused; ordinary retry after
native uncertainty is refused. Backend-specific caller retry versus inspect/resume paths make
the actual journey pass. These are safe interface refusals, NOT new library runtime defects.
Static Optional-plan/dead-branch corrections, same-process SQLite shared-lock reuse (external
probe required), InnoDB metadata cache polling, formatting/type/expectation corrections and
an initially timed-out runner are fixture/audit issues, not product defect evidence.

Advisory coordination only protects participants; schema-writer exclusion is a truthful caller
assertion here. An unrelated-table data writer is NOT proof that concurrent old-schema account
writers are safe through backfill/contraction. Data/codec/domain readiness remains separately
checked. Plan persistence uses current public Pydantic representation, no stable versioned
Prepared wire ABI promised. WAL active death, other receipt-loss windows, noncooperating schema
writers/privilege/session changes/fencing/resource bounds and finite product/backend/version/
recovery/release/ADR/partial-adoption/compiler-epoch scope remain open. Trusted SQL, guides
deferred, draft/incomplete/not production- or merge-ready.
