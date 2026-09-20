# Existing-schema compatibility audit

This records the starting point for #291, before adding declaration interfaces.
It distinguishes declarations that already exist from facts the verifier can
actually certify. Migrations remain hand-authored; none of these declarations
create or alter live schema during initialization or verification.

## Naming

| Concern | Current support | Gap or constraint |
| --- | --- | --- |
| Physical table name | Inferred name or explicit `__tablename__` | No separately declared schema/catalog qualifier. A dotted string is not a qualified identifier. |
| Physical column name | Python attribute name | No independent SQL column-name mapping. Pydantic aliases and query aliases are not physical column renames. |
| Index name | `Index(..., name="existing_name")` | Column `index=True` and `unique=True` use generated names; use explicit `Index` declarations for reviewed existing names. |
| Composite index | Ordered descriptors in `Index(a, b, unique=...)` | No prefix lengths, expressions, predicates, direction, per-index collation, or index-method declaration. |
| Primary-key name | Engine convention | No separately named primary-key constraint. |
| Foreign-key name | No public name option | Verification ignores constraint names and compares scalar relationship facts. |
| Query alias | Explicit `alias(..., name=...)` | Query-only identity; cannot map a model to a differently named physical column. |

Identifier validation is narrower than SQL identifier quoting. Names must start
with a letter or underscore and continue with letters, digits, or underscores.
The implementation uses Python's Unicode character classification, not an
ASCII-only regular expression. Spaces, hyphens, and qualified dotted names fail
validation even if a database could quote them. A name passing this syntactic
check is not a guarantee that every backend accepts its character set or length.

Sources: `snekql/model.py`, `snekql/indexes.py`, `snekql/_schema_plan.py`, and
`snekql/_aliases.py`. Naming changes must cover query compilation, materialization,
FK targets, indexes, scaffolding, and verification together. Adding a constructor
argument without keeping those paths consistent would not provide column mapping.

## Storage and defaults

- MariaDB `Text()` emits `VARCHAR(255) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin`.
  Neither length nor collation is configurable. Actual VARCHAR length already
  participates in normalized type comparison, so a differently sized existing
  column produces drift rather than a representable declaration.
- There is no native long-text declaration for ordinary string values. MariaDB
  `Json()` maps to the LONGTEXT-based JSON alias, but that is a different logical
  value contract, not a substitute for long strings.
- SQLite `Text()` has TEXT storage and expects BINARY collation. Existing
  NOCASE/RTRIM columns cannot be represented through a collation option.
- MariaDB's current reader records collation for VARCHAR, not every text-family
  catalog type. Long-text support must preserve the existing JSON alias behavior
  while making ordinary text collation verifiable.
- `default=` and `default_factory=` normally describe Python construction.
  `default=CurrentTimestamp` is the supported database-generated default marker.
  An ordinary Python literal default is not a SQL DEFAULT declaration.
- Arbitrary literal server defaults, generated expressions, and additional
  server expressions are not representable. Do not hide this with automatic
  model-derived migrations or permissive equality checks.

Sources: `snekql/storage.py`, `snekql/mariadb/storage.py`, backend `schema.py`
modules, and `_validate_column_declaration` in `snekql/model.py`.

## Constraints and indexes

Existing composite primary keys and ordered multi-column indexes must remain
supported. Multiple `primary_key=True` columns produce a table-level key in
declaration order. Ordinary indexes retain ordered column tuples and uniqueness.

The current verifier represents primary-key membership as a per-column boolean;
it does not retain a full primary-key order/grouping record. Do not describe a
successful membership comparison as proof of composite-key ordering.

`ForeignKey(Target.column)` declares one scalar relationship with referential
actions. Verification preserves multiple scalar relationships and their
multiplicity, but flattens composite constraints into scalar facts. It cannot
certify that one composite FK equals several independent scalar FKs.

There is no CHECK declaration. CHECK expressions, generated-column expressions,
index predicates, and triggers are not represented by the shared comparison
shape. SQLite partial-index presence and MariaDB prefix lengths/index methods
can produce drift today, but callers cannot declare their expected counterparts.
MariaDB can also omit otherwise-unmanaged FK-supporting indexes from comparison
because its catalog does not identify whether they were implicit.

Sources: `snekql/_schema_shape.py`, `snekql/_schema_compile.py`, backend catalog
readers, `tests/sqlite/test_schema.py`, `tests/mariadb/test_schema.py`, and
`tests/test_model_declaration.py`.

## Verification outcomes

`SchemaVerificationResult` currently contains `checked_tables` and `issues`.
It does not provide a separate inventory of unsupported or unchecked facts.
An empty issue list means the represented facts match, not complete schema
compatibility. Existing limits are documented in [schema drift](schema-drift.md).

Future changes must distinguish:

- Represented, inspected facts that match the declaration.
- Represented facts that differ and therefore constitute drift.
- Facts that are present or relevant but cannot be certified by that comparison.

Unknown facts must not silently become verified facts. Adding an unsupported-fact
report must not silently change strict/warn semantics or turn intentional gaps
into a blanket permission to ignore drift. This needs its own interface review.

## Proposed delivery boundaries

These are the original work boundaries; implemented extensions are recorded below.

1. Configurable MariaDB VARCHAR character capacity, preserving today's default.
   Test declarations, scaffolding, and verification against hand-created schemas.
2. Reviewed long-text and collation declarations, including the JSON alias and
   index/FK restrictions. Keep database comparison semantics explicit.
3. Verification coverage reporting, including composite-key ordering/grouping
   gaps. Review the public result and policy behavior before changing them.
4. Composite FK declarations and catalog grouping, preserving scalar FKs and
   existing composite primary keys.
5. CHECK declarations with a bounded expression contract and honest verification
   limits, not claims of arbitrary SQL-expression equivalence.
6. Richer server defaults, keeping generated values distinct from Python defaults.
7. Selected backend-specific indexes, with explicit supported forms and matching
   catalog evidence rather than arbitrary SQL fragments.

Each follow-up needs a reviewed interface and public-seam tests before code.
Physical column mapping and broader identifier syntax remain explicit naming
choices, not accidental additions hidden inside storage work. This audit alone
does not fulfill #291 or close its parent epic.

## VARCHAR length extension

The first extension adds `mariadb.Text(length=255)`. It preserves the previous
omitted-argument behavior and accepts exact integers from 1 through 16,383.
The capacity is in characters for utf8mb4, not bytes. Scaffolding renders it,
verification compares it against catalog capacity, and scalar foreign keys
inherit the target's capacity. This does not add collation options, long text,
physical column mapping, or the other declaration interfaces listed above.

Capacity is a storage contract, not a Python string transformation. Values are
not normalized or truncated. Python defaults and validation remain independent;
over-capacity writes are rejected by existing codec guards or the server's
strict-mode storage checks. Server row-size,
index-key, and foreign-key limits still apply, so an accepted length does not
promise that every table or index combination can be created.

SQLite `Text()` deliberately has no `length` argument: SQLite TEXT does not
provide MariaDB's VARCHAR capacity semantics. Existing composite keys and
multi-column indexes retain their declarations and ordered column lists.


## Native LONGTEXT extension

The second extension adds `mariadb.LongText()` with the same logical value
codecs, nullability, and Python defaults as `Text()`. It emits native `LONGTEXT
CHARACTER SET utf8mb4 COLLATE utf8mb4_bin`, without a VARCHAR length argument.
There is no new collation option. Server packet and storage limits still apply;
values are not truncated or constrained by the legacy 255-character codec guard.
Explicit larger VARCHAR capacities also bypass that legacy guard.

The constructor omits primary-key, unique, and index flags. `Index` rejects a
LongText member, including compound indexes; `ForeignKey` rejects a LongText
target. These restrictions remain until appropriate backend-specific index/key
interfaces are reviewed. Ordinary text and integer composite keys are unchanged.

Verification compares the LONGTEXT native type and collation. Existing `Json()`
verification still checks its LONGTEXT backing type without certifying its
collation or JSON_VALID CHECK. Neither declaration certifies arbitrary CHECK
constraints on a hand-created column; matching LONGTEXT storage alone does not
prove that the database accepts every ordinary string.


## Reviewed column collations

The third extension adds `collation=` to SQLite Text and MariaDB Text/LongText.
SQLite accepts `BINARY`, `NOCASE`, and `RTRIM`, defaulting to `BINARY`. MariaDB
accepts `utf8mb4_bin`, `utf8mb4_general_ci`, and `utf8mb4_unicode_ci`, defaulting
to `utf8mb4_bin`. Declarations reject other spellings and non-string values.
Scaffolding emits the chosen policy and verification compares the effective
column collation. Scalar foreign keys inherit their target's policy.

Native comparison and uniqueness semantics apply without changing Python
strings. SQLite NOCASE is ASCII-only; RTRIM ignores trailing ASCII spaces.
MariaDB's supported `_ci` collations also ignore accents. Even the defaults are
not equivalent: MariaDB utf8mb4_bin uses PAD SPACE equality, while SQLite BINARY
distinguishes trailing spaces. SQLite LIKE has its own rules.

This extension does not add custom collations, new character sets, index- or
expression-level COLLATE declarations, or automatic schema changes. JSON
verification keeps its existing scope. Existing-data collisions, index overrides,
foreign keys, and migration sequencing still need review. Verification coverage reporting is described in the following extension.


## Structured verification reporting

The fourth extension adds `SchemaVerificationResult.facts`, an immutable tuple
of `SchemaVerificationFact` values. A fact identifies its table, optional column
or index name, stable kind, status, and human-readable detail. Comparisons emit
`matched` or `drift` alongside the existing diagnostics from the same decisions.
Known limits emit `unchecked`; they do not claim live feature presence or absence.

Strict/warn behavior and existing diagnostic text remain unchanged. Strict
errors expose the same facts as warn results. Missing objects receive presence
drift without fabricated property matches. Optional unavailable metadata is not
reported as matched. JSON backing details, composite key/FK structure, and
MariaDB FK-supporting index origin are explicitly limited.

This reports the existing comparison scope; it does not make unchecked schema
compatible, inventory every catalog feature, or implement the remaining
constraint/default/index declarations. See the [fact-kind reference](schema-drift.md#structured-verification-facts).


## Table-level foreign-key constraints

The fifth extension adds `ForeignKeyConstraint(*columns, references=(...),
on_delete=..., on_update=...)` in `__foreign_keys__`. Both backends preserve the
same explicit column declarations. Validation checks owner identity, backend,
complete ordered candidate keys, conservative storage compatibility, tuple
arity/duplicates, and SET NULL feasibility before database access.

Scaffolding emits one constraint per declaration. Existing scalar FKs share the
same ordered schema plan. Overlapping constraints retain their multiplicity;
self-references bind after the model's column and index metadata is available.

Catalog readers now retain constraint IDs and member positions. IDs are used to
group rows, not compared as names. Verification still exposes flattened scalar
facts, but additionally compares normalized ordered groups. `foreign_keys.grouping`
is now matched or drift, rather than unchecked. Split, reordered, missing, or
repeated groups can fail strict verification where flattened facts previously
passed. MariaDB supporting-index filtering now requires the complete local tuple
as a leading prefix, not merely any member of a composite relationship.

Constraint names, MATCH, deferral, cross-catalog identity, and complete primary-key
ordering remain outside this extension. Declarations do not mutate live schema.
CHECK declarations, richer server defaults, and selected backend indexes remain
unfinished work for #291.


## Named CHECK declarations

The sixth extension adds `CheckConstraint(predicate, name=...)`, returned by a
synchronous `__checks__` classmethod. The method runs once after column metadata
is frozen. The originally proposed class-body list was rejected after a typing
probe showed `ty` treats class-body field variables as dataclass fields; the
reviewed classmethod form preserves bound-column predicate typing.

Integer, Boolean, and ordinary Text predicates compile into named constraints on
both backends. The supported grammar includes comparisons, NULL tests, literal
membership, BETWEEN, and boolean composition. Unsupported storage, foreign
owners, raw SQL, subqueries, functions, and arithmetic are rejected before IO.
Values use column codecs and backend-safe DDL literals, including UTF-8 hex
conversion for MariaDB strings.

SQLite DDL and MariaDB CHECK_CONSTRAINTS supply names and bounded expression
structure. Declared-name absence and changed recognized structure produce drift.
Unsupported SQL, ambiguous names, and unmanaged checks remain unchecked. The
parser preserves unknown syntax rather than dropping it, recognizes only ASCII
SQL keywords and whitespace, and does not claim
arbitrary expression equivalence, data validity, or enforcement settings.



## Literal server defaults

The seventh extension uses `default=LiteralDefault(value)` on `GenCol` columns,
following the existing default-marker convention. Integer, Boolean, ordinary
text including MariaDB LongText, and nullable NULL values are supported. Plain
Python defaults and CurrentTimestamp remain unchanged. Literal values are
validated and encoded during model binding, then emitted as safe DDL constants.

Catalog comparison preserves literal types and recognizes a bounded constant
grammar. Missing or changed known defaults drift; unsupported expressions for
literal declarations are unchecked. MariaDB NULL-default explicitness is not
certified. Hand-created schemas, native insert omission and overrides, logical
validation, codec limits, and public typing have regression coverage.

The next extension covers selected backend-specific indexes.


## MariaDB prefix indexes

The eighth extension adds `Index(..., prefix_lengths=(...))` for MariaDB.
Ordinary Text and LongText can use positive character prefixes, with None for
full-column members. LongText remains nonkeyable outside this explicit index
form. SQLite rejects prefix tuples. Existing full and compound indexes retain
their declarations; distinct named prefix variants can share column lists.

Prefix declarations cannot authorize FK targets. Catalog prefix indexes are no
longer hidden as inferred FK-supporting indexes. Verification compares ordered
prefixes and normalizes full-capacity VARCHAR prefixes to MariaDB's full-column
catalog representation. It does not certify original DDL spelling or data.

Tests cross declarations, scaffold, hand-created catalogs, native prefix
uniqueness, and complete-value materialization. Server key-size limits still
apply. SQLite partial indexes are recorded below.


## SQLite partial indexes

The ninth extension adds SQLite `Index(..., where=predicate)` and synchronous
`__indexes__` factories alongside existing lists. Callbacks run once after column
freezing, and declarations snapshot their predicates. `Index[Self]` preserves
bound-column ownership in factory return annotations; explicit cls annotations
also support concrete model return types.

Predicates share the bounded CHECK expression grammar but obey WHERE truth
semantics: false and NULL exclude rows. Partial uniqueness never establishes an
FK candidate key. Distinct named predicates may share indexed columns. Native
insert/update tests cover subset uniqueness, including excluded NULL rows.

Catalog verification distinguishes supported structural matches, drift, and
unknown expressions, without claiming optimizer behavior. Existing column-only
ON CONFLICT targets remain insufficient for partial-only unique indexes. No
query or automatic-migration extension is included.

All planned declaration extensions for #291 are implemented. Delivery and epic
closure are tracked in #291 and #287; this audit records the supported scope and
its remaining limits.
