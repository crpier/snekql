# Combined query/ownership/preservation lifecycle (#477)

Engineering consumer-program fixtures, NOT a consumer guide/new file-layout convention,
CLI or new construction/adoption permission. Uses the SAME accounts/is_admin→role journey
and generated historical source, now with explicit first adoption and handoff/re-adoption.

- Copy model declarations and typed backfill source from the account-role workflow, only
  substituting backend=sqlite. stage.py explicitly adopts accounts; review.py uses
  Draft.advance for the role migration, then explicit RelinquishTable and later AdoptTable.
  No hand-built TableState/ColumnState/model_copy or private product-helper assertions.
- lifecycle.py supplies independent external-owner DDL/data, NOT raw migration SQL. It first
  queries preexisting accounts/directory through ordinary typed mappings without changing
  user schema or recording ownership history. Directory is NEVER passed to generation.
- Adopt matching accounts with empty application plan, no preparatory history entry, then
  migrate roles and prove typed data. Neither directory nor Notes query mappings acquire
  migration ownership. Raw SELECTs observe unmanaged view/trigger/FK behavior and catalog.
- Plain: zero-SQL handoff retains schema/data/querying; strict zero-SQL re-adoption succeeds.
- Extended: external owner adds note/default/generated field/index/view/trigger/audit/child FK
  after adoption. Default preparation refuses drift; explicit preservation review accepts.
  Role rebuild keeps schema objects, values, generated recomputation, live trigger/audit and
  FK/orphan rejection. Handoff is still zero-SQL, retains rows/schema/queryability. Strict
  re-adoption refuses extra column/index/trigger declarations with BOTH preservation flags,
  does not record004, rewrite history or delete extras to make the claim pass.
- Dependent: unmanaged view reads is_admin. Preservation prepare refuses removal before SQL
  or002 history; original flag rows/view/schema remain usable. No implicit dependency repair.

Initial author-program RED selected ordinary CREATE for existing accounts; prepare demanded
explicit adoption. Adding .adopt made the combined journey pass: NOT a new library runtime
bug. Initial await-in-generator type-check fixture correction excluded from runtime-defect
evidence. Rendered actual programs are ty checked; child forced-lazy setting propagated.

This makes the strict-adoption product limit concrete: existing unmanaged additions preserved
through migration/handoff cannot simply be re-adopted, and preservation is not adoption.
Do not generalize strict adoption or delete external objects/history as a workaround. Partial
adoption/re-adoption remains a deliberate scope/design decision, not permission from queries.

SQLite only. Native adoption/preservation is not silently enabled; native basic role journey
remains independently covered. No full partial-ownership/dependency/evolution/interruption/
coordination/resource/release/readiness certificate. SQL trusted, guides deferred, draft.
