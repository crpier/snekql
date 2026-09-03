# Executable-readiness prototype

This directory is throwaway type-system evidence for `ty 0.0.75`. None of the
classes implement snekql runtime behavior.

Run from the repository root:

```bash
prototypes/issue_245/run.sh
```

## Question

Can Query Builder state reject operations that are guaranteed to fail Query
Compilation while preserving joins, returning result inference, and the erased
application-facing `Select[RowT]` / `Write[ResultT]` annotations?

The readiness rules under test are:

- select and delete start incomplete; either `all()` or `where()` makes them
  executable;
- joins and `returning()` preserve readiness rather than establishing it;
- update starts with neither assignment nor row scope, and becomes executable
  only after both `set()` and either `all()` or `where()` in either order;
- inserts are already executable and need no new state; and
- runtime validation remains authoritative after `Any`, casts, and dynamic use.

## Baseline

`current_negative_probe.txt` exercises the production interface. Its 11 expected
rejections are all unused: current `ty` accepts incomplete selects, deletes, and
updates both in public aliases and at Query Runtime methods. It also accepts an
incomplete joined select and returning writes, demonstrating that result shape
and join scope do not imply readiness.

## Design A: private typestate coordinate

`typestate_design.py` adds one covariant private readiness coordinate to the
existing select/write result carriers. Select and delete use incomplete versus
executable markers. Update uses one four-state automaton:

```text
                         set
       empty --------------------------> assigned
         |                                  |
 all / where                            all / where
         |                                  |
         v                 set              v
       scoped ---------------------------> ready
```

The four states encode the assignment × row-scope product without exposing two
independent coordinates. `join()` and `returning()` preserve the current marker.
`all()` / `where()` transition select and delete to executable; update transitions
depend on its current automaton state.

Private executable aliases hide the coordinate from Query Runtime:

```python
type _ExecutableSelect[RowT] = _SelectShape[RowT, _Executable]
type _ExecutableWrite[ResultT] = _WriteShape[ResultT, _Executable]

type Select[RowT] = _ExecutableSelect[RowT]
type Write[ResultT] = _ExecutableWrite[ResultT]
```

The real aliases would retain the existing backend-family and scope coordinates.
Query Runtime and Execution Plan entry points consume only the executable aliases,
not concrete Query Builder classes or the four update states.

Both positive and expected-rejection probes pass. In particular:

- joins preserve incomplete or executable select readiness;
- `returning()` works before or after readiness transitions;
- `set().where()`, `where().set()`, and `set().all()` all become executable;
- assignment-only and scope-only updates remain rejected; and
- erased `Select[RowT]` / `Write[ResultT]` parameters infer exact results while
  rejecting incomplete assignments and runtime calls.

### Production cost

Python has no higher-kinded `Self` that means “this concrete builder with one
coordinate replaced.” The coordinate therefore has to appear on all 12 affected
concrete select/update/delete builder declarations and their fluent returns.
Shared methods need explicit-self overloads for the concrete result variants, or
the existing overload generator must emit those transitions. Generated
`returning()` arms mechanically preserve the marker.

This is substantial inside `snekql.query`, but local:

- private `_ExecutableSelect` and `_ExecutableWrite` aliases absorb readiness at
  Query Runtime and Execution Plan seams;
- backend namespaces pin or erase the coordinate just as they already do for the
  Backend Family Witness;
- application-facing `Select` and `Write` remain one-argument annotations; and
- state dataclasses and runtime completeness checks do not need a type coordinate.

A concrete builder annotation that deliberately stores an unfinished query would
need an internal/unknown-readiness specialization. The public `Select` and `Write`
annotations should mean executable, which is the useful guarantee at application
helper seams.

## Design B: nominal staged builders

`nominal_design.py` removes the readiness generic entirely. Draft classes do not
inherit executable result carriers; ready classes do. This gives Query Runtime a
very small interface and its positive and negative probes also pass.

The cost is a shallow class matrix. Production currently has four select result
classes, four update result classes, and four delete result classes. Nominal
staging expands those 12 classes to approximately 32:

- select: four result variants × two readiness stages;
- delete: four result variants × two readiness stages; and
- update: four result variants × four readiness stages.

Every result-shape addition multiplies by readiness, and fluent methods repeat on
each stage. The miniature already repeats `returning()` across all four update
stages despite representing only one-column and model returning. The production
eight-column overload surface would magnify that duplication. This fails the
locality/depth comparison even though no generic leaks.

## Comparison

| Property | Private typestate | Nominal stages |
| --- | --- | --- |
| Positive select/delete/update inference | Pass | Pass |
| Negative incomplete-query probes | Pass | Pass |
| Joins preserve readiness | Pass | Pass |
| Returning preserves readiness/result | Pass | Pass |
| Erased `Select` / `Write` stay one-argument | Pass | Pass |
| Query Runtime names concrete builders | No | No |
| Affected production query classes | 12 plus a private coordinate | About 32 staged variants |
| Fluent declaration cost | Explicit transitions; generator-friendly | Repeated across every stage |
| Future result-shape locality | Good | Poor |

## Verdict

Use the private typestate coordinate. It removes a meaningful runtime-only
caveat without changing application annotation arity or teaching Query Runtime
the concrete builder matrix. The generic cost is broad but concentrated in the
Query Builder, where readiness transitions belong. Nominal stages trade that
coordinate for substantially worse class and overload multiplication.

Recommended production shape:

1. Define private incomplete, executable, and four update-state markers in the
   Query Builder.
2. Add one covariant readiness coordinate to `_QueryShape` and `_WriteShape`.
3. Specialize private `_ExecutableSelect` / `_ExecutableWrite` aliases and use
   them at Transaction, Query Codec plan, and nested-query consumption seams.
4. Add readiness to affected concrete builders and generator-owned overloads.
   `join`, `left_join`, `returning`, `order_by`, `group_by`, `having`, `distinct`,
   `limit`, and `offset` preserve it. Select/delete `all` and `where` transition
   it. Update `set`, `all`, and `where` implement the four-state automaton.
5. Keep backend namespace concrete-builder aliases at their current public arity
   by hiding unknown readiness; specialize public `Select` and `Write` to
   executable readiness.
6. Keep every Query Compilation completeness check. They remain required for
   dynamic callers, forged values, `Any`, casts, and runtime state corruption.

Nested selects need the same consumption rule: `scalar`, `exists`,
`not_exists`, and column subquery predicates must accept executable select
carriers. The expression-side structural single-column protocol can add one
private readiness witness from a tiny leaf module; it need not expose another
application generic. Otherwise an executable outer query could still contain a
guaranteed-incomplete nested query.

## Runtime contract after static readiness

Static readiness proves only facts visible in a typed fluent chain. Runtime must
continue checking:

- select/delete has exactly one row-scope choice (`all` or predicates);
- update has at least one authentic assignment and exactly one row-scope choice;
- nested selects are complete;
- operands and state are authentic and target models in scope; and
- backend family matches the executing Transaction.

Those checks cover untyped Python, `Any`, casts, dynamic declarations, and manual
mutation or forgery. Readiness narrows ordinary typed paths; it does not make
Query Compilation trust callers.
