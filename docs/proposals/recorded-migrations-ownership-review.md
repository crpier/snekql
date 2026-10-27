# Recorded migrations: combined ownership lifecycle (#477)

Status: experimental engineering assessment, not a consumer guide or production decision.
The workflow-first prototype now exercises its other distinguishing product requirement:
query mapping does not imply migration ownership, and handing ownership back is not deletion.
No production interface, adoption language or catalog-parser capability changes in this slice.

## Same role migration, different ownership lifecycle

`tests/experimental/test_migration_ownership_lifecycle.py` executes visible consumer programs
in `tests/experimental/fixtures/ownership-lifecycle/`, reusing the account-role model and typed
backfill sources. Actual historical query declarations are generated, imported and type-checked.
The route uses Draft.advance; no hand-built schema states, declaration patches or hidden
state-stitching helper. Independent external-owner fixture SQL is not migration SQL.

1. External owner provides populated matching STRICT accounts(id,is_admin) and directory.
2. Application queries both through ordinary typed models. User schema/history records are
   unchanged. Directory is never selected for migration generation or adopted incidentally.
3. Explicitly adopt matching accounts only. Preparation has no application SQL or history
   entry; applying begins001_adopt without recreating/deleting rows.
4. Author and apply the SAME nullable role/typed backfill/required role/drop old flag revision.
5. Explicitly relinquish accounts in003_handoff: empty application plan, identical physical
   schema and retained rows. The very same query models still work after ownership is empty.
6. Explicitly request004_readopt, with different outcomes below.

## Observed outcomes

| Journey | Outcome |
| --- | --- |
| Plain matching table | adopt → role migration → handoff → strict re-adoption all complete; history001–004, handoff/re-adoption emit no application SQL |
| Preserved external additions | adopt → reviewed preserving role migration → handoff complete; strict re-adoption refuses, history stops at003; additions/rows remain intact |
| External dependency on removed flag | preserving preparation refuses002 before application SQL/history; history stays001 and old flag/view/data remain usable |

The extended journey adds external note/default/generated upper_note, by_note index,
account_notes view, note_write trigger/audit and a links child FK after adoption. Ordinary
preparation refuses catalog drift. Explicit preserve_unmanaged review validates the managed
contract and prepares the rebuilding role migration. Actual results prove retained note values,
uppercase generation/recomputation, unchanged non-account object definitions, live trigger/audit
writes and FK enforcement/orphan rejection. Handoff retains those objects and application rows.
Directory and Notes query-only models never become migration owners of their selected objects.

The dependent journey adds a view that actually reads is_admin. Preservation does not mean
permission to destroy that dependency: preparation refuses with the dependency category,
leaving the old query and original view available. No implicit repair or replay is attempted.
The diagnostic currently names the dependency category, not the precise offending view;
more actionable object identification is a remaining workflow-DX opportunity, not a reason
to widen SQL equivalence or silently drop objects.

## Product limit: preservation is not partial adoption

Strict adoption still requires the entire recorded table declaration/index set to match and
refuses unmanaged triggers. The extended table therefore CANNOT complete re-adoption, with
or without preserve_unmanaged=True. This is the existing intentional admission rule, not a
new execution defect or an excuse to weaken it implicitly. Re-adoption preparation remains
read-only, records no004 and never sanitizes/deletes additions/history to force acceptance.

The same limit matters for first adoption when an existing table already has unmanaged
additions. Query-only use remains available without any adoption. For migration ownership,
we must deliberately choose finite supported scope versus a separately designed partial-
adoption claim/proof. A query model or a preservation flag cannot manufacture that authority.
Do not infer a native adoption implementation from SQLite results; it remains unsupported.

## Evidence and next product work

Evidence `.snektest/477-ownership-lifecycle/` retains actual per-mode programs/packages, static
checks, physical SQLite databases, plans, diagnostics, history and query results. Normal and
forced-lazy parents execute correspondingly configured consumer child processes. The initial
incomplete author program proposed CREATE for existing accounts and was refused; explicitly
adopting made the journey pass. This is author-program TDD, NOT a newly found library defect.
An early await-in-generator typing correction is excluded from runtime-defect evidence.

This closes a combined evidence gap, not every ownership/preservation case. Next product
priorities remain genuine compiler/package/codec/ledger evolution, realistic interruption/
coordination and a finite supported backend/version/release scope, including the strict versus
partial-adoption decision above. Earlier contract/attribute queues do not automatically take
priority. SQL remains trusted; no history conversion/repair/retrospective certification, total-
resource, arbitrary SQL-equivalence or blanket application-readiness guarantee. Guides deferred,
prototype incomplete/draft/not production- or merge-ready.
