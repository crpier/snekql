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

Mapping mode is the default. It returns `dict[str, object]` using driver column
names as keys. Aliases are preserved exactly. Duplicate names raise
`RawResultShapeError`, even when there are no rows.

Use `row_mode="tuple"` for `tuple[object, ...]` rows in column order. Duplicate
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

Result validation contracts are not supported yet. Factory `validate` accepts
only omission or `None`. Transaction `validate` accepts omission or literal
`True`; `False` raises `QueryConstructionError` before execution. Existing Query
Builder validation options are unchanged.

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

A caught shape or cardinality error does not undo a write. If cursor completion
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
