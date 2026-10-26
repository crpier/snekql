# Recorded migrations: native metadata authority (#477)

Status: **bounded experimental G3 prerequisite-policy checkpoint**, not G3 completion,
G4 environment qualification, G5 approval or a general privilege/readiness certificate.
Follows [context-exit policy](recorded-migrations-context-exit-review.md).

## Real gap: filtered absence is not an authoritative negative

Native observations use SHOW FULL TABLES/CREATE/COLUMNS/INDEX, SHOW TRIGGERS and
information_schema.ROUTINES. Server privilege filtering can omit existing objects rather than
raise an error. A dedicated connection with narrow grants could therefore prepare/apply frozen
role003 while an administrator sees operational obstacles that existing gates must reject.

Actual password-authenticated owned MariaDB13.0.2 server, normal aiomysql/project interpreter:

- Routine case: account has schema-wide SELECT/SHOW VIEW/TRIGGER and needed DDL/DML, but not
  EXECUTE. Root-owned `external_constant()` exists; restricted ROUTINES result is empty.
  The function is NOT called by the backfill; this is incomplete observation/admission, not
  proof of bad role values, intrinsic SQL failure, data corruption or a server defect.
- Table case: account has ALL per-table privileges on accounts/history only. External unowned
  MyISAM `external_hidden(id=7)` is invisible in SHOW FULL TABLES. Catalog/history appears
  unchanged; whole-current-schema InnoDB/negative-obstacle evidence is incomplete.
- Actual SHOW TRIGGERS with the first account CAN return a trigger row with NULL statement/
  definer rather than hide the entire row. The probe does NOT establish that every missing
  TRIGGER grant hides triggers or causes data loss. No such overclaim is needed for the fix.

Clean public TDD RED: expected pre-yield DatabaseRuntimeError, but old connect yielded and
original role003 completed. It truthfully recorded its observed schema and expected role
values, but lacked metadata authority. Not false role completion or historical receipt repair.

## Small positive authority check, not an RBAC evaluator

After unchanged shared native identity/version admission, BEFORE policy SETs/yield, require
either the actual server's unrestricted `@@GLOBAL.skip_grant_tables=1` profile OR
**direct global and/or exact-database grants** covering SELECT, SHOW VIEW, TRIGGER and EXECUTE.
Grant bypass is a read-only observation of existing server policy, NOT a new Config/test selector,
request to enable it, authentication/security approval or a recommended deployment setting.
SELECT exposes current-schema objects/members, SHOW VIEW permits view definitions, TRIGGER
covers trigger metadata, EXECUTE exposes stored routine names needed by existing refusal/
recovery gates. Permission to execute a routine does NOT authorize a migration callback or
make routines safe; the existing gate still refuses them.

For grant-enforced servers, read CURRENT_USER() from the actual authenticated server principal, reconstruct its native
GRANTEE representation using the LAST @ (usernames may contain @/apostrophes), query only
that principal's USER_PRIVILEGES and exact current-schema SCHEMA_PRIVILEGES, union coverage.
Compare GRANTEE and TABLE_SCHEMA as **BINARY**: do not borrow a case-distinct account or
case-distinct database's grants through information_schema's case-insensitive collation.
Values are bound parameters, not generated SQL grants or parsed SHOW GRANTS text.

Unknown/missing direct coverage fails closed with DatabaseRuntimeError and sorted missing
privileges, before GET_LOCK/history/DDL/data work. Every cursor/execute/fetch/close uses owned
per-I/O deadlines; failed admission disposes candidate through normal bounded context cleanup.
No GRANT/SET ROLE/FLUSH, authorization repair, GLOBAL/session SQL-mode rewrite, full ordinary
initializer, new Config knob/facade, generic grant/role/wildcard evaluator or alternate observer.

This candidate intentionally does NOT infer authority from roles (even active/default roles),
per-table/per-column grants or wildcard/escaped-database scopes not equal to DATABASE(). They
may genuinely provide sufficient access, but unknown equivalence refuses. Mixed DIRECT global/
exact-schema grants are accepted. This is a migration-target prerequisite, including status;
ordinary query/model use remains independent and ordinary runtime admission is unchanged.
Direct-grant ergonomics and this finite restriction still need G5 approval/finite G4 builds.

## Public representative journeys

`tests/experimental/test_migration_native_metadata.py` uses normal visible models/typed queries,
literal001/002/003, ORIGINAL003 saved BEFORE external-object/access changes and apply, ALL own
prior001/002 columns, unchanged package/prepared bytes. No hand-built declaration state,
private production-helper assertions, driver mocks, new injected migration steps or callbacks.

1. Limited account independently sees no routine/hidden table. Connect refuses BEFORE yield,
   no003, no role UPDATE, unchanged function definition or hidden table/id7 and ALL receipts.
2. External operator deliberately supplies missing DIRECT metadata grants. Same original now
   encounters the REAL obstacle: visible routine causes existing transactional refusal/public
   uncertain003ack0 and ORIGINAL inspection stays ambiguous while routine exists; visible extra
   MyISAM table causes earlier catalog-drift refusal with NO003. Metadata authority != readiness.
3. External owner deliberately removes its OWN object, not library repair/adoption/reconciliation.
   Routine case: blind apply still refuses; ORIGINAL inspect retry_remaining0 and EXPLICIT resume.
   Table case: no003, SAME original applies after original catalog is restored. Both repeat/
   sorted complete status/current typed1admin2user3user; earlier own receipts/bytes unchanged.
4. Four finite identity/scope regressions: quoted/@ username with mixed DIRECT global/schema
   coverage succeeds; case-distinct privileged account and database cannot donate authority;
   active/default role-only coverage deliberately refuses. Operator explicitly supplies direct
   scope after refusals; unchanged001/status/ordinary typed insert/read works. No broad RBAC or
   all principal/hostname/collation/server-build certification.
5. Actual grant-disabled server: explicitly observe GLOBAL flag1, unchanged001 and typed
   insert/read work. Initial implementation false-refused this known unrestricted profile,
   because it has no matching direct-grant rows. Real public RED6pass/1error then explicit
   server-fact branch; no fabricated grants, enabling grant bypass, or mass fixture changes.

## Candidate prerequisite policy decision

Keep automatic admission finite: existing version/TLS/session/integrity/SQLite file-policy
checks plus this positive native metadata profile. Do NOT add a general GRANT/engine/storage/
readiness preflight or promise that every future statement has sufficient privileges. Actual
DDL/DML may still fail with durable native uncertainty/effects; no engine substitution,
NO_ENGINE_SUBSTITUTION, DDL authorization, disk space, clock synchronization, readiness or
physical-stop guarantee is created by metadata coverage. Existing postconditions stay live.

Caller keeps authorization/metadata visibility stable from preparation through execution/
recovery/readiness and excludes incompatible schema/affected-data writers. Participating
coordination does not fence administrators or GRANT/REVOKE changes. A one-time admission check
is not revocation fencing, a security sandbox or backup. SQL/artifacts remain trusted executable
inputs. No historical receipt/Prepared upgrade, old uncertain-history replay or stronger
retrospective certification. SQLite policy/ownership and released migration interfaces unchanged.

This settles the bounded G3 metadata/other-prerequisite engineering choice as a CANDIDATE:
positive direct metadata profile + explicit remaining operational prerequisites, not exhaustive
capability verification. Broader known/unknown COMMIT outcomes and remaining detached-cleanup/
global shutdown/live-loop policy remain G3 work; G4 WAL active death/native lost ack/environment
matrix and G5 interface/ADR0023/coexistence/release approval remain open. Consumer guides deferred.

## Development evidence exclusions

An early selected run (94pass/1fail/44errors) preceded the explicit unrestricted profile.
The44 errors were safe admission refusals on existing grant-disabled owned servers, not data
or transaction defects. One release-deadline test reached `migration execute` instead of its
expected release-control timeout; that report does not qualify the desired window. Keep it
under `before-unrestricted-profile/`, rerun final source; do not label setup/admission/timing
feedback as a released runtime defect or count it as passing final evidence.

## Completed final-source local evidence

- **938 normal + 938 forced-lazy experimental**,1784fast,140+140focused. All zero failures,
  errors and fixture/session teardown failures. Separately repeated actual10.10.7 floor
  regression1normal+1lazy, NOT full old-server/matrix qualification. Existing focused ordinary
  fake-probe/fault regressions remain; not every focused test is real I/O. Normal suites use
  installed13.0.2, old-server selector UNSET.
- **Four fixed normal/lazy and two ACTUAL archived1e55daa traces**, project interpreter/
  checked archive module/source paths. Both old limited profiles yielded/completed SAME frozen
  original003, correct roles/current typed use, unowned obstacle retained and ALL own001/002
  columns unchanged. That is observed prior behavior, NOT passing new authority policy,
  false data completion, compatibility conversion or a release certificate.
- Fixed limited profiles refuse BEFORE yield, actual candidate query log ONLY SELECTs
  (version, server grant-bypass flag, authenticated principal, direct coverage); no package
  lock/history/DDL/DML/policy SET before refusal. Observer verifies unchanged physical data/
  unowned definitions/own receipts and candidate-session disappearance. Explicit full metadata
  grant reveals routine ambiguity or MyISAM catalog drift. Owner removal then ORIGINAL
  inspection/resume or unchanged apply works; current typed1admin2user3user/bytes retained.
- Initial external observer passed empty tuple to a percent-bearing LIKE query, producing
  Python format TypeError; corrected observer default to None, reran ALL four fixed/two
  archived traces under SAME final observer hash. Excluded report retained under
  `before-observer-percent/`, not a runtime defect. Final working Python/program source
  unchanged through completed suites/traces; observer/archive provenance retained separately.
- Whole-tree ty/ruff/format677/diff; **563 stable Python/program hashes**, **69 historical JSONs
  unchanged against1e55daa**, **102 local links checked across six distinct changed Markdown
  files**. Exact committed-source/hash readback, all reports and bodies/head/draft readbacks
  under `.snektest/477-native-metadata/` and matching external cache. All runners/owned servers
  finished. Actions disabled, not requested/polled/awaited/claimed.

Environment: CPython3.15.0/GIL/default asyncio/Linux/SQLite3.53.1/MariaDB13.0.2; no maintained
LTS/SQLite-floor/upgrade/MySQL/all-build/role evaluator/privilege revocation fencing qualification.
G3 remains incomplete; ADR0023 is proposed and G4/G5 stay open. No merge/tag/publication,
dependency change, consumer-guide expansion, new artifact format or historical repair.
