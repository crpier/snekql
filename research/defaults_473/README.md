# Default declaration experiments — #473

Research for [issue #473](https://github.com/crpier/snekql/issues/473), dated
2026-10-25. This is **not an accepted interface proposal**, a production change,
or authorization for a breaking change. Names below are experimental.

## Latest direction

The maintainer now considers an interface change worthwhile and favors **separate
Python `default` / SQL `server_default` parameters** for brownfield flexibility:
other writers use the same database, so Python construction and SQL defaults
must be independently expressible. Different values such as Python False and
SQL True are not inherently incoherent. **Final spelling, compatibility policy,
full semantics and production implementation remain unselected.**

Continue investigating shorter generated-field declarations within that direction,
without expanding the public design families or reviving generated constructors.
A [new callable-intersection prototype](callable-intersections.md) now passes
R1–R11 without repeated pending-default arguments, including identity, with
stock ty. Required ordinary/defaultless fields stay required. The trade-off is
an explicit constructor-required override for SQL-default/required-input cases;
it is checker-sensitive research, not a selected public contract or runtime proof.

[The prior shortlist comparison](shortlist-comparison.md) reviews current,
separate parameters, selector and server prefixes using
[the same review sheet](review-sheet.md). Its evidence remains useful, but its
conservative keep-current recommendation predates and is superseded by the
maintainer's increased weight on independent Python/SQL policies. Current remains
a reference for behavior and migration, not the latest recommendation.

For a **scenario-first Python view**, read [`scenarios.py`](scenarios.py): each
scenario places current, separate parameters and selector declarations together;
invalid cases, accepted gaps and surprising valid forms are grouped at the end.
It is a non-executing visual document, not a production module. Its eleven core
scenarios are also extracted into the existing native typing/consumer checks.
This visual sheet retains the earlier split-signature snapshot; the new
intersection variant and its required-input override are documented separately.

The [implicit server-omission follow-up](implicit-server-omission.md) probes
whether separate parameters can omit the explicit pending default. Six native
mechanisms are checked with required-input and override controls. None of those six satisfies the full desired contract; this is not an
impossibility result. The later callable-intersection result is a different
mechanism, with its own explicit required-input exception.

The [preceding investigation](review-results.md) and its extra variants are
historical evidence, not the current ranking. The annotation-left / SQL-right
split and its generated-typing route are abandoned. Validate locally; do not
wait for GitHub Actions.

The [source-informed omission follow-up](native-omission-hooks.md) traces the
published ty 0.0.84 implementation and adds five paired mechanisms/controls plus
two identity controls on each backend. Registering `__new__` can preserve
requiredness, but does not infer omission; a typed unpack works only by supplying
the same explicit default channel. Those hook probes did not remove duplication;
the subsequent callable-intersection prototype combines two callable views to
make the common generated declarations omittable.

## Nullability handoff

The maintainer requested a separate investigation into explicit SQL nullability
versus annotation-derived nullability. [`nullability-handoff.md`](nullability-handoff.md)
is a self-contained prompt for that agent, including current behavior, brownfield
priorities, scenario coverage, static-only constraints and independent-worktree
instructions. No nullability design is selected here.

## Historical first-round follow-up

The maintainer ranks the outer declaration lower for verbosity, without
eliminating it. [The follow-up research](flat-declarations.md) finds flatter
namespace, prefixed-constructor and ownership-selector forms. In particular,
ordinary descriptor-valued defaults provide another omission route: the
recognized-argument restriction below applies to registered field specifiers.
The remaining sections record the first round, not the final shortlist.

## Scope and method

Following maintainer direction, these experiments are **static-only**. They do
not run generated Python callers, open SQLite or MariaDB, generate DDL, insert
rows, or perform schema verification. Runtime implementation is deliberately
left out. No dependency changes are needed.

Environment: CPython 3.15.0, ty 0.0.84, snekql 0.9.0. The starting source revision
is `395f731c58916109a21b606777fb1729543e92a8`. Findings describe this checker and
these signatures, not an impossibility result for all Python typing designs.

Inputs consulted:

- [Current default-marker decision](../../docs/adr/0007-server-defaults-as-default-markers.md).
- [Per-backend declarations](../../docs/adr/0003-per-backend-namespace-column-declarations.md).
- [Storage primitives and logical types](../../docs/adr/0005-storage-primitive-constructors-with-derived-codecs.md).
- [Generated does not mean immutable](../../docs/adr/0006-columns-are-not-immutable.md).
- [Pending/Row model declarations](../../docs/adr/0020-class-body-models-with-pending-and-row.md).
- [Current temporal meanings](../../docs/adr/0022-explicit-temporal-meanings.md).
- [Supported checker and conformance methodology](../../docs/typing-compatibility.md).

The `.py.txt` files are source templates, not importable modules. Tests render
them into temporary `.py` files and invoke ty in subprocesses. Both backends
use their real Model bases, Col/GenCol descriptors, lifecycle states and query
result types. Experimental field-specifier functions are registered through a
research-only subclass of each backend's metaclass; consumers would not need
such a subclass in an implemented design. Their bodies raise
`NotImplementedError` and are never executed.

Each experiment has an independently clean positive file and a challenge file
with exact expected diagnostic lines and rules. Unrelated errors, a checker
crash, or unexpected acceptance fail the test. The prototype functions have
typed descriptor returns: merely returning Any preserved constructor checking
but initially hid invalid declaration defaults. A declaration-level negative
control caught that weakness; the viable prototypes now reject that mismatch.

## Results

| Shape | Omit defaulted field? | Supply explicit value? | Observation |
| --- | --- | --- | --- |
| Existing `Integer(default=LiteralDefault(7))` | Yes | Yes | Baseline |
| `SplitInteger(server_default=7)` | No | Yes | Omission gets `missing-argument` |
| `SplitInteger(server_default=7, default=PENDING_GENERATION)` | Yes | Yes | Viable, but requires both arguments |
| `PythonInteger(python_default=7)` | No | Yes | Renaming Python defaults alone also breaks omission |
| `DatabaseDefault(Integer(), default=7)` | Yes | Yes | Viable outer declaration |
| `Excluded(Integer())`, with implicit `init: Literal[False] = False` | Yes | No | Explicit override gets `unknown-argument` |

The split prototype gives its `default` parameter a Python signature default
of `PENDING_GENERATION`. That **does not** make the constructor field omittable:
ty needs the recognized argument at the registered field-specifier call in
this experiment.
This reproduces the constraint recorded in the earlier ADR.

The two nonstandard-keyword-only forms also accept the deliberately mismatched
field default in the probe (`GenCol[int]` with `server_default="wrong"`, or
`Col[int]` with `python_default="wrong"`), despite typed return annotations.
Those are recorded limitations of these blocked forms, not positive guarantees.
The viable forms reject the corresponding mismatch with `invalid-assignment`.

**Interpretation:** a separate server-default parameter is possible. By itself
it keeps Python input required in the registered field-specifier mechanism;
that is a valid design, not a typing blocker. Explicit `default=PENDING_GENERATION`
is needed only when Python omission should request server generation. A dedicated
outer declaration provides another omission mechanism, not the only alternative.
See the latest review for the required-input and coexistence cases.

## Compare the viable shapes

### A. Existing tagged defaults

```python
attempts: db.GenCol[int] = db.Integer(default=db.LiteralDefault(7))
created_at: db.GenCol[db.UtcDatetime] = db.Text(default=db.CurrentTimestamp)
```

Smallest interface change: none is required for typing. More explicit marker
names or grouping could make the database ownership clearer, but this round
does not test alternative marker naming with fresh readers. It retains the
central issue: the argument's value, rather than the parameter, determines
whether construction or the database supplies the value.

### B. Separate server declarations and Python omission

```python
attempts: db.GenCol[int] = SplitInteger(
    server_default=7,
    default=db.PENDING_GENERATION,
)
created_at: db.GenCol[db.UtcDatetime] = SplitText(
    server_default=db.CurrentTimestamp,
    default=db.PENDING_GENERATION,
)
```

Makes the schema fact explicit. The second argument states the Python
construction behavior, but it is required typing boilerplate for the shown
signatures. An ordinary `default=False` could retain its Python meaning. This
prototype covers the generated/server-default branch only, not a complete set
of replacement constructor overloads.

### C. Dedicated database-default declaration

```python
attempts: db.GenCol[int] = DatabaseDefault(db.Integer(), default=7)
created_at: db.GenCol[db.UtcDatetime] = DatabaseDefault(
    db.Text(), default=db.CurrentTimestamp
)
nullable: db.GenCol[str | None] = DatabaseDefault(db.Text(), default="fallback")
null_default: db.GenCol[str | None] = DatabaseDefault(db.Text(), default=None)
```

The outer declaration supplies the context: `default=` now always refers to a
database default there. It also carries the omission signal ty understands,
without spelling a pending sentinel at the call site. Scalar values and clock
markers have separate typed overloads in the prototype.

Trade-offs: nested declaration syntax, another field-specifier to learn and
register, and rules still needed for an inner column that already declares a
default. This round neither enables nor forbids combining Python and server
defaults. That decision should follow the eventual design rather than select
it in advance.

Ordinary Python defaults and factories retain their existing forms in all
three viable examples:

```python
done: db.Col[bool] = db.Integer(default=False)
token: db.Col[str] = db.Text(default_factory=lambda: "new")
note: db.Col[str | None] = db.Text(default=None)
required_nullable: db.Col[str | None] = db.Text()
```

Generated IDs likewise retain the existing declaration as a control:

```python
id: db.GenCol[int] = db.Integer(
    primary_key=True, auto_increment=True, default=db.PENDING_GENERATION
)
```

This does **not** settle whether generated IDs should get a more direct
expression. Automatic identity generation is not a SQL DEFAULT clause; an
interface named `DatabaseDefault` should not silently conflate them.

## What the static examples establish

For each viable shape, on each backend:

- Python defaults, factories and server defaults permit constructor omission.
- A nullable field without a construction default remains required.
- Explicit overrides are accepted; explicit None is accepted only for nullable
  constructor fields in these examples.
- Pending generated fields retain the pending sentinel in their inferred type,
  including literal, clock, nullable and NULL server defaults.
- Row fields exclude that sentinel and retain the exact logical type.
- Ordinary Python-defaulted/factory fields have concrete Pending value types.
- INSERT RETURNING retains the exact `Write[Example[Row]]` result type.
- Wrong constructor values, a mismatched literal declaration and a factory
  with the wrong return type are rejected. Boolean server-default fields reject
  integer constructor inputs even when their physical storage is INTEGER.

Typing cannot establish that explicit None is actually sent as SQL NULL, that
a factory runs per instance, that inserts omit pending fields, or that DDL and
verification agree. These remain **untested runtime acceptance criteria**, not
claims made by this research. The prototypes are not exhaustive storage,
foreign-key, alias or backend compatibility tests.

## Where this leaves the design

The dedicated outer declaration is worth discussing alongside the explicit
two-parameter form. It addresses the typing obstacle without forcing everyone
to learn why a SQL default also needs a pending Python default. That is a
promising direction, not evidence that humans prefer its nested syntax.

Before selecting a design:

1. Compare realistic model declarations side by side, especially IDs and clocks,
   rather than optimizing only the literal-default example.
2. Decide whether improving marker vocabulary is enough, or whether separating
   declaration forms substantially improves recognition of value ownership.
3. Let Python/server coexistence follow those choices; do not gate designs on it.
4. Specify compatibility explicitly. No existing Python default should silently
   acquire a SQL default, and no server default should silently become eager.
5. Specify construction, SQL omission/NULL, DDL and verification behavior before
   implementing. No migrations or compatibility policy are chosen in this round.

## Reproduce

```sh
uv run snektest tests/research/test_default_declarations.py
uv run ty check
uv run ruff check .
uv run ruff format --check .
```

The focused test command has **18 passing positive/challenge pairs**, across
both backends, taking approximately three seconds locally. It invokes ty only;
it never executes the generated model declarations or database workflows. The
full runtime test suite is intentionally not part of this research validation.
