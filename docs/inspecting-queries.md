# See the SQL your query will run

Use SQL inspection to check a query without running it. Use EXPLAIN to ask the
database about its plan. These are different tools: EXPLAIN needs a connection,
and MariaDB ANALYZE actually executes the query.

The examples use the `User` model from [the model guide](models.md).

## Compile without a connection

Call `query.compile()` to see the SQL and bound parameters. You do not need a
connection or transaction:

```python
from snekql.sqlite import CompiledQuery, select

compiled: CompiledQuery = select(User.email).where(User.status.eq("active")).compile()
compiled.sql  # 'SELECT "email" FROM "user" WHERE ("status" = ?)'
compiled.params  # ('active',)
compiled.backend  # 'sqlite'
```

Both backend namespaces export `CompiledQuery`. Its fields are frozen, and
`params` is an ordered tuple of dialect-encoded bindings. SQLite uses `?`
placeholders; MariaDB uses `%s` and backtick-quoted identifiers. The query's
models determine the backend; compilation cannot retarget a query.

Compiled output is inspection-only. Pass the original query to a Transaction,
not `CompiledQuery`. Compilation neither executes SQL nor includes private
execution plans, row decoders, or result-cardinality policy. It does not verify
that tables exist on a server. Incomplete queries raise `QueryCompilationError`.
Empty bulk inserts also raise because they have no SQL to compile,
even though executing an empty batch does no SQL.

`repr(compiled)` and `str(compiled)` redact bound values as `<redacted:N>`.
Accessing `.params` explicitly reveals them. SQL text remains visible, including
identifiers and any literals supplied by custom dialect expressions.

## Debug text

Query `repr()` and `str()` show parameterized SQL and redact bindings as
`<redacted:N>`. `query.inspect()` uses the same redacted multiline format as
`str(query)`. These operations need no Database or transaction.

```python
query = select(User).where(User.status.eq("active"))
query = query.where(User.email.like("%@example.com"))

repr(query)
# <SelectModelQuery: SELECT ... FROM "user"
#  WHERE ("status" = ?) AND ("email" LIKE ?) | params=<redacted:2>>

print(query)
# -- parameterized (executes):
# SELECT ... WHERE ("status" = ?) AND ("email" LIKE ?)
# -- params: <redacted:2>

# Trusted local debugging only. This does not change later repr/str calls.
print(query.inspect(parameter_visibility="values"))
# -- parameterized (executes):
# SELECT ... WHERE ("status" = ?) AND ("email" LIKE ?)
# -- params: ('active', '%@example.com')
#
# -- inlined literals (approximate, not executed):
# SELECT ... WHERE ("status" = 'active') AND ("email" LIKE '%@example.com')
```

The inlined form is approximate and must not be executed. Explicit value
inspection can raise compilation or formatting errors. Runtime Config
`parameter_visibility` does not change query formatting; disclosure here requires
this separate per-call choice.

Incomplete queries and ordinary compilation failures render a fixed
`<ClassName inspection unavailable>` marker through default formatting. Exception
messages can contain sensitive inputs, so they are not included. Use `.compile()`
for deliberate validation and structured parameter access; it still raises
compilation and codec errors. Process-control exceptions are not suppressed.

Query text does not include bindings, inlined SQL, or compilation errors by
default. Code parsing older display text
should use `.compile().sql` and `.compile().params`; code using `repr` to validate
bounds should call `.compile()` instead. Use the explicit value-inspection method
only for local diagnostics. Query execution and encoding policies are unchanged.

Redaction covers bound values in default text, not arbitrary object inspection.
SQL identifiers and literals in custom SQL expressions remain visible. Raw
statement `repr`/`str` remain opaque; `.sql` deliberately exposes their SQL.
Traceback locals, exception chains from explicit compilation or execution,
model representations, state inspection, and serializers that traverse object
attributes can expose values. Custom validators and serializers run during
compilation and can have their own side effects. Configure error reporters and
structured loggers accordingly; query formatting is not a sandbox or a secret
scanner. Ordinary logging with `%s` or `%r` uses the redacted defaults.

## Explaining query plans

`await transaction.explain(query)` asks the active backend for a query plan.
It does not apply the query's writes. The query must be a complete builder
from the Transaction's backend, not `raw(...)` or a `CompiledQuery`.

```python
from snekql.sqlite import ExplainResult

async with db.transaction() as transaction:
    plan: ExplainResult = await transaction.explain(
        select(User.email).where(User.status.eq("active"))
    )

plan.backend  # 'sqlite'
plan.columns  # ('id', 'parent', 'notused', 'detail')
for row in plan.rows:
    print(dict(zip(plan.columns, row, strict=True)))  # Deliberate inspection
```

Both namespaces export frozen `ExplainResult` with `.backend`, `.columns`,
and `.rows`. Columns are a tuple of native column names. Rows are a tuple of
row tuples in column order, with native driver values and no model decoding.
SQLite returns `EXPLAIN QUERY PLAN` output, which can be empty for writes.
MariaDB returns native optimizer columns such as `select_type`, `key`, `rows`,
and `Extra`. Column sets, row order, estimates, and detail text depend on the
query and server version. There is no portable optimizer schema.

| Backend | `explain(query)` | `explain_analyze(query)` |
| --- | --- | --- |
| SQLite | `EXPLAIN QUERY PLAN` for SELECT, INSERT, UPDATE, DELETE | Rejected |
| MariaDB | `EXPLAIN` for SELECT, UPDATE, DELETE without RETURNING | `ANALYZE` for the same supported queries |

`explain_analyze` **executes the query**, including UPDATE and DELETE. It returns
execution statistics instead of application rows. MariaDB calls this statement
`ANALYZE`, not `EXPLAIN ANALYZE`; its output includes observed statistics such
as `r_rows` and `r_filtered`. SQLite's unrelated `ANALYZE` command is never used
as a substitute. MariaDB INSERT plans are outside this interface's supported
statement set.

```python
# With MariaDB models and imports only. This DELETE really runs and commits.
from snekql.mariadb import delete

async with db.transaction() as transaction:
    plan = await transaction.explain_analyze(
        delete(User).where(User.status.eq("disabled"))
    )
```

There is no automatic rollback or savepoint around ANALYZE. It uses the active
Transaction's normal commit, rollback, locking, and operation-deadline rules.
Even plain EXPLAIN performs database IO and can acquire metadata locks.
For MariaDB `FOR UPDATE` queries, its optimizer can also acquire row locks;
EXPLAIN and ANALYZE of these queries require a read-write Transaction. Use
`.compile()` when inspection must perform no IO or acquire no locks.

Incomplete queries, empty bulk inserts, and unsupported statement combinations
raise `QueryCompilationError` before query IO. Backend mismatches raise
`DatabaseRuntimeError`. Transaction lifecycle errors remain unchanged.

Plan cells can contain sensitive values. Result `repr` and `str` show only the
backend and column/row counts; accessing `.rows` or `.columns` reveals the
native output. EXPLAIN execution logs and driver-error text omit SQL and bound
values even with `parameter_visibility="values"`. This does not redact a
caller's own logging or server-side instrumentation.

[Query basics](queries.md) · [Error handling](error-handling.md) · [All guides](README.md)
