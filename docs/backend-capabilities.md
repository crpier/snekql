# Backend capability matrix

Choose a backend based on what your application needs, not just matching method
names. Both support the same basic workflow, but result counts, locks, storage,
and RETURNING differ.

This table describes what **snekql supports**, not everything each database can
do. Both require Python 3.14+. See [database settings](engine-settings.md) for
connection requirements and [tested environments](failure-matrix.md) for evidence.

| Capability | SQLite | MariaDB |
| --- | --- | --- |
| Async driver | Optional `aiosqlite` extra | Optional `aiomysql` extra |
| Models, scalar/tuple results, named Pydantic projections | Supported | Supported |
| Positional width | Up to eight result slots | Up to eight result slots |
| Named projections wider than eight fields | Supported | Supported |
| INNER/LEFT joins and aliases | Explicit relationship/owner checks | Explicit relationship/owner checks |
| Generated values | `GenCol`, auto-increment and supported defaults | `GenCol`, auto-increment and supported defaults |
| Core storage constructors | `Integer`, `Real`, `Text`, `Blob` | Same names, with backend-specific storage semantics |
| Native JSON/decimal/UUID/date/datetime declarations | Not exported; supported logical types use codecs over SQLite storage | `Json`, `Decimal`, `Uuid`, `Date`, `DateTime`; also `Boolean`, `LongText` |
| INSERT RETURNING, positional/named | Supported, including supported bulk forms | Supported, including supported bulk forms |
| UPDATE/DELETE RETURNING | Supported | Rejected by the library, even where server syntax exists |
| Conflict handling | Explicit conflict target; `DoNothing` or `DoUpdate` | Server chooses the matching unique conflict; no exact SQLite target equivalence |
| RETURNING with `DoNothing` | Rejected because no row may be returned | Rejected by the library |
| UPDATE affected count | Matched rows | Rows actually changed |
| Savepoints | `begin_nested()` | `begin_nested()` |
| Transaction access/isolation | Read-only policy and supported serializable isolation; immediate write intent | Explicit read-only/read-write and supported native isolation levels |
| `.for_update()` | Rejected, no emulated row locks | Supported policies with backend restrictions |
| Partial indexes | Supported declarations; constrained predicate grammar | Rejected by the library |
| Text prefix indexes | Rejected | Supported declarations with length/type restrictions |
| Descending-index declarations | No dedicated declaration option | No dedicated declaration option |
| CHECK/foreign-key/default declarations | Supported within documented expression/type limits | Supported within documented expression/type limits |
| Schema verification | Partial structural evidence, not full equality | Partial structural evidence, not full equality |
| Hand-authored migrations | Explicit canonical history, separate from initialization | Same ownership model; DDL may commit implicitly and need reconciliation |
| Native integer literals | Bound signed-64 constants in named projections | Same, with explicit width-preserving lowering |
| Typed nonrecursive CTEs and output labels | Supported with named definitions and token-based outputs | Same |
| Named UNION/UNION ALL | Supported with left-output compatibility guards | Same |
| Recursive CTE/window/INTERSECT/EXCEPT builders | Not implemented | Not implemented |
| Raw CTE/window/set SQL | Explicit validated consumption contracts, subject to engine capabilities | Same, with dialect-specific SQL |
| Streaming | Explicit stream lifetime and bounded delivered partitions | Same, using an unbuffered cursor; not a native-memory guarantee |
| EXPLAIN | EXPLAIN QUERY PLAN for SELECT/INSERT/UPDATE/DELETE; no `explain_analyze` | EXPLAIN/ANALYZE for SELECT/UPDATE/DELETE without RETURNING; ANALYZE executes the query |
| Durability | File-backed WAL, configurable NORMAL/FULL policy; storage limits still apply | Server durability and storage configuration remain operator-owned |
| Verified TCP TLS | Not applicable to the embedded database | `TLSConfig`, with certificate and hostname verification |
| Production pool ownership | One Database per owning process/event loop; memory databases have special capacity rules | One Database per owning process/event loop |
| Test database | Temporary file or memory database using real migrations | Owned native temporary server helper |

The identical exported names in the [API index](api-reference.md) do not imply
identical SQL semantics. Raw SQL must be written for the chosen engine and does
not bypass transaction, deadline, backend identity or consumption rules.

Read the [typing guide](typing.md) for declaration and query restrictions,
[raw contracts](raw-sql.md) for typed raw results, [reporting](reporting.md) for
runnable advanced-SQL recipes, and [connection lifecycle](connection-lifecycle.md)
for cleanup and deadline limits. MySQL and PostgreSQL are not supported backends.
There is no automatic migration generation, ORM session, identity map or lazy
relationship loading.

[All guides](README.md)
