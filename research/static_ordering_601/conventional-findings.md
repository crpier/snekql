# #601 restricted-self feasibility (ty 0.0.84)

No repository edits, dependency changes, GitHub interactions, backend execution, or subagents. Commands executed from /home/crpier/Projects/snekql. All artifacts under this directory.

## Verdict

Installed ty supports restricted-self generic methods bounded by a structural ordering protocol on the REAL Attr/Comparable generic hierarchy. Existing descriptor overloads already bridge class-body `field: db.Col[T] = db.Text()` declarations to the inferred non-null CompareT at class access. No constructor, annotation, ReadType, or consumer changes were needed. This is credible ZonedDatetime-specific rejection with ordinary ergonomics, NOT a complete storage-capability design.

## Minimal shape

```python
from typing import Protocol, Self


class _PythonOrdered(Protocol):
    def __lt__(self, other: Self, /) -> bool: ...


# Within Comparable[OwnerT, ValueT, ColumnValueT, FamilyT]:
def gt[OT: _PythonOrdered](
    self: Comparable[OwnerT, OT, ColumnValueT, FamilyT], value: OT
) -> Predicate[OwnerT, FamilyT]: ...


# Within Attr[WriteOwnerT, LoadedOwnerT, OwnerT, WriteT,
#              ReadValueT, SetValueT, CompareT, FamilyT]:
def min[OT: _PythonOrdered](
    self: Attr[
        WriteOwnerT, LoadedOwnerT, OwnerT, WriteT, ReadValueT, SetValueT, OT, FamilyT
    ],
) -> Aggregate[OwnerT, ReadValueT | None, CompareT, FamilyT]: ...
```

Repeat for gte/lt/lte/between, all ordering column-comparison overloads, and Attr asc/desc/min/max. Existing implementations unchanged except annotations; no new casts or ignores. `restriction.patch` contains the exact experimental change with original package names. Not production formatting.

## Reproduction

`uv run ty --version` -> `ty 0.0.84`

```sh
uv run ty check /tmp/snekql-601-capability-7XXAuOdi/baseline.py --output-format concise
# exit 0: 13 forbidden Zoned/nullable/mixed calls all accepted before restriction

uv run ty check --extra-search-path /tmp/snekql-601-capability-7XXAuOdi /tmp/snekql-601-capability-7XXAuOdi/restricted.py --output-format concise
# exit 1: 21 diagnostics, exclusively at those 13 forbidden calls

uv run ty check --extra-search-path /tmp/snekql-601-capability-7XXAuOdi /tmp/snekql-601-capability-7XXAuOdi/positive.py --output-format concise
# exit 0

uv run ty check --extra-search-path /tmp/snekql-601-capability-7XXAuOdi /tmp/snekql-601-capability-7XXAuOdi/wrong-input.py --output-format concise
# exit 1: 20 diagnostics, one per deliberately invalid call/assignment

uv run ty check --extra-search-path /tmp/snekql-601-capability-7XXAuOdi /tmp/snekql-601-capability-7XXAuOdi/capsql --output-format concise
# exit 0: all copied package implementation files check too
```

The local `capsql/` package is a complete temporary source copy with package references consistently renamed, including __init__.pyi; the copied real model/descriptor/query implementation is not a toy or unchecked stub. Initial failed exploratory inspect logs predate fixing the temporary .pyi import reference and are NOT evidence. Final authoritative logs: baseline.log, restricted.log, positive.log, wrong-input.log, implementation.log, package.log.

Representative exact diagnostics:
- restricted.py:14:5: error[invalid-argument-type] Argument to bound method `Comparable.gt` is incorrect: Argument type `ZonedDatetime` does not satisfy upper bound `_PythonOrdered` of type variable `_OT`
- restricted.py:21:5: error[invalid-argument-type] Argument to bound method `Attr.min` is incorrect: Argument type `ZonedDatetime` does not satisfy upper bound `_PythonOrdered` of type variable `_OT`
- wrong-input.py:17:5: error[no-matching-overload] No overload of bound method `Comparable.gt_col` matches arguments
- wrong-input.py:5:16: error[invalid-argument-type] Argument to bound method `Comparable.gt` is incorrect: Expected `int`, found `Literal["wrong"]`

## Positive/negative coverage

Positive file checks Zoned equality/membership, nullable Zoned equality/null checks, mixed Zoned|UTC equality, int/UTC/local ordering/ranges/MIN/MAX, nullable int/UTC ordering/ranges/extrema, int|UTC mixed ordering, column comparisons, Pending/Row field assert_type, nullable Row field types, predicate owner, aggregate owner/value/compare types, whole-model query result via ReadType and async fetch_all. No Any or casts at consumers.

Negatives cover all four literal comparisons, range, asc/desc/min/max, nullable and mixed Zoned, wrong argument types and None rejection, all four column ordering comparisons, nullable/mixed column ordering, wrong predicate/aggregate owners, and SQLite-vs-MariaDB column family. Ignored return values still error; not Never-only rejection.

## Limits

This protocol tests PYTHON ordering, not storage order preservation. It is a useful discriminant for current ZonedDatetime (no __lt__) vs UtcDatetime/LocalDatetime (order=True), not proof for Canonical/OrderPreserving or arbitrary logical/storage mappings. Annotated metadata is invisible. A ZonedDatetime subclass adding __lt__ would pass despite storage semantics; custom storage-orderable logical classes without __lt__ would be newly rejected. Thus shipping this structural bound as universal orderability would be unsound/incompatible. A curated nominal allowlist can replace the bound for a consciously closed supported domain, but arbitrary custom types then need an explicit capability annotation/view/constructor design. No claim that unchanged Col[T] can automatically express arbitrary storage capabilities. CTE named operands, label/scalar propagation, inheritance permutations, FK/GenCol ergonomics, every backend constructor, and runtime compatibility are not exhaustively exercised. Existing runtime guards must remain. Capability-specific descriptor views were not needed to prove this bridge and were not implemented.
