# Recorded migrations (experimental, opt-in)

Use `snekql.experimental.migrations` for an explicitly owned, linear chain of
recorded schema states, typed intermediate data changes, and frozen execution
packages. This is **not** a stable-namespace replacement for
[`db.migrate(MIGRATIONS)`](migrations.md). The raw-SQL runner remains supported
and unchanged.

Choose the runner family **before choosing the deployment target**. Keep raw
and recorded chains on separate deployment targets. Their ledgers and lock names
are separate; they do not coordinate each other. There is no universal
mixed-history detector, raw-to-recorded conversion, implicit stamping, or
automatic cutover. Do not use either family's recovery API on the other's history.

## Three independent contracts

- **Query mapping:** ordinary application models describe queries and values.
  Mapping a table does not acquire migration ownership.
- **Migration ownership:** a chain selects the physical schema facts it manages.
  A recorded state is a declaration, not a live-schema diff or current application
  requirement. Preserving an unmanaged object does not adopt it.
- **Application readiness:** completion records migration execution. Separately
  check current schema expectations, codecs, data invariants, and operating
  conditions before accepting traffic. Structural equality is not data equivalence.

Opening a connection creates no application tables. Authoring and compilation do
not connect to a database. Target-aware preparation observes the chosen database;
application is the separate effectful step.

## Workflow: `is_admin` to `role`

Use distinct authoring, deployment, and application programs:

1. Declare the historical `accounts(id, is_admin)` state using ordinary backend
   models. `generate("001_accounts", [Initial], backend="sqlite")` selects ownership
   and drafts its creation; `m.compile(first_draft)` freezes that first package.
2. `generate("002_roles", [Expanded], backend="sqlite", previous=first)`
   followed by `.then(Checkpoint(name="fill_roles"))` adds nullable `role` while
   retaining `is_admin`. Generate `contract_source(..., point="fill_roles", table="accounts")`
   into an ordinary Python module. Review and type-check it with your typed UPDATEs.
   The intermediate historical query contract is not today's application model.
3. Build `DataChange.from_query(...)` values using that generated contract: assign
   `"admin"` for old true flags and `"user"` for old false flags. Review the
   assignments, filters, affected data domain, and ordering. Type checks do not
   establish those business semantics.
4. Add the changes with `then(...)`. Advance to the final ordinary model containing
   required `role` and no `is_admin`, explicitly authorizing
   `DropColumn(table_name="accounts", column_name="is_admin")`. Checkpoint the result and
   call `m.compile(route)` to freeze the transition.
5. Review the package and its statements. Keep the historical declarations,
   generated query contract, authoring queries, and packages in source control.
   Use `Package.check(draft)` during builds to detect stale packages; loading a
   package for deployment is not a freshness check against today's models.
6. Deploy the backend-specific packages in predecessor order. Deployment loads
   packages without importing authoring or application models. Prepare against the
   real target, review the prepared statements and preservation choices, persist
   the **original** prepared plan, then apply that exact plan.
7. Use the new ordinary application model to read/write `role`, and establish
   application readiness separately. Completion alone does not authorize traffic.

This example deliberately uses Boolean flags represented as integers and text
roles. A different storage encoding or custom codec requires its own reviewed
historical representation and explicit data rewrite. An unchanged schema digest
cannot prove that new codecs can decode old values. Do not silently replace
historical codec behavior with current application bindings.

## Copy and run the authoring recipe

The reading resources contain ordinary source files, not a new library CLI:

- [Historical/expanded/final declarations and staging](../examples/recorded_role_stage.py).
- [Editable typed backfills and freshness checks](../examples/recorded_role_author.py).
- [Private original-plan storage](../examples/recorded_plan_store.py).
- [Separate current application models and queries](../examples/recorded_application.py).

In a fresh consumer project with this build and the needed driver extras installed,
copy the recipe inputs from the installed resources:

```sh
uv run python - <<'PY'
from importlib.resources import files
from pathlib import Path

output = Path("examples")
output.mkdir(exist_ok=True)
output.joinpath("__init__.py").touch()
for source in files("snekql").joinpath("docs", "examples").iterdir():
    if source.name.startswith("recorded_") and source.name.endswith(".py"):
        destination = output / source.name
        with destination.open("xb") as stream:
            stream.write(source.read_bytes())
PY
uv run python -m examples.recorded_role_stage
uv run python -m examples.recorded_role_author
uv run ty check examples
uv run python -m examples.recorded_role_author --check
```

Staging emits separate `001_sqlite_accounts.json`/`001_mariadb_accounts.json`
packages and **actual generated** `examples/recorded_{sqlite,mariadb}_contract.py`
query modules. Those generated contracts are outputs, not replacement live-model
imports. Review and retain them. The author program emits backend-specific
`002_{sqlite,mariadb}_roles.json` packages. `--check` reads without rewriting.
For example, editing a role assignment makes a previously frozen package stale;
assigning `42` to text `role` fails the type check. Recompile only during initial
authoring, review again, and check freshness before deployment. Once applied,
append a new revision instead. Do not rerun this scaffold over deployed history.

The route first initializes **every** account to `"user"`, then updates old true
flags to `"admin"`; contraction makes `role` required and removes `is_admin`.
Review that default classification against your actual data. This recipe is not
a generic value-domain verifier or custom-codec adapter.

For a demonstration, deploy 001 on a **fresh, dedicated** target, insert the old
application rows `(1, True)` and `(2, False)` using its ordinary typed models,
then deploy 002. Do not run raw migrations to create the recorded target. The
current application recipe independently verifies its current model, inserts
`(3, "user")`, and reads `[(1, "admin"), (2, "user"), (3, "user")]`. Its insert is a
one-time smoke check, not an idempotent service startup hook or a complete
readiness assessment. Deployment itself needs neither authoring nor application
modules.

## Deployment and original evidence

```python
import asyncio
from pathlib import Path

from examples.recorded_plan_store import load_original, save_original
from snekql.experimental import migrations as m

# config is the chosen backend's Config; the caller owns this lifetime.
package = m.Package.load(
    await asyncio.to_thread(Path("002_sqlite_roles.json").read_text, encoding="utf-8")
)
lifetime = m.connect(config)
async with lifetime as target:
    prepared = await target.prepare(
        package,
        schema_writers_excluded=True,
    )
    # Review prepared.statements and prepared.preserve_unmanaged here.
    # evidence/ must already be a caller-owned private directory.
    original_path = Path("evidence/002.json")
    await save_original(original_path, prepared)  # refuses an existing file
    result = await target.apply(await load_original(original_path))
await lifetime.wait_closed()
```

Run this inside the owning supervised async loop; configure SQLite here, or use
the MariaDB Config and corresponding package filename for a native target. The
001 predecessor must already be complete. The storage recipe uses off-loop
0600 temporary files, file fsync, same-filesystem non-replacing atomic hard-link
publication, and directory fsync on the qualified Linux environment. It does not
create or secure parent directories, certify power-loss survival, or replace
your evidence backups. A cancelled storage waiter does not prove that its
off-loop filesystem work stopped; inspect the destination before another attempt.
Never overwrite an existing original on rerun: load it
and follow the recovery guide instead. The snippet is not a complete supervisor.

Supply
`schema_writers_excluded=True` only when you actually exclude competing schema
writers and incompatible affected-data writers for the whole operation. Keep
credentials and metadata visibility stable. Coordination does not fence an
administrator, other runner families, or concurrent GRANT changes.

`prepare()` checks recorded catalog continuity. `preserve_unmanaged=True` opts
into a SQLite-only, bounded preservation review when unmanaged facts differ;
native preservation is unsupported. Review what will remain: this is not partial
adoption or permission to modify external policy. Preparation may
refuse declarations, dependencies, catalog renderings, or session policies it
cannot prove safe. Inspect the refusal; do not edit a package digest to bypass it.

Persist `prepared.dump()` using a private destination, file flush/fsync, atomic
publication, and directory fsync. Refuse replacement of an existing original.
Keep it associated with this exact package and target, with appropriate access
control and backups. `Prepared.load(...)` checks a versioned integrity envelope;
it is **not** authentication, encryption, a ledger backup, a portable target
identity, or a frozen Config. Do not reconstruct an original by preparing again.
On interruption, stop and use [recorded recovery](recorded-migration-recovery.md).

A package is target-independent for its declared backend; a prepared plan is
bound to a specific target and observations. SQLite and MariaDB packages are
separate artifacts, even for equivalent authoring intent. Do not compare receipt
hashes between targets or copy prepared plans between them.

After any package has been applied, append a successor instead of editing its
historical declaration, query contract, statements, revision, or digest. There is
one head, not multiple independently composable feature chains. Unsupported old
ledger layouts or interpretation epochs refuse; they are not automatically
converted, recompiled, relabeled, or repaired.

## Connection lifetime and bounded joins

`connect(config) -> Connection` is synchronous and inert. Retain it **before**
opening. It is single-use; `async with` yields a `Target`. After failed entry or
context exit, `await lifetime.wait_closed()` joins that lifetime's known local
cleanup. It also works when opening failed before a Target was yielded.

Each join gets a fresh `Config.operation_timeout`; expiration reports
`DatabaseOperationTimeoutError` with operation `"migration close"`. Waiter task
cancellation, scope cancellation, or timeout does not cancel retained cleanup or
other waiters. A later explicit join can observe completion; retries are not
automatic. Concurrent post-exit waiters are supported. Joining before entry or
while active, reentering, and invalid exit ordering refuse. Do not enter/exit the
same lifetime concurrently.

Keep the owning event loop live while cleanup remains pending, and retain the
lifetime in your supervisor if a join fails. Do not hide it inside a helper that
loses the owner on failed opening. Preserve the primary context error or
cancellation if a cleanup attempt also fails; report the cleanup failure
separately. See the [error-handling pattern](recorded-migration-recovery.md#cleanup-and-primary-errors).

Opening, local-guard admission, backend coordination, each I/O/control operation,
context draining, and physical-close joining retain their separate phase budgets.
There is no cumulative context/package timer or new timeout knob. A failed queued
admission does not invalidate the active owner; context exit stops admission,
rechecks queued callers, and drains without cancelling their tasks.

A successful join observes known local cleanup, **not** remote statement stop,
server rollback, remote lock release, instantaneous thread/transport-callback
quiescence, or application readiness. There is no global drain, all-task-cancel
or stopped-loop guarantee, automatic failed-close repair, or supervisor supplied
by this API. Never queue rollback/cursor/policy SQL on an unsafe interrupted
connection. A deadline or socket close is not proof that physical work stopped.

## Ownership changes and existing databases

- Initial strict SQLite `draft.adopt("accounts")` can claim matching existing schema
  facts with explicit writer exclusion. It is new proved ownership, not evidence
  that an earlier chain ran. Native and partial adoption are unsupported.
- `RelinquishTable(...)` ends ownership without deleting the table or data. It
  does not grant another chain authority or rewrite earlier receipts.
- Preservation retains bounded unmanaged facts without acquiring ownership.
  Read-only/query-only declarations do not silently adopt their tables.
- Re-adoption requires fresh, explicit proof. No multiple heads, blanket stamping,
  unsafe replay, or automatic schema/history repair is provided.

Do not substitute the raw runner's [baseline recipe](migration-baselines.md) for
recorded adoption. They establish different histories and use different ledgers.

## Finite support and promotion status

This opt-in interface remains in **`snekql.experimental.migrations`**. Engineering
acceptance is not a stable namespace, indefinite ABI commitment, release approval,
or permission to convert existing histories.

The completed finite qualification used Linux x86_64, GIL CPython 3.15.0, default
asyncio, disk-backed databases, and both normal and forced `lazy_imports=all`:

| Backend | Exact positive builds and selected settings |
| --- | --- |
| SQLite | 3.45.1 and 3.53.1; DELETE/WAL; requested NORMAL (1)/FULL (2) |
| MariaDB | 10.11.19, 11.4.13, 11.8.9, 12.3.3; InnoDB; owned Unix socket and password-authenticated plaintext loopback TCP |

MariaDB's minimum is 10.11; actual 10.10.7 was negative-only. MariaDB 13.0.2 was
regression-only, not an additional maintained positive build. These exact builds
do not qualify every patch, intervening version, MySQL, in-place upgrades,
free-threaded Python, other OS/event loops, or every transport/TLS combination.
No host/power/volume-loss or secure-erasure certificate is implied.

Session admission verifies inherited integrity policies instead of silently
repairing GLOBAL settings. SQLite requires foreign-key enforcement and UTF-8;
its migration busy budget and requested NORMAL/FULL policy remain explicit.
NORMAL (1) deliberately differs from the earlier accidental FULL (2), and is not
a power-loss guarantee. Native admission normalizes UTC while preserving modes,
verifies strictness/integrity, and requires finite metadata authority: actual
grant-disabled mode, or direct global/exact-schema SELECT, SHOW VIEW, TRIGGER,
and EXECUTE visibility. Role-only/table-only/column-only equivalents are not
proved. Ordinary query credentials need not qualify as deployment credentials.

Frozen package formats 2–8 use execution interpretation epoch 1; prepared wire
format 1 carries its own versioned integrity envelope. Unsupported interpretation
or ledger layout refuses without automatic conversion. Retain released artifacts
and their original evidence; recompiling under a new compiler is not historical
interpretation.

For operational uncertainty, use [recorded migration recovery](recorded-migration-recovery.md).
For the other runner family, use [raw-SQL migrations](migrations.md).
