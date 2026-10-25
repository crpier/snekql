# Recorded migrations: real framework evolution review (#477)

Status: experimental engineering evidence, not consumer guidance, compatibility guarantee or
release/merge decision. No production/interface/parser/format/ledger changes in this slice.
This follows the [application-codec evolution review](recorded-migrations-evolution-review.md)
with actual archived framework writers, readers AND runtimes, not a same-epoch rerun or
cosmetic SQL edit presented as evolution.

## Epochs, real programs and what varies

| Framework source | Actual capability / durable layout | Exercise |
| --- | --- | --- |
| 2ab4e55 | format2; nine ledger columns incl. original plan | writes001 complete receipt; current status/prepare refuse layout intact |
| 033ba56 | format2; eleven ledger columns incl. observation/reconciliations | writes001 complete receipt; current runner retains it and continues |
| b8f9cbf production code | model-derived CreateIndex / format5 | authors new004; old compiler cannot author transition; old reader refuses bytes |

Actual sources are git archives, and consumer subprocesses print imported migration-module
paths. Old runtimes execute001 on real SQLite/private MariaDB, then seed flag rows1/true and
2/false. Historical writer uses model-derived states, ACTUAL emitted historical.py and static
typed imports, frozen scalar backfills, then required-role/drop-flag contraction. The old
public interface has no advance;001 create,002 expand/fill and003 contract are three REAL
lineage revisions, not synthetic stages or manually stitched state declarations.

Both archived writers emit identical literal001–003 bodies/digests. Current code loads them
unchanged. New004 is generated from a current model declaring accounts_by_role and old003 as
predecessor. This changes a real physical index/capability and package version, not formatting.
Old033 compiler refuses that same model alteration as unresolved; its Package.load refuses
actual current format5 bytes through PackageError. No old compiler is required at deployment.

## Retention versus refusal, not migration by analogy

**Supported eleven-column layout:** current public status observes old001 complete. Applying
001 reports already_applied;002/003 retain committed old bytes and run historical data work;
004 creates the actual index. Full original001 receipt remains unchanged, not merely its
revision label. Current typed application independently verifies/index-declares the desired
structure, reads admin/user and inserts/reads a new user. Historical authoring modules are
absent from the current runner, and no compiler/type/module origin is reconstructed.

**Unsupported nine-column layout:** actual old runtime can read its own001 receipt, but
current status AND prepare refuse the incompatible ledger. Original schema, values and all
receipt fields remain unchanged. No implicit initialization, schema-match stamping, receipt
rewriting/deletion, layout conversion or speculative replay makes the journey succeed.
There is intentionally no automatic upgrade or endorsed endpoint-based recovery action.
Safe immediate action: stop the rollout, preserve backups/original receipts, and require a
separately designed/reviewed history transition instead of repairing from endpoint equality.

Prepared-plan identities bind a target: two real old deployments can have different original
plan hashes even with equal package/catalog bytes. Each original receipt is compared with
its OWN pre-upgrade value. Cross-target byte equality is not a recovery invariant and must
not motivate receipt edits. Prior complete evidence is retained, not upgraded to a new
retrospective readiness/recovery certificate.

## Durable regression evidence and limits

`tests/experimental/test_migration_framework_evolution.py` restores independent SQLite SQL
dumps exported from the actual two old runtimes. It exercises public load/generate/compile,
status/prepare/apply, full receipt preservation/refusal and current typed application queries.
The dump is fixture setup, not hand-authored migration SQL or manufactured declaration/receipt.
Committed old/new package bytes under `fixtures/framework-evolution/{sqlite,mariadb}/` have
actual producer provenance; no git/source checkout or old dependency is required in CI.

Additional actual subprocess experiments cover BOTH SQLite and private MariaDB layouts and
compiler/reader behavior. Real programs and ty diagnostics, old module paths, original
receipts, refusal text, plans/digests and current application rows are captured under
`.snektest/477-compiler-evolution/`. Distinguish those native archived-runtime experiments from
the in-suite SQLite snapshot regressions. No vendor tree, old-release fallback, CLI expansion,
new public compiler selector or compatibility framework was introduced just for testing.

The author-program RED omitted the index declaration; adding it satisfies the new requested
route. This is not a new library runtime defect. Initial dynamic-import registration, empty
stdout JSON parsing and cross-target plan-hash expectations were fixture/audit corrections;
final historical query imports are static and real rendered programs are ty checked.

## Remaining decisions

- This is genuine **capability/package-format and ledger-layout evolution**, with a narrow
  retention path and explicit unsupported-layout refusal. It is not a guarantee across every
  historical writer/reader, native catalog version/session profile or ledger interpretation.
- Existing-operation emission happens to remain compatible for this chain. Package.load still
  validates by recompiling frozen draft with current code. A future compiler changing those
  emissions needs an explicit canonical-compiler/epoch or refusal policy; no such registry or
  general frozen-validator independence is proven here. Do not silently regenerate old bytes.
- No migration/conversion of old nine-column evidence is designed or required for this
  unreleased experiment. No automatic repair, uncertain-receipt interpretation or downgrade/
  old-runner fencing is implied by these observations. Old code is not retroactively hardened.
- Opaque codec provenance remains erased/unrecorded as the prior review explains. Structural
  receipts/schema equality are still not current-codec/business/data readiness.
- Realistic interruption/restart/competing runner/unrelated writer and finite backend/version/
  recovery/release/ADR scope remain the next workflow priorities. Partial-adoption limits stay.

Trusted SQL, no arbitrary equivalence/whole-resource/blanket readiness or retrospective
certification. Consumer guides deferred; proposal remains draft/incomplete/not production-ready.
