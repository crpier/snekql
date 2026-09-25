# Class-body results in everyday application code

Local research on `research/class-body-usage`, from main `56dbc32`. Related
[research issue #396](https://github.com/crpier/snekql/issues/396) remains closed.
No production changes, commits, publication, dependencies, or checker plugins.
Fetched-first nesting remains a separate, paused research direction.

## Result

The class-body result declaration is a useful **declaration cleanup**. In the
paired application examples, fields, constructors, methods, DTOs, query bodies,
and concrete helper annotations remain identical. Native SQLite executes both.

The improvement is local to each model declaration:

```python
# Current.
class User[State = Pending](Model[State, "User[Fetched]"]):
    __tablename__ = "users"
    # Fields follow.


# Class-body result declaration.
class User[State = Pending](Model[State]):
    __read_type__: ClassVar[ReadType[User[Fetched]]]
    __tablename__ = "users"
    # Exactly the same fields follow.
```

The second Model and ReadType are research imports. ClassVar comes from typing;
Pending, Fetched, Column Types, query verbs, and the runtime remain native.

This removes the quoted result argument and makes the fetched result explicit in
an ordinary class-body annotation. It adds a line and two annotation names. It
moves the self-reference instead of eliminating it. It neither duplicates fields
nor introduces a second value class.

**One material compatibility exception:** generic helpers annotated against the
old `Model[State, Result]` base lose the result coordinate with this shim. Concrete
model helpers and result-typed query helpers retain their precision. See below.

## Review and run

- [current.py](current.py): original declarations and common application operations.
- [body.py](body.py): the same application with class-body results.
- [sqlite.py](sqlite.py): witness-only research Model. No constructor changes.
- [helpers.py](helpers.py): the generic-helper compatibility control.
- [tour.py](tour.py): runnable creation, reading, mutation, settings, and bulk usage.
- [comparison.json](comparison.json): source hashes and matching SQL/parameters.
- [cases.json](cases.json) / [results.json](results.json): independent ty callers.

```sh
bash scratchpad/class_body_usage/run.sh
uv run python -m scratchpad.class_body_usage.tour
```

The native Database and Transaction own all execution. This option needs no
research transaction wrapper, duplicate storage implementation, or SQL compiler.

## Common use cases

The examples have User, Post, and UserSettings. User includes generated identity
and timestamp columns, a nullable display name, and a client Boolean default.
Post and UserSettings declare field-local FKs. Settings has a database default
and an upsert that updates only the named editable column.

Every operation below has the **same spelling and result type before and after**
for the concrete models:

| Use | Result |
|---|---|
| `User(email=...)` | `User[Pending]` |
| `insert(user).returning()` | `User[Fetched]` |
| `fetch_all(select(User).all())` | `list[User[Fetched]]` |
| `fetch_one_or_none(select(User).where(...))` | `User[Fetched] \| None` |
| Scalar email projection | `list[str]` |
| ID/email projection | `list[tuple[int, str]]` |
| Field-local FK join selecting email | `list[str]` |
| `update(User)...returning()` | `list[User[Fetched]]` |
| `delete(Post)...returning()` | `list[Post[Fetched]]` |
| Settings INSERT with conflict update and RETURNING | `UserSettings[Fetched]` |
| Bulk INSERT with RETURNING | `list[User[Fetched]]` |

Write results in this table are the results of `transaction.execute(...)`, not
the query objects themselves. Query Readiness and Backend Family checks remain.

### Construct and insert

```python
pending = User(email="ada@example.com")
# User[Pending]; pending.user_id is int | PendingGeneration.

user = await transaction.execute(sqlite.insert(pending).returning())
# User[Fetched]; user.user_id is int.
```

No `.Pending`, `.Fetched`, `.create()`, constructor overload, or explicit insert
destination appears. Bare User still means the Pending specialization in value
annotations. This does not adopt fetched-first naming.

### Read through concrete application helpers

```python
async def fetch_user(
    transaction: sqlite.Transaction, user_id: int
) -> User[Fetched] | None:
    return await transaction.fetch_one_or_none(
        sqlite.select(User).where(User.user_id.eq(user_id))
    )


def active_users() -> sqlite.Select[User[Fetched]]:
    return sqlite.select(User).where(User.active.eq(True)).order_by(User.user_id.asc())
```

Both bodies and annotations are unchanged. A missing lookup returns None; too
many rows still raise a cardinality error. A separate explicit PublicUser response
contract selects only email and user_id. The result declaration does not replace
response contracts or authorization.

### Foreign keys

```python
class Post[State = Pending](Model[State]):
    __read_type__: ClassVar[ReadType[Post[Fetched]]]
    __tablename__ = "posts"

    post_id: sqlite.GenCol[int] = sqlite.Integer(
        primary_key=True,
        auto_increment=True,
        default=sqlite.PENDING_GENERATION,
    )
    author_id: sqlite.FKCol[User, int] = sqlite.ForeignKey(User.user_id)
    title: sqlite.Col[str] = sqlite.Text()
```

The FK still names User and its ordinary column, not a fetched specialization.
The join retains native `Post.author_id.references(User.user_id)` syntax.
This study exercises direct FKs, not new self/mutual callable-FK cases.

### Update, delete, and settings saves

```python
users = await transaction.execute(
    sqlite.update(User)
    .set(User.display_name.to("Ada"))
    .where(User.user_id.eq(user_id))
    .returning()
)
# list[User[Fetched]]
```

DELETE and conflict handling also retain their native forms. The settings test
starts with digest_hour 18, omits it from the attempted save, and updates timezone
only. The returned row keeps 18. The separate fresh-insert tour materializes the
SQL default of 9. None of this changes conflict/default semantics.

### Methods and lifecycle annotations

The class stays one generic class, so methods remain available across states.
That does not remove the need to type their permitted states:

```python
def label(self: User[Pending] | User[Fetched]) -> str:
    return self.display_name or self.email


def identity(self: User[Fetched]) -> int:
    return self.user_id
```

Both declaration styles accept the shared method on Pending and Fetched values,
and reject calling the fetched-only method on Pending values.

The tested unconstrained `State` declaration with a plain `def label(self)` cannot
read those descriptors under ty. Both original and class-body controls report
that limitation. An explicit self annotation works. This is a bounded observation
about those declarations, not a claim about every constrained generic alternative.

## Compatibility exception: helpers typed against the old base

This existing helper is precise for the original User:

```python
def insert_generic[Read: sqlite.Model[Any, Any]](
    pending: sqlite.Model[sqlite.Pending, Read],
) -> sqlite.Write[Read]:
    return sqlite.insert(pending).returning()
```

With the class-body User, its result becomes Any. Runtime execution still returns
the correct User, but exact typing is lost. The shim inherits native
`Model[State, Any]`; upcasting to that base forgets the concrete class's result
annotation. Runtime binding cannot recover it for the checker.

Helpers accepting ready queries avoid depending on that old nominal coordinate:

```python
async def execute_write[Result](
    transaction: sqlite.Transaction, command: sqlite.Write[Result]
) -> Result:
    return await transaction.execute(command)
```

Both original and class-body callers preserve the exact fetched type through this
helper. This is evidence for that helper style, not an automatic migration of all
model-based utilities. A public result-aware model interface would need separate
design and validation if those utilities must keep accepting models.

The prototype also changes Model's generic arity. A production increment needs an
explicit adoption plan, such as an opt-in base, or researched coexistence with the
old two-argument declaration. It is not ready to silently replace the exported
Model across an existing application.

## What this deliberately does not fix

Unlike the earlier combined state-declaration study, this shim adds **no explicit
constructors, specialization alias, or fetched-construction guards**. It reuses
only the earlier result metaclass and ReadType descriptor.

Both original and class-body versions retain these executable counterexamples:

```python
row = User[Fetched](email="ada@example.com")
# row.user_id is statically int but actually PENDING_GENERATION.
```

The inherited `.construct(...)` path has the same hole. Also,
`select(User[Fetched])` passes the tested static calls but rejects the specialized
class at runtime. Continue using `select(User)`.

Wrong or missing class-body result declarations can pass static checking. The
metaclass rejects them at declaration time. A successful query result assertion
must not be mistaken for proof of all declaration and constructor invariants.

## Lint and declaration overhead

The body example uses no future import, quoted base argument, or import exception.
A declaration-only native control with a separately imported Fetched reports F401
under isolated Ruff; the class-body declaration uses Fetched in a real annotation.

This benefit is situational. The full current example already uses Fetched in
helper/method annotations, so it also lints clean. Qualifying `sqlite.Fetched`
also avoids an independently unused import in the original design. Python 3.14
already makes future imports optional; the eager base expression is the specific
problem this proposal avoids.

The implementation still resolves deferred annotations internally. It does not
eliminate every form of forward reference in a model graph.

## Evidence

`compare.py` checks the application ASTs after removing only the permitted
imports, result base argument, result annotation, and module description. All
fields, methods, query bodies, helper annotations, and the public response
contract match. It also verifies that the paired runtime test bodies match.

The three-model Scaffold and eight SQL/parameter pairs match exactly: INSERT,
SELECT, projection, FK join, UPDATE, DELETE, upsert, and bulk INSERT. Scaffold
remains initial CREATE text supplied to a native migration, not a migration
planner.

- **63 independent typing observations:** 33 capabilities, 18 rejections, nine
  accepted counterexamples, three unsupported contracts.
- **40 runtime tests**, including matching original/class-body use-case tests.
- **1,127 existing fast tests** passed.
- State-declaration regression: **52 observations / 26 tests**.
- Fetched-first regression: **48 observations / 29 tests**. No further nested
  design work was undertaken.
- Repository ty, Ruff lint/format, and tracked diff checks passed.

Typing observations require clean controls and challenge-line diagnostics.
Versions and source hashes are recorded in results.json. Useful red/validation
logs are under `.git/class-body-usage/`. No MariaDB execution, broad framework
integration, full integration suite, or performance claim.

## Assessment

Keep this option independent of the nested redesign. It improves the declaration
without requiring a different application vocabulary for ordinary CRUD and
concrete-model helpers. Its costs are an extra annotation line, a ReadType helper,
and compatibility work for base-typed generic utilities.

I would review it as a small declaration feature with explicit migration scope,
not combine it with constructor hardening or claim it provides the guarantees of
two independent value classes. The next nested-class direction remains the
user's choice after reviewing these results.
