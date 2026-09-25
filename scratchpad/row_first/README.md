# Row-first declarations

Local research on `research/row-first-declarations`, from main `56dbc32`.
Related issue [#396](https://github.com/crpier/snekql/issues/396) is closed.
Nothing committed, published, or changed in production or earlier adapters.

## Question and verdict

Can `UserRow` own all field/storage definitions, with `User` overriding input
requirements, so navigating to the frequently used row shows its attributes?

**The navigation benefit is real. Plain reversed inheritance is unsafe when an
input can contain Omitted where its row promises an ordinary value.** Real SQL
execution succeeds, but that does not establish a sound Python interface.

A row-first layout with **nominally separate inputs** also executes and avoids
that subtype problem. It needs repeated input annotations or generated source
for `ty` to know the complete input constructor. This study includes a bounded
generator that copies annotations, not storage declarations.

## Read and run

- [rows.py](rows.py): the authoritative, authored row definitions. Start here.
- [examples.py](examples.py): direct reversed inheritance, intentionally retaining
  its static counterexamples.
- [generated.py](generated.py): unrelated inputs with real checked constructors.
- [input_specs.py.txt](input_specs.py.txt): authored overrides for those inputs.
- [tour.py](tour.py): both styles insert; the direct subtype still violates a
  normal complete-row helper.
- [navigation.json](navigation.json): actual `ty server` definition responses.
- [options.py](options.py): ordinary dataclass, generic-specialization, and
  constructor-default controls.

```sh
bash scratchpad/row_first/run.sh
# Tour only:
uv run python -m scratchpad.row_first.tour
# Regenerate input annotations after editing row definitions or overrides:
uv run python -m scratchpad.row_first.generate
```

The runner checks freshness rather than silently regenerating. The tour uses a
disposable in-memory database and opaque password-hash fixtures. No authentication
or password-hashing implementation is claimed.

## Direct reversal

```python
class UserRow(sqlite.Row):
    table_name = "users"
    id: sqlite.Field[int] = sqlite.Integer(primary_key=True, auto_increment=True)
    email: sqlite.Field[str] = sqlite.Text(unique=True)
    password_hash: sqlite.Field[str] = sqlite.Text()


class User(UserRow, sqlite.Model[UserRow]):
    id: sqlite.Field[int | sqlite.Omitted] = sqlite.omitted()
```

All physical declarations are in the row. Input overrides retain the same
immutable declarations and specialized descriptor kinds. `Model[UserRow]`
supplies the exact returned type to `sqlite.insert(user)`; it is a declaration
link, not an explicit destination argument at the insertion call site.

Both constructors work as intended in isolation. The row requires its ID. The
input may omit it. Inserting the input returns a complete `UserRow` with a
generated integer ID. SELECT also materializes `UserRow`.

### The inheritance problem

This passes the installed `ty` checker with all rules enabled:

```python
def identifier(row: UserRow) -> int:
    return row.id


pending = User(email="ada@example.com", password_hash="fixture")
result = identifier(pending)  # Inferred int; actual value is OMIT.
```

`User` is a nominal subtype of `UserRow`, despite weakening its field contract.
A runtime guard inside SELECT or INSERT cannot repair a normal Python function
that accepts a row. Changing the order of the marker bases or using `.create()`
does not change that subtype relationship.

The same result occurs with ordinary frozen dataclasses, without descriptors,
Any-returning default helpers, or the SQL adapter. It is retained as an accepted
counterexample, not described as a static rejection. Another checker might
reject the widened declaration instead; it would still not make the proposed
subtyping relationship valid.

The existing input-first direction does not have this particular issue. A
complete row satisfies the broader construction-value contract. An incomplete
construction value is not a subtype of the complete row.

### Inherited table capabilities

The input also inherits the row's table-source method and columns. `ty` accepts
`select(User)` and `select(User.email)` in the direct-reversal experiment. Runtime
guards reject these input sources. A foreign-key target can similarly name the
input statically because it inherits the row marker.

These are additional role leaks, separate from the ordinary-function subtype
problem. Public row columns still work normally.

### Important exception

An input-only default that supplies a valid complete value need not weaken the
instance type. Overriding a required Boolean constructor argument with a Python
default of True still leaves every instance holding a Boolean. That control
passes. The problematic reversal is specifically the one that admits values
such as Omitted which the complete row excludes. Source-role eligibility remains
a separate question even when all instance values are complete.

## Navigation evidence

Four real `textDocument/definition` requests were sent to the installed
`ty server`, not inferred from Python reflection:

| Usage | Definition target |
|---|---|
| Row-first `UserRow` class | `row_first/rows.py`, containing id, email, password_hash |
| Existing input-first `UserRow` class | `dual_basics/examples.py`, declaring only id refinement |
| Row-first `row.email` | The field declaration on `UserRow` |
| Input-first `row.email` | The inherited field declaration on `User` |

Thus class-level navigation improves as proposed. Attribute-level navigation
already finds the authoritative declaration in the input-first interface, but
that declaration lives in the input class. These observations concern `ty`'s LSP
responses, not every editor's configuration or UI.

The generated alternative below imports the actual authored row classes, so
row navigation still lands in `rows.py`, not in a generated copy of the schema.

## Keep rows primary without the unsafe subtype

The generated input looks like this:

```python
class User(sqlite.Model[UserRow]):
    id: sqlite.Field[int | sqlite.Omitted] = sqlite.omitted()
    email: sqlite.Field[str]
    password_hash: sqlite.Field[str]
```

It does **not** inherit `UserRow`. The runtime associates it with that row and
copies its immutable field declarations for value validation. No storage
constructors, SQL defaults, FK targets, or indexes are restated on the input.

`ty` rejects passing this input to `identifier(UserRow)`, selecting its class,
and selecting its columns. Its own constructor remains checked and
`sqlite.insert(user).returning()` retains `UserRow` exactly. Actual SQLite
execution returns the authored row class.

Those full input annotations could be maintained manually, but the drift cost
would be real. The included generator takes:

1. The real definitions in `rows.py`.
2. The short input overrides in `input_specs.py.txt`.

It emits ordinary Python with all value annotations. A generic base alone does
not synthesize the other constructor parameters: the isolated generic-only
control rejects email/password_hash keywords and cannot infer the email
attribute. Runtime copying by itself does not fix that static limitation.

Generation adds an artifact and a required freshness check. The generated
classes also record their field list, so a stale list fails declaration rather
than silently accepting an outdated constructor. Logical-type/default changes
still pass through the normal declaration validation.

This generator is deliberately narrow: flat row declarations, Field and
ForeignField annotations, supported built-in logical types and row references.
It does not handle arbitrary imported annotation names, inheritance, decorators,
methods on input specs, or arbitrary source layouts. Unsupported shapes reject.
It parses source without executing it and is not a general production generator.

## Generic specialization is another direction, not a finished SQL option

The ordinary dataclass control uses `GenericRow[Identifier = int]` and an input
subclass of `GenericRow[int | Omitted]`. The input is then correctly rejected
where `GenericRow[int]` is required.

That avoids the direct subtype contradiction by making the types different
specializations. It reintroduces generic state/value distinctions. This study
checks a single varying field; it does not implement a SQL adapter for generic
rows or claim that a multi-generated-field design is ergonomic. A lifecycle-aware
version would need another comparison with the original interface.

## Defaults require a spelling distinction

A SQL-generated value must not make a complete-row constructor argument optional.
The experiment therefore uses:

- `Integer(auto_increment=True)` on the row, with a required value annotation.
- `server_default=native.LiteralDefault(9)` for a SQL default on the row.
- `sqlite.omitted()` on the input to default to OMIT.
- `sqlite.default(18)` on the input for an ordinary Python default.

The runtime rejects omission of a non-generated field and rejects changes to
storage, field kind, FK target, or logical domain through input overrides.
Unrelaxed fields remain required at runtime. Bare annotation-only widening to
`int | Omitted` does not make the synthesized constructor argument optional;
the default initializer is needed in this direction.

A control retaining the old `default=OMIT` constructor keyword makes `ty` accept
a missing ID on a row constructor. Runtime completeness then rejects that call.
Renaming which class owns the declaration does not automatically separate SQL
and Python defaults.

These are research spellings, not proposed changes to released constructors.

## `.create()` still works, with a forward constructor

```python
class AccountRow(sqlite.Row):
    table_name = "accounts"
    id: sqlite.Field[int] = sqlite.Integer(primary_key=True, auto_increment=True)
    name: sqlite.Field[str] = sqlite.Text()
    create = sqlite.insert_using(lambda: Account)


class Account(AccountRow, sqlite.Model[AccountRow]):
    id: sqlite.Field[int | sqlite.Omitted] = sqlite.omitted()
```

The thunk accommodates the later input definition. The tested row-owned factory
retains required keywords and rejects wrong values under `ty`; it executes and
returns `AccountRow`. This constructor-thunk variant is new research spelling.

Inheritance exposes another bounded failure: accessing that factory on the
input gives a Self-based result claiming the input type. The runtime rejects
that owner mismatch. This experiment does not claim full inherited-factory
support, and the helper does not repair row/input substitutability.

## Storage and execution evidence

The bridge derives private contracts from the one authored row declaration and
reuses the earlier finalizer, Column Type metadata, native Query Compilation,
codecs, and transaction-owned execution. There is no second hand-authored SQL
schema. The input does not need to exist for row construction or metadata use.

Real SQLite checks cover generated IDs, complete row reads, settings upsert with
a server default, a generated FK input override, and an actual parent-key update
cascading to that FK followed by a typed join/refetch. An input's Python default
of 18 leaves the row's SQL default at 9 and leaves its constructor required.

No general MariaDB, migration-planning, mixin, performance, or full-constructor
compatibility claim is made. Private/Any adapter internals are not production
readiness evidence.

## Validation

- **43 isolated typing observations:** 13 capabilities, 18 rejections, ten
  accepted counterexamples, two unsupported options.
- **24 tests**, including SQLite execution, generated-artifact freshness,
  metadata/default guards, and executable subtype counterexamples.
- **Four actual LSP definition requests**, with source hashes and target lines.
- **1,127 existing fast tests** passed.
- Previous pairing regression: **41 observations / 29 tests**.
- Previous basics regression: **38 observations / 34 tests**.
- Repository `ty`, Ruff lint/format, and tracked diff checks passed.
- No complete integration or performance suite was run.

Controls, source hashes, and diagnostics are retained in `cases.json` and
`results.json`. Useful red/validation logs are under `.git/row-first/`.

## Recommendation

Keep the row-first navigation goal. Do not adopt ordinary reversed inheritance
for inputs that may contain Omitted. If rows must own the complete storage
definitions, nominally separate inputs are the safer tested option, with the
annotation-duplication or generation cost made explicit.

A lighter compromise is to retain input-first inheritance and list every field
annotation on the row. That can make the row's attributes visible without the
subtype reversal, but storage options still live on the input, so it does not
fully satisfy the proposed layout. No new global declaration convention is
chosen by this experiment.
