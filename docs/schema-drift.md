# Schema verification and drift

`db.verify(models, *, policy=...)` checks the live schema against your Table
Models and returns an immutable `SchemaVerificationResult` containing the
ordered checked tables, table-scoped `SchemaDriftIssue` values, and structured
`SchemaVerificationFact` values. It is the
check that ties hand-written migrations back to current model metadata.
`db.verify_migrations(migrations)` separately proves that ordered,
checksummed Migration History is at this code version's exact head by default.
Its opt-in [rolling-deployment policy](migrations.md#rolling-deployments) permits
an explicitly approved later prefix, without relaxing schema verification.
Neither method creates application tables. [Migrations](migrations.md) remain the sole
schema-creation authority.

Run both checks after `migrate`:

```python
MIGRATIONS = {"001_create_user": 'CREATE TABLE "user" (...) STRICT'}
db = await Database.initialize(database=Path("app.db"))
await db.migrate(MIGRATIONS)
await db.verify_migrations(MIGRATIONS)
await db.verify([User])
```

## Verification is a partial, structural check

`verify` is a **semantic, structural tripwire, not a proof of schema equality**.
It compares only the facts snekql controls — the table shape — and is
deliberately blind to everything else. Comparison is semantic: columns and
indexes match by name regardless of declaration order, and cosmetic DDL
differences (identifier quoting, whitespace, type-keyword case, column/index
ordering) are ignored within the supported comparison rules. Matching facts
cover those properties, not every behavior of the live schema.

`verify` **does** compare:

- table presence;
- per column: name, storage type / affinity-class, nullability, primary-key,
  auto-increment, supported server-default expression, and collation. MariaDB
  also compares numeric signedness, VARCHAR character capacity, and datetime precision.
  Declare MariaDB capacity with `Text(length=...)`, defaulting to 255.
  `LongText()` checks native LONGTEXT and its declared collation, defaulting to
  utf8mb4_bin; `Json()` retains
  its partial check of LONGTEXT backing type, not backing collation or JSON_VALID
  constraints. SQLite Text, MariaDB Text, and MariaDB LongText accept the
  [supported column collations](typing.md#column-collations). Verification compares
  the declared column collation, not arbitrary index/expression overrides.
  Storage type is
  compared by each backend's normalized class, not the declared spelling: SQLite
  collapses a column to its [type
  affinity](https://www.sqlite.org/datatype3.html#determination_of_column_affinity)
  (so `INT`/`INTEGER`/`BIGINT` and `VARCHAR(255)`/`TEXT` are equal), and MariaDB
  compares `INFORMATION_SCHEMA.DATA_TYPE` (so `BOOLEAN`≡`TINYINT(1)` and
  `JSON`≡`LONGTEXT`). A genuine affinity/type-class change is still drift;
- per index: name, columns, uniqueness, and SQLite partial/full status; MariaDB
  also compares prefix lengths and index type;
- per foreign key: ordered local/target column pairs, constraint grouping,
  multiplicity, unqualified target table names, and referential actions.
  Every represented relationship is compared, including multiple constraints on
  one local column. Extra occurrences are drift even when their facts duplicate
  another constraint. Constraint names are ignored; diagnostics do not depend on
  catalog row order;
- declared CHECK names and recognized expression structure;
- table storage-option tokens (SQLite `STRICT`, MariaDB `ENGINE=InnoDB`).

`verify` does not certify:

- arbitrary server-default expressions or equivalence through SQL coercion;
- arbitrary partial-index predicate equivalence or optimizer index selection;
- arbitrary CHECK expression equivalence or enforcement settings;
- generated-column expressions;
- triggers and views;
- exact SQLite types (affinity collapses `VARCHAR(255)` and `TEXT`);
- index-column sort direction or collation, which `Index` cannot declare;
- data.

Foreign-key comparison preserves catalog constraint groups and pair order.
One composite constraint does not match separate scalar constraints. Reordering
pairs is also drift, even when it preserves the same flattened relationships.
This tightens verification compared with earlier releases that flattened groups.
Per-column relationship facts remain available alongside the grouping result.

Backend-specific limits are also deliberate:

- SQLite compares the partial/full flag and recognized declared predicate
  structure. Unsupported predicate SQL remains unchecked.
- MariaDB does not compare integer display widths, the compatibility `CHECK` or
  backing collation of its `JSON` alias, index visibility, or foreign-key
  constraint names. Table Models declare none of those facts.
- MariaDB's catalog cannot distinguish an automatically created FK-supporting
  index from an explicit index with the same leading columns. Such an
  otherwise-unmanaged supporting index is ignored; model-named indexes are
  still compared fully.

`CurrentTimestamp` and declared `LiteralDefault` values are compared within their
supported grammar. An undeclared live literal remains drift. For a declared
`LiteralDefault`, an unsupported catalog expression is unchecked, not matched.
CHECK comparison is limited to the supported declarations below; triggers remain
outside verification. Treat
`verify` as a structural net for the drift that breaks queries, not a behavioral
guarantee.

## How drift is detected

1. Generate the expected table shape (columns, indexes, foreign keys, and
   table-level storage options) for each model.
2. Read the live table shape from the selected backend's catalog (SQLite via
   `PRAGMA`, MariaDB via `INFORMATION_SCHEMA`).
3. Diff the two shapes. Columns and indexes match by name independent of
   declaration order; only the facts snekql controls are compared.
4. Report each divergence, naming the specific table, column, index, or foreign
   key, and treat any divergence — including a missing table — as schema drift.

Because generated SQLite tables are always `STRICT`, an existing SQLite
non-`STRICT` table is reported as a storage-option divergence; MariaDB likewise
requires the `InnoDB` engine. Extra, missing, renamed, or uniqueness-changed
indexes on managed tables are also schema drift. Both backends verify managed
foreign-key targets and referential actions. MariaDB requires a supporting index
for every foreign key but does not record whether that index was implicit or
explicit, so verification ignores an otherwise-unmanaged full-column BTREE index
whose leading columns contain the complete ordered local tuple of a live foreign
key. An index with actual character prefixes, or only a composite key's second
member, is not hidden by this rule. A model-declared index remains verified by
name and full shape.

The Migration History table (`snekql_migrations`) is snekql-owned and is never
verified; keep it out of the `models` you pass to `verify`.

Verification is **read-only on both backends and leaves no schema change**,
however it fails. SQLite runs the inspection inside a transaction it always
rolls back (it never commits during verify); MariaDB reads `INFORMATION_SCHEMA`
with no transaction. That asymmetry is invisible to callers: because `verify`
only reads, a failed or drift-raising `verify` leaves the schema exactly as
`migrate` left it. The partial-state question therefore lives entirely in
[migrations](migrations.md#failure-and-transaction-behavior), never in `verify`.

## Schema Policy

The Schema Policy lives on `verify` — it is the choice of how the step that
*detects* drift handles it.

Every requested model is inspected before either policy is applied.
`policy="strict"` is the default. Drift raises `SchemaVerificationError`; its
`.result` contains every issue found:

```python
try:
    result = await db.verify([User], policy="strict")
except SchemaVerificationError as error:
    result = error.result
```

`policy="warn"` logs each divergent table and returns the result:

```python
result = await db.verify([User], policy="warn")
for issue in result.issues:
    print(issue.table_name, issue.detail)
```

Use `warn` when adopting snekql in an environment where you want observability
before enforcing drift failures.

## Structured verification facts

```python
result = await db.verify([User], policy="warn")
for fact in result.facts:
    print(fact.table_name, fact.object_name, fact.kind, fact.status)
```

Each frozen `SchemaVerificationFact` has `table_name`, `object_name`, `kind`,
`status`, and `detail`. `object_name` identifies a column or index; it is `None`
for table-wide facts. Foreign-key relationship facts use the local column name,
or `None` when both compared relationship collections are empty. The type is
exported from both backend namespaces.

- `matched`: the represented, normalized property matched.
- `drift`: the same comparison contributes to an existing drift diagnostic.
- `unchecked`: a known inspection limit. This does **not** assert that the
  feature exists, is absent, or is compatible.

Use `kind` and `status` for programmatic decisions. `detail` is human-readable,
not a stable parsing format. Facts follow requested-model order; consumers
should identify them by `(table_name, object_name, kind)`, not tuple position.
Multiple drift facts can contribute to one legacy column/index issue.

### Compared kinds

| Kind | Meaning |
| --- | --- |
| `table.presence` | Entry for the requested name in the inspected catalog |
| `table.storage_options` | Normalized STRICT or InnoDB storage-option tokens |
| `column.presence` | Column present in both model and catalog, missing, or extra |
| `column.type` | Normalized storage class, including represented type parameters |
| `column.nullable` | Normalized nullability metadata |
| `column.primary_key` | Per-column primary-key membership, not complete key structure |
| `column.auto_increment` | Represented auto-increment flag |
| `column.server_default` | Supported clock or literal default comparison; unsupported expressions for literal declarations are unchecked |
| `column.collation` | Represented column collation |
| `column.datetime_precision`, `column.unsigned` | Optional native metadata where available |
| `index.presence` | Named index present, missing, or extra after backend filtering |
| `index.columns`, `index.unique` | Ordered columns and uniqueness |
| `index.partial` | SQLite partial/full flag |
| `index.predicate` | Recognized declared SQLite predicate structure; unsupported or unavailable expressions are unchecked |
| `index.prefix_lengths`, `index.type` | MariaDB prefix lengths and index method |
| `foreign_key.relationships` | Per-column multisets of unqualified target table/column names and normalized actions |
| `foreign_keys.grouping` | Constraint grouping, ordered pairs, actions, and multiplicity |
| `check.presence` | Declared CHECK name present or missing; unchecked when catalog structure is unavailable |
| `check.expression` | Recognized expression structure matches or differs; unchecked for unsupported SQL or ambiguous names |

A missing table produces only `table.presence` drift. Missing or extra columns
and indexes produce presence drift without matched child properties. Optional
metadata absent from both normalized shapes is not reported as matched.

### Unchecked kinds

Every inspected table reports the applicable known limits. These are scope
statements, not an inventory of live objects:

| Kind | Unchecked scope |
| --- | --- |
| `table.check_constraints` | Unmanaged CHECKs, unsupported expressions, data, and enforcement settings |
| `columns.generated_expressions` | Generated-column expressions |
| `table.triggers`, `table.views`, `table.data` | Triggers, views, stored data |
| `table.other_options` | Options outside normalized storage tokens |
| `primary_key.structure` | Complete primary-key ordering/grouping |
| `foreign_keys.names` | Constraint names |
| `foreign_keys.match`, `foreign_keys.deferral` | MATCH and deferral properties |
| `indexes.expressions`, `indexes.predicates` | Expression/predicate equivalence |
| `indexes.sort_direction`, `indexes.collations` | Index-column direction/collation overrides |
| `columns.declared_types` | SQLite exact declared types/capacity beyond affinity |
| `columns.integer_display_width` | MariaDB integer display widths |
| `indexes.visibility` | MariaDB index visibility |
| `indexes.fk_supporting_origin` | MariaDB unmanaged supporting-index origin and filtering |
| `table.object_type` | MariaDB object type beyond the enforced InnoDB requirement |
| `column.collation`, `column.json_check` | MariaDB JSON backing collation and compatibility CHECK |

Existing drift from incompatible JSON storage still takes precedence over a
collation-limit entry. There is never both a drift and unchecked fact for the
same property. An unsupported default or partial index that previously caused
drift still does; unchecked scope never cancels a represented difference.

This is not an exhaustive capability catalog or proof of semantic compatibility.
For example, normalized relationship targets do not certify cross-catalog
identity. Catalog visibility, permissions, backend/version behavior, and live
schema changes still matter. An absent fact is not proof of absence or support.

Strict and warn retain their existing behavior. Unchecked entries do not raise
or log warnings by themselves; strict errors carry the complete expanded result
in `error.result`. Catalog inspection errors still raise normally and are never
converted into unchecked success. Verification remains read-only and issues no
additional catalog queries for this report.

`SchemaVerificationResult(checked_tables=..., issues=...)` remains constructible
with `facts=()` by default. Result equality includes facts. `verify([])` returns
no facts and certifies nothing about the database. Manually constructed results
with empty facts do not represent successful inspection of every property.

## Deploy and replica use

- A **deploy step** runs `initialize -> migrate -> verify_migrations -> verify`,
  applying the chain and checking history plus model shape before traffic.
- An **app replica** runs `initialize -> verify_migrations -> verify` without
  migration. It fails if history is behind this build even when partial model
  verification cannot observe a data-only migration.

Both follow the caller's topology (see [migrations.md](migrations.md)).

## What verification does not do

`verify` does not:

- create, alter, or drop anything;
- generate migrations;
- preserve or transform data.

To evolve a table, write a [migration](migrations.md) and apply it with
`db.migrate({...})`; then `db.verify` confirms the post-migration schema against
your models.

For nullable MariaDB columns, catalog SQL `NULL` defaults are equivalent to an
absent server default. Quoted text `'NULL'`, other literals and expression
defaults remain distinct and can report drift. Verification never rewrites them.


## CHECK verification

`CheckConstraint` declarations opt specific named checks into verification. Names
must match exactly. SQLite reads stored table DDL, preserving quoted names,
comments, and nested expression structure. MariaDB reads `CHECK_CONSTRAINTS` in
one catalog query for the requested tables. Catalog query failures still raise.

For each declared name:

- Missing: `check.presence` drift, with no matched expression fact.
- Present with recognized SQL: `check.presence` matched, then `check.expression`
  matched or drift.
- Present with unsupported SQL or duplicate names: presence matched, expression
  unchecked. No expression compatibility is asserted.
- Unreadable catalog structure: presence unchecked, not fabricated absence.

Undeclared checks produce `check.unmanaged` unchecked facts, grouped by name.
Anonymous checks share one fact with a count. These are observations
about catalog objects, unlike the table-wide limitation statements. MariaDB's
implicit JSON compatibility checks stay unmanaged unless explicitly declared;
this does not extend the supported CHECK declaration types to JSON.

Comparison ignores cosmetic parentheses, whitespace, comments, and identifier
quoting. It recognizes comparison spelling aliases and normalizes backend NOT
rewrites, including De Morgan forms and boolean association. It does not reorder
terms, simplify arithmetic, infer range equivalence, or prove mathematical
identity. Unknown functions and arithmetic remain unchecked. Ambiguous bare
keywords and MariaDB backslash-escaped string literals may also remain unchecked;
scaffolded string literals avoid that ambiguity.

Strict and warn policies use the same facts. Unsupported or unmanaged checks
alone do not raise or warn. A matched expression does not certify stored data,
SQLite `ignore_check_constraints`, MariaDB `check_constraint_checks`, or the
settings on future connections. Verification is not an authorization to skip
baseline review or data validation.


## Literal default verification

`LiteralDefault` adds model-side values for bounded SQL defaults. Recognized
constants compare after column encoding and catalog normalization. Parentheses,
integer signs and leading zeros, and Boolean keyword spellings can normalize;
quoted text remains text, and quoted `'NULL'` is never SQL NULL. Comparison does
not infer affinity coercions, execute SQL, or prove expression equivalence.

For literal declarations, a missing default or a changed recognized literal
produces `column.server_default` drift. Unknown expressions produce an unchecked
fact and do not alone fail strict verification. Legacy comparisons for absent
declarations and `CurrentTimestamp` retain their existing behavior.

SQLite distinguishes an absent default from DEFAULT NULL. MariaDB normalizes
implicit nullable defaults and explicit DEFAULT NULL to the same catalog value.
A declared NULL literal can match that effective value, but also receives
`column.server_default_explicitness` unchecked. This does not certify an explicit
clause. The catalog limitation also applies to nullable columns without declared
server defaults.

MariaDB backslash-escaped catalog strings can remain unchecked because their
interpretation depends on SQL mode. Scaffolded literals use hex conversion to
avoid this ambiguity. Existing data, future inserts made by other applications,
and automatic backfills are outside verification.


## MariaDB prefix index verification

`Index(..., prefix_lengths=(None, 128))` supplies expected ordered prefix lengths.
`index.prefix_lengths` compares them with catalog SUB_PART values. Missing
indexes, reordered members, changed uniqueness, and changed effective prefixes
remain drift. VARCHAR prefixes equal to column capacity normalize to full-column
entries, matching MariaDB's catalog behavior. Original DDL spelling is not
certified.

Declared names remain significant. Otherwise-unmanaged indexes with actual
prefixes are not ignored as foreign-key support, even when their column names
start with the local FK tuple. Full-column BTREE supporting indexes retain the
existing filtering and origin limitation. An explicitly declared prefixed unique
index cannot authorize a model foreign-key target.

Storage capacity and prefix length use character counts; server key-size limits
also depend on encoding and the complete index. Verification checks what the
server created, not whether every proposed index fits those limits.


## SQLite partial-index verification

`Index(..., where=predicate)` declares a bounded SQLite partial index. Verification
compares its presence, ordered columns, uniqueness, partial/full flag, and
recognized predicate structure. A changed recognized expression or a full index
in place of the declared partial index is drift. A missing index produces presence
drift without fabricated predicate matches.

Cosmetic grouping, comparison spellings, supported NOT rewrites, and SQLite's
ASCII-insensitive column references can normalize. Terms are not arbitrarily
reordered or evaluated. Quoted names, literals, and comments are distinguished
when locating the stored WHERE clause. Unknown quoted operands are not assumed
to be columns, since SQLite may interpret them as string literals.

Unsupported or unavailable predicate metadata yields `index.predicate` unchecked.
That alone does not fail strict verification. `indexes.predicates` continues to
record the general scope limit, not a claim that every predicate is unverified.
Matching structure does not certify optimizer use, existing data, index-level
collation overrides, or arbitrary SQL-expression equivalence.
