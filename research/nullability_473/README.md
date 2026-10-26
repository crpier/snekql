# SQL nullability, logical domains, and construction — #473

2026-10-26. **First research pass, not a selected interface or implementation.**
Started from `origin/main` at `46b2342`. Related defaults research is on
`research/473-default-declarations` / draft PR #539, last consulted at `851a644`.
No production or dependency changes. No model templates, defaults, factories,
queries, codecs, DDL, database workflows, or generated callers are executed.

## Maintainer direction

Separate Python and SQL defaults lead the defaults discussion because different
writers can legitimately have different policies. The maintainer does **not**
consider the callable-intersection candidate's standalone `required=True` escape
worthwhile if the rest of the interface stays unchanged. Investigate whether a
better overall nullability/construction model changes that judgment. Do not design
nullability merely to justify that typing trick. Public names, annotation arity,
compatibility, defaulting policy, and implementation remain unselected.

## Findings so far

1. **Constructor requiredness and SQL nullability cannot be one boolean.** A
   nullable value can be required, and a non-null value can have a Python default
   or be server-generated. `required=True` cannot mean SQL NOT NULL without losing
   valid combinations. [The scenario sheet](scenarios.md) shows the distinctions.
2. **The important existing coupling is deeper than schema inference.** One
   Logical Type governs both application construction and Row validation; one
   `nullable` flag governs schema metadata *and* several NULL validation paths.
   Merely relaxing the declaration guard would allow None into a Row typed str.
3. **An application may legitimately model a stricter domain than its schema.**
   A nullable SQL column with non-null application values can have a truthful
   non-null Row type if materializing an incompatible NULL raises. This is not a
   promise that every database row is decodable. The same distinction already
   exists for constrained Logical Types over broadly permissive TEXT storage.
4. **Accepting legacy NULL on reads while disallowing None on construction is a
   different requirement.** It needs distinct input and read domains (or distinct
   input/Row declarations), not just a schema flag or constructor-required flag.
   A native two-domain annotation probe preserves this distinction at both agreed
   typing seams, including imported consumers and query results.
5. **None of this yet removes the pending-default/required-input trade-off.**
   Separating domains does not by itself change native constructor omission
   metadata. The prototype deliberately retains explicit Python pending defaults;
   it neither adopts `required=True` nor claims shorter generated declarations.

## Baseline: current library contract

Source references below are at the starting main revision. They are source
inspection, not newly executed runtime proof.

| Concern | Current meaning and source |
| --- | --- |
| Logical Type | `CONTEXT.md`: one annotation-provided Logical Type; Column Type chooses storage, Codec bridges them. `docs/adr/0005-storage-primitive-constructors-with-derived-codecs.md` intentionally permits storage/logical mismatches to fail at encoding/decoding. |
| Pending versus Row | `snekql/sqlite/model.py:54–104` and corresponding MariaDB aliases: Col[T] exposes T in both states; GenCol[T] exposes T or PENDING_GENERATION in Pending, T in Row. |
| SQL nullability | `snekql/model.py:833–872`: annotation membership of None is authoritative. Omitted nullable= derives from it; an explicit flag must agree. Nullable PK annotations are rejected. Unresolved membership requires an explicit flag. |
| Alias inspection | `snekql/storage.py:987–1000,1090` and `column_admits_none` at 2554: inspect field-level None membership, not nullable elements inside a container; preserve metadata and follow the existing unknown-result policy. See closed #321 and `docs/typing.md:286–332`. |
| Constructor omission | `snekql/model.py:960–984`: a supplied value, Python default, or factory is obtained; Ellipsis means missing required input. Nullable annotation alone does not supply a value. |
| Server defaults | `snekql/model.py:796–831`: markers require GenCol, disallow a Python factory, become the internal SQL default and Python pending default. SQL ownership currently chooses construction policy too. |
| Input None | `snekql/storage.py:1474–1480,1536–1539`: None bypasses the logical adapter and is accepted/rejected through the physical nullable flag. |
| Read SQL NULL | `snekql/storage.py:1346–1395,1542–1571`: validated primitive/JSON NULL paths check that same flag, then return None without validating it against a separate read domain. Native Boolean/DateTime decoding reaches the same logical-null path. |
| Wire None | `snekql/storage.py:1711–1728`: None encodes directly to SQL NULL before JSON or other codecs. `encode_model_row` in `snekql/_model_materialization.py` omits only PENDING_GENERATION, not None. |
| Read validation | `docs/typing.md:406–414`: validate=False is a raw escape hatch with static result widened to object, not a way to promise a non-null typed Row. |
| Explicit Row snapshots | `snekql/model.py:1042–1077`: complete validates every field via the same model-value validator; it would also need reconsideration if write/read domains differ. |
| Schema consumers | `snekql/sqlite/_schema_ddl.py:59–109`, `snekql/mariadb/schema.py:157–189`, `snekql/_schema_shape.py:172–182`: schema compilation, expected catalog shape and verification compare physical nullability. Verification does not check data or alter schema. |

The declaration guard's errors are **runtime class-definition errors**, not native
ty guarantees. Paired controls demonstrate that ty accepts both
`Col[str] = Text(nullable=True)` and `Col[str | None] = Text(nullable=False)`;
input and Row types still come from the annotation. These incompatible baseline
classes are never executed. Green checker observations do not make them valid
current models.

The older ADR 0008 text predates literal server-default support; use current
`docs/schema-drift.md` and source for literal/NULL default verification.

## A small design comparison

These are logical contracts, not final spellings. B and C share the same idea of
an independently authoritative explicit SQL nullable option; C adds input/read
separation only where it pays for itself.

### A. Keep current coupling

```python
value: db.Col[str | None] = db.Text()
```

- Required constructor argument; accepts None; Row value may be None.
- SQL is nullable; nullable=False contradicts the annotation.
- Compact and coherent for applications whose write/read domains coincide with
  the inferred schema nullability.
- Cannot describe a nullable brownfield column with a strict non-null application
  domain, or a non-null input domain with nullable reads, using that one T.

### B. Independent SQL nullability, one application Logical Type

```python
# Proposed contract, currently rejected at class definition:
value: db.Col[str] = db.Text(nullable=True)
```

- Required constructor argument; application inputs must be str.
- Schema permits NULL, so another writer can store it.
- Successfully decoded Row values remain str; an actual NULL must raise a
  materialization error. Filtering NULL out of a particular query is possible,
  but must not be silently added to every read or treated as universally proven.
- Verification can match a nullable schema while a read rejects incompatible
  data: those are different contracts, not inconsistent verification.
- This is a useful brownfield contract **only when rejecting those rows is an
  acceptable application policy**. It is not equivalent to accepting legacy NULL.
- Needs logical null validation independent of schema nullability. Do not simply
  delete `_validate_column_nullability` and rely on today's decoder.

This is a plausible low-interface-cost improvement, consistent with existing
constrained Logical Types. It does not require introducing two type arguments.
Native evidence here characterizes existing annotation-based types; it does not
implement or prove this future decoding policy.

### C. Independent SQL nullability, separate input/read domains

```python
# Research convention only: Col[Input, Read=Input]. Not an installed interface.
value: Col[str, str | None] = db.Text(nullable=True)
```

- Required constructor argument; None is rejected statically on construction.
- Pending value is str; Row value may be str or None.
- Schema permits NULL; externally written NULL is compatible with the read type.
- Requires separate validation/codec policies for inputs and read results, and a
  decision about what explicit complete snapshots validate against.
- Costs more annotation vocabulary. Separate model declarations are another way
  to express the distinction, not another prototype pursued here.
- The probe covers nullable widening of a shared non-null domain, **not arbitrary
  unrelated write/read types or every possible codec combination**.

The native aliases in `declarations.py.txt` expose existing Attr coordinates;
production aliases are unchanged. Ordinary current default helpers still tie
input/read coordinates together: the generated-default tracer failed even after
changing the aliases. A small, unimplemented research Text field specifier supplies
precise separate-domain returns for a limited subset of the B/C cases. It uses registered
functions and explicit Python defaults, not callable intersections or generated
constructors. Its bodies raise and are never executed.

### What should omitted nullable= mean?

Keep this separate from whether an explicit option is authoritative:

- **Infer when omitted, explicit override wins:** preserves current concise
  declarations and minimizes accidental schema changes. The annotation still
  provides a default, not an invariant. A split-domain design must decide which
  domain supplies that default; read-domain inference is a candidate, not chosen.
- **Schema-only default, e.g. NOT NULL unless nullable=True:** maximally separates
  schema intent but breaks the SQL meaning of existing optional annotations with
  no flag. Requires an explicit compatibility/migration decision. No silent switch
  is authorized.

Neither choice makes nullable= a constructor omission policy.

## How this relates to required=True

There are at least four independent questions:

| Question | Example answer |
| --- | --- |
| Must the constructor keyword be present? | Yes, even if the supplied value is None. |
| Does the input domain contain None? | No, even though a SQL default can supply NULL. |
| Can a successfully decoded Row contain None? | Yes, because another writer stores NULL. |
| May the physical column store SQL NULL? | Yes, independently of the application's subset. |

Generation adds a further distinction: a pending marker is neither a nullable
value nor a guarantee that a declared source will generate a value.

A uniform constructor policy could eventually make an explicit required-input
option meaningful throughout a redesigned interface. But that would have to be
valuable on its own terms. Merely giving nullable= an independent SQL meaning
**does not rehabilitate the rejected standalone required=True trade-off**. Avoid
reusing required to mean both input presence and NOT NULL, or making nullable=True
silently synthesize a Python None default. Both would reintroduce coupling.

The ideal declaration and the available checker mechanism are separate questions.
These probes do not establish that annotation-sensitive omission is impossible;
they also do not establish that it has become possible.

## Native static evidence

`tests/research/test_nullability_declarations.py`: nine scenarios, each
on SQLite and MariaDB, **18 independently clean positive/challenge pairs**.
The exact paired runner is copied from the defaults research at `851a644`, without
importing its historical experiments. Temporary source/modules are checked, never
executed. Public input/read values and constructors are not erased to Any; the
Attr class-expression placeholder and hidden overload implementation use the same
research conventions as the earlier experiments.

1. Current required nullable, Python defaults/factory, SQL literal/NULL defaults,
   and required GenCol distinguish omission from None; exact lifecycle types.
2. Current explicit schema flags do not operate on native constructor/Row types;
   accepted static gaps are recorded rather than counted as declarations rejected.
3. Two-domain defaultless fields: strict str inputs/Pending, nullable Row, required
   keyword, bad inputs and frozen fields. Initial single-domain alias failed the
   nullable-Row assertion; the separate coordinates passed.
4. Two-domain generated overrides: explicit pending default grants omission,
   concrete/sentinel inputs work, None is rejected, Row is nullable and frozen,
   direct Row construction is rejected. Current single-domain and marker producers
   failed before the dedicated typed producer was added.
5. Python values/factories stay in the input domain; SQL DEFAULT NULL can be in the
   broader Row domain. Required SQL fallback remains required without an extra
   flag. Wrong Python None default and wrong defaulted SQL type are rejected.
6. Imported factories/models preserve constructor and lifecycle types, scalar and
   model read results, raw object widening, RETURNING Row results and whole-model
   left-join optionality. No query is executed.
7. One-argument research aliases retain equal input/read domains and required
   defaultless GenCol; current marker helpers do not implement domain separation.
8. **Accepted prototype gaps:** required/no-Python-default registered calls can
   hide incompatible SQL types and an unrelated read-domain mismatch. They still require
   input and reject None/wrong inputs. Nullable input admits a Python None default;
   factories requiring arguments are rejected with exact diagnostics.
9. The same producer surface supports a non-null strict-subset read domain with
   nullable schema and Python/SQL defaults. Initially forcing read nullability
   from the flag failed; independent return coordinates passed. Automatic NULL
   generation into a non-null read domain is rejected by this narrow prototype.
   It also **over-rejects a valid schema-only NULL fallback with a non-null
   Python default** under the strict-subset policy. That is a limitation of these
   overloads, not inherent incoherence or an impossibility result. Future SQL NULL
   decoding failure remains an implementation obligation.

These are not full constructor/backend acceptance or producer implementation
conformance. In particular, the research Text overloads cover only nullable=True
and a narrow server-literal surface, not clocks, identity options, FK declarations,
dynamic flags, every storage type, codec or inheritance pattern. No complete guarantee that producer returns/defaults match the annotated read
domain is justified: the accepted required-path gap is a counterexample. A
nullable schema need not force a nullable read domain; the final tracer proves
that those can remain independent in the same native producer surface.

## Runtime obligations and compatibility

Before selecting or implementing any change:

- Distinguish schema-only defaults for other writers from generation requested
  by this application. A strict-subset application may legitimately describe a
  physical SQL DEFAULT NULL yet reject NULL rows written by others. That is not
  the same as promising that its own omitted generated field will materialize
  successfully as a non-null value. Do not blanket-reject every fallback outside
  an application subset, or treat automatic generation as universally safe.
- Preserve omission versus explicit NULL; Python default=None is not SQL DEFAULT
  NULL, and SQL DEFAULT NULL is not a Python None default. Bound non-null inputs
  override SQL defaults. Identity remains separate from DEFAULT.
- Separate physical NULL permission from logical input/read acceptance in every
  validated NULL path. Pydantic validation is currently bypassed for None in
  important paths; generic validators/serializers must not be executed merely to
  guess nullability at declaration time.
- Separate construction validation from materialization/complete validation if
  domains differ. `_extract_logical_type` currently takes the last alias argument;
  adding an argument alone would not establish separate validation policies.
- Decide whether logical None against SQL NOT NULL is invalid, is rejected before
  writing as a refinement, or has an explicit transformation. Without a transform,
  the current encoder emits SQL NULL; a required flag cannot make that safe.
- Preserve query-induced nullability separately from stored NULL. Whole-model
  LEFT JOIN returns an optional right Row. Projected LEFT JOIN remains unsupported;
  this work does not redesign it. Scalar subqueries/aggregates have their own
  nullable output contracts.
- Keep schema nullability in join-presence planning: `SourceRowShape.for_source`
  uses physical nullable columns to add a witness distinguishing a matched
  all-NULL row from an absent right row. Do not replace all flag consumers with
  input/read None membership.
- Preserve key and relationship rules: nullable FK values differ from absent
  related rows; `SET NULL` requires nullable non-PK local columns
  (`snekql/model.py:656–660`). Strict-subset reads can intentionally fail after
  SET NULL; accepting such rows needs a nullable read domain. New FK overloads
  and target/read compatibility remain unproven. Closed #236 documents why
  required nullable FKs must remain expressible.
- Respect backend-specific PK/catalog normalization: SQLite's STRICT integer-rowid
  alias differs from other/composite PKs, while MariaDB PK parts enforce NOT NULL.
  Catalog nullable metadata is not permission for Python None nor proof of a
  nullable Row. No broad nullable-primary-key policy is selected.
- Keep JSON null distinct from SQL NULL. Wire text `"null"` reaches JSON parsing;
  raw driver None takes the SQL NULL path. The present encoder short-circuits
  Python None to SQL NULL before JSON serialization. Do not assume a nullable
  logical JSON domain can be stored as non-NULL JSON null without a representation
  and codec decision. Nested nullable payload members do not make a column nullable.
- Scaffold and verification must consume the same declared physical policy and
  continue to distinguish backend catalog limits. MariaDB may normalize implicit
  and explicit NULL defaults; structural verification is not data validation.
- Retain alias/Annotated/postponed/unresolved annotation behavior and immutable
  metadata. Do not silently reinterpret existing default=False, optional fields,
  nullable= assertions, or old generated declarations. Existing schema changes
  require explicit human-owned migrations, never automatic ALTER.

## First-pass recommendation and next decision

**Explore B as the smallest independent-schema improvement; pursue C only if
strict input plus nullable successful reads is an important requirement.** B's
partial decoding is legitimate, not a typing lie, provided incompatible NULLs
raise rather than leak into a non-null Row. C is justified when rejecting such
rows is not acceptable. Neither should be selected merely to keep the intersection
workaround alive.

The useful maintainer question is: for a nullable brownfield column, do you want
NULL to be **invalid application data that fails materialization**, or a **valid
read result even though Python constructors should reject None**? Those are
both coherent policies and could coexist per field; the question is which should
have first-class support and how much declaration complexity is justified. This research
establishes the distinction and a narrow native typing witness, not a final answer.

## Reproduce locally

```sh
uv run snektest tests/research
uv run ty check
uv run ruff check .
uv run ruff format --check .
git diff --check
```

The latest completed local batch passed 18 paired tests in 2.68 seconds on CPython
3.15.0 and ty 0.0.84. No runtime/backend suite or GitHub Actions is used.
