# Recorded migrations: finite G4 environment and failure-window qualification (#477)

Status: engineering qualification record for26c61c7; **G5 was unapproved at this checkpoint**. Counts below
are recorded only after finished final-source runs. No merge/tag/publication or Actions work.

## Finite maintained set

`tests/experimental/qualification-matrix.json` is the maintained selection: GIL CPython3.15.0,
Linux x86_64/default asyncio/disk-backed files; actual SQLite3.45.1/3.53.1 DELETE/WAL with requested
NORMAL/FULL; Community MariaDB10.11.19/11.4.13/11.8.9/12.3.3 InnoDB. Both normal and forced-lazy
modes are required, not inferred from a mode-neutral run. Exact builds, not every intervening
patch, in-place engine upgrade/downgrade, MySQL or other event loops/platforms/free-threading.

Native selection runs the visible author/edit/typecheck/model-free deploy/current-app journey,
actual codec replacement/explicit translation, target-specific ORIGINAL drift refusal, zero-SQL
whole-table handoff with unchanged query use, five real transactional COMMIT request/OK/EOF
windows and two real final-role ALTER OK-loss windows. Source/package/receipt identities are
compared to their OWN earlier values, not another database/version's digests. SQLite selection
runs authoring/codec journeys, strict adoption/preservation/dependency refusal/re-adoption,
DELETE/WAL + NORMAL/FULL actual UPDATE-session policy, and actual WAL client death.

The native test-only external installation selector supplies public temporary-server executable/
installer/client paths. It never downloads, silently skips or alters production admission.
`SNEKQL_TEST_EXPECT_MARIADB` checks actual VERSION; optional report captures actual /proc PID exe,
SHA and workflow evidence. Other tests share that same explicitly selected installation.
Password-authenticated plaintext loopback TCP and owned local socket are the selected native
transports, not all TLS/transport/version combinations. Missing builds fail; no fake ABI shim,
vendoring, dependency bump, system replacement or alternate migration runtime is introduced.

External official MariaDB archives are compared to exact ARCHIVE entries of published SHA256
manifests before extraction. Initial downloader matched the signature filename's digest instead
of the archive filename; exact-token matching corrected that setup mistake BEFORE extraction.
For SQLite3.45.1 the actual amalgamation SHA3 matches the official release log; stock CPython3.15.0
source archive SHA256 matches the published sigstore message digest (no signature-verification
claim). Build the real library/interpreter externally; actual module/library maps/version/GIL
and normal/lazy mode are recorded. Identical installed project dependencies are used; no claim
of generic Python/dependency ABI compatibility follows. SQLite3.53.1 is the current actual
managed interpreter build. Existing13.0.2/negative10.10.7 remain separately labelled regression/
negative environments, not maintained positive matrix rows.

## Actual DDL acknowledgement loss

`test_migration_ddl_outcomes.py` uses the existing test-only real-packet forwarding/drop edge,
now optionally matching one EXACT frozen statement rather than only COMMIT. It forwards actual
server greeting/authentication/framing/requests/replies and captures genuine OK bytes. No fake
SQL/result/errors/history, migration callback, driver fault injection or synthesized greeting.

Use literal001/002/003 role packages and visible ordinary typed flags1/2. Save ORIGINAL003
BEFORE apply. Same stable forwarding endpoint for preparation/application/fresh recovery;
independent direct endpoint OBSERVES/ordinary application use only. Drop the genuine OK after
actual role ALTER (required role + dropped flag), either withhold to driver timeout or close TCP
for real2013. Independent SHOW COLUMNS/data proves both structural facts and admin/user while
raw ledger remains started2of3. Target closes; no rollback/release SQL is sent on interrupted
wire. Actual greeting session is independently observed absent before fresh recovery.

Public status is uncertain2. Original apply refuses, inspection gives reconcile_structural2,
resume refuses: matching live endpoint alone does not authorize replay or infer a receipt.
Explicit reviewed reason accepts supported structural facts; fresh original inspection then
finish/resume records completion. One reconciliation, ONE forwarded ALTER and TWO original
UPDATEs total; all earlier own receipt columns and original bytes unchanged. Typed current app
reads1admin2user and creates3user. Structural acceptance does not assert original client ACK,
replay data, automatically repair history or retrospectively strengthen earlier receipts.

The initial DDL cases already PASSED current runtime. No manufactured runtime RED/fix/archive
comparison; all production files remain unchanged against6877111. Optional test-only reports
retain actual OK hex, independent rows/columns/ledger, original plan, assessment, reconciliation,
forwarded SQL and session absence. Real local packet loss is NOT server crash/fsync/host death.

## WAL, release-window fixture and evidence discipline

The [WAL checkpoint](recorded-migrations-wal-interruption-review.md) supplies actual partial
uncommitted audit spill with valid header/frame checksums, whole-client SIGSTOP/SIGKILL and fresh
atomic no003/original completion. A pinned reader sees its old snapshot even after fresh COMMIT.
Physical rejected bytes may remain; no secure-erasure/power-loss proof. The selected window is
now run on BOTH SQLite builds/modes, not inferred from ordinary application WAL initialization.

Two earlier broad950 runs failed the existing release test because migration-execute timeout
arrived BEFORE the desired release window. No inference of rollback/no effects or runtime defect.
The test formerly allowed only0.15s for every I/O while demanding later release failure. Keep
same public seam/positive release/disposal/receipt assertions, but allow1.5s per I/O and expand
bootstrap recursion4096→65536 so release still exceeds a bounded whole-control budget. Real
three-case probe passes; no test weakening/production change/fault callback or infinite retry.
Final runs use this frozen source; earlier reports and original WAL traces remain development
checkpoint evidence, not mixed into final-source totals.

G3 lifetime restrictions still require live-loop/individual cleanup ownership and do not supply
global shutdown or physical-close-failure recovery. G4 selects truthful database outcomes after
client death/lost replies, NOT universal graceful cleanup after process/host termination.
G5 must approve adequacy, interface/names/ADR0023/coexistence/release scope. Consumer guides deferred.

## Completed matrix/source provenance (2026-10-26)

All **12 environment/mode rows /148 selected cases** completed, zero failures/errors/fixture or
session teardown failures. Eight native rows each12 cases; four SQLite rows each13. Paired
SQLite/native counterparts in authoring/codec files are ancillary, not extra maintained targets.
**16 maintained-build actual DDL-loss traces** and four final-source WAL operator traces retain
raw OK/page bytes, original plans and independent state. Broad default regression completion is
recorded separately below; do not infer it from matrix completion.

Official native archive SHA256 values:

- **10.11.19**: `7efb257927f31f4422f496246b32590d0b7617f3d9dd900e575de761b302d919`.
- **11.4.13**: `3cebf63914df3154b7cb6d548337eb2be42c773aeb641110446b72e2746cfed7`.
- **11.8.9**: `32f8871a2aa38b36aa418b7f4abc6fc0c6ef1ba5a45798cacb2afa52c8a6113b`.
- **12.3.3**: `a12bf7bce08a896cdd01f174f04b4ce1d5da43ec250a5e7fceb9972119514329`.

Stock CPython3.15.0 source archive SHA256:

`ba4bed1ba346b916890b76d9e320451420aa69f6408997d33c66482eeae3d575`

SQLite3.45.1 official amalgamation SHA3-256:

`0474604df9e1b69a5544295dd046aad954749279780d557da80f44b958100295`

The source/installer/download/build records remain external-cache-only. Local actual platform:
Linux7.2.8/x86_64/glibc2.44, btrfs disk-backed files; managed Clang22.1.3 CPython3.15.0 builtin
SQLite3.53.1 and real GCC16.2.1 CPython3.15.0 linked to real SQLite3.45.1. GIL enabled and actual
module/library maps recorded. Driver/Pydantic versions are captured with uv project Python,
not inferred from system Python. No general filesystem/dependency-ABI guarantee.

## Final gate readback

**G4 is complete for the explicitly selected finite candidate**, not accepted G5 release scope.
Final working Python/program source stayed frozen through all suites/traces; all production
`snekql/` files are byte-identical to6877111. Final completed reports:

- **953 normal +953 forced-lazy experimental**, **1784 fast**, **157+157 focused**.
- Actual10.10.7 negative **1+1**, separately selected, never called positive LTS evidence.
- Matrix **148 cases /12 rows**; **20 captured real DDL-loss traces** (16 maintained +4 local
  regression); four final-source WAL operator traces, plus matrix WAL process-death tests.
- All zero failures/errors/fixture/session teardown failures. Whole-tree ty/ruff/format687/diff
  and explicit standalone worker checks pass. **569 Python/program hashes** stable; **69
  historical package artifacts** unchanged. Final local-link scan covers eight distinct Markdown.
- Actual owned-server /proc audit empty. Every runner finished; no Actions request/poll/await,
  merge/tag/publication, consumer guide promotion or dependency change.

Evidence: `.snektest/477-g4/` (reports/manifests/matrix environments/actual packet and WAL bytes/
originals/provenance/cleanup/final status). `.snektest/477-wal-death/` retains BOTH earlier
949pass/1fail broad reports with execute-before-release miss, and the observer/setup reports.
Those are excluded from final-source totals, not discarded or called runtime defects.

Initial post-run finalizer incorrectly rejected ALL ROLLBACK commands in the combined multi-
connection trace, including legitimate FRESH-target refusal/recovery rollbacks. The actual test
already checked no ROLLBACK BEFORE starting any fresh target; all20 traces show the next command
following affected DDL is fresh connection admission `SELECT VERSION()`. Correct the external
finalizer's scope to that pre-fresh segment; retain its failed report under
`before-finalizer-scope/`. No working Python/program source change or runtime repair. Actual
session absence was independently awaited BEFORE fresh use, not inferred from this ordering.

Remaining promotion work is **G5**: names/interface, lifecycle adequacy within stated exclusions,
proposed ADR0023 acceptance/amendment, released/recorded coexistence/cutover and release scope.
No global-loop shutdown, failed physical-close recovery, power/host/volume loss, every patch or
all transports/capabilities is inferred from this bounded G4 completion.

## Subsequent G5 lifetime change

The [G5 decision review](recorded-migrations-g5-decision-review.md) adds the approved observable
Connection lifetime. This changes production source after26c61c7, so the completed G4 counts
above are NOT its validation. The expanded finite matrix/broad suites are rerun on frozen new
source, with explicit lifetime/failed-entry/retained-close cases. That216-case matrix and broad
validation now pass; final bounded G5 engineering acceptance belongs there, not to these old runs.
