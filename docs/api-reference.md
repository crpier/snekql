# API reference

Import from `snekql.sqlite` or `snekql.mariadb`. `from snekql import sqlite` and
`from snekql import mariadb` select those same namespaces. Do not import a symbol
from its internal definition module just because an editor suggests it.

This page is searchable Markdown. Search for an operation or use the complete
[namespace index](#namespace-export-index). The linked guides cover declaration
options, examples and restrictions; the [backend matrix](backend-capabilities.md)
distinguishes library support from server SQL capabilities.

## Database and transaction lifecycle

| Operation | Contract | Details |
| --- | --- | --- |
| `Config(...)` | Backend-owned connection, pool, timeout and durability settings | [Connection lifecycle](connection-lifecycle.md), [engine settings](engine-settings.md) |
| `await Database.initialize(config, observer=...)` | Connect and establish policy; never create schema | [Service recipes](service-recipes.md) |
| `async with database` / `await database.close()` | Own and close the pool, including failure cleanup | [Connection lifecycle](connection-lifecycle.md) |
| `database.transaction(timeout=..., mode=..., read_only=..., isolation=...)` | A single-use async context manager; commit on success, roll back on failure | [Transactions](../README.md#runtime) |
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
| `await explain(query)` | Backend-specific plan inspection; see supported statement kinds |
| `await explain_analyze(query)` | Executes the supported query; can have effects, unlike ordinary plan inspection |

[Typing](typing.md) defines scalar, tuple, Row Model and named Pydantic result
shapes. [Raw SQL](raw-sql.md) defines construction-time validation and raw consumer
restrictions. Do not pass `validate=False` at raw consumption sites; validation
belongs to `raw(...)`. See [plan inspection](../README.md#explaining-query-plans)
before using EXPLAIN/ANALYZE in production.

## Query construction and expression annotations

| Name or method | Meaning and restrictions |
| --- | --- |
| `select(...)` | Start a typed select; establish row scope with `.all()` or `.where(...)` before execution |
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
| `Boolean`, `DateTime`, `Decimal`, `Json`, `JsonCol`, `Uuid`, `LongText` | Additional MariaDB-only declarations; not SQLite exports |
| `CurrentTimestamp`, `LiteralDefault` | Supported server defaults; distinguish them from Python defaults |
| `UtcDatetime`, `ZonedDatetime`, `CanonicalDecimal`, `Duration` | Curated logical types with documented wire equality/order behavior |
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
| `LexicalDatetimeWarning` | yes | yes |
| `LexicalDecimalWarning` | yes | yes |
| `LexicalDurationWarning` | yes | yes |
| `LiteralDefault` | yes | yes |
| `LongText` | no | yes |
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
| `PendingGeneration` | yes | yes |
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
