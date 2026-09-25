# Backend-owned dual declarations

Local follow-up to issue #396. Baseline main: `56dbc32`.
Production is unchanged; nothing in this study is published or committed.

## Answer

The tested backend witnesses can remain private. Application models need neither
lifecycle generics nor an explicit backend parameter, and their fields can use
ordinary `Integer()`, `Text()`, and `Json()` constructors.

The bounded interface also preserves typed MariaDB JSON operations, rejects mixed
backend operations, and closes the earlier join-owner inference hole for its
class-source interface. Exact typing is checked against the executed Python
implementation, not an idealized stub.

This is not a complete backend facade. It deliberately implements a small set of
constructors, SELECT/model/scalar reads, explicit joins, and INSERT with optional
RETURNING. It does not establish full production query compatibility.

## Read and run

- [examples.py](examples.py): SQLite account/entry and MariaDB document models.
- [sqlite.py](sqlite.py), [mariadb.py](mariadb.py): public research namespaces.
- [core.py](core.py): private family/scope witnesses, descriptors, and execution.
- [tour.py](tour.py): SQLite application with a result-only query helper.
- [test_mariadb.py](test_mariadb.py): actual JSON projections and INSERT RETURNING.
- [options.py](options.py): retained generic-self counterexample.

```sh
bash scratchpad/dual_backends/run.sh
# SQLite only:
uv run python -m scratchpad.dual_backends.tour
```

The tour prints `['hello']`. The full runner requires the existing MariaDB tools
and drivers. Its temporary server uses `.git/dual-backends/mariadb` and a local
Unix socket without TCP listening.

## Ordinary declarations

```python
class NewAccount(sqlite.Input):
    id: sqlite.Field[int | sqlite.Omitted] = sqlite.Integer(
        primary_key=True, auto_increment=True, default=sqlite.OMIT
    )
    name: sqlite.Field[str] = sqlite.Text()


class Account(NewAccount, sqlite.Model):
    table_name = "accounts"
    id: sqlite.Field[int] = sqlite.required()
    create = sqlite.insert_using(NewAccount)
```

The constructor wrapper captures native storage facts; it does not implement
another codec. The inherited shared declaration finalizer still creates native
models and retains their descriptors, validation, schema checks, and runtime.

`NewAccount(name="Ada")` can omit the ID. `Account(name="Ada")` is rejected.
`Account.create(name="Ada")` captures the input signature and returns a typed write
command. Commands do not execute themselves.

Namespaces own the constructors and descriptor annotations. A SQLite field
initialized by MariaDB's `Integer()` rejects statically. A fully MariaDB-annotated
field placed inside a SQLite input still type-checks; declaration guards reject
that inconsistent class. Python's class body does not impose the base class's
backend on every annotation.

`Input` and `Model` are study names, not a final naming recommendation. Constructor
options are a subset of main's options. Adding an option should delegate to its
native constructor, not duplicate native storage policy.

## Native JSON stays typed

```python
class NewDocument(mariadb.Input):
    id: mariadb.Field[int | mariadb.Omitted] = mariadb.Integer(
        primary_key=True, auto_increment=True, default=mariadb.OMIT
    )
    payload: mariadb.JsonField[dict[str, int]] = mariadb.Json(default_factory=dict)


class Document(NewDocument, mariadb.Model):
    table_name = "documents"
    id: mariadb.Field[int] = mariadb.required()
    create = mariadb.insert_using(NewDocument)
```

These expressions have exact types:

```python
Document.payload  # JsonColumn["mariadb", Document, dict[str, int]]
Document.payload.json_extract_int("$.answer")  # Scalar[..., int | None]
```

Actual MariaDB execution inserted `{"answer": 42}` and `{}`, then fetched
`[42, None]`. The missing JSON path remains nullable. INSERT RETURNING also
materialized a `Document` with an integer generated ID and dictionary payload.

A `JsonField` refinement keeps the specialized descriptor. Plain `Field[dict]`
can use JSON storage but does not statically expose JSON-specific operations. This
matches the reason main has `JsonCol`; dual classes do not remove that distinction.

An attempted native JSON `LiteralDefault('{}')` hit main's existing restriction
that literal defaults require ordinary integer, Boolean, or text storage. The
positive refinement test uses a client factory, rather than bypassing that rule.

## Family propagation

The private backend coordinate continues through:

- Field and foreign-column declarations.
- Class sources and scalar projections.
- Queries, joins, and predicate consumption.
- Schema scaffold inputs.
- Input-constructor bindings and INSERT commands.
- RETURNING results and active transaction adapters.
- Result-only query helpers.

The static probes reject SQLite consumption of a MariaDB model, column, JSON
projection, join source, SELECT, INSERT, RETURNING command, scaffold input, input
factory, and native transaction wrapper.

Runtime checks reject erased mixed-family operations too. The schema and native
runtime retain their own backend checks; frontend witnesses are not a substitute
for them.

A bare mixed-family predicate combination remains an accepted static
counterexample because this adapter inherits the previous predicate interface.
Its runtime operator rejects the combination, and consuming it in a SQLite query
also rejects statically. Do not describe every expression-composition operation as
fully backend-checked at its call site.

## Source witnesses and class-only selection

The chosen model marker returns an invariant witness:

```python
@classmethod
def __table_source__(cls) -> Source[Literal["sqlite"], Self]:
    return Source("sqlite", cls)
```

The witness fixes both family and model identity. The query accepts
`type[Table[Family, Row]]`, not a bare `type[Row]` whose type variable can widen to
include an unavailable predicate owner.

The independently checked alternative is:

```python
@classmethod
def __table_source__[Row](cls: type[Row]) -> Source[Literal["sqlite"], Row]:
    return Source("sqlite", cls)
```

That generic-self spelling still accepts the tested extra-owner join. The `Self`
spelling rejects it while preserving exact positive join result types. The
alternative is retained in `options.py`; Ruff's automatic rewrite to `Self` is
disabled there because it changes the observation.

Using `type[Protocol]` also rejects a fetched instance passed where a model class
is expected. Input classes and their columns are not selectable.

This proof covers class sources. Aliases, nullable occurrences, CTE roles, and
other source kinds need their own invariant witnesses. Do not erase those
coordinates by pretending every source is a plain model class.

## A metadata typing leak mattered

The first attempt still accepted `sqlite.select(NewAccount)` with an Unknown
result. Its class matched the scalar-selection protocol through the inherited
metaclass's `__getattribute__ -> Any`.

Changing that hook to return `object` removed the accidental protocol match.
Declared field types still infer exactly. Runtime binding can remain erased
internally without making every missing class attribute look like a valid method.

Two small changes to the previous finalization adapter support this study:

1. The metaclass lookup return is `object`, not Any.
2. Foreign annotation checks recognize descriptor subclasses and locate the target
   argument independently of an extra private family coordinate.

The earlier finalization tests and typing observations are rerun after these
changes. No production implementation changed.

## Helpers keep family and readiness

```python
def account_names() -> sqlite.Select[str]:
    return sqlite.select(Account.name).all()
```

`sqlite.Select[Result]` hides source coordinates without hiding family or readiness.
It permits transaction consumption and SQL inspection. It deliberately does not
expose scope-changing query methods after those coordinates have been hidden.

The probes reject an unscoped query returned as `sqlite.Select[Account]`, a
MariaDB query returned as `sqlite.Select[Document]`, and an attempt to apply an
unrelated WHERE through a result-only helper.

This avoids returning `Query[..., Any, ...]` and then accidentally allowing callers
to add unchecked predicates. No `.into()` or Python result-mapping helper is needed.

## Actual execution and a caught adapter bug

The SQLite tests execute model/scalar selection, explicit FK joins, generated
foreign defaults, input commands, RETURNING, and result-only helpers. MariaDB tests
execute native JSON projections and model RETURNING.

The first model-join adapter raised `IndexError` during native materialization.
Rebuilding a native model-select query after a join allowed native result-shape
rules to count joined models while the adapter promised only the original model.
The adapter now uses explicit column projections and constructs the promised
Fetched Model from those values. The selected result stays stable across a join.

That behavior is disclosed: main's default model joins can append model results.
This thin adapter is not proposed as a drop-in replacement for main's query
interface.

## Remaining limits

- Only representative constructors are implemented. Many native type options and
  backend-specific types remain outside this namespace experiment.
- Default-value domains and some field refinements can still pass ty and fail
  runtime validation. `required()` remains an erased field-specifier marker.
- Inconsistent input-base/fetched-marker combinations and fully foreign field
  annotations need runtime declaration checks.
- Foreign target identity and physical candidate-key validity remain separate.
  Generated FK typing and real SQLite default insertion work, but this study is
  not an exhaustive FK/nullability/backend matrix.
- No alias/outer-join, CTE, grouping, multi-slot projection, UPDATE, conflict, or
  complete expression-extension interface is implemented here.
- Native lowering and execution still use Any and private helpers. The two backend
  transaction adapters wrap real active transactions; they do not own or replace
  native transaction lifetime, cancellation, or commit behavior.
- The inherited Record hook does not cooperate with Generic initialization. The
  research generic input base places Generic first to initialize its parameters.
  A production implementation should fix that hook rather than retain the workaround.
- No performance or full framework-integration claim is made.

## Recommendation

Backend-owned dual declarations remain viable without exposing lifecycle or backend
generics to model authors. Retain native constructors and specialized descriptor
annotations where they carry real operations.

For query integration, preserve invariant occurrence witnesses and exact `Self`
binding. Keep result-only helpers ready and terminal for further query mutation.
Avoid Any-returning metadata hooks that can make nonexistent methods satisfy
structural interfaces.

The next substantial query question is whether the same guarantees survive aliases
and nullable occurrences with the existing production conventions. This study does
not settle that by assuming a model-class witness covers every source.

## Evidence

- **54 isolated typing observations:** 32 rejections, 15 capabilities, six accepted
  counterexamples, one unsupported case.
- Controls are checked separately. Expected diagnostics must occur on challenge
  lines; checker failures and unrelated errors do not count as rejections.
- `results.json` records actual diagnostics and hashes of the executed interface,
  namespace files, alternative, and shared finalizer.
- Logs under `.git/dual-backends/` preserve the failed input-source check,
  constructor-hook failure, join materialization failure, and runtime red tests.
- Python 3.14.2, ty 0.0.77, MariaDB 12.3.2. No new dependencies.

Final validation:

- **22 research tests pass**, including three actual MariaDB cases.
- **1,127 existing fast tests pass**.
- Earlier research passes: **33 + 57 + 123 + 60 + 158 + 91 typing observations**
  and **31 + 58 + 42 + 24 + 53 + 41 runtime/construction tests**.
- Repository ty, Ruff lint/format, and diff checks pass. **558 files formatted**.
- No full repository integration suite or performance suite was run.

Work remains local and uncommitted. The only shared-adapter edits are the two
finalizer changes described above; production files are unchanged.
