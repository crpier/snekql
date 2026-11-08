# #601: ty-specific exclusion feasibility

## Verdict

Positive feasibility proof for the narrow nominal ZonedDatetime exclusion on ty 0.0.84, including the actual Model/Col/Attr descriptor API, NOT a portable/general metadata-driven capability design or complete implementation. No observed crippling loss of ordinary int/UTC/local calls, equality/membership, nominal values, Row/Pending snapshots, owner/family inference or selected result types in these probes. Explicit significant tradeoffs: experimental ty-specific forms; generic ordering helpers must carry exclusion evidence; runtime annotation evaluation is not proven. Any still escapes as usual.

## Actual exposed feature, not just internal narrowing

`ty_extensions` is NOT installed as an importable runtime Python module (`find_spec` returned None), but installed ty resolves its vendored checker-only stub. `if TYPE_CHECKING: from ty_extensions import Intersection, Not` works with all project diagnostics set to error. Named forms work without experimental-syntax suppression. `A & B` and `~T` spellings trigger error[experimental-syntax] under current project settings (initial run; forms.py now uses named forms). `Not` and `Intersection` are documented as experimental end-user APIs in upstream `crates/ty_vendored/ty_extensions/__init__.pyi` (saved as ty_extensions-source.pyi). Upstream main revision saved in source-revision.txt; installed-version execution is the authoritative compatibility evidence, not that current-main stub. Source fetched using gh API, no issue/PR interactions.

`forms.py` also reveals `~ZonedDatetime` after negative isinstance narrowing. Unconstrained generic ordering fails; a `T: Not[ZonedDatetime]` bound works. `self_variants.py` shows directly replacing invariant Attr's value argument with Not[Z] wrongly rejects ordinary int, while protocol self constraint and intersection self constraints avoid that.

## Minimal mechanism

```python
if TYPE_CHECKING:
    from ty_extensions import Intersection, Not


class Domain[T](Protocol):
    def domain(self) -> T: ...


class Attr[Owner, T]:
    def domain(self) -> T:
        raise NotImplementedError

    def eq(self, value: T) -> bool:
        return True

    def asc(self: Intersection[Attr[Owner, T], Domain[Not[ZonedDatetime]]]) -> Owner:
        raise NotImplementedError
```

This is a covariant read-only witness to decoded value type, not a blanket Python-__lt__ capability. Existing production Attr already exposes `__column_value_type__`; the bridge reuses that witness instead of changing field types or adding capability parameters. Protocol is structural; the excluded target is nominal ZonedDatetime. Nullable Z and unions containing Z are excluded, while nullable UTC and int|UTC remain usable.

## Test-first real API bridge

Before policy changes, positive.py passed and acceptance failed: 20 negative sites expected, only 7 diagnosed; 13 ZonedDatetime ordering sites were incorrectly accepted. See red.log and baseline-negative.log. Then make_overlay.py copied repository snekql into overlay/snekql entirely under this directory and applied only copied-source signature restrictions plus a witness protocol/imports. expressions.patch and storage.patch show the changes. No repository files were modified.

After policy changes: positive.py passes; all 20 marked negative sites receive actual call/assignment diagnostics and no unexpected negative-file lines are diagnosed (green.log). The nine nonnullable direct operations are asc, desc, min, max, lt, lte, gt, gte, between. Additional negatives: nullable Z asc/lt, int|Z asc, Annotated[Z, OrderPreserving] asc, incorrect scalar inputs, nominal equality/membership inputs, None comparison, frozen Row/Pending writes. The marker does not override the nominal exclusion.

Examples of exact concise diagnostics:

```
negative.py:5:5: error[invalid-argument-type] Argument to bound method `Attr.asc` is incorrect: Expected `Never`, found `Attr[Table[Pending], Table[Row], Event[Pending], ZonedDatetime, ZonedDatetime, ZonedDatetime, ZonedDatetime, Literal["sqlite"]]`
negative.py:9:5: error[invalid-argument-type] Argument to bound method `Comparable.lt` is incorrect: Expected `Comparable[Event[Pending], ZonedDatetime, ZonedDatetime, Literal["sqlite"]] & _OrderingDomain[~ZonedDatetime]`, found `Attr[Table[Pending], Table[Row], Event[Pending], ZonedDatetime, ZonedDatetime, ZonedDatetime, ZonedDatetime, Literal["sqlite"]]`
```

The first diagnostic mentions Never because the RECEIVER intersection is impossible: this is a real call-site error, not a callable returning Never. Return types remain OrderBy/Predicate/Aggregate. Full diagnostics in restricted-negative.log.

Positive controls assert exact owner/family Predicate/Aggregate/OrderBy types; int/UTC/local order operations, nullable UTC ordering, Z equality/membership including nullable columns, nominal Row/Pending reads, assignment expression construction, selected tuple result `list[tuple[ZonedDatetime, int]]` and model result `list[Event[Row]]` all check. Both Pending and Row are already immutable in this repository, so assignment-negative controls preserve that policy rather than expecting mutable Pending.

Copied policy-bearing expressions.py and storage.py themselves also pass ty (definitions.log), not just consumer imports.

## Generic helpers and costs

helpers_positive.py passes: bounded generic Attr sort/min retain owner and result type, nullable UTC works while preserving independent comparison type, and an intersection of Comparable with an independently declared structural witness supports generic lt while preserving owner/family. Generic equality remains unconstrained and accepts ZonedDatetime.

helpers_negative.py produces exactly 8 diagnostics: prohibited actual arguments to generic helpers, wrong literal type, unbounded generic ordering, bare Comparable ordering despite a Not bound (Comparable itself lacks the decoded-value witness), and object-valued ordering. Thus existing broad generic ordering helpers may need updated bounds/signatures, not merely checker upgrade. Any-valued fields remain accepted, as is normal for gradual typing. No casts/Any were used to make the positive feasibility examples pass.

## Exact commands (run from /home/crpier/Projects/snekql)

```
uv run ty --version
# ty 0.0.84
uv run python /tmp/snekql-601-ty-uFNOB7/accept.py
# exit 1: positive 0 errors, negative missing 13 expected errors
uv run python /tmp/snekql-601-ty-uFNOB7/make_overlay.py
uv run python /tmp/snekql-601-ty-uFNOB7/accept.py --overlay
# exit 0: positive 0 errors, negative 20/20 expected error lines
uv run ty check --project . --output-format concise --extra-search-path /tmp/snekql-601-ty-uFNOB7/overlay /tmp/snekql-601-ty-uFNOB7/overlay/snekql/expressions.py /tmp/snekql-601-ty-uFNOB7/overlay/snekql/storage.py
# exit 0
uv run ty check --project . --output-format concise --extra-search-path /tmp/snekql-601-ty-uFNOB7/overlay --extra-search-path /tmp/snekql-601-ty-uFNOB7 /tmp/snekql-601-ty-uFNOB7/helpers_positive.py
# exit 0
uv run ty check --project . --output-format concise --extra-search-path /tmp/snekql-601-ty-uFNOB7/overlay --extra-search-path /tmp/snekql-601-ty-uFNOB7 /tmp/snekql-601-ty-uFNOB7/helpers_negative.py
# exit 1: eight expected error lines
```

accept.py prints exact underlying absolute-path ty commands. Extra search paths ensure copied modules win resolution; diagnostics name copied signature changes and checking copied definitions passes.

## Remaining proof / boundaries

- Experimental ty-specific API is a real portability cost. No evidence this works on standard mypy/Pyright; no new runtime module/dependency was installed. TYPE_CHECKING protects ordinary runtime imports but resolving these function annotations via get_type_hints/annotationlib is unproven and could fail without names/runtime equivalents.
- Only a narrow nominal exception. Does not interpret Annotated Canonical/OrderPreserving; says nothing general about custom serializers or storage-aware capability inference. Unknown non-Z logical types are not certified order-preserving by this predicate.
- Minimal overlay deliberately leaves ordering `_col` overloads and Aggregate.asc/desc, CTE/alias/expression surfaces untouched. unrestricted_seams.py passes for Event.z.lt_col(Event.z), gte_col, and an explicitly typed ZonedDatetime Aggregate.asc: this is NOT complete static enforcement. Those signatures would need equivalent restrictions and new tests before implementation claims.
- No backend suites, runtime query execution, packaging validation, other-checker validation, full repository static check, FK/GenCol/CTE/join/recursive integration matrix, metadata override policy or broader marker-driven design. Owner/family/result preservation is established for tested direct and generic paths only.
- All artifacts remain under this unique directory. git status was clean after work. No issue or PR interactions, dependencies, subagents, repository edits or commits.
