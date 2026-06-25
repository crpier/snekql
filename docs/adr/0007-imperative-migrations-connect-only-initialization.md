# Imperative migrations; initialization only connects

Status: **Accepted**.

snekql applies migrations and creates schema through explicit verbs on an
initialized `Database`, never as a side effect of `Database.initialize()`.
`initialize` becomes **connect-only**: it opens connectivity and a connection
pool and hands out transactions, and does no schema work at all. Migrations are
applied by an explicit `migrate(...)` call on the live `Database`; the resulting
schema is checked by an explicit `verify(...)` call ([ADR 0008](0008-separate-partial-schema-verification.md)).

This reverses the entry point in [ADR 0001](0001-hand-authored-raw-sql-migrations.md)
(migrations were a `dict[str, str]` passed to `Database.initialize()` and applied
during startup) and **removes automatic table creation from models entirely**.
There is no longer a world in which `initialize` creates tables: schema comes
into existence only by running migration bodies. "Table creation is just a
migration" collapses the previous two-mode behavior — *omit `migrations`* →
auto-create, *pass `migrations`* → migrations-are-sole-authority — into one
unconditional path.

The advisory-lock coordination in [ADR 0002](0002-advisory-locked-concurrent-migrations.md)
is unchanged; the lock now wraps `db.migrate()` instead of the
`initialize(migrations=...)` / `Database.migrate(...)` entry points it named.

## Context

In the previous model, passing `migrations` did double duty: it applied the
migrations *and* its mere presence flipped schema startup from "auto-create
missing tables" to "report a missing table as drift" (`create_missing=False`).
That implicit mode switch — initialization silently changing what it does to
your schema based on whether an argument was present — is the coupling this ADR
removes. Pulling migrations and creation out of boot forces the choice to be an
explicit, separately-named act.

The cost is real and accepted: even a three-line app or a single test must now
define models *and* author a `CREATE TABLE` migration *and* run `migrate`. The
schema scaffold (see the [ADR 0001 amendment](0001-hand-authored-raw-sql-migrations.md#amendments))
removes the tedium of *writing* that DDL; it does not remove the act of applying
it.

## Considered Options

- **Keep migrations on `initialize` (status quo).** Rejected: it couples schema
  mutation to process boot, makes every booting replica a migrator (advisory-lock
  contention on every rollout), and keeps the `migrations`-presence flag that
  silently flips auto-creation.
- **Keep auto-create-from-models alongside imperative migrations.** Rejected:
  two schema authorities — the models and the migration chain — that can diverge
  with nothing at runtime to reconcile them. Making creation *only* a migration
  leaves one authority.
- **Bootstrap a fresh database from current models, then stamp the whole chain
  as applied.** Rejected: this is a *second construction path*
  (create-from-models) that must produce a schema byte-equivalent to *replaying
  the chain*, forever, with nothing at runtime to catch divergence — the classic
  baseline-drift bug. `verify` cannot catch it (it would compare the bootstrapped
  schema against the very models it was built from and pass). Fresh databases
  **replay the entire chain**. If bootstrap is ever revisited, it owes a CI test
  that replays the chain on an empty database and diffs the result against
  create-from-models.
- **A model-direct `create_all(models)` shortcut for tests/quickstart.**
  Rejected for the same reason, sharpened: a second construction path is most
  dangerous in tests, which are the thing meant to *catch* drift. Tests replay
  the chain like production (amortized once per session/run). If replay is
  measurably slow, cache the *replay output* keyed on a hash of the migration set
  — never a model-built snapshot.
- **Keep the standalone `Database.migrate(...)` classmethod.** Rejected: it was
  sugar for "stand up a throwaway runtime, migrate, tear down," which is now the
  deploy step's explicit `init → migrate → verify` lines. `initialize` is the one
  construction path; everything else is a method on the live `Database`.

## Consequences

- `initialize` is model-free and schema-free. It validates only that it can
  connect. A wrong-backend deploy (e.g. SQLite-declared models against a MariaDB
  runtime) is caught at the first `verify` or query, not at init.
- `schema_policy` no longer lives on `initialize`; it moves to `verify`
  ([ADR 0008](0008-separate-partial-schema-verification.md)).
- The deploy/release topology is the caller's choice — one deploy step, or every
  replica calling `migrate` and trusting the lock. The library blesses neither;
  the advisory lock (ADR 0002) keeps every arrangement safe. Documentation
  recommends migrating from one place and having replicas only `init → verify`.
- Tests and `:memory:` databases replay the migration chain; there is no
  model-direct schema shortcut anywhere in the library.
- Breaking change. `docs/migrations.md`, `docs/schema-drift.md`,
  `docs/adoption.md`, the `create_missing` schema-startup path, and the
  `initialize` / `migrate` signatures must all be updated, and the change noted
  in `CHANGELOG.md`.
