# Actual framework capability/package/ledger evolution (#477)

Engineering fixture, not consumer guidance or general cross-version compatibility promise.
Use real archived implementations, not edited current-source SQL or invented ledger rows.

## Producers and artifacts

- `2ab4e55`: format2 writer/runtime, actual nine-column progress ledger.
- `033ba56`: format2 writer/reader/runtime, actual eleven-column observation/reconciliation ledger.
- Current `b8f9cbf` production code: supports new model-derived named index transition/format5.
  The old compiler refuses the same indexed model transition as unresolved; the old reader
  refuses the actual newly emitted format5 package through PackageError.

`stage_old.py.in` generates an actual historical.py; `author_old.py.in` statically imports
that declaration for typed backfill. Three ACTUAL revisions use old public generation,
compile and resolve interfaces:001 create,002 expand/fill,003 require/drop. They are not
synthetic staging artifacts or manually constructed TableState/ColumnState/model_copy DTOs.
Current004_index adds a real named nonunique role index. No cosmetic SQL rewrite stands in
for compiler evolution, and no historical artifact is regenerated for the new capability.

The sqlite/ and mariadb/ JSON references are emitted by archived033ba56 (001–003) and current
code (004). Archived2ab4e55 emits the SAME001–003 package bytes. All bodies/digests/load/dump
are retained. `ledger-supported.sql` and `ledger-unsupported.sql` are independent sqlite3
iterdump exports of actual old-runtime001 receipts plus two seeded flag rows. They are
fixture RESTORES, not migration SQL, manually synthesized receipts or conversion recipes.

Prepared-plan digests are target-specific: another genuine old deployment can have a
DIFFERENT original plan hash even with identical package/catalog bytes. Compare each receipt
with its OWN before-upgrade value; never rewrite it to match another target's plan digest.

## Public workflow and evidence

CI regressions restore actual SQLite snapshots. Supported eleven-column receipt: public
status retains001, prepare/apply001 reports already_applied, current model/codec-free runner
applies COMMITTED old002/003 then reviewed004, original FULL001 receipt unchanged. Separate
current typed app verifies named index/structure, reads historical roles and inserts a user.
Unsupported nine-column receipt: BOTH status and prepare refuse; full physical dump unchanged.
No stamping, ledger conversion, deletion, replay, endpoint-based repair or retrospective proof.

Additional actual archived-process runs in `.snektest/477-compiler-evolution/` repeat BOTH
paths on SQLite and owned private MariaDB, plus old-compiler/old-reader refusals, full original
receipt comparisons, current typed app and real rendered-program ty checks. CI SQLite snapshot
regressions are distinct from those actual native old-runtime experiments; do not imply CI
executes a vendored old runtime. No old-source/dependency requirement is added to the test suite.
Actual module paths are captured. Authoring source is deleted before current deployment;
reviewed-authoring/ is evidence only, not a runtime import path.

Author-program RED omitted the new index declaration, so the requested format5 authoring
assertion failed before deployment. Adding the explicit model index made it pass. This is
workflow TDD, NOT a new library runtime defect. Initial importlib module-registration, trace
empty-output decoding and cross-target plan-hash expectation mistakes are fixture/audit
corrections, not defect evidence. Final authoring uses ordinary static historical imports.

This proves capability/format evolution with preserved old-operation emission for this chain,
NOT support when a FUTURE compiler changes existing-operation emission. Package.load still
recompiles frozen draft to check consistency. No versioned canonical compiler/ABI registry,
arbitrary format conversion, unsupported-ledger recovery, uncertain old receipt interpretation,
fleet downgrade/fencing, opaque codec provenance, whole-resource or application-readiness proof.
Finite support/epoch/refusal policy and realistic interruption/coordination remain open.
Trusted SQL, guides deferred, draft/incomplete/not production- or merge-ready.
