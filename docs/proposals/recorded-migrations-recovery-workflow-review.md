# Recorded migrations: real role-recovery workflow review (#477)

Status: experimental engineering evidence, not consumer guidance or production/release scope.
No production/interface/parser/format/ledger changes. This follows actual
[framework evolution](recorded-migrations-framework-evolution-review.md) with real process
death, server restart, competing operators and an unrelated ordinary application writer.

## One representative route, distinct durable outcomes

The visible programs under `tests/experimental/fixtures/role-interruption/` reuse the actual
role journey's Initial/Expanded/Account models and revised typed historical backfill. Three
REAL revisions let expansion deploy first:001 initial table,002 nullable role addition,003
backfill/classification then required-role/drop-flag contraction through Draft.advance.
Generated historical.py is statically imported, not inferred later from current models or
hand-made states. Tests compare literal author dumps and deploy committed bytes with authoring
source removed. The model/codec-free worker saves original Prepared JSON before application.

| Observation | SQLite DELETE-journal case | Private MariaDB/InnoDB case |
| --- | --- | --- |
| Actual blocking condition | reader holds shared lock; separate-process reader observes busy/write journal | first UPDATE waits on row2; engine reports rows_modified>=1 |
| Process killed | own migrator SIGKILL during active package | own migrator SIGKILL during partially performed first UPDATE |
| Remaining schema/data | expanded002 and original flags/NULL role | expanded002 and rolled-back flags/NULL role |
|003 history | absent after rollback | uncertain, acknowledged0 remains durable |
| Safe caller action | fresh prepare/apply unchanged frozen package | ordinary apply refuses; inspect original plan, explicitly resume proven remaining work |
| Two operators prepared/assessed before either executes | one applied, one already_applied | one applied, one refusal requiring status reassessment |

These are different workflows, not a generic crash handler that blindly retries. Neither
uses history deletion/stamping, edited packages, endpoint-based repair or unsafe replay.

## Actual engine observations, not internal fault hooks

SQLite uses a fresh file and experimental direct connection preserving default DELETE mode.
A real independent reader prevents exclusive access. The probe must run in a DIFFERENT OS
process: SQLite connections in the reader process can reuse its shared lock and produce a
false negative for pending-writer observation. After observed busy plus journal existence,
kill child, release reader and inspect full rows/history. The rollback leaves no003 receipt.
The two ordinary retry workers both prepare before either applies; public under-lock recheck
converges. A separate current typed app verifies, reads admin/user and inserts/reads a user.

This does NOT exercise active-backfill death in WAL mode. Ordinary application initialization
uses WAL; its final connection after this test may change mode, which cannot retroactively
certify the earlier interruption. Other cache/spill/durability modes and power-loss behavior
are not inferred from this bounded experiment.

Native orchestration holds a real row lock, then observes the actual migration UPDATE in
information_schema.INNODB_TRX with at least one modified row. Polling allows the engine metadata
cache to refresh; a loop pinning an empty cache is a fixture failure, not execution evidence.
The row lock is not a production callback or fake driver error. While UPDATE remains blocked,
a separate typed application commits42 into an unowned InnoDB audit table. After child death,
release blocker, wait for server connection removal, and verify user-row rollback plus durable
uncertain003 acknowledged0. Earlier expansion is NOT rolled back with this later revision.

Then SIGKILL the OWNED server and restart the same data directory/socket/config identity.
Uncertainty and the unrelated committed write survive. Fresh ordinary preparation refuses.
Original Prepared bytes remain unchanged, public inspect reports retry_remaining0, and both
resumers assess before either executes. Winner runs remaining transactional updates and final
contraction; loser is explicitly refused once no incomplete execution remains, sees completed
status, and must reassess rather than replay. A separate ordinary terminal apply reports
already_applied; the current typed app verifies/data-reads/inserts successfully.

The server kill occurs AFTER client disconnect/transaction rollback, not during COMMIT or
DDL. This is not lost-receipt structural reconciliation, all crash windows or proof that the
schema contraction rolled back on native failure. The contraction runs later on explicit resume.

## Interface friction and caller policy

- The same logical operator action cannot use one retry entry point on both backends. Native
  recovery requires the ORIGINAL reviewed Prepared evidence; caller must retain it before
  execution in storage surviving worker replacement, and reconnect with the same target identity.
  This test retains that file on the same host; it does not test host/volume loss.
  Current public Pydantic JSON works
  for this process/restart case; no versioned stable Prepared serialization ABI is promised.
- Resume is not an idempotent apply wrapper: a competing resumer can be refused after another
  completes. Show status/reassess, don't automatically repair/replay or turn every error into
  success. Ordinary post-reassessment prepare/apply can confirm already_applied.
- Advisory locking coordinates migration participants. It demonstrably does not pause the
  application: unrelated data work commits during the migration lock. No fence, live old-model
  account-writer safety or global quiescence is implied. Schema exclusion here is caller-owned
  and truthful; account-data rollout/quiescence/compatibility remains caller policy.
- Structural completion and history are not logical-data/codec readiness; current application
  verification AND typed data assertions remain separate, as in the earlier codec review.

## Validation boundaries and next decisions

`tests/experimental/test_migration_role_interruption.py` uses only previously approved author,
package/load/prepare/apply/status/recovery/current-query seams, plus real external engine/OS
observations. Visible programs, generated historical imports, no manually patched declarations,
private production-helper assertions, mocked steps or hidden convenience framework. Private
server/process ownership and cleanup; unrelated services/global settings untouched. Parent
forced-lazy mode explicitly propagates to children; real rendered sources ty checked.

The operator-program REDs demonstrate safe refusal: native recovery on SQLite; ordinary apply
after native uncertainty. Correct caller paths make the journey pass. They are NOT newly
found runtime defects. Initial typing/dead-branch, lock-observer/cache, runner timeout and
fixture expectation corrections are excluded from runtime-defect evidence.

Evidence `.snektest/477-role-interruption/` retains actual rendered author review/worker/app,
committed package copies, original plans, observed journal/native modified-row wait, uncertainty,
restart, competing outcomes and current application rows. Existing historical references stay
unchanged; current format2 fixture digests do not prove a new compiler epoch.

Next consolidate finite supported backend/version/recovery/product/API/ADR scope. Explicit
open limits include WAL active-backfill interruption, remaining native receipt-loss windows,
Prepared persistence ABI, compiler existing-operation emission/epoch policy, opaque codec
provenance and partial adoption. Do not expand the parser checklist by default. Trusted SQL;
no blanket equivalence/readiness/resource/downgrade/fencing/retrospective certificate. Consumer
guides deferred; whole prototype remains draft/incomplete/not production- or merge-ready.

The subsequent [supported-scope proposal](recorded-migrations-supported-scope.md) turns these
limits into explicit promotion gates rather than immediately adding another interruption test.
It recommends strict adoption and caller-excluded incompatible writers, with execution-epoch/
original-plan persistence and runtime deadline/session contracts preceding finite qualification.
WAL and one selected real native receipt-loss window remain targeted qualification gaps; no
new runtime behavior or broader recovery guarantee follows from that engineering proposal.
