# Changelog

## [Unreleased]

### Changed

- Query `repr`/`str` now redact bindings and omit compilation-error details.
  `query.inspect(parameter_visibility="values")` enables value-bearing diagnostics
  for one explicit local call. Use `.compile()` for validation and structured
  SQL/parameter access instead of parsing display text or relying on repr to raise.
  Raw statement representations remain opaque. Addresses #294.

### Added

- Optional `snekql.opentelemetry.OpenTelemetryObserver` exports duration histograms
  and request-parented spans through caller-owned SDK interfaces. Fingerprint
  metric labels use a fixed allowlist; in-flight span storage is bounded. Install
  the `opentelemetry` extra for the API dependency. Completes #293.

- Parameter-free runtime observations now separate driver work, materialization,
  transaction duration, and stream lifetime. `CompiledQuery.fingerprint` identifies
  exact backend SQL without reading bound values; raw operations use one category.
  Cancellation preserves cleanup and commit evidence. Part of #293.

- `Database.pool_stats()` exposes immutable admission utilization, waiters,
  acquisition failures/cancellations, explicit discards, and observer failures.
  Optional synchronous observers receive parameter-free pool wait and checkout
  events in isolated caller contexts. Callback failures do not fail database work;
  cancellation retains cleanup ownership. First part of #293.

- SQLite `Index(..., where=predicate)` declares bounded partial indexes through
  synchronous `__indexes__` factories. Existing lists remain supported. Native
  subset uniqueness, conservative FK eligibility, and structural predicate
  verification are covered; unknown catalog expressions remain unchecked.
  Column-only upsert targets do not gain partial-index inference. Part of #291.

- MariaDB `Index(..., prefix_lengths=(...))` supports ordered character prefixes
  on ordinary Text and LongText. Scaffold and verification preserve prefix facts,
  including native full-capacity VARCHAR normalization. Prefix declarations do
  not authorize FK targets; unmanaged catalog prefix indexes are no longer
  hidden as FK support. Part of #291.

- `LiteralDefault(value)` declares bounded SQL defaults through `default=` on
  generated columns, including integer, Boolean, ordinary text, and nullable NULL
  values on SQLite and MariaDB. Values are validated and encoded at declaration;
  scaffold and catalog verification preserve the distinction from Python defaults.
  Unknown expressions for literal declarations and MariaDB NULL-default
  explicitness remain unchecked. Part of #291.

- Named `CheckConstraint` declarations via synchronous `__checks__` classmethods
  on SQLite and MariaDB. Bounded local predicates scaffold native constraints;
  declared names and recognized catalog expressions produce presence/expression
  verification facts. Unsupported expressions and unmanaged checks remain
  explicitly unchecked. Fact results do not certify data or enforcement settings.
  Part of #291.

- `ForeignKeyConstraint(*columns, references=(...), on_delete=..., on_update=...)`
  in `__foreign_keys__` declares ordered table-level relationships on SQLite and
  MariaDB. Explicit local storage, composite candidate keys, overlapping
  constraints, self-references, and native referential actions are supported.
  Invalid ownership, storage, key shape, or SET NULL declarations fail before
  database access. Part of #291.

- `SchemaVerificationResult.facts` exposes immutable `SchemaVerificationFact`
  records for matched properties, drift, and known unchecked scope on SQLite and
  MariaDB. Existing issues and strict/warn policy remain unchanged; missing
  objects cannot produce matched child facts. Result equality includes facts;
  existing two-argument construction defaults to an empty fact tuple. Part of #291.

- Reviewed `collation=` choices for SQLite Text and MariaDB Text/LongText,
  preserving defaults. Scaffolding and verification honor the choice; physical
  foreign keys inherit it. SQLite verification recognizes quoted collation names
  and the effective final COLLATE clause. Part of #291.

- `mariadb.LongText()` declares native LONGTEXT, defaulting to utf8mb4_bin collation,
  ordinary text codecs, and Python defaults. Scaffolding and verification honor
  its native type and collation. Physical foreign keys and indexes involving
  LongText are rejected. Part of #291.

- `mariadb.Text(length=...)` declares VARCHAR character capacity from 1 to
  16,383, retaining the 255-character default. Scaffolding and schema verification
  honor the length, and foreign keys inherit it from their target. No automatic
  schema alteration or value truncation. First implementation part of #291.

- MariaDB migration-recovery runbook and tested reconciliation example for DDL
  committed without history, including lost commit replies and unsafe mixed
  DML/DDL replay. Expand/contract examples include bounded, resumable backfills
  with atomic data/checkpoint commits on both backends. (#290)

- Reviewed baseline adoption example and checklist for existing SQLite/MariaDB
  databases without history. Preflight checks reject unreviewed schema and invalid
  data before ordinary migration execution; no history-stamping verb. Part of #290.

- `Database.migration_status()` reports immutable applied/pending migration names
  and history presence without applying or adopting changes on SQLite/MariaDB.
  `snekql migrations status` and `plan` load trusted application database contexts,
  support JSON, and show pending SQL only with `plan --sql`. Part of #290.

- SQLite migration bodies support multiple statements in one atomic unit with
  one exact-body checksum and history row. SQLite-aware statement boundaries
  preserve triggers, comments, and quoted semicolons. Every statement retains
  transaction, main-schema, and history protections. Table rebuilds support
  main-table renames without permitting temporary application objects. Failed
  SQLite unit commits now raise `MigrationError` with their native cause. (#289)

- `Database.verify_migrations()` retains strict exact-head verification and adds
  opt-in `policy="compatible"` with an explicitly checksummed `approved_later`
  suffix. The complete known chain remains required; unknown or divergent later
  history is rejected. Migration application and schema verification remain
  separate and unchanged. (#288)

- MariaDB Config gains optional connection lifetime and idle limits plus
  `health_check="checkout"`. Recycling and non-reconnecting health probes share
  the acquisition deadline, preserve TLS and session settings, and never replay
  active Transactions. Defaults preserve passive checks with no age limits. (#286)

- SQLite `Config(durability="full")` applies and verifies WAL plus
  `synchronous=FULL` on initial, additional, and replacement connections. The
  default `"normal"` policy is unchanged. Unsupported values and FULL on in-memory
  targets are rejected before connection initialization. (#285)

- `Transaction.commit_outcome` distinguishes unattempted, rejected, acknowledged,
  and unknown managed commits. Acknowledgement survives subsequent cleanup
  failures; interrupted or lost acknowledgements stay unknown. Both namespaces
  export `CommitOutcome`. A tested opt-in whole-transaction retry example documents
  bounded backoff, idempotency, and ambiguous-outcome reconciliation. (#284)

- Transaction failures expose optional frozen `DatabaseFailure` metadata through
  `DatabaseRuntimeError.failure`, including portable categories and available
  native codes, SQLSTATE, and structured constraint names. Classification covers
  query, stream, acquisition, and control failures without authorizing recovery
  or automatic retries. Transaction-control logs omit driver messages. (#284)

- MariaDB SELECTs support `for_update(wait="block" | "nowait" | "skip_locked")`
  for single-table model, scalar, tuple, named, and alias projections. SQLite,
  joins, grouped/aggregate queries, DISTINCT, and locking subqueries fail
  compilation. Read-only transactions reject locking queries, including native
  EXPLAIN/ANALYZE, before IO. MariaDB EXPLAIN can itself acquire row locks while
  optimizing a locking SELECT; use `compile()` for inspection without IO. (#283)

- `Database.transaction(isolation=..., read_only=...)` provides explicit outer
  transaction policy. MariaDB supports four isolation levels; SQLite supports
  serializable isolation and rejects unsupported combinations before acquisition.
  SQLite restores temporary connection settings before pool reuse, while MariaDB
  uses next-transaction settings. Both namespaces export `IsolationLevel`. (#283)

- Explicit `Transaction.begin_nested()` savepoint contexts reuse the outer
  connection, roll back nested failures, and release without committing.
  Recognized immediate constraint errors can recover after rollback/release;
  uncertain IO and whole-transaction failures remain terminal. Nested contexts
  enforce task ownership, stream cleanup, single-use, and stack-order rules.
  Independent `db.transaction()` nesting is unchanged. (#282)

- Backend `case(condition, then=..., otherwise=...)` factories build typed,
  row-local searched CASE expressions with explicit fallback and nullable
  branch contracts. Nested CASE composes with arithmetic, value functions,
  predicates, and UPDATE assignments. Dependency checks include condition reads
  and both branches. Column comparisons accept computed right operands with
  ordered bindings and scope validation. (#278)

- Native values support typed `coalesce()` fallbacks. Native text supports
  `lower()` and `char_length()`, including nullable results, further expression
  composition, and text UPDATE assignments. JSON-encoded strings are rejected;
  casing and character counting retain documented backend behavior. (#278)

- Native integer/float `.add()`, `.sub()`, and `.mul()` expressions support
  projections, predicates, and atomic UPDATE assignments via `.to_expr()`.
  Types track numeric domains, source ownership, and SQL nullability. Compilation
  rejects assignment dependencies with backend-dependent evaluation order.
  Literal `.to()` validation is unchanged. (#278)

- Named SELECT contracts through `.project(Result, **bindings)` and supported
  write results through `.returning_as(Result, **bindings)` remove the
  eight-value projection ceiling without requiring table models. Results retain
  helper typing, backend identity, readiness, logical codecs, strict Pydantic
  validation, and nullable LEFT JOIN fields. Binding shape and label guards
  reject missing, extra, incompatible, or ambiguous fields. (#279)

- Joins accept ordinary ON predicates without foreign-key declarations, including
  compound comparisons, filters, and correlated subqueries. Left-join ON filters
  preserve unmatched rows. Each ON clause sees only its join prefix and enclosing
  scopes; later joins are not visible. Existing `.references(...)` conditions
  remain supported. (#277)
- `alias(Model, Role, name=...)` gives a table a typed query role for self-joins,
  repeated joins, and correlated subqueries. Alias columns preserve logical
  codecs; model results remain original Fetched Models with optional left-join
  slots. Compilation rejects visible SQL-name and role collisions. Aliases are
  query-only, not schema declarations or mutation targets. (#277)
- `query.compile()` returns inspection-only `CompiledQuery` with parameterized
  SQL, ordered encoded bindings, and backend identity. Both backend namespaces
  export the frozen result type; its text representation redacts bindings.
  Incomplete queries and empty bulk inserts raise `QueryCompilationError`. (#276)
- `Transaction.explain(query)` returns frozen `ExplainResult` with native
  optimizer columns and rows for SQLite and MariaDB. The separate
  `explain_analyze(query)` executes supported MariaDB queries, including writes,
  under normal transaction rules. SQLite ANALYZE and unsupported statement
  shapes fail before query IO. Plan text and execution diagnostics omit
  sensitive output and bindings. (#276)

## 0.7.0 - 2026-09-04

### Added

- MariaDB TCP configuration supports certificate-verifying TLS through
  `TLSConfig`, including system or explicit CA roots and optional mutual-TLS
  client credentials. Hostname verification, certificate verification, and TLS
  1.2 or newer are mandatory on this path. (#255)

- Transaction driver operations now have bounded deadlines. Backend Configs
  separate `operation_timeout` from `acquire_timeout`, while an explicit
  `transaction(timeout=N)` applies to both. Timeouts raise
  `DatabaseOperationTimeoutError` and discard uncertain physical connections.
  (#255)

- Required CI now covers the full test, typing, lint, generated-interface, lock,
  build, and isolated-wheel smoke path on Python 3.14 and live MariaDB 12, plus
  a separate example run on the exact MariaDB 12.2 minimum. CodeQL, dependency
  review, Dependabot, private security reporting guidance,
  trusted release publishing, and artifact provenance are configured. (#255)

- The project is MIT licensed; the SPDX expression and license text are included
  in distribution metadata and artifacts. (#255)

- `ZonedDatetime` preserves an aware datetime's UTC instant and exact IANA zone
  identity or fixed offset through `Text()` storage on SQLite and MariaDB.
  Equality requires both the instant and timezone to match. Chronological
  ordering and range operations are rejected; use `UtcDatetime` when those
  operations are required. (#237)

### Changed

- Schema verification now retains foreign-key constraint grouping, pair order,
  and multiplicity. **Compatibility change:** split or reordered groups that
  previously passed flattened comparison now produce drift and can fail strict
  verification. `foreign_keys.grouping` facts are now matched or drift, not
  unchecked. MariaDB only treats a complete ordered FK tuple as a supporting
  index prefix. Constraint names and other documented limits remain unchecked.
  Part of #291.

- Public typing validation and adoption guidance now target `ty==0.0.77`.
  Artifact smoke tests derive that exact pin from project metadata so release
  validation cannot silently use an outdated checker.

- Query logs and `ExecutionError` strings redact bound values by default while
  preserving explicit `.sql` and `.params` inspection. Set
  `parameter_visibility="values"` only for controlled local diagnostics. (#255)

- The bundled SQLite and MariaDB Migration examples use immutable,
  one-statement bodies. Both declarations are executed in tests, with fresh
  replay versus incremental-upgrade convergence checks. SQLite operations
  documentation now states and justifies the runtime's fixed file-backed WAL
  and `synchronous=NORMAL` durability profile. (#255)

- Query Builder types now carry private executable-readiness state. `ty` rejects
  selects and deletes without row scope, updates without both row scope and an
  assignment, and incomplete nested selects at public `Select`/`Write` and Query
  Runtime seams. Joins and `returning()` preserve readiness, application-facing
  annotation arity is unchanged, and runtime completeness checks remain for
  dynamic callers. (#245)

- Public `Predicate`, `Aggregate`, `Scalar`, `JoinOn`, `OrderBy`, and
  `Assignment` names are now non-constructible annotations backed by private
  Query Builder nodes.
  Factory-produced expressions retain exact inference, forged implementations
  are rejected during Query Construction, and `ColumnRef` now supports typed
  equality comparisons and projection while excluding mutation methods. (#248)

- SQLite and MariaDB APIs now propagate private backend-family type witnesses.
  `ty` rejects cross-family models, query verbs, configurations, Transactions,
  stored queries, joins, foreign keys, and Scaffold calls while public `Model`,
  `Select`, `Write`, and `Transaction` annotations retain their existing arity.
  Runtime checks remain for dynamically typed callers. (#246)

- Query Compilation now produces private typed execution plans for `fetch_one`
  and writes. Plans carry SQL, parameters, backend identity, cardinality, and
  validation policy, so Query Runtime no longer dispatches writes by concrete
  builder class. Missing single-row `RETURNING` results now raise
  `ResultCardinalityError` instead of leaking `IndexError`. (#250)

### Fixed

- MariaDB owns shutdown independently of cancelled callers and waits for
  discarded leases. Partial connection authentication shares the acquisition
  deadline and closes sockets on cancellation. Cleanup errors preserve the
  initialization failure, shutdown rejects in-flight checkout completions, and
  failed idle socket closes remain owned for retry.
  Credential rotation and backend shutdown policies are documented. (#286)

- SQLite shutdown attempts all idle connection closes after a driver failure,
  retains failed handles for a later `close()` retry, and rejects new work until
  cleanup succeeds. Returned connections keep shutdown waiting for physical
  cleanup; failed discards retain their handles and reject new work, including
  after a concurrent shutdown timeout. (#286)

- MariaDB `json_extract_int()` binds JSON paths as driver parameters instead of
  interpolating SQL literals, including hostile quote-bearing input. Partial
  initialization, cancelled configuration, timed-out queries, and failed
  begin/commit/rollback paths now close or discard physical connections rather
  than leaking or pooling unknown state. (#255)

- `Database.verify(...)` now inspects every requested Table Model before applying
  policy and returns an immutable, machine-readable `SchemaVerificationResult`;
  strict failures carry the same result. SQLite verification is cancellation
  safe and now distinguishes exact `AUTOINCREMENT`, partial indexes, collations,
  and supported server defaults. MariaDB now verifies foreign keys, signedness,
  datetime precision, index prefixes/types, and supported server defaults while
  excluding required implicit FK indexes. Catalog reads are batched where the
  backends permit. (#253)

- Bound column descriptors now freeze public owner, name, nullability, default,
  key, and storage metadata after Table Model declaration finishes. Attempts to
  assign or delete finalized metadata raise `FrozenModelError`. (#249)

- Required nullable enforced foreign keys can be declared as
  `FKCol[Target, T | None] = ForeignKey(Target.id, nullable=True)`. Pending
  construction requires the field while accepting `T` or `None`; add
  `default=None` to make it omittable. (#236)

- Fluent query methods whose runtime contract requires at least one value now
  reject zero-argument calls under `ty`. Nullable columns retain nullable result
  types while rejecting `None` in literal comparisons; use `is_null()` or
  `is_not_null()` for SQL NULL checks. Runtime construction guards remain in
  place for dynamically typed callers. (#247)

## 0.6.0 - 2026-08-31

### Breaking changes

- Migration declarations now define one complete ordered chain instead of an
  independently composable name set. `migrate()` rejects removed, reordered,
  unknown, or edited applied entries by comparing one-based positions and exact
  SQL SHA-256 checksums. An empty declaration still inspects history. Existing
  non-empty name-only history must be explicitly accepted once with
  `migrate(..., adopt_legacy=True)`. SQLite migration bodies must be one
  persistent main-database statement and cannot contain transaction control,
  PRAGMAs, `VACUUM`, attachment changes, or temporary objects. MariaDB bodies
  can still contain multiple statements but cannot issue transaction control,
  change required session settings, call advisory-lock functions, or execute
  dynamic SQL. MariaDB now requires an InnoDB page size of at least 8 KiB for
  byte-exact history-name uniqueness. (#254)

- Public typing now targets `ty==0.0.75` exclusively. Model fields use the
  owner-free forms `Col[T]`, `GenCol[T]`, `FKCol[Target, T]`, and
  `JsonCol[T]`; concrete descriptors, metaclasses, model bounds, and query-state
  classes are no longer exported. Stored queries use the annotation-only
  `Select[Row]` and `Write[Result]` aliases, which are not constructors or
  runtime `isinstance` targets. Projection and mutation `returning(...)`
  inference is supported through eight selected values. (#241)

- A scalar subquery can no longer be the first item in a multi-value projection.
  The first projected expression establishes the outer query's `FROM` scope;
  allowing a scope-free scalar in that slot let static scope checking diverge
  from Query Compilation. Put a model-owned column, aggregate, or dialect
  expression first and scalar subqueries in later slots. (#241)

- The column metadata attribute `Attr.sqlite_storage_class` is **renamed to
  `storage_class`** (the ADR-0003 sanctioned backend-neutral name); values are
  unchanged (`"INTEGER" | "REAL" | "TEXT" | "BLOB"`). Code declaring columns
  through the documented constructors is unaffected; only code reading the
  attribute off a column descriptor must switch to the new name. The internal
  `AttrConfig`/`build_attr` construction helpers are gone: `Attr.__init__` now
  takes the column metadata as keyword arguments directly. (#228)

- `Predicate` is now an **abstract base class**; every predicate builder
  (`.eq()`, `.in_()`, `&`/`|`/`~`, `exists()`, ...) returns a dedicated frozen
  node that compiles itself through the open-AST seam, replacing the former
  type-erased `Predicate(kind=...)` record. Constructing a bare `Predicate()`
  now raises `TypeError` at construction instead of failing later with
  `QueryConstructionError` when the predicate reached `where()` validation.
  Code that builds predicates through the documented column/aggregate methods
  and composes them with `&`/`|`/`~` is unaffected, including
  `isinstance(..., Predicate)` checks and `Predicate[Owner]` annotations. (#227)

- A **naive `datetime` is now rejected** when encoding a MariaDB native
  `DateTime` column, with a `ModelValidationError`. That column stores
  offset-less UTC text, and the previous encoder normalized with `astimezone`,
  which interprets a naive value as the **write machine's local zone** — so the
  same wall-clock value landed as a different stored instant depending on where
  the write ran, and read back aware-UTC (an asymmetric, machine-dependent
  round-trip). snekql no longer guesses the zone: attach a timezone, or annotate
  `Col[AwareDatetime]` to reject naive at model construction. Aware datetimes are
  unaffected. The primitive-storage path (SQLite `Col[datetime] = Text()`) is
  unchanged and still round-trips naive as naive wall-clock text.

- Columns are now **NOT NULL by default**. Omitting `nullable=` (or passing
  `nullable=None`) previously produced a physically nullable column whose
  non-optional read type promised a non-`None` value — a silent mismatch where a
  `NULL` row decoded to `None` while the type checker believed otherwise (#203
  F9). An unset `nullable=` now means NOT NULL, identical to `nullable=False`;
  only `nullable=True` (which still requires a `| None` read type) opts into a
  nullable column. Scaffolded/migrated DDL for any column declared without
  `nullable=` now emits `NOT NULL`; if you relied on the old implicit-nullable
  behavior, declare the column `Col[T | None]` with `nullable=True`. This holds
  even when the declaration-time annotation cross-check cannot resolve the hint
  (e.g. a forward reference), closing a second seam where a skipped cross-check
  left a non-optional column silently nullable. (#203)

### Fixed

- SQLite now starts `BEGIN IMMEDIATE` before reading Migration History and
  commits each body with its history row, which closes the cross-instance race
  and the body/bookkeeping crash gap. MariaDB now commits transactional InnoDB
  DML with its history row, confirms advisory-lock release, and discards the
  physical connection when lock cleanup is uncertain. MariaDB DDL retains its
  documented implicit-commit crash window. Legacy MariaDB upgrades now resume
  exact staging state without requiring adoption consent a second time. (#254)

- Valid required-nullable and non-`None`-defaulted `ForeignKey` declarations now
  satisfy the field-specifier overloads in both backend namespaces. Public
  `Select[Row]` and `Write[Result]` annotations can now be passed directly to
  Query Runtime methods without losing their result type. (#241)

- Generated-column detection now resolves the actual annotation rather than
  searching its source spelling, so an imported alias of `GenCol` preserves
  pending-generation behavior. Partially resolved forward references are no
  longer cached permanently; later module-level payload types resolve on retry,
  while a later function-local payload now fails at declaration with guidance to
  define it first. An application table named `Model` is treated as a concrete
  table instead of a framework base. (#241)

- `insert(...)` now rejects database-materialized Fetched models, uninitialized
  model objects, and mixed-model bulk batches during Query Construction.
  Aggregate function names must be exact built-in strings even when an
  expression node is constructed directly, preventing arbitrary function text
  or hostile string subclasses from reaching SQL compilation. (#241)

- Package metadata no longer installs `snektest` for library consumers, and the
  source distribution now uses an explicit release-input allowlist instead of
  including local caches, settings, tests, reports, and research artifacts.
  (#241)

- `scalar(subquery)` is now typed `Scalar[Any, T | None]` and decodes a no-match
  to `None` instead of raising. A SQL scalar subquery evaluates to `NULL` on an
  empty/no-match result set regardless of the inner column's `NOT NULL`
  constraint; the projected slot previously typed the inner column's
  non-optional type and raised `ModelValidationError` at fetch when the subquery
  matched zero rows (#203 F10).

### Added

- `Database.migrate(...)` now returns an immutable `MigrationResult` with
  ordered `applied` and `already_applied` names plus an explicit legacy-adoption
  flag. `Database.verify_migrations(...)` performs a read-only exact-head check
  for replicas and deployment gates. New public migration errors distinguish
  declaration, history, body, and lock failures. (#254)

- Insert queries now support atomic conflict handling with
  `.on_conflict(..., action=DoUpdate(...))` and
  `.on_conflict(..., action=DoNothing)`. `DoUpdate` accepts several typed
  assignments; `column.to_inserted()` references the attempted insert value,
  while ordinary `.to(value)` and `.to(CurrentTimestamp)` assignments remain
  available. SQLite emits `ON CONFLICT`; MariaDB emits `ON DUPLICATE KEY UPDATE`
  and checks every unique key because it has no explicit conflict-target syntax.
  Single and bulk `DoUpdate` inserts retain `.returning(...)`; `DoNothing`
  rejects it because SQLite may produce no row. (#239)

- `UtcDatetime`, exported from `snekql.sqlite` and `snekql.mariadb`, is a curated
  datetime logical type for database timestamp columns. It rejects naive values,
  normalizes aware values to UTC milliseconds at validation, and serializes as
  fixed `YYYY-MM-DDTHH:MM:SS.sssZ` text so SQLite `Text()` equality, ordering,
  and range predicates compare by instant. SQLite `Text()` columns annotated as
  bare `datetime` or pydantic `AwareDatetime` now emit a suppressible
  `LexicalDatetimeWarning` at model declaration because their raw ISO text
  compares lexically; attach `OrderPreserving` to a custom `Annotated` type to
  self-certify an order-safe wire form. (#212)

- `db.transaction(mode="immediate")` declares write intent so SQLite acquires
  the single writer lock up front via `BEGIN IMMEDIATE`, resolving writer
  contention fairly at acquisition instead of mid-transaction. On top of the
  per-connection `busy_timeout` PRAGMA, snekql now retries that acquisition with
  bounded exponential backoff and jitter (`Config.busy_max_retries`, default 5;
  backoff tunable via `Config.busy_base_backoff` and `Config.busy_max_backoff`),
  so a burst of concurrent writers is absorbed rather than surfacing
  `OperationalError`/`ExecutionError`; a genuinely stuck lock still surfaces once
  the budget is spent. `mode` defaults to `"deferred"` (unchanged behavior) and
  is a no-op on MariaDB, whose InnoDB engine uses row-level locks. See
  [docs/engine-settings.md](./docs/engine-settings.md). (#201)

## 0.4.0 - 2026-06-28

### Breaking changes

- `Database.initialize(...)` is now **connect-only**: it opens connectivity and a connection pool and does no schema work. It no longer accepts `models=`, `schema_policy=`, or `migrations=`. Migrations and verification are explicit verbs on the live Database, and **automatic table creation from Table Models is removed entirely** — schema comes into existence only by running migration bodies. Move `initialize(migrations=..., models=..., schema_policy=...)` to `initialize → migrate → verify`:
  ```python
  db = await Database.initialize(database=Path("app.db"))
  await db.migrate({"001_create_user": 'CREATE TABLE "user" (...) STRICT'})
  await db.verify([User], policy="strict")
  ```
  `db.migrate(migrations)` applies the migrations imperatively with the same apply runner, Migration History, idempotency, and advisory-lock coordination as before. `db.verify(models, *, policy=...)` checks the live schema against the models and is where the Schema Policy now lives (`strict` raises, `warn` logs). A fresh database is built by replaying the whole migration chain; the dev-time `scaffold(...)` helper emits the initial `CREATE TABLE` DDL so you do not hand-write it. The standalone `Database.migrate(...)` classmethod is removed — `initialize` is the single construction path. This reverses the entry point and timing of the migrations design introduced earlier in this unreleased cycle (see [docs/adr/0007-imperative-migrations-connect-only-initialization.md](./docs/adr/0007-imperative-migrations-connect-only-initialization.md), [docs/adr/0008-separate-partial-schema-verification.md](./docs/adr/0008-separate-partial-schema-verification.md)).
- Renamed the generated-value sentinel from `MISSING` / `Missing` to `PENDING_GENERATION` / `PendingGeneration`.
- Replaced the structured-logger requirement with standard-library `logging`. `Database.initialize(...)` no longer accepts a `logger=` argument, and `StructuredLogger` is no longer exported from the backend namespaces. snekql now logs through the stdlib `logging` hierarchy under per-module loggers rooted at `snekql` (`snekql.runtime`, `snekql.sqlite.runtime`, …), emitting conventional message-style records (`logger.info("...", arg)`) instead of structlog-style event dicts. An application controls all snekql output from the one `snekql` logger (e.g. `logging.getLogger("snekql").setLevel(logging.WARNING)`); a `NullHandler` is attached at import so snekql stays silent until the app configures logging. To recover machine-readable fields, point a JSON/structured formatter (such as `structlog`'s `ProcessorFormatter`) at the handler receiving `snekql` records.
- Removed the flat top-level import surface. Public symbols are no longer importable from the package root (`from snekql import select` / `Model` / `Text` / ... now fail); the `snekql` root only exposes the `mariadb` and `sqlite` namespace handles (`snekql.__all__ == ["mariadb", "sqlite"]`). Import everything -- the dialect-neutral verbs and builders as well as a backend's `Model` and column constructors -- from a backend namespace instead: `from snekql.sqlite import Model, Text, select` or `from snekql.mariadb import Model, Json, select`. Each namespace re-exports the shared neutral symbols alongside its own dialect-specific ones, so an application imports its whole surface from one namespace. This keeps SQLite-only and MariaDB-only symbols from colliding and stops type-checker auto-imports from landing on the wrong backend (see ADR 0004).
- Table Model field values are now validated against their declared logical type with a strict per-column pydantic `TypeAdapter`, both when constructing a Pending Model and when materializing a Fetched Model. Values that previously slipped through column coercion (for example a `bool` or `float` for an `Integer` column, or a JSON payload that does not match its annotated container shape) now raise `ModelValidationError`. The logical type comes from the column's `Col[T]` / `GenCol[T]` / `FKCol[Target, T]` annotation.
- `DateTime` columns now require timezone-aware `datetime` values and reject naive ones (validated via pydantic `AwareDatetime`). UTC and millisecond canonicalization happen only when the value crosses the database boundary, so a Pending Model now holds the raw aware `datetime` you constructed it with rather than a pre-normalized UTC value.
- `Json` columns validate the annotated container shape at construction; JSON serializability is now a wire-codec concern checked only when the value is encoded for storage. A value matching the annotated shape but not serializable is accepted at construction and rejected at encode time.
- Removed the `foreign_key=` parameter from `Integer`, `Real`, `Text`, `Blob`, and `DateTime`, and the primary-key-default foreign-key resolver. Foreign keys are now declared with the `ForeignKey(target_column)` specifier, which names the target column explicitly (including primary-key targets).
- SQLite connections now enforce foreign keys (`PRAGMA foreign_keys = ON`), so previously inert `FOREIGN KEY` constraints are now enforced on every write. MariaDB tables are created with `ENGINE=InnoDB` and enforce foreign keys via `foreign_key_checks`. Databases with pre-existing referential-integrity violations may surface errors on writes that touch the dangling rows; see [docs/engine-settings.md](./docs/engine-settings.md).
- MariaDB text columns are now created as `VARCHAR(255) ... COLLATE utf8mb4_bin` (case-sensitive) to match SQLite's default `BINARY` collation. Existing tables using the default case-insensitive collation are reported as schema drift.
- MariaDB runtime now requires MariaDB **>= 12.2**; older or non-MariaDB servers are rejected at initialization.
- `Transaction.execute(update(...))` and `Transaction.execute(delete(...))` now return the affected-row count (`int`) instead of `None`. The count is the driver's own `rowcount` for the statement: SQLite counts every row the `WHERE` clause matched, while MariaDB (via aiomysql, without `CLIENT_FOUND_ROWS`) counts only rows an `UPDATE` actually changed, so updating a row to its current value does not increment the count there. A plain `insert(...)` still returns `None`.

- `CurrentTimestamp` is now used as a bare class object rather than an instance: pass `server_default=CurrentTimestamp` instead of `server_default=CurrentTimestamp()`. The old call form no longer registers a server default and now fails model declaration with `unsupported server default`.
- `Transaction.fetch_one` now carries an exactly-one contract. It returns the single matching row in the selected shape and raises the new `NoResultError` when no row matches or `MultipleResultsError` when more than one does, instead of returning the first row or `None`. The single-value overload return type drops `| None` accordingly, so a `None` from a single-value `fetch_one` now unambiguously means a SQL `NULL` value rather than a missing row (resolving the no-row vs `NULL` ambiguity). The zero-or-one behaviour moves to the new `fetch_one_or_none`; take the first of several rows on purpose with `.limit(1)`.

### Added

- Column-level `index=True` flag on `Integer`, `Real`, `Text`, `Blob`, `ForeignKey` (and the MariaDB `Json`, `Boolean`, `DateTime`, `Uuid` columns), sugar for a non-unique single-column index named `ix_<table>_<col>` — the non-unique counterpart to the existing column-level `unique=True`. It is equivalent to an `Index(col)` entry in `__indexes__` and collides with one as a duplicate. Rejected on primary-key columns and alongside `unique=True`, since both are already indexed.
- `column.to(CurrentTimestamp)` server-expression update assignment: `update(Model).set(Model.edited_at.to(CurrentTimestamp))` refreshes a column to the database clock on update, the way `server_default=CurrentTimestamp` fills it on insert. It renders the backend's current-timestamp SQL inline in the `UPDATE` (no bound parameter) and works identically on SQLite and MariaDB. SQLite has no native `ON UPDATE CURRENT_TIMESTAMP`, so the refresh is explicit at the call site rather than an implicit on-update default; include the assignment in each update that should bump the timestamp. `.to(...)` still takes a plain Python value for ordinary assignments.
- `Database` is now an async context manager: `async with await Database.initialize(...) as db:` closes the runtime on block exit, including when the body raises, so a forgotten `close()` (and the shutdown hang it causes) can't happen. `__aexit__` calls the existing `close()`, so the shielded, idempotent shutdown semantics are unchanged; explicit `initialize()`/`close()` still works for callers that manage the lifecycle by hand.
- `Transaction.fetch_one_or_none`: the zero-or-one read. It returns the matching row or `None` when none matches, and raises `MultipleResultsError` on more than one row. It is offered only for model, tuple, and join selects, where `None` can only mean a missing row; single-value selects are rejected (a type error, and a `QueryConstructionError` at runtime) because their `None` would conflate a missing row with a SQL `NULL` value -- use `fetch_all` (the list distinguishes `[]` from `[None]`) or project a tuple including a non-nullable column. See [docs/typing.md](./docs/typing.md).
- `NoResultError` and `MultipleResultsError` exceptions (both `DatabaseRuntimeError` subclasses), exported from the `sqlite`/`mariadb` backend namespaces, raised by `fetch_one`/`fetch_one_or_none` when result cardinality violates their contract.
- `Transaction.fetch_chunks(select(...), size=N)`: streaming/bounded reads for large result sets. Unlike `fetch_all`, which loads the whole result into memory, it fetches rows incrementally from a server-side (unbounded) cursor in batches of up to `N` materialized rows. It returns the new `ChunkStream[Row]` — an async context manager that is also an async iterator — consumed inside `async with` so the cursor is closed and the connection released deterministically on full consumption, early `break`, or an error mid-iteration: `async with tx.fetch_chunks(select(User).all(), size=500) as stream: async for batch in stream: ...`. The stream holds the transaction's single connection for its whole lifetime (no other query may run on the transaction until it closes) and must be opened and consumed within one task; `size` must be a positive integer (a `QueryConstructionError` otherwise). On MariaDB it uses an unbuffered `SSCursor`, since a default aiomysql cursor buffers the whole result client-side and would defeat streaming. `ChunkStream` is exported from the `sqlite`/`mariadb` backend namespaces for typed annotations. Resolves issue #59.
- `Transaction.fetch_all` now yields a cooperative `anyio` checkpoint every `FETCH_ALL_YIELD_INTERVAL` (1000) rows while materializing, so a large result set no longer monopolizes the event loop for the whole synchronous materialization stretch. The interval is large enough that bounded reads pay no measurable overhead. The docstring and the README reads section now state explicitly that `fetch_all` is for bounded result sets and that large or unbounded reads belong in `fetch_chunks`, which streams from a server-side cursor and keeps per-batch materialization small. Resolves issue #187.
- Versioned migrations applied imperatively with `db.migrate(migrations)`: an ordered `dict[str, str]` of migration name to raw SQL body run on a live, connect-only Database. snekql ensures a snekql-owned `snekql_migrations` history table, runs each pending migration (mapping keys not yet recorded) once in insertion order, and records each success. Migrations are hand-authored and never generated, and are the sole schema-creation authority (there is no automatic table creation from models). snekql does not wrap a migration body and its history row in one transaction (bodies are applied as-is and must be idempotent); a failing body halts with the new `MigrationError`, naming the migration, while already-applied migrations stay recorded. Concurrent runs across instances are coordinated by a backend advisory lock (see below). See [docs/migrations.md](./docs/migrations.md) and [docs/adr/0001-hand-authored-raw-sql-migrations.md](./docs/adr/0001-hand-authored-raw-sql-migrations.md).
- `db.verify(models, *, policy=...)`: an explicit, partial, structural schema check separate from initialization and migration. It inspects each Table Model's live table and reports Schema Drift under the Schema Policy (`strict` raises `SchemaVerificationError`, `warn` logs), never creating anything. It is the only feedback loop tying the hand-written migration chain back to the models. It is deliberately structural and cannot see default values, `CHECK` constraints, generated-column expressions, triggers, views, exact SQLite types, or data. Run `migrate` then `verify` together; deploy steps run `initialize → migrate → verify`, replicas run `initialize → verify`. See [docs/schema-drift.md](./docs/schema-drift.md) and [docs/adr/0008-separate-partial-schema-verification.md](./docs/adr/0008-separate-partial-schema-verification.md).
- `scaffold(*models)` dev-time helper, exported from each backend namespace (`from snekql.sqlite import scaffold`). It returns the initial `CREATE TABLE` (and index) DDL for one or more Table Models as text you own and paste into your migration set — append-only and immutable once committed. It is a pure function: no database, no model-vs-live diffing, no `ALTER` generation, no autogenerate.
- Concurrent migration runs are coordinated by a backend advisory lock, so several instances calling `db.migrate(...)` at once are safe. The lock wraps the whole apply flow (ensure history, read applied, run pending, record); the winner applies pending migrations while losers wait and then observe the completed Migration History, so no migration applies twice. MariaDB uses a connection-scoped per-database `GET_LOCK` advisory lock released on success, failure, and disconnect; a loser that cannot acquire it within `acquire_timeout` raises the new `MigrationLockTimeoutError` having applied nothing. SQLite has no advisory-lock primitive and relies on its single-writer file lock plus `busy_timeout` to serialize concurrent runs. See [docs/migrations.md](./docs/migrations.md) and [docs/adr/0002-advisory-locked-concurrent-migrations.md](./docs/adr/0002-advisory-locked-concurrent-migrations.md).
- `MigrationError` exception (a `SnekqlError`), exported from the package root, raised when a migration body fails to apply.
- `MigrationLockTimeoutError` exception (a `SnekqlError`), exported from the package root, raised when an instance cannot acquire the migration advisory lock within the acquire timeout.
- Ordered-comparison and range column predicates: `.gt(...)`, `.gte(...)`, `.lt(...)`, `.lte(...)`, and `.between(low, high)`. They compile to `> >= < <=` and `BETWEEN ? AND ?`, are scope-checked and composable with `&`/`|`/`~` like the existing predicates, and reject `None` arguments (steering callers at `is_null()`/`is_not_null()`).
- `ForeignKey` column specifier, exported from the package root and the `sqlite`/`mariadb` backend namespaces. It records the referenced column on the descriptor, derives the column's storage class from that target, and cross-checks the target against the column's `FKCol[Target, T]` annotation at declaration time.
- Foreign keys may reference any unique non-primary-key target column (for example `User.email`), not only the target's single primary key.
- `ForeignKey(...)` accepts `on_delete=` and `on_update=` referential actions (`"CASCADE"`, `"RESTRICT"`, `"SET NULL"`, `"NO ACTION"`), rendering `ON DELETE`/`ON UPDATE` clauses on the generated constraint so owned child rows can cascade or null out when their parent changes instead of requiring a manual, order-sensitive multi-table delete. Both backends render identically through the shared schema compiler. `SET DEFAULT` is intentionally unsupported: SQLite honors it but InnoDB silently ignores it, so it is not portable. An action left unset renders no clause (the database default `NO ACTION`), keeping existing scaffolds byte-for-byte unchanged. `on_delete`/`on_update` `"SET NULL"` is rejected at declaration on a `NOT NULL` or primary-key foreign-key column, where it could never fire. On SQLite, `verify(...)` now also compares the referential action and reports a model/live mismatch as drift (MariaDB does not verify foreign keys).
- Centralized engine-settings seam that applies and verifies the connection settings snekql depends on, failing fast when a setting cannot be confirmed. SQLite verifies `foreign_keys`, `busy_timeout`, and UTF-8 `encoding` on every pooled connection; MariaDB verifies a strict `sql_mode` (`STRICT_ALL_TABLES`, `NO_ENGINE_SUBSTITUTION`), UTC `time_zone`, and `foreign_key_checks` on every physical connection, plus a minimum-version guard. Documented in [docs/engine-settings.md](./docs/engine-settings.md).
- `Model.construct(**values)` classmethod that builds a Pending Model while skipping per-column logical validation, for values already known to satisfy their declared types. Defaults, missing/unknown-field structural checks, and freezing still apply.
- `validate: bool = True` keyword on Query Runtime fetch methods and mutation
  execution (threaded through row materialization) to skip read-side logical
  validation for trusted result sets while keeping wire decoding. Calls with
  literal `validate=False` are typed as raw `object`-shaped results rather than
  promising the selected logical type.
- `Json` columns now serialize and decode through the same per-column pydantic `TypeAdapter` that drives validation (`dump_json` / `validate_json`), making the codec symmetric. Any type the `Col[T]` annotation can validate -- `datetime`, pydantic models, `list[Model]`, and so on -- now round-trips, rather than only `dict`/`list`/primitives. Native payloads keep the same compact, byte-stable text as before. A `validate=False` decode still returns the raw `json.loads` value with no type coercion.
- Subquery support: a select can now be nested inside another query.
  - `column.in_subquery(select(...))` / `column.not_in_subquery(select(...))` test membership against a single-column subquery (`IN (SELECT ...)` / `NOT IN (...)`). The subquery must project exactly one column whose value type matches the column's, enforced both in the typed surface and at construction.
  - `exists(select(...))` / `not_exists(select(...))` package-root predicates compile to `EXISTS (...)` / `NOT EXISTS (...)` and accept any select (the projection is irrelevant to existence).
  - Column-to-column comparisons `.eq_col(...)`, `.ne_col(...)`, `.gt_col(...)`, `.gte_col(...)`, `.lt_col(...)`, `.lte_col(...)` compare a column against another column or a scalar subquery. A column operand on the inner side referencing the outer query is how a **correlated** subquery relates its row to the outer row; correlation is scope-checked when the query compiles.
  - `scalar(select(...))` wraps a single-column select as a value usable in a projection (`select(User.id, scalar(...))`) or as a `*_col` comparison operand, decoding through the subquery's projected column or aggregate.
  - Nesting is arbitrary-depth; inner and outer placeholders stay aligned in textual order across SQLite and MariaDB. An out-of-scope correlation (a referenced table in neither the subquery nor any enclosing query) is a `QueryCompilationError`, and a multi-column `in_subquery`/`scalar` subquery is a `QueryConstructionError`.
- Bulk inserts and `RETURNING`-backed writes:
  - `insert([row, row, ...])` accepts a sequence of Pending models and compiles to one multi-row `INSERT ... VALUES (...), (...)` statement instead of one round-trip per row. Every row must set the same columns (so they share one `VALUES` list; a mismatch is a `QueryCompilationError`), and an empty sequence is a no-op that issues no SQL. Typed as the new `InsertManyQuery`.
  - `.returning()` on a single or bulk insert recovers the values the database produced (auto-increment primary keys, `CurrentTimestamp` and other server defaults) as Fetched models, with no follow-up `select`. It is always explicit: a plain `insert(...)` still returns `None`. `Transaction.execute` is typed accordingly -- a single returning insert yields one Fetched model, a bulk one yields a `list` -- via the new `InsertReturningQuery` / `InsertManyReturningQuery`. `RETURNING` works identically on SQLite and MariaDB (>= 12.2), projecting every column in declaration order, and `execute` takes the same `validate: bool = True` toggle as the fetch methods for the returned rows.
  - `InsertManyQuery`, `InsertReturningQuery`, and `InsertManyReturningQuery` are exported from the package root. `InsertQuery` now carries a second type parameter (the Fetched read type): `InsertQuery[Owner, Read]`.

### Changed

- `ExecutionError` now folds its chained cause into `str()` (`cause=<type>: <message>`) when raised with `raise ... from cause`, so the underlying driver error (e.g. `no such table: ...`) is visible without inspecting `__cause__` or the traceback. All execution-failure sites already chain the original error, so the message gains the cause across the board; the SQL and params context is unchanged.
- Encoding now rejects values no backend can persist losslessly with a `ModelValidationError`, before the value reaches the driver: non-finite floats (`nan`, `inf`, `-inf`) on real-number columns (`nan` would silently become `NULL` in SQLite `REAL`, and MariaDB `DOUBLE` refuses them outright) and integers outside the signed 64-bit range `[-2**63, 2**63 - 1]` on integer columns (previously the SQLite driver raised a raw `OverflowError` at bind time). See [docs/adr/0005-storage-primitive-constructors-with-derived-codecs.md](./docs/adr/0005-storage-primitive-constructors-with-derived-codecs.md).
- Encoding now rejects `Text`/`Blob` values that exceed a backend's variable-width column ceiling with a `ModelValidationError`, before the driver silently truncates them: MariaDB `Text` is `VARCHAR(255)` (255 characters) and `Blob` is `BLOB` (65535 bytes), so a value past either limit would corrupt in MariaDB non-strict mode. SQLite's shared ~1 GB `TEXT`/`BLOB` limit is treated as unbounded, and MariaDB `Json` (LONGTEXT-backed) is unbounded. See [docs/adr/0005-storage-primitive-constructors-with-derived-codecs.md](./docs/adr/0005-storage-primitive-constructors-with-derived-codecs.md).

### Fixed

- The MariaDB `Json` column constructor now has a `default=None` overload matching `Integer`/`Real`/`Boolean`, so a nullable JSON column (`Col[dict[...] | None] = mariadb.Json(nullable=True, default=None)`) type-checks instead of narrowing the column to `None`.
- SQLite connection pool acquisition is now first-in-first-out fair. Previously a task that released a connection could immediately re-acquire it ahead of tasks already waiting (`condition.notify_all()` with no ordering), so under contention one worker could monopolize the pool while another was starved for the duration of the load (Jain fairness index ≈ 0.13 at `pool_size=1, workers=8`, with ~1 s tail acquire latency). Waiters are now served in arrival order via a ticket queue, eliminating the starvation (Jain ≈ 1.0, millisecond tail latency) with unchanged throughput. The MariaDB runtime delegates to the `aiomysql` pool and still exhibits this starvation; that is tracked separately. See `benchmarks/` and issue #66.

### Notes

- Following pydantic's documented behavior, `Real` columns accept an `int` and widen it to `float` even under strict validation.
- Storage codecs carry two intentional precision losses, now documented in ADR 0005: MariaDB `DateTime` columns truncate `datetime` values to millisecond precision (`DATETIME(3)`) and normalize to UTC on encode; SQLite `Col[datetime] = Text()` preserves microseconds and the original offset.

## 0.3.0 - 2026-06-07

### Breaking changes

- `Database.initialize(...)` now requires an explicit structured logger keyword argument.
- Backend drivers are optional extras; install `snekql[aiosqlite]` for SQLite runtime support and `snekql[aiomysql]` for MariaDB runtime support.
- Table models carry backend identity, and runtime initialization/execution rejects mixed-backend models and queries.

### Added

- MariaDB backend namespace, runtime configuration, schema startup, query execution, value codecs, indexes, and schema drift verification.
- Temporary MariaDB test-server support for local integration tests, including reset helpers and a CLI entry point.
- Structured Query Runtime logging for database initialization, schema startup, transactions, query execution, pool lifecycle, shutdown, and failures.
- Public `StructuredLogger` protocol for structlog-style application loggers.
- Schema index support for column-level unique indexes and table-level indexes.
- Adoption, schema drift, error-handling, typing, and MariaDB testing documentation with runnable examples.

### Changed

- Refactored SQLite runtime behind backend-neutral runtime adapter seams.
- Deepened query compilation through Dialect-owned SQL rendering instead of MariaDB translating SQLite-shaped SQL.
- Deepened schema startup through a shared schema plan while preserving backend-specific DDL and drift checks.
- Deepened Table Model materialization through shared Pending Model encoding, Fetched Model decoding, and backend column codecs.
- Deepened Backend Runtime Adapter selection so `Database` remains focused on lifecycle and transactions.
- Reorganized tests into backend-specific packages and removed redundant MariaDB test-server coverage.
- Updated package metadata to describe both SQLite and MariaDB support.

## 0.1.0 - 2026-05-31

Initial v1 release.

- Typed table model declarations with pending/fetched lifecycle states.
- SQLite-first storage declarations and logical codecs.
- Immutable query builders for single-table select/insert/update/delete.
- Async SQLite runtime with bounded connection pool and transactions.
- Deterministic SQLite `STRICT` table creation and schema verification.
- Public `SnekqlError` exception hierarchy.
- PEP 561 typing support with `py.typed` and a public facade stub.
