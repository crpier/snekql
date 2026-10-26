# Recorded migrations: real native COMMIT outcome evidence (#477)

Status: **bounded G3 outcome-policy decision and selected G4 COMMIT-window qualification**,
not G3/global-shutdown completion, an environment matrix or G5/release approval. Follows
[native metadata authority](recorded-migrations-native-metadata-review.md).

## Test-first qualification, not a manufactured runtime fix

The remaining question was whether actual native COMMIT request/response loss preserves
truthful progress/original recovery, rather than inferring rollback from an exception.
Write the real public journey FIRST. Its initial withheld-server-OK case PASSED unchanged
runtime70d91c5. Expand only the finite request/response/EOF/final-marker windows below; all five
pass. No production patch, forced RED, simulated driver response, fabricated receipt, new
exception/outcome property or claim of a newly fixed runtime defect is warranted.

`tests/experimental/test_migration_commit_outcomes.py` forwards actual password-authenticated
MariaDB TCP greeting/authentication/packets to a real isolated server. A test-only TCP edge
withholds exactly one actual COMMIT request OR actual server OK response, or closes the
connection after receiving that OK. It NEVER constructs a server greeting/response/error,
changes SQL/data/bindings, invokes a mocked migration driver or inserts a migration callback.
The driver/framework/runtime are unchanged. This is controlled protocol-message loss, not
qualification of TCP retransmission, every network failure, TLS or a new production selector.

## Same original role journey, five finite windows

Literal001/002/003, real typed flags1/2, unchanged ORIGINAL003 retained BEFORE apply. All
migration targets use the SAME stable proxy endpoint, including fresh observation/recovery;
independent direct observer is not used to apply a target-specific original on another endpoint.
Real greeting's connection id plus independent PROCESSLIST establish physical server-session
absence after the failed caller. No caller-return/closed-socket == physical-stop inference.

| Fault window | Independent durable observation | Public next action |
| --- | --- | --- |
| First transactional COMMIT request withheld before forwarding | While pending, committed flags remain/roles NULL and003started0. After deadline/disposal/session absence the same evidence remains. | Original apply refuses uncertainty; ORIGINAL inspect retry_remaining0; EXPLICIT resume repeats rolled-back first UPDATE. Actual forwarded first UPDATE count2, not replay of committed work. |
| First transactional COMMIT actual server OK withheld | Actual server OK captured; another connection sees both roles user/003started1 before caller timeout. Session absence does not erase committed marker/data. | Original inspect retry_remaining1/resume skips first UPDATE, then admin backfill/contraction complete. First UPDATE forwarded exactly once across original apply and recovery. |
| First transactional COMMIT OK then TCP connection closed | Driver's real OperationalError2013 survives cleanup; marker/data1 are committed. | SAME original recovery from1; primary EOF error not replaced by rollback/cleanup failure. No rollback bytes on the failed transport. |
| Final COMMIT request withheld | Role/admin work, contraction, marker3 AND phase complete are ALREADY durable. Completion UPDATE runs in autocommit before the final explicit COMMIT call. | Deadline is NOT evidence of rollback/non-completion. Fresh complete003, original apply already_applied; no recovery/replay. |
| Final COMMIT actual server OK withheld | Actual OK captured; same durable complete3. | Same truthful fresh completion/already_applied; first UPDATE exactly once. |

Fresh sorted complete status, ordinary typed1admin2user3user, ALL own prior001/002 columns and
original package/Prepared bytes retained. Independent observation is paired with public
status/inspect/resume, not private production-helper assertions. Forwarded request counts are
actual network observation: edge never drops an UPDATE, only selected COMMIT/OK. No special
non-idempotent test migration step or incompatible affected-data writer is introduced.

Caller exceptions alone do not distinguish these windows: both first request/response stalls
raise existing DatabaseOperationTimeoutError/`migration commit`, yet have DIFFERENT durable
outcomes. Protocol EOF preserves existing driver error. Closed target refuses further work.
Interrupted connection emits no rollback/policy-release bytes; fresh connection and ORIGINAL
evidence are required. This is not proof of all raw-driver cleanup/error permutations.

## Candidate outcome-policy decision

1. Preserve caller knowledge separately from actual server outcome. A failed/timed-out/cancelled
   COMMIT awaiter must not claim rollback, completion or physical stop. Discard unsafe sessions;
   do not retry/reconstruct against uncertainty. Existing per-operation/context budgets stay.
2. In supported native InnoDB transactional steps, data AND their progress marker commit in
   ONE transaction. The public acknowledged_steps counter is DURABLE progress recovered from
   the ledger, not proof that the original caller received a protocol OK. Server commit can
   make marker1 durable while caller acknowledgement is lost. Fresh original assessment may
   therefore legitimately resume after1, never replay that committed unit.
3. Completion evidence is phase complete plus live endpoint validation, not whether the last
   explicit COMMIT call returned. Here final completion UPDATE is autocommitted already; the
   final COMMIT can fail without erasing a truthful complete receipt. Fresh observation wins,
   not an invented rollback/unknown-data blanket label or automatic force-complete.
4. Acknowledged COMMIT followed by release/cleanup failure retains committed evidence; the
   [bounded positive-release checkpoint](recorded-migrations-native-release-review.md) already
   exercises post-success cleanup expiry. Error reporting is not receipt rewriting. Primary
   errors/cancellation survive failed cleanup; post-success cleanup failure surfaces as error.
5. Do NOT add a single public Target.commit_outcome flag: a package spans multiple committed
   units, nontransactional DDL, durable completion and cleanup. Existing explicit status and
   original inspect/resume/reconcile interface carries the useful evidence without conflating
   a driver's one COMMIT with whole-package completion/readiness or a reusable connection.

This resolves the bounded G3 known/unknown-COMMIT engineering decision as a candidate policy;
G5 approval still applies. Known synchronized engine errors, native DDL/lost-receipt structural
reconciliation and SQLite late-COMMIT observations retain their existing scoped evidence;
this unit does not silently promote them into every protocol/engine outcome guarantee.

## Limits still open

Selected COMMIT delivery windows are now real evidence on ONE local build/transport. Not a
server crash during COMMIT/fsync, host/storage/power loss, native DDL acknowledgement loss,
all COMMIT rejections/cancellation/cleanup errors or maintained LTS matrix. SQLite DELETE
late COMMIT is separate; WAL active-backfill process death still open. Caller retains original
evidence durably, excludes incompatible writers and keeps authorization/policy stable through
recovery/readiness. Participating coordination is not fencing, backup or data/codec readiness.

G3 retained SQLite cleanup/global shutdown/live-loop policy remains to settle. G4 finite matrix,
WAL death and selected native DDL loss remain; G5 names/interface/ADR0023/coexistence/release
approval stays open. No new artifact/epoch/layout, compatibility conversion, data replay,
dependency upgrade, consumer guide, merge/tag/publication or changed released runtime policy.

## Completed final-source local evidence

- **943 normal + 943 forced-lazy experimental**,1784fast,145+145focused; zero failures/errors/
  fixture/session teardown failures. Actual10.10.7 version-floor regression separately1normal+
  1lazy, not full old-server/matrix qualification; normal suites use13.0.2, old selector unset.
  Existing focused ordinary fake-probe/fault regressions remain; not every focused case real I/O.
- **Ten actual packet/physical-state traces**, same final observer and qualification adapter,
  five windows in normal/lazy modes. Both modes independently recover uncertain0 (first UPDATE
  count2 after confirmed rollback), uncertain1 (count1, no committed-unit replay), or observe
  complete3/already_applied (count1). Raw EOF2013 remains primary. Original plans saved before
  apply, actual OK payloads/forwarded SQL/server greeting ids, physical session absence and
  full own ledger/data snapshots retained. No rollback/release bytes on failed transport.
- **All production files under snekql/ unchanged against70d91c5**, exact per-file SHA evidence
  retained. No archive/pre-fix comparison or runtime defect/fix claimed: current baseline was
  already correct, test-first qualification protects/clarifies it. Annotation/noqa setup
  corrections happened before first completed baseline; no setup error labelled runtime defect.
- Whole-tree ty/ruff/format679/diff, **564 stable Python/program hashes**, **69 historical JSONs
  unchanged against70d91c5**, **107 links checked across six distinct changed Markdown files**.
  Source stable through all final suites/traces, exact committed-source/hash/GitHub body/head/
  draft readbacks and observer/adapter provenance retained. Evidence `.snektest/477-native-commit/`
  and matching external cache. All runners/owned servers finished. Actions disabled, not
  requested/polled/awaited/claimed.

Environment: CPython3.15.0/GIL/default asyncio/Linux/SQLite3.53.1/MariaDB13.0.2/aiomysql0.3.2/
PyMySQL1.2.0, plain TCP on isolated loopback. Not TLS/server crash/power-loss/host-loss/upgrade/
MySQL/LTS matrix/all-driver/all-COMMIT qualification. G3 retained cleanup/shutdown and G4/G5
remain open. No merge/tag/publication, dependency change or consumer-guide promotion.

## Retained cleanup/lifetime follow-through

The [retained-cleanup checkpoint](recorded-migrations-retained-cleanup-review.md) now joins a
Target's known SQLite close with a fresh close budget even after unsafe I/O. Success observes
that close result; expiry/cancellation retains physical ownership and preserves primary errors.
Actual DELETE role work proves caller return can precede worker disappearance, then independent
physical cleanup/fresh original apply/current app. Candidate G3 shutdown policy requires live
loop/supervision, NOT global quiescence/all-task cancellation/failed-close/host-loss support.
Remaining G4 matrix/WAL death/native DDL loss and G5 lifecycle-interface/ADR/release approval
remain; candidate policy decisions do not approve promotion or add a public supervisor.
