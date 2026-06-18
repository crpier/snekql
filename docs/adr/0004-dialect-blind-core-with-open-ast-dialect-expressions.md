# Dialect-blind core with open-AST dialect expressions

snekql will grow dialect-specific query features — MariaDB JSON path operators
(`JSON_EXTRACT`, `JSON_CONTAINS`), typed JSON extraction, and eventually a
Postgres backend with its own operators (`@>`, arrays). Today the Dialect seams
(`snekql/_query_dialect.py`, `snekql/_schema_dialect.py`) centralize backend
divergence as facts-plus-callbacks that shared Query Compilation runs against,
which works while divergence is *parameterizable* (placeholder, identifier
quoting, value encoding). It does not cover a feature **one backend has and the
others lack**: a new operator is a new node in the Query Builder's expression
AST and a new branch in Query Compilation's `kind` dispatch. Absorbing those into
the shared core makes the core learn every backend's vocabulary, so the core
grows with every backend — exactly the wrong direction as MariaDB features and a
Postgres backend land.

This ADR records two coupled commitments.

**1. The core stays dialect-blind.** No core module (the Query Builder, Query
Compilation, Materialization, pool, runtime selection) imports a Backend
Namespace (`snekql.sqlite`, `snekql.mariadb`). The concrete Dialect / Backend
Runtime Adapter is injected at the edge — when a `Database`/`Config` is built —
never imported by the core. The invariant is mechanically checkable:

```
grep -rn "snekql.sqlite\|snekql.mariadb" snekql/_*.py snekql/{runtime,query,model,storage}.py
```

returns nothing. Two violations exist today and are the scope of phase 1:
`snekql/_pool.py` imports SQLite connection settings, and
`snekql/_runtime_selection.py` hard-defaults to the SQLite `Config`.

**2. Dialect-specific query operators are added as open-AST expressions.** A
Backend Namespace defines column subtypes (building on
[ADR 0003](0003-per-backend-namespace-column-declarations.md): per-namespace
column declarations) whose methods return expression objects that satisfy two
core *structural protocols* rather than new core AST nodes:

- an operand-render seam (`__compile_sql__(ctx)`) so the expression works as a
  predicate operand in `WHERE`;
- a projection seam (`__compile_select_sql__(ctx)` + `__decode__(raw) -> T`) so
  it can be projected in `SELECT` and Materialized to a typed value.

Query Compilation renders operands by calling the protocol (structural dispatch),
and Materialization decodes by calling `__decode__`; neither names the leaf type.
Type-safety and ergonomics live entirely on the column subtype's methods (which
return `Comparable[Owner, T]` / `Selectable[T]`) and the per-arity `select`
overloads; the open seam itself carries no user-facing types, so it does not
dilute the type surface. The result type flows from the selectable into the
query result purely through the `select` overloads. The `CompileCtx` injected by
the core is the carrier for the Dialect facts an expression needs to render
(placeholder style, quoting).

This was validated against `pyright` in a throwaway prototype kept at
`proto_open_ast/`: a MariaDB `json_extract_int` operator is type-safe as a
`WHERE` operand and as a typed `SELECT` projection (`int` / `tuple[str, int]`),
illegal uses (the operator on a non-JSON column; a wrong-typed comparison; an
incorrectly-asserted decode type) are rejected, and the core compiles and
materializes it while importing no Backend Namespace.

## Considered Options

- **Gated AST: core grows the node, guarded by a Dialect capability flag**
  (`dialect.supports_json_path`). Rejected: simple and type-safe, but the core
  learns every backend's operator vocabulary, so it grows with each backend —
  the bloat this ADR exists to prevent — and does not scale to Postgres.
- **Open AST via structural protocols, operators hung off per-namespace column
  subtypes.** Chosen. The core defines the protocols; each Backend Namespace
  ships the operators. Adding a backend adds zero core nodes and zero `select`
  overloads.
- **Free-function operators exported by the Backend Namespace**
  (`mariadb.json_extract(col, path)`). Rejected: weaker ergonomics and against
  the established "methods on the column/model over new top-level factory
  functions" preference; the column-subtype-method form also scopes the operator
  to exactly the columns that support it.

## Consequences

- Each dialect expression implements the render seam (and, to be projectable,
  the decode seam). `__decode__` is the leaf-owned raw→typed conversion (e.g.
  MariaDB JSON scalars arrive as text → `int`); it is the correct home for it.
- Query Compilation's operand renderer dispatches structurally (the operand
  satisfies a protocol) instead of assuming an `Attr`. Small runtime cost; the
  `CompileCtx` becomes the contract for what an expression may rely on.
- Per-arity `select` overloads are still required for tuple projection, but that
  is orthogonal — a dialect selectable adds none; it only has to *be* a
  `Selectable[T]`.
- Phase 1 is the only required refactor: close the two core→namespace import
  leaks so the blindness invariant holds. The open-AST protocols can be
  introduced when the first dialect operator (MariaDB JSON) lands, ideally
  **before** Postgres so Postgres validates the seam rather than reshaping it.
- This unblocks, but does not mandate, a later split into separate distributions
  (`snekql-core` + per-backend packages) to solve import ergonomics and stop
  pyright auto-imports crossing backends — viable only once the core provably
  imports no Backend Namespace. That packaging change is explicitly a downstream
  phase, out of scope here.

## Open Questions

- **Nullable decode**: a JSON path that misses yields `NULL`; whether typed
  extraction should surface as `T | None` (and how the user opts in) is
  unresolved. Same seams, a typing choice.
- **Other clauses**: dialect expressions in `ORDER BY` / `GROUP BY` and as
  aggregate arguments are expected to ride the same render/decode seams but are
  not yet prototyped.
