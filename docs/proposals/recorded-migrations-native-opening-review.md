# Recorded migrations: owned native connection opening (#477)

Status: experimental, bounded G3 follow-through, not production/merge approval. Follows the
[checked-out I/O checkpoint](recorded-migrations-io-deadline-review.md) and
[supported-scope proposal](recorded-migrations-supported-scope.md). This is native opening,
not completion of acquisition, session, durability or shutdown policy on both backends.

## What changed

Dedicated native `m.connect(config)` now bounds the physical opening await chain with the
existing `Config.acquire_timeout`. Socket establishment alone is not acquisition: waiting
for the server greeting, authentication, TLS and driver initialization belongs to opening.
Expiry raises the existing `PoolTimeoutError`, identifying opening a migration connection.
There is no new option, public transport interface, pool or generic runtime facade.

The acquisition scope ends BEFORE yielding the target. Checked-out statements/control/cleanup
continue to get independent `operation_timeout` budgets; caller time in the context is not
charged to either a whole-context or whole-package deadline. Existing driver/server failures
are not blanket-converted to operation-deadline errors.

Opening uses the existing aiomysql 0.3.x ownership and mandatory-TLS adaptation, now shared by
ordinary pool filling and dedicated migration connections through one private owned connector.
It creates the concrete connection BEFORE awaiting opening and closes it on `BaseException`,
including caller cancellation. Pool size accounting, stale-reader checks and TLS diagnostics
retain their previous behavior; global driver behavior and dependency caps are not changed.

This also closes an experimentally reproduced Config-admission defect: the prior direct
aiomysql opening treated an explicit TLS context opportunistically. Against an owned real
password-authenticated TCP server with SSL disabled, `m.connect` entered its body despite
`TLSConfig()` being supplied. The corrected path uses the same required-TLS guard as the
ordinary runtime and rejects a greeting without TLS support before authentication. Certificate
verification, hostname checking and minimum TLS policy remain the existing shared Config policy,
not a new migration-specific policy.

## Public-seam evidence

Tests are in `tests/experimental/test_migration_connection_opening.py`. They use `m.connect`,
package/Prepared load, prepare/apply/status and ordinary typed application queries. Models and
previously committed role packages are real. No declaration-state builders, fabricated receipts,
private production-helper assertions, internal driver replacements or injected migration steps.

### An accepted socket is not an acquired session

An owned local TCP listener accepts the real driver socket but sends no database greeting.
It does not implement or mock a database protocol. The old public interface remains pending
beyond the shorter acquisition budget: RED is **native opening acquisition deadline ignored**.
The watchdog detects missing library behavior; it is not the cancellation action or disposal
proof. The test always retains and joins its client task and owns all accepted peer sockets.

After implementation, acquisition expiry reports `PoolTimeoutError`, no target body is entered,
and the independent peer reads EOF with **zero client authentication/SQL bytes**, before fixture
peer cleanup. This is actual transport evidence, not a closed flag, task completion or a timeout
being mistaken for physical disposal. It qualifies this TCP/greeting window, not every possible
DNS/TLS/OS cancellation window.

### Cancellation and the two budgets

Separate task and AnyIO-scope cancellation cases wait for actual acceptance, pause longer than
`operation_timeout` but well below `acquire_timeout`, then cancel the opening. The opening must
still be pending before that cancellation: a checked-out I/O budget must not accidentally govern
opening. Task cancellation remains `CancelledError`; the caller's scope catches its own scope
cancellation. Both peers observe EOF/zero bytes before peer teardown. No late target work runs.

The connection owner covers opening failure paths; a cooperative deadline still does NOT prove
that all server work, OS resolver work or TLS shutdown finished synchronously. These tests do
not induce a failed socket close or certify physical quiescence in all transport phases.

### TLS refusal and the actual role workflow

A separate owned MariaDB TCP server explicitly disables SSL. The configured-TLS test's genuine
RED is **Expected to raise an exception but no exception was raised**. After the shared owner
integration it refuses with **MariaDB server does not support required TLS**. An earlier incomplete
launch during fixture setup has no completed result and is excluded: the corrected fixture uses
TCP and a plaintext administrative CLI for the deliberately non-TLS server. Its orphaned owned
server was identified by its exact temporary data path and stopped; unrelated services were not
used or changed. Static import/lint authoring corrections are not runtime defects.

The positive journey uses a real certificate-verifying TLS server/forwarding peer from the
existing TLS test fixture. Load the unchanged native001 accounts/002 expansion/003 role packages.
Open model-free, inspect empty status, and deliberately pause beyond the acquisition budget in
the yielded context. Apply001, seed typed initial rows, apply002 and load/apply the ORIGINAL
versioned003 Prepared evidence. All work runs with truthful schema-writer exclusion on the
owned isolated server; there is no new fencing claim.

Completion/already_applied and ordered complete progress are observed. The ordinary typed
application reads1 admin/2 user and inserts/reads3 user through its normal TLS-enabled runtime.
Package/Prepared bytes remain unchanged. Application models are present in this test process;
this does not replace the earlier separate-process author-source-removal evidence. The eight
existing ordinary-runtime TLS tests also exercise growth/replacement, trust, hostname, protocol,
plaintext-authentication refusal and cancellation after sharing the same connector.

## Remaining G3 and qualification

- SQLite opening/partial-open worker ownership and acquisition deadlines remain unresolved.
  Passing acquire_timeout as a SQLite busy setting is NOT a bounded opening contract. No journal
  mode, durability or SQLite cleanup behavior changes here.
- Local target-guard waiting and server coordination-lock acquisition still need an explicit
  acquisition policy distinct from opening and per-driver-I/O waits. This slice does not assert
  that every use of acquire_timeout is now integrated.
- Native application session settings, metadata visibility/privilege prerequisites and the
  remaining Config admission policy remain separate from TLS/transport admission. Accepting the
  Config does not imply that all ordinary runtime settings are now applied to migration targets.
- Known/unknown commit outcomes around post-commit cleanup, bounded shutdown/detached cleanup,
  actual WAL death and selected native lost-ack windows remain. Opening refusal/expiry is not
  evidence authorizing migration replay, history repair or a rollback claim about later work.
- Maintained-version qualification, remaining cross-version evidence/storage policy and final
  interface/ADR/coexistence/release approval are still open. No dependency maintenance or
  security-alert remediation is mixed into this migration change.

Query mapping stays independent of ownership. All construction/catalog/recovery gates, historical
execution epoch one, package/Prepared layouts and historical artifact bytes remain unchanged.
The prototype remains incomplete/draft; no merge, tag or publication is authorized.

## Completed local validation

- **888 normal +888 forced-lazy experimental**, **1,784 fast**, **20 focused normal +20
  forced-lazy**, all exit0 with zero failures/errors/fixture/session teardown failures. Focused
  runs combine the five opening cases, seven checked-out-deadline cases and eight existing
  ordinary-runtime TLS cases. Native normal/lazy runs were sequential with distinct external
  TMPDIRs and context-aware warnings; **548** Python/program source hashes stayed unchanged.
- Whole-tree ty/ruff/format/diff pass; **67** local links in changed engineering documents pass.
  All **68** historical package/Prepared JSON references remain byte-identical to the previous
  checkpoint; there is no new serialized format or regenerated historical artifact.
- A completed final-source standalone trace observes acquisition0.15/operation5, actual expiry
  at about **0.157 seconds**, no target yield, and peer EOF/zero bytes before peer cleanup. The
  same trace deploys the frozen role chain over the shared TLS path, retains original Prepared
  bytes and **every column/value of the earlier001 receipt**, then reads1 admin/2 user/3 user.
  The ordinary runtime independently reports negotiated **TLS_AES_256_GCM_SHA384**. This cipher
  observation is on the ordinary runtime session, not a new private target-session probe.

Evidence is under `.snektest/477-native-opening/` with matching external-cache scripts. The local
Linux/default asyncio/GIL CPython3.15.0, MariaDB13.0.2, aiomysql0.3.2/PyMySQL1.2.0 environment is
not the proposed maintained-version matrix. No full-suite, all-transport cancellation, physical
TLS-shutdown, WAL/native lost-ack or exact-head CI-success claim follows. Pending/unregistered
checks are not awaited or counted as success.
