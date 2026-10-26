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
`.rows`, `.format`, `.analyzed`, and `.plan`. Columns are a tuple of native column
names. Rows are a tuple of row tuples in column order, with native driver values
and no model decoding.
SQLite returns `EXPLAIN QUERY PLAN` output, which can be empty for writes.
MariaDB returns native optimizer columns such as `select_type`, `key`, `rows`,
and `Extra`. Column sets, row order, estimates, and detail text depend on the
query and server version. There is no portable optimizer schema.

| Backend | `explain(query)` | `explain_analyze(query)` |
| --- | --- | --- |
| SQLite | `EXPLAIN QUERY PLAN` for SELECT, INSERT, UPDATE, DELETE; typed native steps | Rejected |
| MariaDB | `EXPLAIN` for SELECT, UPDATE, DELETE without RETURNING; optional `format="json"` | `ANALYZE` for the same supported queries; optional `format="json"` |

### Structured evidence for other programs

The default `format="native"` preserves the existing columns and rows. SQLite
also returns a `SQLiteQueryPlan` in `.plan`. MariaDB's default tabular result
leaves `.plan` as `None`; request `format="json"` to receive a
`MariaDBQueryPlan` along with the original one-column JSON result. This changes
the requested database output format, not how the query is executed.
SQLite rejects JSON plans with `QueryCompilationError` before query IO.

Both plan types have immutable `.roots` and a `.walk()` iterator. Traversal is
**preorder structural traversal, not a physical execution timeline**. These
are public query-plan evidence types, not snekql's private Execution Plans.
Narrow `.plan` with `isinstance` once to get backend-specific typed fields.

For SQLite:

```python
from snekql.sqlite import SQLiteQueryPlan

async with db.transaction() as transaction:
    result = await transaction.explain(query)

plan = result.plan
assert isinstance(plan, SQLiteQueryPlan)
for step in plan.walk():
    # Native integers, native prose, and typed parent/child relationships.
    evidence = (step.id, step.parent, step.auxiliary, step.detail)
    for child in step.children:
        assert child.parent == step.id
```

`SQLitePlanStep` retains all four native fields. Root steps have a parent ID
that does not refer to a returned step; multiple roots and empty write plans
are valid. `auxiliary` preserves SQLite's currently unused third integer.
The detail string is intentionally not parsed into scan/index/sort flags:
[SQLite warns that its QUERY PLAN output can change](https://sqlite.org/eqp.html).
No estimates or observed timings are invented from this text.

For MariaDB, use models and imports from that backend only:

```python
from snekql.mariadb import MariaDBQueryPlan, select

async with db.transaction() as transaction:
    result = await transaction.explain(
        select(User.email).where(User.status.eq("active")),
        format="json",
    )

plan = result.plan
assert isinstance(plan, MariaDBQueryPlan)
evidence = [
    {
        "path": node.path,
        "table": node.table_name,
        "access_type": node.access_type,
        "index": node.key,
        "estimated_rows": node.estimated_rows,
        "estimated_filtered_percent": node.estimated_filtered_percent,
    }
    for node in plan.walk()
    if node.table_name is not None
]
# Pass evidence to your analyzer/dashboard. Logging it is deliberate disclosure.
```

`MariaDBPlanNode.operation` is its containing native JSON key, such as `table`,
`filesort`, or `query_block`, not a portable operator classification. Each node
represents a JSON object beneath the document root, including unfamiliar shapes
and objects inside arrays. Array entries inherit the containing key as their
operation. `.path` is a tuple of object keys and array indices locating that
object in the original document. `.children` follows object containment,
preserving object/array order; objects such as engine statistics and optimization
timings are included, not falsely classified as physical execution steps.
`table_name` can be a query alias rather than the physical table name.

The selected typed metrics map directly to MariaDB fields:

| Typed field | Native JSON field | Meaning |
| --- | --- | --- |
| `table_name`, `access_type`, `key` | Same names | Native table/alias, access method, chosen index; strings or `None` |
| `estimated_rows` | `rows` | Native estimated rows for this access, exposed as `float` |
| `estimated_filtered_percent` | `filtered` | Estimated percentage surviving native filtering, not a 0–1 fraction |
| `actual_rows` | `r_rows` | Observed average rows read per execution, not total result rows |
| `actual_loops` | `r_loops` | Native integer execution count |
| `actual_filtered_percent` | `r_filtered` | Native observed filtering percentage |
| `total_time_ms` | `r_total_time_ms` | Native accumulated node time in milliseconds, including child time |
| `table_time_ms` | `r_table_time_ms` | Native time spent reading the table, in milliseconds |

Metrics are `None` when absent or null, **not zero**. Zero values remain zero.
Except for integer `actual_loops`, metrics are finite floats; malformed known
fields raise `DatabaseRuntimeError` with redacted diagnostics. A node need not
have table access or any metrics. See
[MariaDB's ANALYZE FORMAT=JSON semantics](https://mariadb.com/docs/server/reference/sql-statements/administrative-sql-statements/analyze-and-explain-statements/analyze-format-json)
for version-specific filtering and execution-statistics details. Field availability
and plan shapes vary across server versions; this is a selected typed view,
not an exhaustive or version-independent optimizer schema.

`.native_json` preserves the complete original JSON text, also retained in
`result.rows[0][0]`. Unmodeled fields such as conditions, buffers, costs, engine
statistics and future metrics are not discarded. Consumers can use `json.loads`
and a node's `.path` to inspect them. The structured view never rewrites native
SQL conditions or converts them into performance verdicts.

To collect actual statistics, explicitly use
`await transaction.explain_analyze(query, format="json")`. The returned
`.analyzed` is `True`; ordinary `.explain()` returns `False`. This flag records
which method ran, not whether any rows were changed. Parent and child times can
overlap; **do not sum them** as independent durations. Write-analysis time does
not include transaction commit time. A full scan can be appropriate, and an
estimated plan cannot prove an actual timing bottleneck. Keep warning thresholds
and recommendations in the consuming program. For regressions, record server
version, parameter/data context, and comparable execution conditions separately;
snekql does not attach them to the plan or run extra provenance queries.

### Executing analysis and safety

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

There is no automatic rollback or savepoint around ANALYZE. A JSON decoding
failure happens after execution and does not undo writes if the caller catches
the exception inside the Transaction. ANALYZE uses the active Transaction's
normal commit, rollback, locking, and operation-deadline rules.
Even plain EXPLAIN performs database IO and can acquire metadata locks.
For MariaDB `FOR UPDATE` queries, its optimizer can also acquire row locks;
EXPLAIN and ANALYZE of these queries require a read-write Transaction. Use
`.compile()` when inspection must perform no IO or acquire no locks.

Incomplete queries, empty bulk inserts, and unsupported statement combinations
raise `QueryCompilationError` before query IO. Backend mismatches raise
`DatabaseRuntimeError`. Transaction lifecycle errors remain unchanged.

Plan cells can contain sensitive values. Result `repr` and `str` show only the
backend and column/row counts; structured plan and node formatting also shows
counts only. Accessing `.rows`, `.columns`, `.plan` fields or `.native_json`
is deliberate inspection of potentially sensitive evidence. EXPLAIN execution
logs and driver-error text omit SQL and bound values even with
`parameter_visibility="values"`. This does not redact a
caller's own logging or server-side instrumentation.

[Query basics](queries.md) · [Error handling](error-handling.md) · [All guides](README.md)
