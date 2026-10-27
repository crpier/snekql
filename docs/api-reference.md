# API reference

Know the operation you need? Look it up here, or jump to the
[complete export list](#namespace-export-index). For a walkthrough, start with
[queries](queries.md) or [transactions](transactions.md).

Import from `snekql.sqlite` or `snekql.mariadb`. Those are the supported application
imports, even when an editor suggests the internal file that defines a name.
The [backend table](backend-capabilities.md) lists differences between SQLite and
MariaDB support.

## Database and transaction lifecycle

| Operation | Contract | Details |
| --- | --- | --- |
| `Config(...)` | Backend-owned connection, pool, timeout and durability settings | [Connection lifecycle](connection-lifecycle.md), [engine settings](engine-settings.md) |
| `await Database.initialize(config, observer=...)` | Connect and establish policy; never create schema | [Service recipes](service-recipes.md) |
| `async with database` / `await database.close()` | Own and close the pool, including failure cleanup | [Connection lifecycle](connection-lifecycle.md) |
| `database.transaction(timeout=..., mode=..., read_only=..., isolation=...)` | A single-use async context manager; commit on success, roll back on failure | [Transactions](transactions.md) |
| `transaction.begin_nested()` | Explicit nested, task-owned, LIFO scope, not another pool checkout | [Connection lifecycle](connection-lifecycle.md) |
| `transaction.commit_outcome` | Evidence about the managed outer commit; uncertainty is not permission to replay | [Errors and retry](error-handling.md) |
| `database.pool_stats()` | Frozen local snapshot; no query or connection checkout | [Telemetry](telemetry.md) |

Never share a live Transaction between tasks. Share the Database within its owning
process/event loop and open a fresh transaction for each unit of work. A timeout
on acquisition is distinct from an operation deadline. Neither bounds arbitrary
application code inside a transaction.

## Executing queries

| Transaction operation | Result and failure behavior |
| --- | --- |
| `await fetch_one(query)` | Exactly one decoded row; `NoResultError` or `MultipleResultsError` otherwise |
| `await fetch_one_or_none(query)` | Zero or one decoded row for supported model/tuple/join and raw contracts; multiple rows still fail |
| `await fetch_all(query)` | A list with the query's declared row shape |
| `async with fetch_chunks(query, size=...) as stream` | Iterate bounded delivered partitions; keep it inside the Transaction; does not promise bounded native memory |
| `await execute(insert_query)` | `None` without RETURNING; projected result(s) with supported RETURNING |
| `await execute(update_or_delete)` | Affected-row count without RETURNING; returned projections when supported |
| `await execute(raw_statement)` | Execute a raw non-fetch operation using its declared contract |
| `await explain(query, format="native")` | Native columns/rows plus typed SQLite steps; MariaDB `format="json"` adds a typed structural plan |
| `await explain_analyze(query, format="native")` | Executes supported MariaDB queries; `format="json"` adds typed actual rows, loops and timings; can have effects |

[Typing](typing.md) defines scalar, tuple, Row Model and named Pydantic result
shapes. [Raw SQL](raw-sql.md) defines construction-time validation and raw consumer
restrictions. Do not pass `validate=False` at raw consumption sites; validation
belongs to `raw(...)`. See [plan inspection](inspecting-queries.md#explaining-query-plans)
before using EXPLAIN/ANALYZE in production.

## Query construction and expression annotations

| Name or method | Meaning and restrictions |
| --- | --- |
| `select(...)` | Build an immediately executable typed SELECT; add filters with `.where(...)` |
| `.where(...)`, `.group_by(...)`, `.having(...)` | SQL predicates and aggregate filtering with checked ownership |
| `.join(...)`, `.left_join(...)` | Join explicit declared relationships; LEFT joins make the right result optional |
| `alias(Model, ...)` | A distinct table occurrence for self-joins and correlated work |
| `.project(Result, **bindings)` | Named Pydantic projection; use instead of widening beyond eight positional slots |
| `.label(name)` | Identity-bound typed expression output token |
| `.union(other)`, `.union_all(other)` | Compatible completed named projections; the left output contract governs nullability |
| `combined.column(left_label)` | Combined output for final ordering; convert to a CTE for filtering/joins |
| `.cte(Role, name=...)` | Completed named SELECT as a reusable nonrecursive query source |
| `cte.column(label)`, `cte.alias(Role, name=...)` | Token-based output lookup and distinct CTE occurrences |
| `.order_by(...)`, `.limit(...)`, `.offset(...)` | Explicit ordering and pagination; no implicit stable row order |
| `.for_update(wait=...)` | MariaDB locking policy; unsupported SQLite locking fails explicitly |
| `insert(row)` | Write one Pending value; omitted generated values use database generation |
| `update(Model).set(...)` | Explicit assignments; row scope remains required |
| `delete(Model)` | Explicit `.all()` or `.where(...)` intent is required |
| `.on_conflict(...)`, `DoNothing`, `DoUpdate` | Backend-specific conflict behavior, not portable merge semantics |
| `.returning(...)`, `.returning_as(Result, **bindings)` | Supported write projections; restrictions differ by backend and conflict action |
| `literal(integer)` | Backend-owned signed-64 integer constant for named projections; no FROM owner |
| `recursive_cte(anchor, Role, name=...).step(callback)` | Staged recursive builder; see [recursive contracts and limits](recursive-ctes.md) before use |
| `scalar(...)`, `exists(...)`, `not_exists(...)`, `case(...)` | Typed SQL composition, not a trigger for hidden database IO |
| `ReadQuery[Scope, Result]`, `OptionalRead[Scope, Result]` | Read helper annotations retaining table information and optional-fetch eligibility |
| `ready(query)`, `ClosedRead[Result]`, `ClosedOptional[Result]` | Compile a finished read for a shorter execution/inspection annotation; no database I/O |
| `PendingInput[Owner, Result]`, `Write[Result]` | Pending input and executable write helper annotations |
| `Cte[Source, Result, Role, NonNullableSource=Source]` | Nonconstructible named relation annotation; backend pinned by namespace |
| `NamedOperand[Result]` | Nonconstructible completed named operand annotation for UNION and recursive members |
| `ColumnRef`, `Scalar`, `Predicate`, `Assignment`, `OrderBy`, `Aggregate`, `JoinOn` | Expression annotations, not general-purpose constructors |
| `.compile()` | Parameterized SQL and bindings with construction validation |
| `.inspect(parameter_visibility=...)` | Explicit diagnostic value visibility; repr/str remain redacted by default |

Use the [typing guide](typing.md) for exact annotation arity, inferred result
shapes, owner constraints and overload examples. [Typed CTEs](ctes.md) covers
implemented labels and nonrecursive definitions. [Named UNION](unions.md) covers
set operators, output contracts and final pagination. [Reporting](reporting.md) covers
validated raw recursive-CTE/window/set-operation recipes.
[Query composition design](query-composition-design.md) distinguishes implemented
CTEs and named set operators from future builder syntax.

## Models, storage and schema

| Declaration or operation | Meaning |
| --- | --- |
| `Model`, `Pending`, `Row` | Immutable declaration facts and explicit write/read states; no identity map or lazy loading |
| `__row_type__: ClassVar[ReadType[User[Row]]]` | Declare the whole-model result type inside `User` |
| `insert_many(Model, rows)` | Insert a homogeneous Pending batch with a declared destination; empty batches do no SQL |
| `complete(Model, **values)` | Validate every field and create a Row snapshot without database I/O; keywords are runtime-checked |
| `is_complete(value)` | Check Row state and narrow its type; does not inspect database persistence |
| `Col[T]`, `GenCol[T]`, `PENDING_GENERATION` | Logical type and generated-value availability; storage comes from the column constructor |
| `ForeignKey`, `ForeignKeyConstraint`, `FKCol` | Explicit columns, callable targets with Python defaults, and composite constraints; see [binding timing](typing.md#callable-self-reference-targets). These are not loaded relationships |
| `Integer`, `Real`, `Text`, `Blob` | SQLite storage classes and corresponding MariaDB namespace constructors |
| `Boolean`, `Date`, `DateTime`, `Decimal`, `Json`, `JsonCol`, `Uuid`, `LongText` | Additional MariaDB-only declarations; not SQLite exports |
| `CurrentTimestamp`, `LiteralDefault` | Supported server defaults; distinguish them from Python defaults |
| `UtcDatetime`, `LocalDatetime`, `ZonedDatetime`, `CanonicalDecimal`, `Duration` | Curated logical types with documented wire equality/order behavior |
| `Canonical`, `OrderPreserving` | Annotations for declared wire-form guarantees; see restrictions in the typing guide |
| `Index`, `CheckConstraint` | Explicit schema facts, not automatic database alteration |
| `scaffold([Model, ...])` | Dev-time initial DDL text for review; never regenerate deployed migration bodies at startup |
| `await database.migrate(chain)` | Apply an explicitly supplied canonical ordered migration chain |
| `await database.migration_status(chain)` | Read current prefix/application status |
| `await database.verify_migrations(chain, approved_later=...)` | Check history; a reviewed later suffix is explicit, not an unknown-history bypass |
| `await database.verify(models, policy=...)` | Partial structural verification with matched/drift/unchecked evidence; never a schema equality proof |

[Schema drift](schema-drift.md), [migrations](migrations.md),
[rolling deployments](rolling-migrations.md), [reviewed baselines](migration-baselines.md)
and [recovery](migration-recovery.md) explain the operational contracts. Keep one
migration owner when [adopting alongside another layer](service-recipes.md#incremental-adoption).

## Opt-in recorded migrations

These names are in **`snekql.experimental.migrations`**, not the backend export
index below. They remain experimental, with a bounded execution contract rather
than a stable replacement/indefinite ABI promise. Start with the
[recorded workflow](recorded-migrations.md) and
[recorded recovery](recorded-migration-recovery.md), not the raw runner's baseline
or recovery APIs. Use separate deployment targets for the two families.

| Operation/value | Contract |
| --- | --- |
| `generate(revision, models, backend=..., previous=...) -> Draft` | Select owned declarations and draft against recorded state, never a live-database diff |
| `Draft.then(...)`, `.resolve(...)`, `.adopt(...)`, `.advance(...)` | Immutable explicit authoring; named adoption is SQLite-only; resolve unsupported/removal decisions before compilation |
| `Checkpoint(name=...)`, `DataChange.from_query(...)` | Bind a typed UPDATE to a named historical contract; no arbitrary Python migration callback |
| `contract_source(draft, point=..., table=...)`, `contract_digest(draft, point=...)` | Generate actual importable historical query source and bind its contract, not today's model/codec ABI |
| `compile(draft) -> Package`, `Package.check(draft)` | Freeze reviewed intent; separately check build freshness against supplied authoring |
| `Package.dump()/load(...)` | Persist/load supported frozen interpretation without importing models |
| `connect(config) -> Connection` | Inert, single-use owner exists before opening; async context entry yields a Target |
| `await Connection.wait_closed()` | Post-failure/exit bounded join of this lifetime's known cleanup; keep its owning loop live |
| `await Target.prepare(package, schema_writers_excluded=..., preserve_unmanaged=...) -> Prepared` | Read-only, target-aware preparation; explicit native writer exclusion; bounded preservation is SQLite-only |
| `Prepared.dump()/load(...)` | Versioned original evidence; durably save before apply, not authentication or a portable Config/target |
| `await Target.apply(original)` | Return `"applied"` or `"already_applied"`; an incomplete native history requires review, not blind replay |
| `await Target.status() -> tuple[Progress, ...]` | Durable `complete`/`uncertain` progress and separate reconciliation audit; ordering unspecified |
| `await Target.inspect_recovery(original, schema_writers_excluded=True) -> Recovery` | Fresh MariaDB evidence/classification, not a retry policy |
| `await Target.reconcile(recovery, reason=..., schema_writers_excluded=True) -> Recovery` | Explicitly accept exactly a proved structural outcome; re-evaluate the returned classification |
| `await Target.resume(recovery, schema_writers_excluded=True)` | Recheck and continue only `retry_remaining`/`finish` native evidence |
| `PackageError` | Refused, stale, unresolved, inconsistent, or unsupported experimental input |

Generated operation values describe creation/adoption, nullable additions,
required/drop-column contraction, nullability/default changes, named indexes and
CHECKs, and `RelinquishTable`. State/column/table values are inspection and trusted
authoring representations, not a shortcut to fabricate construction authority or
history. Unsupported SQL/dependencies refuse; this is not a general parser or
raw-SQL runner. Completion and local cleanup are separate from application
readiness, ordinary mapping, codecs, and physical remote quiescence.

## Errors, telemetry and test support

Catch `SnekqlError` for intentional package-originated failures, or the narrower
public error type listed below. Use structured failure fields instead of parsing
messages. Classifying a deadlock or connection failure does not by itself prove
that replay is safe. [Error handling](error-handling.md) describes evidence and
[connection lifecycle](connection-lifecycle.md) describes cleanup.

`Observer`, `PoolStats` and `TelemetryEvent` are also public from
`snekql.telemetry`. `snekql.opentelemetry.OpenTelemetryObserver` is optional;
follow the [telemetry guide](telemetry.md), including its bounded attribute rules.

`snekql.testing.mariadb` exports `TemporaryMariaDBServer`,
`temporary_mariadb_server`, `MariaDBAuth`, `MariaDBTransport`,
`MariaDBCommandResult` and `TemporaryMariaDBServerError`. These are owned,
throwaway native test servers, not production provisioning. See
[test-server support](testing-mariadb.md) and the executable
[database fixtures](../examples/service_fixtures.py).

## Namespace export index

`yes` means the name is exported, not that every operation involving it is
supported identically by both backends. Semantic restrictions remain in the
[capability matrix](backend-capabilities.md). The test suite checks this inventory
against both namespaces' `__all__` lists.

| Export | SQLite | MariaDB |
| --- | --- | --- |
| `Aggregate` | yes | yes |
| `Assignment` | yes | yes |
| `Blob` | yes | yes |
| `Boolean` | no | yes |
| `Canonical` | yes | yes |
| `CanonicalDecimal` | yes | yes |
| `CheckConstraint` | yes | yes |
| `ChunkStream` | yes | yes |
| `ClosedOptional` | yes | yes |
| `ClosedRead` | yes | yes |
| `Col` | yes | yes |
| `ColumnRef` | yes | yes |
| `CommitOutcome` | yes | yes |
| `CompiledQuery` | yes | yes |
| `Config` | yes | yes |
| `Cte` | yes | yes |
| `CurrentTimestamp` | yes | yes |
| `Database` | yes | yes |
| `DatabaseCloseTimeoutError` | yes | yes |
| `DatabaseClosedError` | yes | yes |
| `DatabaseClosingError` | yes | yes |
| `DatabaseFailure` | yes | yes |
| `DatabaseOperationTimeoutError` | yes | yes |
| `DatabaseRuntimeError` | yes | yes |
| `DateTime` | no | yes |
| `Date` | no | yes |
| `Decimal` | no | yes |
| `DoNothing` | yes | yes |
| `DoUpdate` | yes | yes |
| `Duration` | yes | yes |
| `ExecutionError` | yes | yes |
| `ExplainResult` | yes | yes |
| `FKCol` | yes | yes |
| `FailureCategory` | yes | yes |
| `ForeignKey` | yes | yes |
| `ForeignKeyConstraint` | yes | yes |
| `FrozenModelError` | yes | yes |
| `GenCol` | yes | yes |
| `Index` | yes | yes |
| `Integer` | yes | yes |
| `IsolationLevel` | yes | yes |
| `JoinOn` | yes | yes |
| `Json` | no | yes |
| `JsonCol` | no | yes |
| `LexicalDecimalWarning` | yes | yes |
| `LexicalDurationWarning` | yes | yes |
| `LiteralDefault` | yes | yes |
| `LongText` | no | yes |
| `MariaDBPlanNode` | no | yes |
| `MariaDBQueryPlan` | no | yes |
| `MigrationDeclarationError` | yes | yes |
| `MigrationError` | yes | yes |
| `MigrationHistoryError` | yes | yes |
| `MigrationLockError` | yes | yes |
| `MigrationLockTimeoutError` | yes | yes |
| `MigrationResult` | yes | yes |
| `MigrationStatus` | yes | yes |
| `Model` | yes | yes |
| `ModelDeclarationError` | yes | yes |
| `ModelError` | yes | yes |
| `ModelValidationError` | yes | yes |
| `MultipleResultsError` | yes | yes |
| `NamedOperand` | yes | yes |
| `NoResultError` | yes | yes |
| `Observer` | yes | yes |
| `OptionalRead` | yes | yes |
| `OrderBy` | yes | yes |
| `OrderPreserving` | yes | yes |
| `PENDING_GENERATION` | yes | yes |
| `Pending` | yes | yes |
| `PendingInput` | yes | yes |
| `PoolStats` | yes | yes |
| `PoolTimeoutError` | yes | yes |
| `Predicate` | yes | yes |
| `QueryCompilationError` | yes | yes |
| `QueryConstructionError` | yes | yes |
| `QueryError` | yes | yes |
| `RawResultShapeError` | yes | yes |
| `RawResultValidationError` | yes | yes |
| `RawStatement` | yes | yes |
| `Real` | yes | yes |
| `ReadQuery` | yes | yes |
| `ReadType` | yes | yes |
| `ResultCardinalityError` | yes | yes |
| `Row` | yes | yes |
| `SQLitePlanStep` | yes | no |
| `SQLiteQueryPlan` | yes | no |
| `Scalar` | yes | yes |
| `SchemaDriftIssue` | yes | yes |
| `SchemaError` | yes | yes |
| `SchemaPolicy` | yes | yes |
| `SchemaVerificationError` | yes | yes |
| `SchemaVerificationFact` | yes | yes |
| `SchemaVerificationResult` | yes | yes |
| `SnekqlError` | yes | yes |
| `SnekqlWarning` | yes | yes |
| `TLSConfig` | no | yes |
| `TelemetryEvent` | yes | yes |
| `Text` | yes | yes |
| `Transaction` | yes | yes |
| `TransactionClosedError` | yes | yes |
| `TransactionMode` | yes | yes |
| `TransactionNotStartedError` | yes | yes |
| `TransactionReuseError` | yes | yes |
| `TransactionStateError` | yes | yes |
| `UtcDatetime` | yes | yes |
| `LocalDatetime` | yes | yes |
| `DatetimeError` | yes | yes |
| `Uuid` | no | yes |
| `Write` | yes | yes |
| `ZonedDatetime` | yes | yes |
| `ZonedDatetimeError` | yes | yes |
| `alias` | yes | yes |
| `case` | yes | yes |
| `complete` | yes | yes |
| `delete` | yes | yes |
| `exists` | yes | yes |
| `insert` | yes | yes |
| `insert_many` | yes | yes |
| `is_complete` | yes | yes |
| `literal` | yes | yes |
| `not_exists` | yes | yes |
| `raw` | yes | yes |
| `recursive_cte` | yes | yes |
| `scaffold` | yes | yes |
| `ready` | yes | yes |
| `scalar` | yes | yes |
| `select` | yes | yes |
| `update` | yes | yes |

[All guides](README.md)
