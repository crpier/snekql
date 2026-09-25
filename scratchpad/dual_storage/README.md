# Dual classes with real storage and relationships

Local follow-up to historical issue #396, against main `580c9b6`.
Production is unchanged. This research is uncommitted and unpublished.

## Answer

**Dual classes can preserve the storage and relationship behavior exercised here.**
There is no evidence in these tests that storage primitives, codecs, schema
constraints, or database execution require the original lifecycle-generic model
interface.

That is narrower than claiming a production-complete replacement. The study uses
an explicit finalization step and dynamically builds private native models. Its
small query adapter is not a replacement for the production query interface.

The useful design rule is:

> An input and its Fetched Model share one storage declaration. Refinement changes
> constructor presence and removes Omitted, never replaces the storage declaration.

This avoids the earlier prototype's FK metadata loss. It also makes generated
foreign keys practical without choosing between generated-value typing and
relationship-target typing.

## Read and run

- [examples.py](examples.py): a storage-rich account pair.
- [tour.py](tour.py): native migrate/verify, INSERT RETURNING, codecs, and a refetched
  FK cascade. No handwritten CREATE TABLE definitions.
- [interface.py](interface.py): bounded declaration/finalization adapter.
- [current.py](current.py): independent original-interface controls.
- [test_mariadb.py](test_mariadb.py): real MariaDB execution through the native bridge.

```sh
bash scratchpad/dual_storage/run.sh
# SQLite application tour only:
uv run python -m scratchpad.dual_storage.tour
```

The complete runner requires the project's MariaDB tools and optional drivers.
The temporary server uses a local Unix socket, no TCP listener, with its data
under `.git/dual-storage-research/mariadb`. Test-support manages server lifetime.

Tour output:

```text
{'old_manager_id': 1, 'refetched_manager_id': 10,
 'balance': '12.5', 'payload': {'answer': 42}}
```

The previously fetched Python object does not update itself when the database
cascades a key change.

## Actual declaration shape

Abbreviated from the executable example:

```python
class NewAccount(Record):
    id: Field[AccountId | Omitted] = stored(
        sqlite.Integer(primary_key=True, auto_increment=True),
        default=OMIT,
    )
    code: Field[str] = stored(sqlite.Text(unique=True))
    manager_id: ForeignField[Account, AccountId | None] = foreign(
        lambda: Account.id,
        default=None,
        on_update="CASCADE",
        on_delete="SET NULL",
    )
    created_at: Field[sqlite.UtcDatetime | Omitted] = stored(
        sqlite.Text(), default=sqlite.CurrentTimestamp
    )
    payload: Field[Json[dict[str, int]]] = stored(sqlite.Text(), default_factory=dict)


class Account(NewAccount, ReadRow):
    table_name = "accounts"
    id: Field[AccountId] = required()
    created_at: Field[sqlite.UtcDatetime] = required()
    create = insert_using(NewAccount)


SCHEMA = Schema(Account)
```

`stored(...)` is research glue around the real Column Type constructors. It is
not a recommendation to add nested constructors to the public interface.
Defaults appear on its outer call so dataclass-transform sees constructor
optionality. A production backend namespace should expose the familiar
`Integer`, `Text`, and other constructors directly with the dual descriptors.

Keeping `required()` explicit made the metadata-preservation rule easier to
inspect. Annotation-only spelling is a separate choice and was not the focus.

## What executes, and what does not

| Behavior | Evidence |
| --- | --- |
| Column Types remain independent of Logical Types | Native constructors captured once; native codec derivation retained |
| Generated integer IDs and server timestamps | SQLite insert/materialization and timestamp UPDATE |
| Required generated FK with a literal default | SQLite supplies parent ID 7 through a real physical FK |
| Nullable generated FK | SQLite supplies NULL; fetched constructor still requires the field |
| Client defaults/factories | UUID factory runs once per command, not again on fetch |
| SQLite logical codecs | JSON dict, UUID, CanonicalDecimal, UtcDatetime, Duration, bool, and BLOB round-trips |
| Canonical decimal equality | Stored 12.50 matched by a 12.5 predicate using the native codec |
| MariaDB native codecs | Decimal, UUID, JSON, DateTime/UtcDatetime, Boolean execute on MariaDB 12.3.2 |
| Native descriptor-specific operations | MariaDB JSON extraction compiles and executes after capture |
| Scalar FK storage derivation | Target storage, collation, length, decimal precision/scale preserved |
| FK existence enforcement | Both SQLite and MariaDB reject missing parents |
| FK actions | SQLite scalar CASCADE/SET NULL; composite update/delete CASCADE; MariaDB decimal CASCADE |
| Composite FK semantics | Same-parent-row enforcement and NULL-component bypass execute |
| Composite primary key made of FKs | Native scaffold test |
| Typed-only reference | Orphan scalar accepted without a physical FK |
| SQLite collation | NOCASE FK accepts differently cased text without changing Python values |
| Keys/indexes/checks | Ordinary keys and indexes; SQLite CHECK and partial unique index execute |
| MariaDB prefix index | LongText prefix index scaffolds; no runtime prefix-index test |
| Schema verification | Native verify succeeds for migrated models and detects an altered FK action |
| Input-template extension | New required input, rebound column owner, retained parent FK target, original input still works |
| Forward declaration | Child declared before parent finalizes successfully |
| Mutually recursive table declarations | **Unsupported by this adapter**; finalization fails without publishing partial bindings |

The CHECK/partial-index declaration adapter deliberately covers a small predicate
grammar. Main's full grammar was not reimplemented. No arbitrary multiple-
inheritance or full query-language compatibility claim follows from these tests.

## How metadata survives

The earlier `required()` installed a new ordinary Field and discarded the foreign
subtype. Here it creates another descriptor of the **same kind**, holding the
**same immutable Declaration**. Storage facts, foreign target, defaults, and
referential actions are not restated on the Fetched Model.

A fetched declaration cannot replace that column with another Column Type.
An incompatible logical refinement fails during declaration. A generated input
annotation must admit Omitted; the fetched annotation must remove it.

During finalization:

1. Resolve the model/column dependency graph, including deferred targets.
2. Allocate fresh native descriptors from captured Column Type metadata.
3. Bind complete native logical annotations and native schema policies.
4. Validate the whole native scaffold before publishing any input/fetched binding.
5. Freeze model metadata and resolved relationship targets.

Foreign thunks are evaluated during finalization, not on each query. A test
changes the thunk's backing value afterward; the previously resolved target
remains fixed. Reusing a finalized root retains its dependency closure.

Class replacement and descriptor-metadata mutation are guarded. Native Attr
metadata also retains main's freezing behavior. This is ordinary Python
immutability, not protection against deliberate `object.__setattr__` bypasses.

The prototype constructs a private native model from the declaration. There is
**no separately authored storage counterpart**, unlike the earlier recursive
adapter. Native schema/compiler/runtime code owns DDL, encoding, decoding,
constraints, verification, and transaction lifetime. The input/fetched pair owns
its constructor contracts.

## Where dual classes can improve the interface

### Generated FKs need not lose target-aware columns

This combination works statically and through actual SQLite execution:

```python
class NewChild(Record):
    parent_id: ForeignField[Parent, int | Omitted] = foreign(
        Parent.id, default=sqlite.LiteralDefault(7)
    )


class Child(NewChild, ReadRow):
    table_name = "children"
    parent_id: ForeignField[Parent, int] = required()
    create = insert_using(NewChild)
```

`Child.create()` can omit the column. `Child(parent_id=7)` is complete.
`Child()` is rejected by ty. `Child.parent_id.references(Parent.id)` retains the
relationship target. The database still enforces the referenced row's existence.

Main can already express the same **physical schema** with `GenCol` plus a
`ForeignKeyConstraint`; the matching scaffold is tested. That spelling does not
retain the target-aware `.references()` interface. Dual classes make the input
omission an independent type coordinate, rather than another competing column
category.

This is an interface improvement, not new SQL power. Main could also gain a
combined generated/foreign column annotation without adopting dual classes.

### Input templates can preserve complete storage declarations

An extended input can inherit physical facts and add a required field. Its Fetched
Model rebinds the constructor and refines generated fields. The tested extension
retains defaults, codecs, keys, and its inherited FK target.

Two distinctions matter:

- Column ownership rebinds to the new Fetched Model.
- A declared FK to Account remains a FK to Account. It does not automatically
  become a self-reference to every subclass.

A stale `insert_using` binding is rejected at finalization rather than discovered
only when an insert is attempted. ty still accepts that stale declaration; the
guard is runtime evidence, not a static guarantee.

This makes controlled input templates worth investigating. It does not justify
silently merging arbitrary table policies through Python MRO.

### Constructor honesty survives the integration

The public Fetched Model does not expose a lifecycle parameter that callers can
specialize while retaining omitted generated values. Its constructor requires the
refined fields, and runtime construction rejects omission after type erasure too.
Inputs are not query or update targets. SQL can still update generated columns and
primary keys; frozen Python values do not impose SQL immutability.

## Findings that are not benefits of dual classes

### Main's scalar decimal FK loses precision

The original-interface control currently raises:

```text
SchemaError: Decimal column is missing precision metadata
```

Its `ForeignKey` constructor copies the storage kind and text facts but not decimal
precision/scale. The prototype exposed this when native finalization rejected a
storage mismatch. Copying those parameters before native binding fixed the study,
and an actual MariaDB decimal FK cascade passed.

That correction belongs in the shared storage implementation if pursued. It is
not an argument for replacing the model interface. The failing original control
is retained as an observation, not a desired behavior.

### Native descriptor kinds carry behavior

Copying only Attr constructor values initially removed MariaDB's
`json_extract_int`. Retaining the native descriptor subtype restored it.

The lesson is broader than two classes: metadata preservation includes behavior
associated with a Column Type, not merely the CREATE TABLE spelling.

### Native limitations remain native limitations

A nominal ID with `LiteralDefault(None)` remains rejected by main's bounded
literal-default validation. The study does not erase the nominal type to bypass
that rule. Other native constraints, including candidate-key requirements and
SET NULL nullability, also remain enforced.

## What remains unresolved

- **Finalization timing.** Main fixes declaration facts when a Table Model class
  is created. This study captures field declarations then, but requires
  `Schema(...)` before constructing values. That buys deferred targets at the cost
  of another phase. A production design needs an explicit decision here.
- **Mutual cycles.** The adapter topologically creates native models and cannot
  finish A→B→A. A two-phase native metadata finalizer would be needed to test this
  improvement honestly. Self-FKs and acyclic forward references are demonstrated.
- **Backend typing.** Native models retain Backend Family witnesses. The small
  public research adapter does not propagate those witnesses through every type.
  Re-finalizing a pair under another backend is runtime-rejected, not statically
  rejected. MariaDB tests deliberately use the erased native bridge.
- **Specialized public columns.** Native JSON operations survive and execute, but
  plain `Field[dict[...]]` does not expose them statically. A typed JsonField or
  equivalent backend-owned descriptor is still needed.
- **Query interface.** Keep production query conventions and guarantees. The thin
  adapter's bare-class join can infer a wider owner and accept an unavailable
  predicate owner; native construction rejects it. This is a recorded adapter
  typing defect, not evidence that main has that defect.
- **Declaration checking.** `required()` and `stored()` have erased initializer
  return types. ty can accept contradictory metadata, bad ordinary defaults,
  and wrong refinements. Runtime declaration/validation guards remain necessary.
  Required and nullable FK initializer forms do not behave identically under ty.
- **Metadata breadth.** Tests cover the listed native types and policies, not every
  combination, custom codec, schema-inspection case, or inheritance pattern.
- **Integration cost.** Private native classes and extra validation are research
  mechanisms. No performance claims, complete framework integration, full public
  facade, or production-ready authoritative registry are established here.

## Recommendation

Continue with dual classes as the strongest redesign candidate. Preserve the
original Column Type constructors, codec derivation, query conventions, and native
schema/runtime semantics.

The next production-facing design question is the authoritative metadata record
and its finalization phase. Both classes should refer to that one record.
Do not port the earlier prototype's descriptor replacement or add a second
hand-maintained schema.

The demonstrated benefits are honest constructor shapes, composable generated-FK
typing, and controlled reuse of input declarations. Database referential integrity
and codec behavior are existing strengths to preserve, not new benefits to claim.

## Evidence

- **57 isolated ty observations:** 25 rejections, 18 capabilities, 12 accepted
  counterexamples, two unsupported cases. Every observation has a clean control;
  expected diagnostics must occur on challenge lines. No crashes/timeouts count
  as successful rejection.
- `results.json` records actual diagnostics, source hashes, Python and ty versions.
- **58 research tests pass**, including four actual MariaDB runtime tests.
- **1,100 existing fast tests pass**, plus **19 native SQLite FK cases** and
  **21 native SQLite literal-default cases**.
- Earlier research runners still pass: **123 + 158 + 91 + 60 typing observations**
  and **42 + 53 + 41 + 24 runtime tests**.
- Repository ty, Ruff lint/format, and diff checks pass. **524 files formatted**.
- No full repository database/integration suite or performance suite was run.

Python 3.14.2, ty 0.0.77, MariaDB 12.3.2. No new dependencies.
