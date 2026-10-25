# Python on the left, SQL on the right

Research for #473, 2026-10-26, continuing from `cedd4a9`.
Environment: CPython 3.15.0, ty 0.0.84, snekql 0.9.0.
This is a **static-only feasibility prototype**, not an accepted interface or a
production implementation. No dependency changes or database runtime tests.

## Goal

Separate the declaration by responsibility:

- Left of `=`: Python field type, permission to hold a pending value, construction
  defaults and factories.
- Right of `=`: physical storage, SQL defaults, identity generation and constraints.

Illustrative source (the helper spellings are not existing exports):

```python
quantity: db.Col[int] = Integer()
done: Annotated[db.Col[bool], Default(False)] = Integer()
token: Annotated[db.Col[str], Factory(make_token)] = Text()

id: Annotated[db.GenCol[int], Default(db.PENDING_GENERATION)] = Integer(
    primary_key=True, auto_increment=True
)

server_done: Annotated[db.GenCol[bool], Default(db.PENDING_GENERATION)] = Integer(
    server_default=False
)

created_at: Annotated[db.GenCol[db.UtcDatetime], Default(db.PENDING_GENERATION)] = Text(
    server_default=db.CurrentTimestamp
)
```

The prototypes use local SQL-only `Integer` and `Text` signatures and a
research-only Model metaclass registering them. Logical types and lifecycle
states are the actual backend `Col`, `GenCol`, `Pending` and `Row` types.

The verbose `Annotated` spelling is a test vehicle, not a recommendation about
final shorthand. Arbitrary constructed Python values are expressible: a UUID
instance default and `uuid4` factory are included, not just literal type arguments.

## Native ty results

| Attempt | Result |
| --- | --- |
| `Annotated[Col[bool], Default(False)] = Integer()` | Construction still requires the field |
| Metadata containing `dataclasses.field(default=False)` | Same result, even with the helper registered |
| Metadata containing Pydantic `Field(default=False)` | Same result, even with the helper registered |
| Unregister the SQL declaration functions | Omission works, but required fields become optional too |
| Let RHS `Integer(default=False)` mean SQL DEFAULT | Native field-specifier handling incorrectly treats it as a Python construction default |

Metadata does not give native ty the required constructor-default information
in these experiments. Making all fields optional is not an acceptable workaround.
This is evidence about these strategies and this checker, not a proof that no
other native typing design can exist.

The SQL declaration signatures have independent write/read type parameters:
a SQL default does not force a pending Python shape. Their typed overloads do
not return Any to consumers. A field-specifier call with a nonstandard
`server_default` argument can nevertheless hide a mismatched declaration value
in native checking. Constructor signatures alone do not close that hole either.

## Working route: generate typing evidence from the declaration

`annotation_signatures.typing_overlay(source)` parses the source with `ast` and
emits a temporary typing projection. It does not import or evaluate that source,
its annotations, its default expressions, or its factories.

For each model it adds a type-checking-only constructor, conceptually:

```python
if TYPE_CHECKING:

    def __init__(
        self: Entry[db.Pending],
        *,
        quantity: int,
        required_generated: int | db.PENDING_GENERATION,
        done: bool = ...,
        id: int | db.PENDING_GENERATION = ...,
    ) -> None: ...
```

No caller-maintained duplicate signature, cast, loose `**kwargs`, or disabled
checker rule is used. The generated signature comes from the left-hand field
annotation. An explicit stub-body constructor prevents dataclass-transform
inference from confusing SQL defaults with Python construction defaults.

The projection also emits typed checks for **both halves**:

- `Default(value)` is checked against the Python field's allowed input type.
- `Factory(callback)` is checked against `Callable[[], InputType]`, without
  invoking it.
- The SQL declaration expression is checked against its declared column type
  outside the special field-specifier context. This catches mismatched SQL
  literal and clock defaults that the class-body call alone can miss.

All generated checks are under `TYPE_CHECKING`. Source comments in challenge
fixtures attach expected diagnostic markers to generated checks; comments do
not determine whether the checks are emitted or what types they check. The
invalid-default challenges have separately regenerated positive controls with
corrected default/factory/SQL values and all validation checks still present.

The tests check generated model code itself, same-module consumers, and a
separate importing consumer. Imported models retain exact constructor and query
result types. This is a working typing projection, **not** a claim that ordinary
ty can now understand the unmodified source.

## Decisions remain independent

These are all meaningful declarations in the split prototype:

```python
# Required Python input, despite a database default for omitted SQL writes.
required: db.Col[bool] = Integer(server_default=False)

# Explicit value or explicit pending sentinel required from the caller.
required_generated: db.GenCol[int] = Integer(server_default=7)

# Omission during Python construction supplies a pending sentinel.
omittable_generated: Annotated[db.GenCol[int], Default(db.PENDING_GENERATION)] = (
    Integer(server_default=7)
)

# Python construction and SQL omission have independent defaults.
label: Annotated[db.Col[str], Default("python")] = Text(server_default="database")
```

Thus `GenCol` does not imply a Python default, and the existence of a SQL default
does not imply `GenCol`. An ordinary `Col` can have a SQL default while Python
always supplies a concrete value. Coexistence falls out of the separation; no
upfront policy enabling or forbidding it was imposed.

The consumer examples also distinguish nullable-but-required input, an explicit
Python None default, a pending nullable value, and a SQL NULL default. They
preserve concrete Python factory values versus unresolved database values.

Both `server_default=` and a SQL-only `default=` spelling pass the full split
consumer when checked through the projection. The latter is **not** selected:
changing today's `default=False` into SQL DEFAULT would be a breaking semantic
change and must not happen silently. Compatibility policy remains open.

## Static guarantees exercised

On both backend namespaces:

- Required inputs remain required, including `GenCol` without a Python default.
- Only left-hand `Default`/`Factory` metadata makes construction omittable.
- Wrong constructor values, invalid None, and a sentinel supplied to a plain
  `Col` field are rejected.
- Default and factory result types are checked, including a pending sentinel
  used as a default on an incompatible plain `Col`.
- Mismatched SQL literal and clock types are rejected by projection checks.
- Pending fields and Row fields retain exact types; generated fields lose the
  sentinel only in Row types.
- Pending-only construction, frozen field assignment checks and exact INSERT
  RETURNING result types are retained.
- Constructed UUID defaults, UUID factories, nullable values, database clocks,
  literal defaults, identity declarations, and independent defaults are covered.

These are compile-time observations. No generated model is executed. There is
no claim about actual INSERT omission, DDL, verification, factory invocation
frequency, default evaluation timing, or runtime lowering.

## What it costs / what is not solved

The working route requires generated typing information. Two possible integration
paths would be a checker workflow using fresh source projections, or generated
`TYPE_CHECKING` regions in model modules. Neither production workflow is built.
Editor integration, regeneration/staleness detection and diagnostics mapped back
to original source locations are unresolved costs. The current harness reports
diagnostics against the temporary projection, not an original-source map.

The parser is intentionally narrow: explicit top-level, single-state models with
a direct `LeftModel` base, explicit `Col`/`GenCol`, and at most one explicit
`Default` or `Factory` marker. It rejects the tested unsupported cases rather
than silently generating partial constructors: local/inherited models, custom
constructors, conditional fields, wrapper annotation aliases, extra model type
parameters, missing SQL declarations, conflicting Python defaults, and a field
named `self`. It is not a full alias/import resolver or a production compiler.
No foreign-key, decorator-heavy, inheritance, or complete storage surface is
certified by these examples.

If fresh generated typing information is not an acceptable user-facing cost,
this experiment is **not yet a solution**. We would need another design or native
checker support for the annotation metadata. Separately, the verbose annotation
spelling still needs a human-readability comparison.

## Files and reproduction

- `annotation_signatures.py`: research-only AST-to-typing projection.
- `left_declarations.py.txt`: typed metadata and SQL declaration signatures.
- `left_*.py.txt`: consumer and invalid-default examples.
- `tests/research/test_left_defaults.py`: native controls, generated-source
  consumers, imported consumer, and unsupported-syntax tests.

```sh
uv run snektest tests/research
uv run ty check
uv run ruff check .
uv run ruff format --check .
```

**80 tests pass**: 70 static positive/challenge pairs (42 previous, 28 this round)
and 10 in-memory parser rejection tests. The focused suite takes approximately
11 seconds locally. Some static pairs intentionally record failed native
strategies; the count does not mean all investigated strategies work. No SQL
runtime suite is run.
