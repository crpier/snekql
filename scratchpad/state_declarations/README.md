# State declarations without quoted base arguments

Local research on `research/state-declarations`, from main `56dbc32`. Related
research issue [#396](https://github.com/crpier/snekql/issues/396) remains closed.
Production and earlier implementations are unchanged. No commits or publication.

## Question

Can a model avoid `Model[State, "User[Fetched]"]`, the associated Ruff unused-import
exception, and future imports, while keeping exact query results and the better
value-contract guarantees investigated with dual classes? State generics and
repeated field annotations are acceptable.

**Yes, with explicit tradeoffs.** Two declaration styles execute actual SQLite
queries and retain exact types. Neither needs a quoted base argument, a future
import, a checker plugin, or Ruff's `Fetched` import allowance.

1. **Keep `User[Pending]` / `User[Fetched]`.** Put the result witness in an ordinary
   class-body annotation. This moves the self-reference; it does not eliminate
   the need to name the fetched specialization. Stronger direct constructors
   additionally need explicit overloads and runtime specialization checks.
2. **Put a real `Fetched` class inside `User`.** Repeat complete field annotations
   there, inherit storage metadata through the library, and use `User.Fetched`.
   This eliminates the self-type link entirely, but changes the public spelling
   and retains two nominal value classes.

Plain Self and inherited generic-self controls did not infer the changed state.
Those failures are bounded evidence, not a proof that every possible interface
requires a per-model witness.

## Start here

- [examples.py](examples.py): generic User and UserSettings, including the actual
  constructor overloads. Native Column Types, queries, Database, and Transaction.
- [nested_example.py](nested_example.py): nested fetched contracts. Smallest useful
  example of the permitted field-annotation duplication.
- [tour.py](tour.py): both declaration styles inserting into disposable SQLite DBs.
- [options.py](options.py): native method-witness, missing-witness, and Self controls.
- [cases.json](cases.json) / [results.json](results.json): isolated typing evidence.
- [lint-results.json](lint-results.json): isolated Ruff checks without project allowances.

```sh
bash scratchpad/state_declarations/run.sh
# Application tour only:
uv run python -m scratchpad.state_declarations.tour
```

The prototype targets CPython 3.14 and the installed `ty`. Names in the experimental
modules are not released snekql interfaces.

## 1. A normal annotation can carry the generic result

The declaration header becomes:

```python
class User[State = Pending](Model[State]):
    __read_type__: ClassVar[ReadType[User[Fetched]]]
    # Storage fields and constructor signatures follow in examples.py.
```

`Model` and `ReadType` above come from this experiment. Column Types and state
markers still come from native snekql. The result annotation is not a field and
is not a constructor argument.

The tested operations retain the existing native query spelling:

```python
pending = User(email="ada@example.com")  # User[Pending]
row = await transaction.execute(native.insert(pending).returning())
# User[Fetched], with row.user_id: int

rows = await transaction.fetch_all(native.select(User).all())
# list[User[Fetched]]
```

The actual native runtime executes these commands. No replacement transaction
facade or SQL compiler is needed for this option. Native scalar projections,
field-local FK joins, and a settings upsert also execute. The upsert changes the
timezone while preserving unlisted generated digest/revision values.

### What moved, and what disappeared

Python 3.14 defers ordinary annotations. It does not defer class-base expressions.
Moving the result evidence into the body therefore avoids the quoted base and
makes the `Fetched` import visible to Ruff. The metaclass resolves the annotation
with the just-created class available and validates that it names that model's
Fetched specialization. A function-local declaration is tested too.

There is still a conceptual self-reference in `User[Fetched]`, and the library
uses annotationlib ForwardRef handling while the class name is being bound.
This is not a claim to eliminate all deferred name resolution. It eliminates the
specific application ceremony under discussion.

The library hides the old native result parameter as Any internally. A missing
or wrong witness is rejected at runtime rather than silently publishing that
fallback as a valid model. Exact assertions verify that application query results
do not become Any. Static checking alone does not prove witness identity: a
wrong model's fetched type is a retained accepted counterexample, rejected by the
metaclass at declaration time.

### A normal classmethod works too

The native method control instead declares:

```python
@classmethod
def __read_type__(cls) -> type[MethodUser[sqlite.Fetched]]:
    return MethodUser[sqlite.Fetched]
```

It also avoids quotes/future imports and preserves exact query inference, with
actual INSERT/RETURNING execution. It repeats the result type in the annotation
and body. It is a useful control, not a new recommendation to make every
application author implement a framework method.

### Constructor truth is a separate problem

The result witness does not fix generated constructor signatures. The method
control still allows this under `ty`:

```python
row = MethodUser[sqlite.Fetched](email="ada@example.com")
# row.id is statically int, but actually PENDING_GENERATION.
```

The original native declaration has the same fetched-constructor counterexample.
Successful INSERT/RETURNING inference must not be presented as fixing it.

The generic main example explicitly declares two `__init__` overloads. Pending
accepts omitted generated values; Fetched requires concrete values. The
implementation repeats the keyword parameters and delegates value validation to
native snekql. This is more repetition than the one-line result witness.

At runtime, a small specialization alias checks complete column presence,
rejects generation sentinels, invokes the existing constructor, checks that the
constructor did not discard a generated value, and then marks the value Fetched.
This is needed because static overloads alone do not enforce specialization at
runtime. Two independently generated settings fields are covered, not just an ID.

Direct `User[Fetched](...)` construction is checked both statically and after
erasure in the tested cases. A pending User is rejected by a helper requiring
User[Fetched]. A constructed fetched value is rejected by native INSERT. Fetched
here still does not prove that a database row exists.

**Remaining holes are explicit:**

- Inherited `User[Fetched].construct(...)` bypasses the alias's completeness check.
  The existing unvalidated constructor can still return an omitted generated
  value while its specialization promises an integer. Retained executable
  counterexample; not fixed by this study.
- `select(User[Fetched])` type-checks but the native query builder does not accept
  the specialization alias at runtime. The supported application spelling here
  is `select(User)`.
- Invalid state specialization can be expressed statically as a query source;
  runtime specialization rejects it. The explicit constructor overloads do reject
  construction in an invalid state.
- No general generic inheritance, extra type-parameter, framework-introspection,
  or serialization compatibility guarantee is claimed for the specialization alias.

## 2. Nested fetched contracts remove the self-type link

The other tested declaration is:

```python
class User(sqlite.Model):
    table_name = "nested_users"
    id: sqlite.Field[int | sqlite.Omitted] = sqlite.Integer(
        primary_key=True, auto_increment=True, default=sqlite.OMIT
    )
    email: sqlite.Field[str] = sqlite.Text(unique=True)

    class Fetched(sqlite.Fetched):
        id: sqlite.Field[int]
        email: sqlite.Field[str]
```

Here `sqlite` is the experimental nested namespace. Application calls are:

```python
pending = User(email="ada@example.com")
row = await transaction.execute(sqlite.insert(pending).returning())
# User.Fetched

rows = await transaction.fetch_all(sqlite.select(User.Fetched).all())
# list[User.Fetched]
```

The nested class itself supplies the static insertion result witness. There is
no quoted self-type, result base parameter, result annotation pointing back to
User, or pairing callback.

Storage constructors appear once, on User. Every fetched field repeats its
annotation, removing Omitted where needed. The enclosing declaration binds those
annotations to the same immutable storage declarations. Missing fields, changed
logical types, and restated storage are rejected at declaration time. Exact field
set/type agreement is a runtime guard, not a static guarantee.

The classes are nominally separate. User is not a User.Fetched, so the unsafe
row-first subtype relationship does not return. `ty` rejects incomplete inputs
where complete rows are required, missing generated values on fetched
construction, and using the input class or its columns as query sources.

Both constructors use existing descriptor/dataclass-transform machinery; no
manual constructor overloads or generated source file is needed. Real SQLite
insertion, row SELECT, and a field-local FK join through UserSettings.Fetched work.

This option uses the previous research metadata/transaction adapters over the
native runtime, unlike the directly native generic option. It is not yet a full
replacement for the native query interface. It also changes usage to
`User.Fetched`, requires repeated annotations for ordinary fields as well as
generated ones, and does not share instance methods by making the fetched class
a subtype of the input. Navigating to User shows both declarations; the nested
fetched body has annotations, with storage options on its enclosing User.

The frozen value/declaration machinery is reused. Broad nested inheritance,
mutual/self-FK declarations, specialized backend fields, and framework support
were not established here.

## Controls that did not remove the mapping requirement

- Hiding the result parameter with no concrete witness yields Any. An exact
  fetched-result assertion fails even though a runtime class can still exist.
- An inherited `__read_type__ -> type[Self]` preserves User[Pending]; it does not
  substitute Fetched into the concrete model.
- An inherited generic-self method constrained to Table[Fetched] still produced
  the pending specialization in the tested query calls.
- `Self[Fetched]` was accepted as an annotation by this checker, but the query
  result became Unknown and the exact fetched assertion failed. Annotation
  acceptance alone is not evidence of a working type transformation.

No checker crashes or unrelated import errors count as rejections. Generated
per-model query overloads and checker plugins were not added. A plugin-free
universal type-level state substitution has not been proved impossible.

## Lint and runtime import evidence

`lint.py` checks the consumer examples and controls with:

```sh
uv run ruff check --isolated --target-version py314 --select F,UP037 ...
```

It also rejects future imports and quoted type expressions in their class bases
by inspecting the source. All three consumer modules pass. A native quoted-base
control, without the repository allowance, reports exactly F401 for the Fetched
import. No F401/F821 suppression is used for the new examples.

The project already supports native models without future imports on Python
3.14, independently of this experiment. That is not a new feature introduced by
these declarations.

## Validation and limits

- **52 typing observations:** 17 capabilities, 20 rejections, 11 accepted
  counterexamples, four unsupported options.
- **26 runtime tests**, including both SQL paths and the retained constructor holes.
- **1,127 existing fast tests** passed.
- Previous row-first regression: **43 observations / 24 tests**.
- Previous pairing regression: **41 observations / 29 tests**.
- Repository ty, Ruff lint/format, and tracked diff checks passed.
- No MariaDB execution, full integration suite, or performance validation in this study.

Sources/checker versions and hashes are recorded in results.json. Useful red and
validation logs remain under `.git/state-declarations/`.

## What is worth reviewing

If retaining `User[Pending]` / `User[Fetched]` and the native query language is the
priority, the ordinary result annotation is the smallest demonstrated change.
Constructor strengthening should be reviewed separately; the explicit overloads
are verbose and the inherited construct escape still needs a policy.

If avoiding the self-link entirely and keeping constructor declarations simple
matters more, the nested fetched class is the more promising tested alternative.
It spends the allowed duplication on field annotations instead of constructor
overloads. No production design or declaration spelling is chosen by this study.
