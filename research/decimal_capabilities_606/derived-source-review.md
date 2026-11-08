# Issue 606: derived-query typing research

Preliminary independent source review, before the parent's overlay experiment.
The `/tmp` paths below describe that historical run; the consumer is preserved
alongside this file as `original-derived-probe.py.txt`. See README.md for the
subsequent overlay results and replay instructions.

Read-only research; no repository changes or DB execution. Read GLOSSARY and relevant ADRs 0005 and 0010: logical annotation, codec and storage are independent axes; canonical text decimal allows equality but not numeric ordering, native MariaDB DECIMAL supports numeric ordering/aggregation. Query Mapping is distinct from schema ownership.

## Reproducible public API probe

`/tmp/snekql606_probe.py` is the complete minimal consumer; run `uv run ty check /tmp/snekql606_probe.py` from the checkout. Its intentional two bad `eq('bad')` calls fail with `invalid-argument-type`; all `reveal_type`s are diagnostics, and both native and text `.gt(Decimal('1'))` and `.sum()` type-check. No Any-based success is involved in those inferred public types. The example uses two class-body `mariadb.Col[Decimal]` fields with `mariadb.Decimal(10, 2)` versus `mariadb.Text()`, labels both, projects to a Pydantic Result, creates one CTE, and obtains each output by its original token. This is a typing-only `TYPE_CHECKING` example; it makes no runtime execution claim.

Exact ty types (both columns/labels/outputs respectively coincide):

* `Item.native` and `Item.text`: `Attr[Table[Pending], Table[Row], Item[Pending], Decimal, Decimal, Decimal, Decimal, Literal["mariadb"]]`.
* `a`, `b`: `_NullExtendedLabel[Item[Pending], Decimal, Decimal, Literal["mariadb"]]`.
* `c`: `_Cte[Literal["mariadb"], Item[Pending], Result, Role, Item[Pending]]`.
* `x`, `y`: `_CteOutput[_CteOwner[Literal["mariadb"], Item[Pending], Role], Decimal, Decimal, Literal["mariadb"]]`.
* `x.gt(...)`, `y.gt(...)`: `Predicate[_CteOwner[Literal["mariadb"], Item[Pending], Role], Literal["mariadb"]]`.
* `x.sum()`, `y.sum()`: `Aggregate[_CteOwner[Literal["mariadb"], Item[Pending], Role], Decimal | None, Decimal, Literal["mariadb"]]`.

The bad comparisons reject str for both, demonstrating value-domain checking, not storage-operation discrimination. `.gt`/`.sum` on the text output being statically accepted is the negative capability hole, not evidence it runs safely.

## Exact seams and proposed bounded overlay

* `snekql/model.py:129` Col alias and `snekql/storage.py:1145` Attr do not encode constructor/storage capability. Class access overloads at `storage.py:1272-1318` rebind owner and compare type from read value, and have no storage coordinate to retain. Class-body annotation fixes the declared type; distinct RHS constructors alone do not yield distinct exposed types here. Thus ordinary identical `Col[Decimal]` declarations cannot statically distinguish storage without changing the declaration/type surface or checker behavior. Parent's direct-column overlay must resolve this first; no derived-only change can recover erased facts.
* `storage.py:1166` Attr.label returns `_NullExtendedLabel[Owner, ReadValue, Compare, Family]`. `snekql/_output_label.py:10-40` token carries only owner/value/comparison/family witnesses, not storage capability. `query.py:697-704` project accepts expression-family labels and records Result, not a typed field map; `query.py:538-548` cte carries family/owner/result/role/nullability-owner, not projected field capabilities. Crucially token lookup sidesteps needing a variadic field map: `_cte.py:258-274` recovers each output's generics from the *caller-supplied label token*, not from Result or CTE's row generic. Runtime `column` checks token identity, not just name.
* Most credible minimal one-CTE type overlay, conditional on parent proving direct class-body capability: give the source descriptor capability coordinate C, preserve it through `__get__`, `label`, `_OutputLabel`/`_NullExtendedLabel`, `_LabelContract`/`_SensitiveLabelContract`, each `column` overload and `_CteOutput`. Preserve C independently from Decimal T and CompareT, family and owner. Put operation availability on appropriately constrained output methods or a suitably specialized output interface; ensure inherited `Comparable.gt` and unconditional `_CteOutput.sum`/`asc` etc do not leave a bypass. Test exact native positive and text negative through the same single CTE, plus ordinary expression operation positive/negative, with explicit assertions and no Any. Capability may be a distinct subtype instead of generic, but it must carry equivalent independent information across each of these seams; no need to parameterize the whole `_Cte` for this token route.
* `_cte.py:104-220` `_CteOutput` already has runtime provenance forwarding, ordering and aggregate guards; `_output_layout.py:81` makes OutputProvenance from source, and `_output_provenance.py:58-113` reuses derived slot proofs or constructs them from an Attr. Runtime storage metadata survives even while static generic capability is erased; `native_profile`, `require_numeric_source` and `require_ordering` consult retained proofs (`_output_provenance.py:130+`). Do not conflate runtime provenance with a statically visible type witness.

## Limits / holes

No overlay was implemented or validated; ty's support for overload/self constraints and inference of an added coordinate needs an isolated positive/negative probe. Existing generic defaults/Any in implementation and protocol variance/overload fallbacks can accidentally admit negatives, especially for widened/mixed tokens, nullable outer joins, aliases, scalar expressions, unions, and aggregate outputs; the single-CTE evidence proves none of those. Project's runtime checks and identity membership are not static proof that a given token belongs to this CTE. Also distinguish ordering capability from arithmetic and aggregate capability; text canonical equality alone is not numeric ordering. The probe does not establish whether existing runtime guards accept/reject these calls, nor whether arithmetic operators can preserve C correctly. Avoid inferring C from Result's `Decimal` or from backend family alone.
