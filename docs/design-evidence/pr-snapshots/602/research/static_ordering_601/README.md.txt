# Static ordering rejection: narrow feasibility proof (#601)

## Conclusion

**Yes: ty 0.0.84 can reject unsupported ZonedDatetime ordering at the call site,
without changing ordinary class-body declarations.** Two independent agents tested
restricted receiver signatures against temporary copies of the real package—not
just toy column classes. This is feasibility evidence, not a production patch.

Existing declarations remain:

```python
z: db.Col[db.ZonedDatetime] = db.Text()
```

The ty-specific approach uses checker-only `ty_extensions.Intersection` and `Not`
plus the existing read-only `__column_value_type__` witness. Schematically:

```text
self: Intersection[original column type, value-witness[Not[ZonedDatetime]]]
```

That is an exclusion on the method's receiver, not a Never return type. A forbidden
call is diagnosed even when its return value is ignored. Nullable and mixed unions
containing ZonedDatetime are rejected too. Canonical/OrderPreserving Annotated
metadata is not inferred or turned into storage capabilities by this experiment.

## Evidence (2026-11-08)

- Baseline real consumer: positive examples pass; 13 forbidden direct Zoned ordering
  calls are accepted. Seven other expected negative controls are already diagnosed.
- Restricted copied-source consumer: positive examples pass; all 20 marked negative
  sites are diagnosed, with no diagnostics on unmarked lines.
- Positive controls include Zoned equality/membership, int/UTC/local/nullable UTC
  ordering, exact owner/family/result types, whole-model and tuple results, and
  Pending/Row fields and immutability.
- Additional generic-helper probes establish that helpers can carry exclusion
  evidence, but existing unconstrained ordering helpers need stronger signatures.
- Parent independently reran baseline and restricted acceptance with those results,
  and reran the conventional positive consumer successfully.

The second approach bounds receivers by a Python `__lt__` protocol. Its probes also
preserve declarations and catch Zoned ordering, including column comparisons. But
Python comparability is **not** storage order preservation, so that is not a sound
general policy. It can admit ordered Zoned subclasses and reject custom types that
have appropriate storage but no Python ordering. The ty nominal-exclusion approach
does not rely on that assumption.

## Costs and boundaries

- Intersection/Not are experimental ty-specific features. They are imported only
  under TYPE_CHECKING; the experiment installs no runtime module. Other checkers,
  runtime annotation introspection, packaging and compatibility remain unproven.
- This excludes a known nominal type. It does not certify arbitrary other types or
  mappings as storage-order-safe, and does not solve decimal-over-text ordering.
- The minimal ty patch does not restrict every column-comparison overload, Aggregate
  ordering or derived CTE/expression path. `unrestricted_seams.py.txt` explicitly
  preserves examples of accepted holes. It must not be called complete enforcement.
- Owner/family/result preservation is established only for the tested paths, not
  the entire joins/FK/GenCol/recursive-query compatibility matrix.
- Generic sorting helpers need evidence their value domain excludes ZonedDatetime.
- No consumer casts or Any were needed to make the positive examples pass. Explicit
  Any remains an ordinary gradual-typing escape hatch.
- Keep runtime guards until a separately designed implementation establishes all
  required guarantees. No production behavior changed here.

## Reproduce the ty-specific proof

The `.py.txt` files are deliberately stored as typing fixtures so ordinary package
checks do not mistake expected errors for project errors. From the project root:

```sh
probe=$(mktemp -d /tmp/snekql-601-replay-XXXXXX)
for source in research/static_ordering_601/ty_probe/*.py.txt; do
  name=$(basename "$source" .txt)
  cp "$source" "$probe/$name"
done
uv run ty --version
uv run python "$probe/accept.py"
# Expected exit 1: positive passes; 13 expected ordering errors are missing.
uv run python "$probe/make_overlay.py"
uv run python "$probe/accept.py" --overlay
# Expected exit 0: positive passes; all 20 negative sites diagnosed.
```

`make_overlay.py` copies the real package beneath the temporary directory and edits
only that copy. It must be run from the repository root. Fixtures depend on the
source layout/signatures at this research baseline; they are not a maintained
compatibility tool. Do not apply the retained patches to production as-is.

## Artifacts and scope

- `ty-findings.md`: agent's detailed evidence and remaining proof.
- `ty_probe/`: portable acceptance runner, copied-source policy builder, consumer
  examples, helpers, known holes and original experimental patches.
- `conventional-findings.md`: independent restricted-self findings.
- `conventional/`: comparison patch and consumers. Their original temporary renamed
  package is not vendored here; reproduction details/path remain in the findings.

This research follows the maintainer's explicit request for subagent-led,
public-consumer static probes. Red acceptance preceded restrictions. No backend
execution, dependency changes, broad capability design or runtime implementation.

The result is enough to justify further design work; it does not select the
experimental ty API as a permanent public dependency.
