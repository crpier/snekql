# Recorded migrations: native UTC session admission (#477)

Status: **bounded experimental G3 checkpoint**, not full session/config admission,
production/merge/release approval or an accepted ADR change. Follows
[SQLite coordination](recorded-migrations-sqlite-coordination-review.md).

## Real workflow defect and decision

The dedicated native connection inherited server time_zone, unlike ordinary typed runtime
connections. A frozen typed CurrentTimestamp UPDATE rendered CURRENT_TIMESTAMP(6) into native
DATETIME and a canonical TEXT expression ending in literal Z. On an owned server whose default
was+05:30, the role chain and004 clock work acknowledged completion but ordinary UTC decoding
read local wall fields as UTC instants. The real RED was **migration DATETIME clock labeled
local time as UTC**. This is a temporal data-semantics defect, not a schema-construction loss or
evidence that a receipt alone proves readiness. Incorrect acknowledged rows are NOT repaired,
relabelled, retrospectively certified or replayed by this fix.

Before yielding any dedicated native target, apply AND read back the existing UTC session
policy through target-owned fail-closed I/O. The common `_UTC_TIME_ZONE_SETTING` declaration
is the SAME policy value used by ordinary native connection settings; no second clock policy.
A small private SettingsProbe adapter delegates every interaction to Target._query, keeping
cursor/execute/fetch/close deadlines, primary-error precedence and unsafe-session disposal.
Physical opening finishes its acquisition scope before session admission; each admission I/O
gets a fresh operation_timeout. No whole-connect/body/package/cumulative clock is introduced.
The existing owned close handles admission failure before yield; no database objects/history
are created by connection admission. No public method, option, registry or runtime facade.

Only time_zone is configured here. Do NOT call the entire ordinary native settings initializer:
that would overwrite sql_mode, erase NO_BACKSLASH_ESCAPES/rendering differences and change
recovery evidence rather than prove it. Existing mode/CHECK/FK/catalog/refusal gates remain
active. Version floor, metadata/privilege admission, strictness/enforcement and other native
prerequisites remain G3 work. Pool/recycling policy is not implied by a dedicated connection.

## TDD and public seam evidence

`tests/experimental/test_migration_native_utc.py` contains real models and the visible authoring
route. It loads unchanged committed001/002/003 role packages, selects a real StampedAccount
model for004, names a historical stamp checkpoint and freezes a typed UPDATE assigning
CurrentTimestamp to nullable UtcDatetime DATETIME(6) and TEXT fields. No hand-built states,
model_copy declaration patching, fabricated receipts, private helper assertions or injected
migration steps. The explicit codec-bearing historical declaration is deliberate; erased
codec identity cannot be reconstructed from physical storage.

- Save owned-server GLOBAL time_zone/sql_mode; select+05:30 or-07:00 and add
  NO_BACKSLASH_ESCAPES. Restore both in finally. No unrelated server/global setting is touched.
- Apply001, normal typed flag rows1/2, apply unchanged002/003, retain original004 Prepared
  BEFORE clock execution. Literal format2 first-writer004 is committed; current authoring must
  match it exactly. Named-checkpoint work does not import runtime Python into the artifact.
- Apply ORIGINAL004, read sorted complete status, repeat original already_applied. Both native
  and canonical TEXT clock values must decode to equal UTC instants within an independently
  measured local UTC clock bracket. This finite test uses the owned server on the same machine;
  it is not clock-synchronization certification or a business timestamp guarantee.
- Normal typed app reads admin/user, inserts3user and performs its own typed CurrentTimestamp
  refresh; both representations agree and fall in the UTC bracket. GLOBAL offset/mode remain
  as selected, while ALL recorded rendering profiles retain the actual SQL mode rather than a
  normalized replacement. Package/Prepared identities remain; earlier001–003 receipts are not
  upgraded to claim stronger timestamp semantics.

The minimal UTC SET/readback first passed the real RED; review then shared the existing policy
value/probe machinery and repeated the same workflow. Type guarding raw observation strings
and using actual normalized server mode spelling were authoring corrections, not runtime bugs.

## Boundaries and next work

The fix applies to future work on newly admitted native targets, including original supported
packages. It does not convert historical values or strengthen old receipts. Epoch-one SQL and
package bodies/ledger identities stay unchanged; fixing a violated UTC contract is not a new
compiler interpretation. Caller-maintained schema/affected-data writer exclusions and separate
readiness/codec checks remain necessary. Normalizing time_zone does not normalize SQL modes.

No deliberate failed UTC SET/readback, stalled admission-response, grant-at-cancel, other
clock/server implementations or metadata privilege matrix is qualified here. Existing _io
policy is reused, not a claim to have exercised every admission cancellation window. Remaining
G3 session/config/metadata, SQLite journal/durability, end-to-end admission choice and positive
release/commit-outcome/shutdown/live-loop policy stay open. G4 matrix/WAL active-death/native
lost-ack and G5 interface/ADR/coexistence/release approval remain. No parser/adoption/dependency/
consumer-guide expansion, automatic replay/stamping/repair, writer fencing or release action.

## Completed local validation and archived counterfactual

- **908 normal +908 forced-lazy experimental**, **1,784 fast**, **37 focused normal +37 lazy**,
  all exit0/zero failures/errors/fixture/session teardown failures. Focused = earlier30 opening/
  guard/coordination/I/O cases +two offset cases +five REAL ordinary native connection-settings
  regressions. Whole-tree ty/ruff/format/diff pass; sequential native suites/distinct external
  TMPDIRs/context-aware warnings. Existing safety gates remain exercised, not normalized away.
- **555** Python/program hashes stable across final native suites/four final-source standalone
  traces/archived comparison/commit readback; **68** prior package/Prepared JSONs byte-identical
  to16e48f3, plus one new literal004 first-writer reference; **78** local engineering links.
  New format2/epoch1 digest `5df892374b1b4bc324714d2a7f03f71d89016708be3eb7faae7d58a8348e0d7b`.
- Four final-source standalone normal/lazy east/west traces load all four literal packages,
  save ORIGINAL004 before apply, apply/repeat, retain every prior001–003 receipt column/value
  against its OWN pre004 values and retain original bytes. Both representations for rows1/2
  fall inside the independently measured UTC bracket; typed app reads/admin/user and writes/
  refreshes3user correctly. Actual NO_BACKSLASH_ESCAPES mode remains in every recorded profile;
  selected GLOBAL offset/mode remain unchanged by target admission. Own settings restore after
  each trace. Models remain present; no new model/author-source removal claim.
- An isolated archive of the ACTUAL16e48f3 runtime executes the SAME literal004/reference/typed
  consumer under+05:30 with the project's interpreter, asserting actual archive module paths.
  It completes004/already_applied but produces BOTH native/TEXT values near18:47 UTC-labeled
  when the real UTC bracket is near13:17: the same+05:30 error. Its ordinary app-created row3
  is near13:17 and correct, isolating the dedicated migration-session gap. Archive provenance/
  source hashes and actual typed/wire values are retained. No mocked server/driver/version,
  production step injection, altered current source or automatic repair. This supplements the
  first RED, which stopped at the native-column assertion before checking its TEXT counterpart.

Evidence: `.snektest/477-native-utc/`, matching external-cache scripts; final/archived runners
finished, owned-server audit empty. Local Linux/default asyncio/GIL CPython3.15.0/MariaDB13.0.2
is not maintained-version qualification. Actions remain maintainer-disabled: no CI requested,
polled, awaited or claimed. No full-suite/matrix/all-admission-failure/privilege/WAL/lost-ack/
shutdown qualification, consumer guide, dependency upgrade or merge/tag/publication follows.

## SQLite encoding/FK admission follow-through

The [SQLite admission checkpoint](recorded-migrations-sqlite-admission-review.md) applies and
verifies shared foreign_keys/UTF-8 policy before yielding a dedicated target, through owned
per-I/O deadlines. Real UTF-16 files refuse without byte/schema/data/history conversion; an
explicitly different UTF-8 target deploys original role packages and normal typed application.
The ordinary fixed busy wait/WAL/synchronous initializer is deliberately NOT imported, so
migration acquisition and pending journal/durability policy are not silently changed. This is
not complete SQLite runtime admission, failure-window qualification or completion of G3/G4/G5.
