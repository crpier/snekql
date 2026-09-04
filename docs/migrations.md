# Migrations

snekql applies named, hand-authored SQL changes and records them in Migration
History. Migrations are the sole schema-creation authority: a fresh database is
built by replaying the complete chain. snekql does not generate upgrades or diff
Table Models against a live database.

## Lifecycle

`Database.initialize(...)` only opens connectivity. A deploy applies and checks
the complete migration declaration, then separately checks the live schema
against current Table Models:

```python
MIGRATIONS = {
    "001_create_user": (
        'CREATE TABLE "user" ('
        '"id" INTEGER PRIMARY KEY AUTOINCREMENT, '
        '"email" TEXT NOT NULL'
        ") STRICT"
    ),
    "002_add_user_status": (
        'ALTER TABLE "user" ADD COLUMN "status" TEXT NOT NULL DEFAULT \'active\''
    ),
}

db = await Database.initialize(database=Path("app.db"))
result = await db.migrate(MIGRATIONS)
await db.verify_migrations(MIGRATIONS)
await db.verify([User])
```

These checks answer different questions:

- `verify_migrations(MIGRATIONS)` proves that recorded names, positions, and
  exact SQL checksums are at this code version's complete head.
- `verify([User])` checks the live tables against the current model
  contract. It does not prove that data migrations, triggers, or other effects
  ran.

Replicas that do not apply migrations should run `initialize ->
verify_migrations -> verify` before accepting traffic.

## One complete linear chain

`migrate()` accepts an ordered `dict[str, str]`. Every call supplies the one
complete canonical declaration for that code version. Mapping insertion order is
authoritative; names are opaque and are never parsed as versions.

Do not compose independent subsets per feature, environment, or process:

```python
# Correct: the later code version still declares the complete prefix.
MIGRATIONS = {
    "001_create_user": CREATE_USER_SQL,
    "002_add_status": ADD_STATUS_SQL,
}

# Incorrect: this is not an independently composable migration subset.
await db.migrate({"002_add_status": ADD_STATUS_SQL})
```

The mapping is synchronously copied and validated before connection acquisition.
Names and bodies must be exact built-in strings and valid UTF-8. Names must be
non-empty and at most 255 characters; bodies must contain SQL. Later mutations
of the caller's dictionary cannot alter an in-progress run.

Once a migration has been applied anywhere, never remove, reorder, rename, or
edit it. Append a new entry instead. A body that failed before its history row
was recorded remains pending and may be fixed.

## Migration History v2

The `snekql_migrations` table stores one row per migration:

| Column | Meaning |
| --- | --- |
| `position` | Positive, unique, one-based declaration ordinal |
| `name` | Non-empty unique caller identity, compared byte-exactly |
| `checksum` | Lowercase SHA-256 of the exact UTF-8 SQL body |
| `applied_at` | Server-side UTC timestamp for observability only |

MariaDB stores names and checksums with unpadded binary comparison. Both
backends enforce the correctness-bearing shape in their history DDL.

Before pending SQL runs, `migrate()` requires recorded history to equal the
declaration prefix:

```python
actual == expected[: len(actual)]
```

It rejects holes, reordered or removed entries, renamed migrations, edited
bodies, unknown rows, and history longer than the declaration. An empty
declaration still inspects history and therefore fails against non-empty
history.

`migrate()` returns an immutable `MigrationResult`:

```python
MigrationResult(
    applied=("003_add_audit",),
    already_applied=("001_create_user", "002_add_status"),
    legacy_adopted=False,
)
```

Both tuples follow declaration order. `legacy_adopted` is true when the call
accepted non-empty v1 history as a baseline or completed a previously consented
MariaDB staging upgrade.

## Read-only verification

`verify_migrations(MIGRATIONS)` requires exact equality with the declaration's
full head. It does not create the history table, acquire the migration lock,
upgrade legacy history, adopt a baseline, or execute migration SQL.

It fails when:

- a non-empty declaration has no history table;
- any migration is pending or divergent;
- history is v1, an upgrade staging shape, or an unknown shape;
- an empty declaration encounters non-empty history.

An empty declaration succeeds when no history table exists.

## Failure and transaction behavior

`MigrationDeclarationError` reports invalid declarations before database I/O.
`MigrationHistoryError` reports malformed, divergent, legacy, or pending
history. `MigrationError` means a migration body failed. Migration lock failures
use `MigrationLockError`, with `MigrationLockTimeoutError` for acquisition
timeouts.

The chain commits one successful migration at a time. If a later migration
fails, earlier rows and changes stay committed, the failing migration is not
recorded, and later migrations do not run.

### SQLite

Each pending migration runs in its own transaction:

1. `BEGIN IMMEDIATE` takes the writer lock before history is read.
2. History is ensured or atomically upgraded and checked again.
3. The one pending body executes.
4. Its history row is inserted.
5. The body and history row commit together.

This serializes cooperating runners across independent connections and makes a
persistent SQLite body atomic with its history row. Failure and cancellation
roll back the transaction; a connection whose cleanup cannot be confirmed is
discarded instead of returned to the pool.

One SQLite body must be one persistent statement against the main database.
Transaction control, `VACUUM`, `ATTACH`, `DETACH`, PRAGMAs, temporary objects,
and stacked statements are rejected. Trigger bodies containing internal
semicolons remain one valid SQLite statement.

### MariaDB

MariaDB holds one connection-scoped `GET_LOCK` across history upgrade,
preflight, application, recording, and commits. Lock release is shielded and
must return success; otherwise the physical connection is discarded.

Transactional InnoDB DML and its history insert use one commit. MariaDB DDL
still commits implicitly, so a crash after successful DDL but before history
recording can cause that DDL to run again. Keep DDL idempotent where practical.
Multiple-statement bodies remain supported, and earlier DDL in a body can remain
committed if a later statement fails. Bodies cannot issue transaction control,
change required session settings, call advisory-lock functions, or execute
dynamic SQL because those operations could escape snekql's DML/history
transaction or leave a pooled connection misconfigured.

## Legacy history adoption

History created before v2 contains only `(name, applied_at)`. It cannot prove
the original order or SQL bodies. Ordinary `migrate()` therefore rejects a
non-empty v1 table with instructions to opt in:

```python
result = await db.migrate(MIGRATIONS, adopt_legacy=True)
```

Adoption is a one-time statement of trust in the current declaration. It is not
historical verification. Legacy names must equal the set of names in one
declared prefix; unknown names, holes, inserted predecessors, and overlong
history are rejected. Positions and checksums are assigned from the current
declaration, and existing timestamps are preserved.

SQLite rebuilds v1 atomically. MariaDB uses restartable v1, staging, and final
v2 shapes because its DDL commits implicitly. Once exact staging exists, a
restart continues without asking for consent again and never overwrites a
populated checksum. An empty v1 table may upgrade without consent.
`verify_migrations()` never adopts or upgrades.

Back up the database and stop old application versions before adoption. An old
runner does not understand v2 history.

## Scaffolding the first table

`scaffold([Model])` is a development-time printer for initial DDL:

```python
from snekql.sqlite import scaffold

print(scaffold([User]))
```

Copy its output into source control, split table and index statements into
separate migration bodies, review it, and then treat the literal SQL as
immutable. Do not call `scaffold([CurrentModel])` while the application starts.
Model metadata can legitimately improve over time; recomputing historical SQL
would then change a v2 checksum.

Later changes remain hand-authored `ALTER`, `CREATE INDEX`, `UPDATE`, and other
raw SQL. snekql does not generate model diffs or down migrations.

## Deployment and tests

A release job commonly runs:

```text
initialize -> migrate -> verify_migrations -> verify
```

Application replicas commonly run:

```text
initialize -> verify_migrations -> verify
```

Tests should use an isolated database per canonical chain and replay the same
committed migration declaration as production. A test suite must not rely on
globally unique names to combine unrelated subsets in one history table; exact
prefix semantics deliberately reject that composition.

The bundled `basic` (SQLite) and `mariadb` examples contain committed,
one-statement Migration bodies and run the complete migrate → verify-history →
verify-schema path. Print them with `snekql --example basic` and
`snekql --example mariadb`. The repository suite executes both declarations and
checks that fresh replay and prefix-then-upgrade produce the same final catalog
shape on each backend.
