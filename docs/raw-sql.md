# Raw SQL

Use the backend-owned `raw` factory for trusted SQL that the Query Builder does
not express. It uses the current Transaction connection and native connector
parameters. It does not parse SQL, translate placeholders, encode parameters, or
apply table-column codecs to returned values.

```python
import asyncio

from snekql import sqlite as sql


async def main() -> None:
    async with await sql.Database.initialize(database=":memory:") as database:
        statement = sql.raw("SELECT :value AS answer", params={"value": 42})
        async with database.transaction() as transaction:
            print(await transaction.fetch_one(statement))  # {'answer': 42}


asyncio.run(main())
```

Import `RawStatement[RowT]` from the same backend to annotate statements passed
between application functions. The alias preserves backend identity. There is no
root-level `snekql.raw` or separate command factory.

## Consumption

Every Transaction call executes the statement anew. A statement can be reused
across transactions of the same backend.

| Method | Required first result | Result |
| --- | --- | --- |
| `execute` | No result columns | Native `int` rowcount, including negative sentinels |
| `fetch_all` | Result columns | List of rows |
| `fetch_one` | Result columns | Exactly one row |
| `fetch_one_or_none` | Result columns | One row, or `None` when absent |
| `fetch_chunks(..., size=N)` | Result columns | Existing `ChunkStream`, yielding lists of rows |

Mapping mode is the default. Without a contract it returns `dict[str, object]` using driver column
names as keys. Aliases are preserved exactly. Duplicate names raise
`RawResultShapeError`, even when there are no rows.

Use `row_mode="tuple"` for unvalidated `tuple[object, ...]` rows in column order. Duplicate
names are allowed in tuple mode. Both modes require row width to match metadata.
There is no scalar extraction or automatic value decoding.

A zero-row result is valid for `fetch_all`, `fetch_one_or_none`, and streaming.
`fetch_one` raises `NoResultError` for zero rows. Capped reads raise
`MultipleResultsError` for excess rows. They request at most two rows, but this
does not bound connector buffering or server execution.

Use streaming within its owning task and context:

```python
statement = sql.raw("SELECT :value AS answer", params={"value": 42})
async with database.transaction() as transaction:
    async with transaction.fetch_chunks(statement, size=100) as chunks:
        async for chunk in chunks:
            print(chunk)
```

The stream holds the Transaction lock until context exit. Failed raw streams
complete their cursor before propagating ordinary result errors and cannot
resume. Earlier chunks remain consumed; a failed chunk is not partially yielded.

Transaction `validate` accepts omission or literal `True`, honoring the statement's
policy. `False` raises `QueryConstructionError` before execution, and a dynamic
`bool` is rejected statically. `True` does not add validation to an unvalidated
statement. Existing Query Builder validation options are unchanged.

## Result contracts

Validated raw statements require Python's context-aware warnings at startup:

```bash
PYTHON_CONTEXT_AWARE_WARNINGS=1 python app.py
# Alternatively: python -X context_aware_warnings=1 app.py
```

Without that setting, any non-None validation contract raises
`QueryConstructionError` before Pydantic runs, including contracts intended for
`execute`. Unvalidated raw statements and Query Builder operations do not require
it. Adapter warnings are suppressed in context-local scopes, never through a
process-global filter fallback.

Pass a Pydantic-compatible declaration to factory `validate`. Snekql constructs
one adapter per statement, before any execution. Invalid declarations, including
unresolved annotations, raise sanitized `QueryConstructionError` immediately.
Omission or `validate=None` creates no adapter.

```python
import asyncio
from dataclasses import dataclass

from snekql import sqlite as sql


@dataclass
class CustomerTotal:
    customer_id: int
    total: int


async def main() -> None:
    statement = sql.raw(
        "SELECT :customer_id AS customer_id, :amount AS total",
        params={"customer_id": 1, "amount": "42"},
        validate=CustomerTotal,
    )
    async with await sql.Database.initialize(database=":memory:") as database:
        async with database.transaction() as transaction:
            rows = await transaction.fetch_all(statement)  # list[CustomerTotal]
            print(rows)  # [CustomerTotal(customer_id=1, total=42)]


asyncio.run(main())
```

Dataclasses, Pydantic models, TypedDicts, and tuple annotations infer exact row
types. A dynamically selected valid row mode does not erase a declared type.
Arbitrary annotations also work at runtime, but may infer `RawStatement[object]`.
Direct `Annotated[...]` uses that fallback. Put constraints inside a supported
row declaration when exact inference matters.

Each packaged mapping or tuple goes to `validate_python` with normal Pydantic
behavior. Required fields, aliases, defaults, extras, nullability, coercion, and
custom validators belong to the contract. No table-column codecs are inferred.
A result contract validates fetched values. It proves neither SQL correctness
nor that the query returned the intended answer.

Mode is never inferred from the declaration. For positional validation, specify
both options:

```python
statement = sql.raw(
    "SELECT '42', NULL",
    row_mode="tuple",
    validate=tuple[int, str | None],
)
```

With default mapping mode, that tuple declaration fails on an incompatible row.
A scalar declaration such as `int` does not extract a single column. Use a
one-field mapping or one-element tuple contract instead.

Empty results do not invoke the adapter or establish compatibility with the
contract. `execute` also never invokes row validators and still returns `int`,
even for `RawStatement[CustomerTotal]`. Construction validates the declaration
regardless of its eventual consumption method.

If a validator produces `None` for an existing row, `fetch_one`, `fetch_all`, and
streaming retain it. `fetch_one_or_none` instead raises `RawResultValidationError`
with the fixed `none_result` code. Its successful `None` means no row exists.

Validation runs synchronously outside the driver Operation Deadline. Large
buffered materialization retains cooperative checkpoints. Custom synchronous
validators can block the event loop; snekql does not interrupt or offload them.

### Validation failures

`RawResultValidationError` is a `DatabaseRuntimeError` with:

- `operation`, the fetch method name.
- `row_index`, the zero-based position across the operation, not within a chunk.
- `details`, a tuple of records exposing only `location` and `code`.

Every location segment becomes `"<redacted>"`, including integer dictionary keys.
Root locations stay `()`. Selected built-in Pydantic codes are retained from a
fixed package allowlist. Unknown codes and ordinary validator exceptions use
`custom_validation_error`. Details never retain inputs, messages, context, or
original exceptions. Normal exception chaining is suppressed.

Metadata and cardinality checks precede validation. Buffered cursors complete
before row validation. Streams validate a whole chunk before yielding it; a bad
row prevents that entire chunk from being yielded. Earlier chunks remain
consumed. Failed streams are terminal, and indices reset for each execution.
Cleanup failure or timeout takes precedence over validation failure. Cancellation
and process-control exceptions retain their meaning.

Catching a validation error does not roll back SQL. A write with `RETURNING` can
still commit after a caught failure if cleanup established reusable state. Let
the error escape the Transaction to use its existing rollback lifecycle for
transactional effects. See the limitations below.

## Native parameters

| Backend | Named | Positional |
| --- | --- | --- |
| SQLite | `:name`, plus other native SQLite forms | `?` |
| MariaDB | `%(name)s` | `%s` |

Parameters accept a string-keyed mapping, a positional sequence, or `None`.
Mappings and sequences are shallow snapshots. Changing the original container's
membership or order cannot change execution; contained mutable values are not
copied and must not be mutated during execution. Strings, bytes, bytearray,
memoryview, generators, sets, and non-string mapping keys are rejected as
top-level parameter containers.

Omission and `params=None` omit the connector parameter argument. Explicit `{}`
and `()` remain supplied containers. This matters for aiomysql, which uses
client-side escaping and percent formatting, not server-side prepared statements:

```python
from snekql import mariadb

literal = mariadb.raw("SELECT '100%%' AS value")  # returns '100%%'
escaped = mariadb.raw("SELECT '100%%' AS value", params=())  # returns '100%'
named = mariadb.raw("SELECT %(value)s AS value", params={"value": "100%"})
```

Native binding errors are connector-defined. Snekql does not scan placeholders,
check unused parameters, or substitute identifiers. SQL text is stored verbatim
and is available deliberately through the read-only `.sql` attribute.

## Effects and cleanup

Result checks happen after execution. `execute` rejects any result columns,
including an empty rowset. Fetch methods reject a no-column command response.
Fetching a write with backend-supported `RETURNING` is allowed. These checks do
not prevent writes or make SQL read-only.

A caught shape, cardinality, or validation error does not undo a write. If cursor completion
established reusable state, the Transaction can continue and may commit that
write. An uncaught error uses the existing rollback lifecycle for transactional
effects. Timeout, cancellation during driver work, and uncertain cleanup make the
connection non-reusable.

Only one statement and one result are supported per operation. MariaDB can execute
multiple statements before snekql detects additional results. Completion checks
also apply to extra command responses and stored-routine trailing responses.
Detection fails with `RawResultShapeError` and discards unsafe connections without
loading the next result. A stream can yield earlier chunks before detection.
Neither detection nor disposal proves that side effects were prevented or rolled
back.

Transaction-control SQL and changes to runtime-dependent session settings are
unsupported. Transaction owns begin, commit, and rollback. There is no SQL parser
or verb allowlist. MariaDB DDL, routines, implicit commits, and nontransactional
storage can escape rollback guarantees.

## Diagnostics and trust

Only trusted text belongs in `raw`. Pass untrusted values as parameters. SQL or
identifier interpolation before calling the factory remains unsafe.

Default raw statement representations, package logs, errors, and normal exception
chains omit SQL text, parameter names and values, driver messages, and returned
column names or data. Native execution failures retain `ExecutionError` and
deadlines retain `DatabaseOperationTimeoutError`, with sanitized diagnostics.
Raw aiomysql cursors suppress server warning text without changing process-wide
warning filters. Parameter-visibility settings never enable raw SQL or driver
message visibility.

This covers package-controlled diagnostics. It does not hide frame locals or
source text from debuggers and traceback formatters, prevent deliberate private
inspection, or control external driver instrumentation and user code.
