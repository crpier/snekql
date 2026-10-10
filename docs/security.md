# Security boundaries

snekql helps construct and execute SQL. It is not a SQL sandbox, an authorization
system, or a guarantee that a query is inexpensive.

The application chooses what to query. snekql must preserve the distinction
between **SQL structure** and **data** in its built-in structured APIs.

## What belongs to the library

- Bind query values, including patterns, JSON paths, limits, offsets, arithmetic
  operands, and CASE values. Do not silently reinterpret strings as SQL.
- Quote identifiers in every clause, including projections, CTE references,
  ordering, joins, and RETURNING. MariaDB query identifiers must also survive the
  driver's percent-format parameter binding.
- Validate SQL syntax selectors and dimensions at runtime. Python annotations
  alone do not establish that an input is a supported operator or native integer.
- Render bounded schema literals without SQL-mode-dependent quote escape gaps.
  CHECK literals and literal server defaults are data even though DDL cannot
  generally bind them as query parameters.
- Omit bound values from default query logging and execution-error rendering,
  including chained driver messages and exception notes. Keep classified failure
  evidence available through `error.failure`.
- Reject primitive/JSON serialization type mismatches without value-bearing
  serializer warnings or chained errors. This does not reapply stored-value
  constraints to comparison bounds.
- Omit invalid values from built-in model validation errors. Typed JSON
  extraction errors must not disclose either the bound path or the stored value.
- Do not forward MariaDB cursor server-warning text through Python warnings.
  Server diagnostics can contain values. This does not disable unrelated Python
  warnings or package advisory warnings.

These responsibilities do not depend on whether the application also validates
its request inputs. Validation and SQL parameterization solve different problems.

## What belongs to the caller

- **Authorization and query intent.** Choose allowed tables, columns, predicates,
  and operations. Binding a tenant ID does not enforce tenant isolation. An
  intentional full-table DELETE is not an injection defect.
- **Trusted SQL text.** Raw statement text and migration bodies are application
  code. Bind untrusted values; do not interpolate them into SQL or quote native
  placeholders yourself. Raw SQL retains native driver placeholder rules.
- **Trusted Python extensions.** Models, validators, serializers, default
  factories, and custom dialect renderers execute application Python code. Do
  not construct them from untrusted executable input. snekql cannot prevent
  callbacks from logging secrets or raising their own value-bearing exceptions.
- **Database and transport policy.** Use least-privilege credentials and verified
  TLS when needed. Maintain the server, driver, OS, and dependencies. Temporary
  MariaDB servers with insecure authentication are only for isolated tests.
- **Resource policy.** Bound workload sizes and concurrency, choose deadlines,
  and apply database-side limits. An operation deadline is not a proof that the
  server has stopped executing, and recursive queries are not automatically
  cheap. Read-only transactions are a database policy, not a sandbox.
- **Explicit inspection.** `CompiledQuery.params`, `ExecutionError.params`, raw
  results, and EXPLAIN cells can contain sensitive data. Keep them out of routine
  logs. `parameter_visibility="values"` is an unsafe diagnostic opt-in: builder
  execution errors can retain the original driver cause under that policy.

Parameterized SQL and identifiers remain visible in builder diagnostics. Do not
put secrets in identifiers, schema literals, custom SQL, exception notes added
by application code, or source-code literals and expect value redaction to hide
those channels. Traceback renderers that collect local variables are also outside
this guarantee. Connection lifecycle and migration diagnostics are not a promise
that every third-party exception is confidential.

## Hardening checklist

For a new rendering path, classify each interpolated input as exactly one of:

1. A bound value.
2. A dialect-quoted identifier, with any required driver-format escaping.
3. A runtime-validated member of a bounded SQL-token vocabulary or numeric domain.
4. Explicit trusted application SQL.

Follow an input through construction, compilation, driver binding, and result
materialization. Pay particular attention to feature combinations: a label may
become a CTE output, an ordering operand, or a downstream projection.

Test through public boundaries:

- Query construction and `.compile()` for SQL shape and parameter order.
- Transactions on real SQLite and MariaDB for native interpretation.
- `scaffold()` and public configuration for DDL and connection policy.
- Ordinary `str`/`repr`, full `traceback.format_exception`, logs, warnings, and
  observer events for unintended disclosure, including driver-originated timeouts
  and public test-support credential objects.
- Native task cancellation as well as AnyIO scope cancellation, including a
  second cancellation during cleanup. Prove that subsequent leases work and
  pending writes do not leak into another transaction.
- Rejected cross-task stream reads and exits, verifying that the owning task's
  cursor remains usable and its lock ownership is intact.

Use known payloads containing quotes, backticks, percent signs, comment markers,
periods, NUL, and control characters as appropriate to each input domain. A query
merely failing at the server is not proof of correct quoting. Assert the intended
result or an intentional package error at the public boundary.

The upstream review motivating this checklist found Django fixes for aliases,
JSON keys, EXPLAIN options, date-part selectors, and internal-looking connector
keywords. SQLAlchemy fixes covered literal execution, DDL/default escaping,
connection-setup rendering, and credential/parameter diagnostics. These are
examples of preserving an API's promised meaning, not of policing query intent.

## Reporting

Follow [the security policy](../SECURITY.md). Report suspected vulnerabilities
privately, with the public API call, affected backend/version, reproduction, and
impact. A historical review or passing regression suite is not a security
certification.
