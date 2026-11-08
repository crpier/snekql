# Design evidence capsules — 2026-11-08

**Historical research, not installed APIs or current usage examples.** This directory
supports the [checkpoint](../design-checkpoint.md) and
[PR inventory](../design-research-index.md). It keeps the strongest small executable
proofs plus concrete failure examples available without merging exploratory branches.

## Archived fixtures

[manifest.json](manifest.json) records each original commit/path, archive path and
SHA-256. The nine fixture files are byte-preserving copies from the recorded PR heads.
They use `.txt` extensions because some deliberately contain invalid consumer code or
experimental copied-source edits. They are not discovered as supported package tests.

- [Unparsed proof](595/proof.py.txt) and its
  [original positive/negative test harness](595/test_unparsed_type_adapter.py.txt),
  from #595. Historically two focused tests passed on ty 0.0.84. The proof produces
  `True int 42 int` and `True str 42 int`; the harness also checks three invalid
  assignments at their exact lines. No runtime Unparsed instance is created.
- [Static-ordering acceptance runner](602/accept.py.txt),
  [temporary-source builder](602/make_overlay.py.txt),
  [positive](602/positive.py.txt), [negative](602/negative.py.txt),
  [positive generic helpers](602/helpers_positive.py.txt),
  [negative generic helpers](602/helpers_negative.py.txt) and
  [known unrestricted paths](602/unrestricted_seams.py.txt), from #602.

These fixtures are not new experiments. Their original results are summarized below;
this consolidation verified archive identity, not a fresh behavior/backend matrix.

### Replaying #602 when separately desired

From a repository checkout with the source layout and pinned ty 0.0.84 used by #602:

```sh
probe=$(mktemp -d /tmp/snekql-ordering-replay-XXXXXX)
for source in docs/design-evidence/602/*.py.txt; do
  name=$(basename "$source" .txt)
  cp "$source" "$probe/$name"
done
uv run python "$probe/accept.py"
# Expected failure: 13 required ordering errors are missing.
uv run python "$probe/make_overlay.py"
uv run python "$probe/accept.py" --overlay
# Expected success: positive controls pass; all 20 negative sites diagnosed.
```

The builder modifies only its temporary copy of snekql. It depends on exact original
source signatures and is not a maintained patching tool. Baseline 13 missing errors
plus seven existing error sites becomes 20 diagnosed sites after restriction. This
is not 20 newly prevented ordering operations. Generic-helper and known-hole fixtures
need their own checker calls; the acceptance runner covers positive/negative.py.

For #595, the original harness expects `research/unparsed_593/proof.py.txt` relative
to the working directory. Restore the archived proof and harness under their original
manifest paths in a disposable checkout before running it with snektest. Don't edit
normal application code or install a nominal Unparsed runtime container to reproduce it.
The selected TypeAdapter supplies its output type; the marker doesn't recover it.

## Defaults: preserve the review criteria and gaps

The original #473 report concerned snekql 0.9.0: a declaration using
`sqlite.Integer(default=False)` was paired with independently written SQL
`DEFAULT 0`. CRUD and static checks passed, but schema verification **correctly
rejected the mismatch**: the declaration supplied a Python default, not the matching
SQL default. This was a declaration misunderstanding, not a verifier failure.
All researched main spellings still permitted a Python-only default; none made that
original misunderstanding statically impossible.

#539 used eleven core column scenarios, with explicit values/NULL and static
Pending/Row controls as well as omission:

| Scenario | Constructor omission | Intended schema |
| --- | --- | --- |
| Required non-null | Rejected | NOT NULL, no default |
| Required nullable | Rejected; explicit None accepted | Nullable, no default |
| Python value default | Concrete value | NOT NULL, no default |
| Python None default | None | Nullable, no default |
| Nullable Python value default | Concrete value; explicit None accepted | Nullable, no default |
| Python factory | Factory result | NOT NULL, no default |
| Server literal default | Pending | NOT NULL, literal default |
| Server expression | Pending | NOT NULL, clock/default expression |
| Nullable server default | Pending; explicit None accepted | Nullable, SQL default |
| Server NULL default | Pending | Nullable, DEFAULT NULL |
| Identity | Pending | Generated identity |

Contrast cases include required Python input despite a SQL default, independent
Python/SQL defaults, defaultless GenCol and explicit overrides. SQL DEFAULT NULL,
Python None and pending omission may store the same NULL but aren't the same policy.

Historical #539 validation reports 224 tests: 214 paired static checks and ten parser
rejection cases. That is not a backend execution total or proof every invalid
combination was rejected. In the native omission workaround:

```text
GenCol[bool] = Integer(server_default=False)                 accepted, omittable
Col[bool]    = Integer(server_default=False)                 rejected
Col[bool]    = Integer(server_default=False, required=True)  accepted, required
```

This moves the extra spelling to the required-input case; it doesn't prove annotation-
only omission inference. The maintainer later rejected its standalone trade-off.

At that same research head, these **bad SQL declarations were accepted statically**
while constructor input types were still checked:

```text
Col[int] = Integer(server_default="wrong", required=True)
Col[str] = Text(server_default=None, required=True)
Col[str] = Text(server_default=CurrentTimestamp, required=True)
```

These are prototype gaps, not a claim all three are impossible database declarations
under every future independent schema contract. The clock/string combination in
particular doesn't establish the required temporal contract.

## Nullability: different contracts and over-rejection

#583 reported 18 paired static tests (nine scenarios × two namespaces), without model
or database execution. It distinguished:

- `Col[str]` over nullable storage: inputs and successful Rows stay strings; reading
  externally stored NULL must fail validation.
- Experimental `Col[str, str | None]`: inputs stay strings; successful Rows can include
  NULL. This is another contract, not an accepted public alias arity.

Historical source inspection in #583, at its baseline `46b2342`, found physical
nullable checks also affected input/read None handling (`snekql/storage.py` input
paths around lines 1474–1480/1536–1539 and read paths around 1346–1395/1542–1571).
This is not a fresh confirmation of today's implementation. That audit established
an obligation: removing only the declaration agreement guard isn't enough if those
paths bypass a non-null logical contract. Any implementation must demonstrate the
non-null successful Row guarantee, regardless of the chosen spelling.

One prototype rejected the following despite its legitimate schema-only fallback:

```text
Col[str] = Text(default="client", server_default=None, nullable=True)
```

Other writers could receive NULL; the strict application could supply a string and
reject NULL on reads. Over-rejecting this is a producer-signature gap, not a reason
to call independent policies nonsense. Required paths also accepted some mismatched
SQL defaults/unrelated read-domain declarations. Green tests included gap witnesses.

## Pydantic: strictness, representation and serializer evidence

#594 was source/upstream-test inspection, not an executed local strictness matrix.
#597 later reported 120 synthetic Pydantic cases and #598 reported 57 composition cases.
None was a native database query suite.

The retained interpretation is:

| Input "42" | Declared policy | strict=True | Forced strict=False (not a selected mode) |
| --- | --- | --- | --- |
| int | Produces 42 | Rejects | Produces 42 |
| StrictInt | Rejects | Rejects | Produces 42 |

Declared validators still run under strict mode. Before-validation conversions are
part of the contract only when explicitly declared; Python/JSON entry points differ.
#598's global SQL-read context propagated into nested JSON, allowing integer `[1]`
through a context-sensitive strict Boolean payload. Its non-idempotent-validator
controls also exposed repeated logical validation. Those are concrete reasons not
to assume an operation-wide phase flag or parse-then-revalidate composition is safe.

#600 reported 30 focused cases on Python 3.15.0/Pydantic 2.14.0. For strict Decimal
with max_digits=5 and decimal_places=2, 1.23/1.2300/999.99 and scaled zero passed;
1.234/1000/non-finite values and float inputs failed in the tested cases. A small
AfterValidator retained millisecond-aligned datetime objects and rejected excess
fractions. These are reusable application constraints, not all-backend fitting proofs.

The serializer counterexample is important even though extra runtime hooks were
subsequently rejected:

```text
Logical contract: Decimal, five digits, two decimal places
Validated value:  Decimal("1.23")
Custom serializer output: "1.234"
dump_python(..., warnings="error"): succeeds
```

Serialization output type checking isn't destination-fit validation. Also, a
serializer that rounds to a fitting but changed value defeats a fit check. Preserve
this limit without resurrecting the rejected extra checking layer.

## Static ordering: bounded success, not general capabilities

The archived ty proof uses Intersection/Not and a covariant value witness to exclude
nominal ZonedDatetime. It does not derive capabilities from Annotated metadata.
It preserves tested ordinary declarations, supported ordering, equality/membership,
Pending/Row types and selected owner/family/result types. Calls with discarded results
still receive errors; returning Never alone would not prove prevention.

Its known-hole fixture allows column comparisons and explicitly constructed aggregate
ordering outside the minimal restrictions. Arbitrary derived-query propagation and
Decimal text versus native storage are unproven. The independent Python-__lt__ receiver
proof is not the general rule: Python comparability doesn't establish storage ordering.

## How to use this capsule

Use these observations as regression oracles and design constraints, not final public
signatures. Exact full report revisions and additional fixture paths are in the
[research inventory](../design-research-index.md). Before retiring other drafts,
select any additional executable controls worth keeping. No raw research archive here
changes runtime behavior, extends backend support or authorizes PR retirement.
