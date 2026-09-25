# Implicit input-to-row pairing

Local, uncommitted research on `research/dual-implicit-pairing`, from main
`56dbc32`. Related research issue [#396](https://github.com/crpier/snekql/issues/396)
is closed; no issue update or publication was made. Production and earlier
research implementations are unchanged. No dependencies or checker plugins.

## Question and result

Can an independently constructed `UserSettings` be inserted with
`sqlite.insert(user_settings)`, with `ty` inferring `UserSettingsRow` for
RETURNING, without an explicit destination argument?

**Yes, with a declaration-side row link.** Three tested spellings preserve exact
command/result types and execute against SQLite. `.create()` remains optional,
including on models that declare no implicit pair.

This is implicit at the insertion call site, not automatic reverse inference
from inheritance. The successful options name the row once on the construction
class. Row inheritance supplies the fields; the forward link supplies the
static returned type and canonical insert destination.

## Start here

- [examples.py](examples.py): annotated pairs and the complete settings upsert.
- [tour.py](tour.py): standalone construction, first save, repeat save, preserved
  digest schedule, and refetch. No explicit destination or transaction wrapper.
- [generic_example.py](generic_example.py): the generic alternative, including
  constructing an input before declaring its row.
- [sqlite.py](sqlite.py): annotation/callback pairing and insert adapter.
- [generic.py](generic.py): generic namespace alternative.
- [controls.py](controls.py): runtime discovery and an identity decorator.

```sh
bash scratchpad/dual_pairing/run.sh
# Tour only:
uv run python -m scratchpad.dual_pairing.tour
```

Tour output:

```text
{'first_digest_hour': 9, 'saved_timezone': 'Europe/Paris', 'preserved_digest_hour': 18, 'rows': 1}
```

The in-memory database is disposable. Scaffold provides CREATE text, not a
migration planner. The password-hash fixture is not password hashing or a usable
credential. The tour uses known timezone values; this study does not implement
request authentication or repeat the previous study's timezone validation.

## Option 1: typed class attribute

This is the main runnable example, not a settled naming decision.

```python
from typing import ClassVar
from scratchpad.dual_pairing import sqlite


class User(sqlite.Model):
    __row__: ClassVar[type[UserRow]]
    id: sqlite.Field[int | sqlite.Omitted] = sqlite.Integer(
        primary_key=True, auto_increment=True, default=sqlite.OMIT
    )
    email: sqlite.Field[str] = sqlite.Text()


class UserRow(User, sqlite.Row):
    table_name = "users"
    id: sqlite.Field[int]
```

CPython 3.14's deferred annotations allow the forward reference. `ClassVar`
keeps this out of constructor arguments and storage fields. The library installs
a lazy descriptor behind the annotation and validates the relationship on first
use. This works for the tested module-level and function-local declarations.

Cost: one conspicuous class annotation and an implementation-defined `__row__`
name. It is not a field or an application-facing row instance.

## Option 2: one row-type parameter

```python
from scratchpad.dual_pairing import generic as sqlite


class User(sqlite.Model["UserRow"]):
    id: sqlite.Field[int | sqlite.Omitted] = sqlite.Integer(
        primary_key=True, auto_increment=True, default=sqlite.OMIT
    )
    name: sqlite.Field[str] = sqlite.Text()


class UserRow(User, sqlite.Row):
    table_name = "users"
    id: sqlite.Field[int]
```

This is the shortest declaration. The parameter names the returned row, not a
Pending/Fetched state or Backend Family. The namespace supplies the private
backend witness as before. The actual generic example executes INSERT/RETURNING.

Cost: an explicit generic parameter and string forward reference. The current
resolver handles module-level forward strings. **Function-local forward strings
pass `ty` but fail resolution in this adapter.** That limitation is retained as
an accepted static counterexample and a runtime test, not represented as a
successful general-purpose resolver. This is not a proof that generic pairing
cannot support local classes.

The existing model machinery already inherits Generic, so the new generic base
must compose with it in the correct MRO. An explicit dataclass transform retains
the Column Type constructors as field specifiers. These are adapter details,
not extra application declarations.

## Option 3: lazy callback

```python
from scratchpad.dual_pairing import sqlite


class User(sqlite.Model):
    __row__ = sqlite.paired(lambda: UserRow)
    id: sqlite.Field[int | sqlite.Omitted] = sqlite.Integer(
        primary_key=True, auto_increment=True, default=sqlite.OMIT
    )
    name: sqlite.Field[str] = sqlite.Text()


class UserRow(User, sqlite.Row):
    table_name = "users"
    id: sqlite.Field[int]
```

`ty` infers the callback result without a handwritten return annotation in the
tested cases. A closure resolves a function-local row as well as a module-level
row. The callback is not executed during input construction.

Cost: an extra helper and callback. It must be synchronous and side-effect-free.
This experiment reuses native once-only binding rather than repeatedly invoking
it to choose a destination.

## The insertion call site is the same

```python
user_settings = UserSettings(
    user_id=actor.user_id,
    email_notifications=request.email_notifications,
    timezone=request.timezone,
)
row = await transaction.execute(
    sqlite.insert(user_settings)
    .on_conflict(
        UserSettingsRow.user_id,
        action=sqlite.DoUpdate(
            UserSettingsRow.email_notifications.to_inserted(),
            UserSettingsRow.timezone.to_inserted(),
        ),
    )
    .returning()
)
```

The result is exactly `UserSettingsRow`, not `Any`, its construction class, or a
union inferred from the destination columns. The adapter preserves existing
values and generated omissions; it does not reconstruct the input or rerun its
client factories. Complete row instances can also supply insert values. This is
an INSERT operation, not an automatic UPDATE because the value is a row.

Normal conflict ownership and Backend Family checks remain in the earlier
adapter. `DoNothing` still has no public RETURNING method. Without RETURNING,
execution returns None. Native Query Compilation, storage validation, codecs,
and transaction lifetime remain unchanged.

## What did not supply an exact static pair

| Control | Runtime observation | Static observation |
|---|---|---|
| Discover the unique direct row subclass | Inserts and materializes; rejects multiple candidates | Returned type is Any; nonexistent result attributes are accepted |
| Identity-preserving class decorator | Can install a link through a privileged mutation | Cannot add a new member to the original class's static type |
| `type __row__ = UserRow` | Not a row-class value | Does not satisfy the class-valued witness protocol |

The decorator control deliberately bypasses metadata freezing with
`type.__setattr__` to isolate the static question. It is not a recommended way to
modify completed declarations. The runtime-discovery control uses no maintained
registry; its direct-subclass scan has the same missing-static-information issue
as an ordinary runtime registry.

These are bounded observations, not an impossibility theorem. A generated
per-model overload facade could carry the missing static information, at the cost
of generated artifacts and freshness checks. That route was not implemented in
this part. No class-replacing decorator or checker plugin was introduced.

A native-interface typing control confirms that the original design already
carries its fetched result in the model's type parameters. The dual design still
needs equivalent static information somewhere; runtime registration does not
make it appear automatically.

## Binding and failure semantics

- Input values can be constructed before their row exists. There is no schema
  registration or database access during construction.
- Building an implicit insert needs the row. Using a pair before its forward
  reference is defined fails and **memoizes the failure**, matching this study's
  once-only callback policy. Defining the row later does not retry that pair.
  Constructing early is supported; prematurely consuming the pair is not.
- Successful binding is stable after callback state changes. Additional row
  subclasses do not redirect a declared pair. The input has one canonical
  implicit destination, not whichever subclass was most recently declared.
- Ordinary reassignment or deletion of the declared pair is blocked. This is
  declaration immutability, not protection against arbitrary Python reflection.
- Two concurrent first inserts resolve the callback once. Callback failures are
  memoized. Swallowed recursive lookup poisons the pair instead of publishing it.
- Relationship validation checks the input/row class relationship, Backend
  Family, and field set. Existing finalization still checks row refinement,
  completeness, and physical schema validity.
- A new input subclass cannot silently write into its parent's row. The runtime
  rejects that inherited stale link. A tested explicit extension of both input
  and row classes, with a narrowed link, works and compiles to its own table.
  This is not a general inheritance or mixin guarantee.
- Pairing chooses the insert destination; it does not retarget field-local FKs.
- `.create()` needs no implicit link at all. Its existing typed constructor
  binding remains an alternative rather than an implementation dependency here.

## Static limits retained

All three successful spellings can claim an unrelated row of the correct family
and still type-check. The runtime must verify that the row actually extends the
construction contract. Static rejection of that semantic mismatch is not claimed.

The protocol also admits a non-model object advertising the right values and row
members. Runtime nominal checks reject it. Requiring the instance `values`
property closed an initial hole where an actual model class was accepted as an
input value.

Other recorded counterexamples are inherited stale links, runtime-discovery type
loss and nonexistent result members, local generic forward-string resolution,
and class-attribute assignment allowed by typing but rejected by metadata
freezing. Expected failures are not counted as successful static guarantees.

## Evidence and scope

- **41 isolated typing observations**: 16 capabilities, 13 rejections, nine
  accepted counterexamples, three unsupported options. Each uses a clean control
  and checks diagnostic location; exact inferred types use `assert_type`.
- **29 tests** covering real SQLite materialization for all three options,
  existing-value upserts, preserved defaults, factory counts, `.create()` with
  and without implicit pairing, erased guards, late definitions, binding
  stability, two-thread first use, and retained failure controls.
- **1,127 existing fast tests** passed.
- Basics regression: **38 observations and 34 tests**, including its native
  runtime controls. Backend regression: **54 observations and 22 tests**,
  including the earlier MariaDB cases.
- Repository `ty`, Ruff lint/format, and tracked diff checks passed.
- No MariaDB implicit-pairing implementation, complete integration suite,
  performance study, aliases, or additional basic SQL operations in this part.

Useful logs live under `.git/dual-pairing/`. Runtime additions here are private
prototype adapters over the earlier prototypes. Any/private access in lowering
is not evidence of production readiness. Historical declaration spellings were
not changed.

## Review decision

The requested insertion shape is viable without making `.create()` mandatory.
Choose the declaration spelling before expanding the implementation. The class
annotation avoids generic application bases and callbacks; the generic form is
shorter; the callback handles lexical forward references directly. None requires
an explicit destination at the insertion call site.
