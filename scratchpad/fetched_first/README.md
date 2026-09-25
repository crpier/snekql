# Fetched-first nesting

Local research on `research/fetched-first-nesting`, from main `56dbc32`.
Related [research issue #396](https://github.com/crpier/snekql/issues/396) remains
closed. Production and earlier implementations are unchanged. Nothing committed
or published; no dependency or checker-plugin additions.

## Verdict

**Yes: `User` can own all storage declarations and represent complete rows, while
`User.Pending(...)` constructs a separate input.** Actual SQLite INSERT/RETURNING
and SELECT infer exactly `User`, not a generic specialization or Any.

Two variants work, with different costs:

| | Explicit outward annotation | Owner-bound constructor |
|---|---|---|
| Row name / query source | `User` | `User` |
| Construction spelling | `User.Pending(email=...)` | `User.Pending(email=...)` |
| Extra row link | `__row__: ClassVar[type[User]]` | None |
| Construction result | Ordinary `User.Pending` instance | Typed `PendingValue` wrapper |
| Read input field | `pending.email` | `pending.value.email` |
| Name input type | `User.Pending` | Wrapper type; `User.Pending` is a factory, not a type |
| INSERT result | `User` | `User` |
| Pending is a User subtype | No | Neither wrapper nor wrapped input is |

Both repeat **all input field annotations**, never SQL storage options. Both avoid
quoted class-base references, future imports, and special unused-import allowances.
The explicit annotation still refers to the enclosing User. Python 3.14 defers
that ordinary annotation; it is not an eager base expression.

My preference for further review is the explicit-link version. Its extra line is
less surprising than making a declared nested class turn into a factory and
requiring `.value` for field access. The no-link version is still meaningful
positive evidence: automatic owner inference is possible here if that different
construction result is acceptable.

## Start here

- [examples.py](examples.py): normal nested class with an outward annotation.
- [bound_examples.py](bound_examples.py): no-link, owner-bound constructor.
- [tour.py](tour.py): the application calls against disposable SQLite databases.
- [sqlite.py](sqlite.py): shared declaration binding and explicit-link insertion.
- [bound.py](bound.py): class-descriptor factory and typed wrapper.
- [cases.json](cases.json) / [results.json](results.json): independent ty callers.
- [navigation.json](navigation.json): actual ty go-to-definition evidence.

```sh
bash scratchpad/fetched_first/run.sh
# Application usage only:
uv run python -m scratchpad.fetched_first.tour
```

These are experimental namespaces, not released snekql interfaces.

## A. Ordinary nested input class

```python
from typing import ClassVar
from scratchpad.fetched_first import sqlite


class User(sqlite.Row):
    table_name = "users"
    id: sqlite.Field[int] = sqlite.Integer(primary_key=True, auto_increment=True)
    email: sqlite.Field[str] = sqlite.Text(unique=True)

    class Pending(sqlite.Pending):
        __row__: ClassVar[type[User]]
        id: sqlite.Field[int | sqlite.Omitted] = sqlite.omitted()
        email: sqlite.Field[str]
```

Usage:

```python
pending: User.Pending = User.Pending(email="ada@example.com")
user: User = await transaction.execute(sqlite.insert(pending).returning())
users: list[User] = await transaction.fetch_all(sqlite.select(User).all())
```

No explicit destination argument, no factory callback, no handwritten constructor
overloads, and no generated application source. Storage options are on the short
row name, so navigation goes to the declaration the user needs most often.

`User(id=1, email="A")` constructs a complete value. `User(email="A")` is rejected
by ty and by runtime validation after erasure. A database-supplied value is still
required on a row constructor. Only the nested input can omit a generated value.
Complete construction is not evidence that the row exists in the database.

An ordinary helper works without state parameters:

```python
def identifier(user: User) -> int:
    return user.id
```

Passing `User.Pending(...)` is rejected. The input does not inherit User, so this
is not the unsafe row-first inheritance previously tested. Conversely, User is
not a User.Pending either. INSERT accepts the pending contract; queries accept
the row and its columns.

### Why the outward annotation remains

Nesting tells the runtime where the input belongs, but a bare input class does not
automatically expose that association to a generic `insert` function. The class
attribute is the tested static witness. Runtime binding validates that it names
exactly the enclosing row, then publishes the actual class value.

The ordinary annotation resolves for both module-level and function-local rows.
The library installs no user callback and does no database work during binding.
`Self` inside the nested class names the input, not its enclosing row; that
control fails insertion typing rather than providing the desired mapping.

## B. No outward annotation, but a different construction result

[bound_examples.py](bound_examples.py) uses the same declaration except for:

```python
from scratchpad.fetched_first import bound as sqlite


# ...same User storage declarations...
class Pending(sqlite.Pending):
    id: sqlite.Field[int | sqlite.Omitted] = sqlite.omitted()
    email: sqlite.Field[str]
```

That Pending block lives inside User. It contains no `User` reference.

A descriptor on the pending class's **metaclass** receives the enclosing row when
Python evaluates `User.Pending`. It returns an owner-bound factory. ParamSpec
preserves the input constructor's required keywords and value types, while the
factory carries the row type into its returned wrapper.

```python
pending = User.Pending(email="ada@example.com")
# pending.row: type[User]
# pending.value.email: str
# pending.value.id: int | Omitted

user = await transaction.execute(sqlite.insert(pending).returning())
# Exactly User.
```

The wrapper contains an ordinary validated input instance and the known row.
It does not run SQL or replace transaction ownership. Actual returned rows remain
ordinary User objects. Their field access has no wrapper.

### The cost is observable

This is not a drop-in replacement for an ordinary nested class:

- `pending.email` is rejected; use `pending.value.email`.
- `pending: User.Pending` is rejected because User.Pending is a factory value.
- Helpers that only insert can accept a suitably parameterized `PendingValue`.
  A tested generic helper preserves the row type, but this is less convenient
  than naming an ordinary nested input class.
- The raw constructor is available through the factory, but its raw result does
  not carry the static owner association. A runtime-only insertion control
  returns the right User at runtime but has Any as its static result.
- The wrapper's public constructor admits mismatched owner/input combinations
  statically. INSERT validates the relationship and rejects a forged destination
  at runtime. This is retained as an accepted counterexample.

There is no claim that metaclass descriptors, ParamSpec, or this wrapper preserve
all framework introspection, serialization, inheritance, or editor behaviors.
Only the installed ty and the reported cases were tested.

## Storage, defaults, and SQL

The outer Row owns the authoritative Column Types and complete Logical Types.
The inner Pending repeats annotations and may change Python constructor defaults.

The binding reuses previous row-first validation and creates private value
contracts. It does not author a second physical schema. Runtime metadata copies
are not being counted as static constructor synthesis: the explicit input
annotations are what supply checked fields and constructors to ty.

Examples include UserSettings with:

- A field-local FK to `User.id`, also the settings primary key.
- A required timezone.
- A database default of 9 for `digest_hour`.
- Pending omission for digest_hour, while the row constructor requires it.

The explicit-link tests execute INSERT/RETURNING, model SELECT, scalar FK joins,
and a settings upsert preserving an unlisted digest value of 18. A first insert
materializes the SQL default of 9. The no-link variant executes INSERT/RETURNING,
model SELECT, and an FK join.

Both variants reuse the earlier research Database/Transaction adapter and native
storage, validation, codecs, compilation, and transaction runtime. This is not a
second SQL engine, nor proof of complete native query-interface parity.

## Declaration and runtime guards

Binding rejects missing input fields, changed logical types, changed FK targets,
new storage declarations on Pending, and omission of nongenerated fields. The
explicit variant also rejects a missing or wrong outward witness.

These cross-class declaration relationships are not all statically proven.
Accepted invalid declarations are retained in the matrix and reject at runtime.

Bound metadata and public pairing attributes are frozen. Tests cover replacing
the row link, deleting the row link, and replacing the nested constructor. This
is ordinary API protection, not reflection security.

A detached pending declaration cannot construct values before a row binds it.
An initial AttributeError exposed that missing guard; it now raises a declaration
error. Constructor-default typing also needed care: treating `omitted()` as a
dataclass field specifier without a declared default parameter incorrectly made
the generated field required. The corrected descriptor convention is checked.

## Navigation

Four actual `ty server` definition requests verify the outer class and email
attribute for both variants. They land on the appropriate User in examples.py or
bound_examples.py. Those class bodies declare all storage fields, and the email
attribute resolves to its `Text(unique=True)` declaration.

This directly addresses the earlier input-first navigation problem. It is
language-server evidence, not a claim about every editor or nested factory
navigation behavior.

## Validation

- **48 typing observations:** 13 capabilities, 25 rejections, six accepted
  counterexamples, four unsupported contracts.
- **29 runtime tests**.
- Two consumer modules pass isolated Ruff F/UP037 checks without project import
  exceptions. The runner also rejects future imports and quoted base arguments.
- **1,127 existing fast tests** passed.
- Previous state-declaration regression: **52 observations / 26 tests**.
- Previous row-first regression: **43 observations / 24 tests**.
- Repository ty, Ruff lint/format, and tracked diff checks passed.

Typing results include checker version and source hashes. Each negative caller
has an independently clean control and diagnostics on its challenge lines.
Checker crashes, missing imports, and runtime failures do not count as static
rejections. Useful red and validation logs are under `.git/fetched-first-nesting/`.

## Scope still open

This establishes fetched-first naming, separate constructors, precise implicit
results, navigation, and representative SQLite execution. It does not establish
arbitrary inheritance, self/mutual FK resolution, specialized JSON/MariaDB fields,
shared instance-method conventions, comprehensive framework compatibility, full
integration, or performance. Rows and inputs remain separate nominal classes;
nesting alone does not share their instance methods.

The next design choice is therefore concrete: **one outward annotation and an
ordinary input class, or no outward annotation and an owner-bound wrapper**.
Neither choice requires the frequently used row to have the longer name.
