# Throwaway output-layout typing prototype

Question: can named UNION retain exact per-field types, including nullable
right-hand bindings, without accepting invalid inputs and repairing them only
at runtime?

This is a **signature-only experiment**, not an implementation of SQL UNION.
The `.pyi` files describe candidate interfaces. Consumer files are checked, not
executed. `value()` is a typing probe, not a proposed fetching operation.
Some negative files deliberately pass the checker; those expose rejected
candidates. Never copy these stubs into the production package.

## Run

From a checkout of the prototype branch:

```sh
uv run python snekql/_union_layout_prototype/assess.py \
  --output "$HOME/.cache/snekql-union-layout-assessment"
```

The runner records every diagnostic and an assessment JSON. Exit zero means the
assessment ran, not that every candidate is safe. Inspect `requirement_met`.
Experiments used ty 0.0.77 against the real production sources at 3548668.
No casts, Any, or diagnostic suppressions are used to pass the consumer cases.
No other checker or native database execution is certified by this prototype.

## Results

| Candidate | Result |
| --- | --- |
| Existing named query carriers | Earlier production probe showed nullable/nonnullable bindings erase to the same query type. |
| Generic layout selector callback | Precise optionality, but accepts incompatible domains and missing fields. Rejected. |
| Explicit schema plus selector callback | Fixes shape/domain matching. A mixed-field selector still passes as `Slot[Unknown, Unknown]`, even with structural witnesses. Rejected. |
| Whole variadic output pack | Does not compute fieldwise widening; rejects the valid nullable-right example. This tests this signature, not every conceivable variadic design. |
| Handwritten result-specific query type | Accurate two-field typing and six intended rejections. Requires result-specific query signatures. Does not integrate real owner/family facts. |
| Explicit schema, union of whole layouts, direct column attributes | Promising. Seven focused consumer cases meet their expectations, including a twelve-field shape. No result-specific union overloads needed. |

The last candidate keeps `Query[Schema, LeftLayout | RightLayout]`. Accessing
`combined.columns.event_id` lets ordinary Python attribute-union typing preserve
both alternatives. A structural value consumer infers `int | None`, while an
unrelated required text field remains `str`. There is no user callback selecting
a different column for each operand.

It supports reordered constructor keywords, reversed operands, repeated/mixed
set operations, typed helpers, and more than eight fields. Wrong logical domains,
missing schema fields, and consuming optional values as required are rejected.
The wide schema file is a second concrete shape, not a generated general solution.

## What this does not prove

- This changes the interface. Callers need an explicit generic output-schema
  declaration in addition to the result model, and direct output attributes
  instead of looking up the first query's original label. General schema creation
  from an arbitrary Pydantic class is not implemented.
- Real source labels work as inputs in the simple case. Source labels alone do
  not carry LEFT-join null extension. One successful integration probe uses
  existing CTE output rebinding first. It duplicates declaration work; a direct,
  ergonomic projection adapter remains unproven.
- The simplified specialized factory loses real source-backend facts, despite
  correctly rejecting deliberately modeled mismatched family witnesses. Its
  production-family negative is intentionally retained to expose that gap.
- Wire compatibility is not encoded in the current label type. The real
  `production_wire_erasure.py` probe shows Integer-backed and Text-backed `int`
  fields have identical label types on the same owner. Validator/codec guarantees
  do not follow from a matching Python type. Static-only compatibility would
  require further declaration changes, generated signatures, or restrictions.
- Readiness, ownership after rebinding, optionality-sensitive operations,
  parameter order, SQL grouping, materialization, and optimizer behavior have not
  been implemented or validated here. The initial explicit-schema signatures
  are not a production safety guarantee.

## Verdict

Exact nullable UNION typing is possible with a redesigned explicit schema;
it is not impossible in Python. The union-of-layouts approach is the best result
of this experiment and avoids per-result union code generation.

It does not deliver the current fluent label interface plus fully static
compatibility for existing snekql declarations. Under that requirement, prefer
the agreed fallback for the first UNION implementation: the left output contract
must accommodate every right output, with construction-time guards for facts not
present in types. A larger projection redesign can pursue the promising schema
approach separately. This recommendation is not a claim of mathematical
impossibility, nor a reason to accept unsound inferred types.
