# Issue 246 backend-family propagation prototype

This directory is throwaway evidence. It compares two static interfaces under
`ty 0.0.75`; none of these classes implement snekql runtime behavior.

Run from the repository root:

```bash
prototypes/issue_246/run.sh
```

## Question

Can each Backend Namespace reject models, queries, foreign keys, and Scaffold
inputs from the other family without exposing another generic argument in
application annotations or duplicating Query Runtime implementation?

The probes cover:

- model and projection selects;
- inserts and returning result inference;
- namespace verbs;
- Transaction reads and writes;
- joins;
- foreign keys;
- Scaffold inputs;
- Database initialization; and
- stored `Select[ResultT]` and `Write[ResultT]` annotations whose result types
  are deliberately identical across families.

## Baseline

`current_positive.py` records production model, projection, and returning
inference for both backends. `current_negative_probe.txt` runs the rejection matrix
against that interface. Its 27 expected error suppressions are all unused. The
checker currently accepts every tested cross-family operation.

## Design A: namespace facades

`facade_design.py` keeps query carriers family-erased. SQLite and MariaDB get
nominal sibling Model bases plus separate verb, Transaction, and Database type
facades. Stored queries recover backend identity from covariant scope and owner
protocols.

This design passes all positive and negative probes. It preserves exact model,
projection, and returning results, including stored query annotations.

Its costs are hard to ignore:

- The miniature duplicates eleven declarations per backend: seven verbs, two
  Transaction methods, and two Database methods.
- Production would mirror every fetch and execute overload in both facades.
- A mixed-family join remains constructible. The typed Transaction rejects it
  when consumed, before compilation or execution, but `.join(...)` itself does
  not reject it.
- The real public Model bases first need to become nominal siblings. MariaDB's
  Model currently subclasses the core Model exported as SQLite's Model, so a
  simple SQLite Model bound also accepts MariaDB models.
- Every new Query Runtime or Query Builder operation needs matching facade work.

The runtime can remain shared through composition or type-only aliases, but the
interface is shallow. Most shared methods become repeated declarations that can
drift.

## Design B: propagated family witness

`propagated_design.py` carries one private `Literal["sqlite"]` or
`Literal["mariadb"]` through Model, Column, join conditions, select and write
carriers, Config, Database, and Transaction. One generic verb interface and one
Transaction interface serve both Backend Namespaces. Public aliases hide the
family argument.

This design also passes every probe. It rejects a mixed-family model directly at
`.join(...)`, and backend identity survives result-erased public
`Select[ResultT]` and `Write[ResultT]` annotations.

Application syntax stays the same:

```python
class User[S = Pending](Model[S, "User[Fetched]"]): ...


async def load(tx: Transaction, query: Select[User[Fetched]]) -> None:
    await tx.fetch_all(query)
```

The Backend Namespace pins the hidden family in `Model`, `Transaction`,
`Select`, and `Write`.

The implementation change is broad. Current production code contains 229
`Table[Any]` references, 382 `Attr[...]` references, and 33 private select/write
carrier references. Those are pressure points, not a claim that every occurrence
must change.

One `ty` constraint matters. A dependent bound such as
`OwnerT: _Model[FamilyT, ...]` fails with `invalid-type-variable-bound` because
ty does not allow a generic upper bound. The successful prototype puts
`FamilyT` directly on model protocols, columns, and query carriers. Trying to
hide the family only in a TypeVar bound will not work on the supported checker.

SQLite and MariaDB still need distinct Database initialization declarations.
SQLite supports the path convenience form; MariaDB requires MariaDB Config.
That is real backend variation, not accidental duplication.

## Comparison

| Property | Namespace facades | Propagated witness |
| --- | --- | --- |
| Positive model/projection/returning inference | Pass | Pass |
| Namespace verb rejection | Pass | Pass |
| Transaction rejection | Pass | Pass |
| Stored `Select`/`Write` family identity | Pass through scope/owner protocols | Pass directly |
| Join rejection | At Transaction consumption | At `.join(...)` |
| Public family generic | Hidden | Hidden |
| Shared Query Runtime implementation | Yes | Yes |
| Repeated backend declarations | High | Low |
| Internal migration size | Moderate, then ongoing | Broad, mostly mechanical |
| Locality for future query operations | Poor | Good |

## Verdict

Use the propagated witness, with tiny namespace adapters that pin the literal
family. The initial migration is larger, but the family is an execution fact and
belongs on the same private carriers as result shape. Facades alone make every
new operation repeat backend constraints and still reject mixed joins late.

Do not expose `FamilyT` in application annotations. Backend Namespace exports
should specialize the shared internals:

```python
# Illustrative only
type _Select[FamilyT, RowT] = ...

# snekql.sqlite
type Select[RowT] = _Select[Literal["sqlite"], RowT]

# snekql.mariadb
type Select[RowT] = _Select[Literal["mariadb"], RowT]
```

A production change should proceed in tracers: first model verbs and one select
execution path, then joins and stored queries, then writes, foreign keys, and
Scaffold. Keep each tracer green before moving the next interface.

## Runtime contract after typing erasure

Static propagation does not replace runtime checks. Production must keep or add:

- model backend metadata and `require_model_backend`;
- Execution Plan backend validation in Transaction;
- Database `verify` model validation;
- family validation when a Backend Namespace verb receives a dynamic model;
- same-family checks when constructing joins and foreign keys; and
- model-family validation before Scaffold builds a schema plan.

These checks cover `Any`, casts, untyped consumers, and runtime objects loaded
dynamically.
