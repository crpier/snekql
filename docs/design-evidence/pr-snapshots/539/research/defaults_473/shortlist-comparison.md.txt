# Compare the shortlist, including keeping the current interface — #473

2026-10-26. Continuing research commit `066e3ae`. No final public interface selected.

**Subsequent maintainer direction:** an interface change is now considered
worthwhile, with separate parameters favored for brownfield flexibility and
independent Python/SQL policies. The conservative recommendation below is
historical and superseded by that reprioritization. The scenario evidence remains
relevant; C1/C2 carry more weight under the clarified goal. See the
[latest direction](README.md) and [new callable-intersection omission prototype](callable-intersections.md).
The latter removes pending boilerplate from common split declarations with an
explicit required-input exception; the syntax snapshots below predate it.

This report records the **earlier four-way decision comparison**, superseding the
ranking in [the preceding investigation](review-results.md). At that stage the
maintainer considered separate parameters shortlist-worthy, was unsure about the
selector, and was not enthusiastic about prefixes. The compared options were:

- **Keep current:** plain Python values/factories, `LiteralDefault` for SQL
  literals, `CurrentTimestamp` for SQL clocks, and explicit pending for identity.
- **Separate parameters:** Python `default` and SQL `server_default`.
- **Selector:** `default_on="python"` / `"server"`, with Python as the default mode.
- **Server prefixes:** ordinary constructors plus `ServerInteger` / `ServerText`,
  retained for completeness but lower preference, not promoted by new names.

Symmetric prefixes, value policies, outer wrappers and namespaces remain prior
research, not new contenders in this comparison. The annotation split and its
typing generator remain abandoned. Names for unimplemented choices are provisional.

## Original summary judgment (recommendation superseded)

There is no core-capability winner: **all four cover R1–R11 with truthful native
Pending/Row typing in the tested declarations.** The decision is predominantly
about how callers recognize ownership and how much interface change that buys.

- **Current is a credible final choice**, not a temporary defeat. It has the
  smallest change cost, compact declarations, and existing runtime implementation.
  Its weakness is the demonstrated need to recognize value markers as ownership
  signals. Keeping it leaves that learning cost; it does not erase the evidence
  in #473. Better explanations/examples can be pursued without inventing an
  interface, but this comparison does not establish that documentation alone
  resolves the misunderstanding.
- **Separate parameters are best for literal, independent statements of Python
  initial state and SQL schema.** Every `default` is a Python initial value,
  including pending. The common server-omission case exposes the lifecycle
  sentinel and repeats two facts. C1/C2 fall out naturally; that is useful where
  needed, not a reason to reward independently configurable settings by itself.
- **The selector is the most targeted change for uniform ownership wording.**
  A SQL literal and a SQL clock use the same explicit `"server"` qualifier, with
  no extra constructor family and no explicit pending marker for those defaults.
  Like the current design, the entire expression determines what `default`
  means. It is flatter for literals, not universally shorter; clocks get longer.
  Qualifying a parameter with another parameter is not inherently misleading.
- **Prefixes make the whole server-supplied declaration clear**, including the
  represented identity form, but expand the public storage-constructor vocabulary.
  Given the maintainer's preference, their concise syntax is not enough to rank
  them ahead of the other choices. Do not keep proposing prefix variants.

**Recommendation at that stage:** retain the current interface as the no-change reference and
compare any proposed change against it, not just against the other proposals.
If uniform owner wording is worth a change, favor the selector for that purpose.
If explicit Python state is the priority, favor separate parameters. On the
current evidence, neither benefit is established strongly enough to say a
change is required. Keeping current is my conservative decision today, with
selector versus separate parameters the actual change decision for the maintainer.
This is advice for review, not a recorded interface decision.

## 1. R1–R6: identical declarations in all four choices

```python
# R1: required, non-nullable
required: db.Col[str] = db.Text()
# R2: required, nullable
required_nullable: db.Col[str | None] = db.Text()
# R3: Python value
python_value: db.Col[int] = db.Integer(default=7)
# R4: Python None
python_none: db.Col[str | None] = db.Text(default=None)
# R5: nullable Python value
python_nullable: db.Col[str | None] = db.Text(default="guest")
# R6: Python factory
python_factory: db.Col[UUID] = db.Text(default_factory=uuid4)
```

`db` denotes either backend. Normal model lifecycle/row-type boilerplate is in
`review_baseline.py.txt`; these examples omit it. The current choice uses actual
`db.Model`, `Integer` and `Text` without a research metaclass or replacement
constructor. The three other choices use the preceding native signature fixtures.

| Scenario | Omission / intended initial value | Explicit values and None | Pending type | Intended INSERT / SQL | Row type |
| --- | --- | --- | --- | --- | --- |
| R1 | Rejected | str accepted, None rejected | str | Supplies input; NOT NULL, no default | str |
| R2 | Rejected | str or None accepted | str or None | Supplies input/NULL; nullable, no default | str or None |
| R3 | Concrete 7 | int accepted, None rejected | int | Supplies value; NOT NULL, no default | int |
| R4 | None | str or None accepted | str or None | Supplies value/NULL; nullable, no default | str or None |
| R5 | Concrete guest | str or None accepted | str or None | Supplies value/NULL; nullable, no default | str or None |
| R6 | Factory-produced UUID | UUID accepted, None rejected | UUID | Supplies value; NOT NULL, no default | UUID |

Nullability never supplies an omission default by itself. R4 and R5 share a type
but differ on omission. No option improves these six declaration forms in the
versions under review.

## 2. R7–R10: where ownership is expressed

Common annotations, in every choice:

```python
server_value: db.GenCol[bool]
server_clock: db.GenCol[db.UtcDatetime]
server_nullable: db.GenCol[str | None]
server_null: db.GenCol[str | None]
```

### Keep current — implemented interface

```python
server_value: db.GenCol[bool] = db.Integer(default=db.LiteralDefault(False))
server_clock: db.GenCol[db.UtcDatetime] = db.Text(default=db.CurrentTimestamp)
server_nullable: db.GenCol[str | None] = db.Text(default=db.LiteralDefault("fallback"))
server_null: db.GenCol[str | None] = db.Text(default=db.LiteralDefault(None))
```

Ownership is in the kind of value passed to `default`. Literal and clock forms
are different markers. The current term `LiteralDefault` does not itself say
"server", and Python values are also literals: callers must learn the marker.
After that rule is known, the declarations are compact and retain the established
runtime/DDL/verification route.

### Separate parameters — prototype

```python
server_value: db.GenCol[bool] = db.Integer(
    default=db.PENDING_GENERATION, server_default=False
)
server_clock: db.GenCol[db.UtcDatetime] = db.Text(
    default=db.PENDING_GENERATION, server_default=db.CurrentTimestamp
)
server_nullable: db.GenCol[str | None] = db.Text(
    default=db.PENDING_GENERATION, server_default="fallback"
)
server_null: db.GenCol[str | None] = db.Text(
    default=db.PENDING_GENERATION, server_default=None
)
```

SQL ownership is in a named channel; construction state is explicit in another.
`server_default` alone would leave Python input required, not silently grant
omission. The sentinel is load-bearing for the tested registered signatures.

### Selector — prototype

```python
server_value: db.GenCol[bool] = db.Integer(default=False, default_on="server")
server_clock: db.GenCol[db.UtcDatetime] = db.Text(
    default=db.CurrentTimestamp, default_on="server"
)
server_nullable: db.GenCol[str | None] = db.Text(
    default="fallback", default_on="server"
)
server_null: db.GenCol[str | None] = db.Text(default=None, default_on="server")
```

SQL ownership is a qualifier shared by every SQL default. `False` is a SQL
fallback, not the initial Python value. Both this choice and the current choice
require interpreting the entire default expression; the distinction is explicit
owner wording versus marker recognition, not conditional versus unconditional
semantics. Python mode can be written explicitly but is implicit in R1–R6.

### Server prefixes — prototype, lower preference

```python
server_value: db.GenCol[bool] = db.ServerInteger(False)
server_clock: db.GenCol[db.UtcDatetime] = db.ServerText(db.CurrentTimestamp)
server_nullable: db.GenCol[str | None] = db.ServerText("fallback")
server_null: db.GenCol[str | None] = db.ServerText(None)
```

Ownership is in the constructor. No nested literal marker or explicit pending
argument is needed. This buys short, clear server forms at the expense of an
additional storage-constructor family. Ordinary Python ownership stays implicit.

### Identical R7–R10 behavior contract, all four choices

Let PG mean `db.PENDING_GENERATION` in this table only.

| Scenario | Omission / intended initial value | Explicit values and None | Pending type | Intended INSERT / SQL | Row type |
| --- | --- | --- | --- | --- | --- |
| R7 | PG, not False | bool accepted, None rejected | bool or PG | Omits if pending; NOT NULL, DEFAULT False | bool |
| R8 | PG, not a Python clock result | UTC timestamp accepted, None rejected | UtcDatetime or PG | Omits if pending; NOT NULL, backend UTC clock default | UtcDatetime |
| R9 | PG, not fallback or None | str or None accepted | str or None or PG | Omits if pending; nullable, DEFAULT fallback | str or None |
| R10 | PG, not None | str or None accepted | str or None or PG | Omits if pending; nullable, explicit DEFAULT NULL | str or None |

In every row, an explicit concrete value is supplied to INSERT and overrides
the fallback. In R9/R10, explicit None supplies SQL NULL; it does not request
the SQL default. Even when R10's omitted and explicit-NULL inserts would both
produce NULL, their Pending states and INSERT shapes are intentionally distinct.

The nullable-clock extension follows R9 using `GenCol[UtcDatetime | None]`:
omission is pending, an explicit timestamp overrides, and explicit None means
NULL. All four accept its constructor/types. Current ty additionally admits
wrong clock declarations, recorded below; successful construction typing does
not validate that a SQL clock can produce the declared logical type.

## 3. R11: generated identity is not a SQL default

Current, separate and selector use the same declaration:

```python
identity: db.GenCol[int] = db.Integer(
    default=db.PENDING_GENERATION, primary_key=True, auto_increment=True
)
```

Prefixes use:

```python
identity: db.GenCol[int] = db.ServerInteger(primary_key=True, auto_increment=True)
```

All four: omission means pending; explicit int IDs are accepted by the typing
probe, subject to backend runtime support; explicit None is rejected. Pending
reads as `int | PENDING_GENERATION`, Row as int. INSERT omits pending, supplies
an override, and the intended SQL declares an identity/primary key rather than
an SQL DEFAULT.

The selector does not eliminate the pending marker for identity: the selector
qualifies an actual default value, not the independent identity mechanism. This
is a real asymmetry compared with its literal/clock forms, shared with current.
The prefix covers both under "server", with a larger public vocabulary.

## 4. Contrast cases: capability, not extra points by themselves

| Case | Current | Separate | Selector | Prefix |
| --- | --- | --- | --- | --- |
| C1: required Python input, SQL default for other writers | Not expressed by current public default form | Natural | Not expressed by tested form | Not expressed by tested form |
| C2: concrete Python value/factory and SQL default | Not expressed by current public default form | Natural | Not expressed by tested form | Not expressed by tested form |
| C3: required GenCol accepting explicit value or PG | Yes | Yes | Yes | Yes |

Separate examples, already checked with negative controls:

```python
required: db.Col[bool] = db.Integer(server_default=False)
both: db.Col[bool] = db.Integer(default=False, server_default=True)
factory: db.Col[str] = db.Text(
    default_factory=lambda: "client", server_default="server"
)
```

C3 example, all four choices:

```python
value: db.GenCol[str] = db.Text()
# Entry(value="given") and Entry(value=db.PENDING_GENERATION): accepted
# Entry(): rejected
```

C3 is about construction requiredness; it does not prove SQL generation exists.
Coexistence in the other proposed families might be extended, but no machinery
or new contender is added to make those cells say yes. Current rejects supplying
both a default marker and a factory through its public signatures.

## 5. Nonsense audit: don't reward prettier syntax with unearned guarantees

These are exact native-ty observations on both backends, not guesses from names.

| Case | Current | Separate | Selector | Prefix |
| --- | --- | --- | --- | --- |
| Wrong Python value, None, factory result | Rejects tested mismatches | Rejects | Rejects | Rejects |
| Factory needing an argument | Rejects | Rejects | Rejects | Rejects |
| Wrong SQL literal type / NULL on non-nullable field, with omission | Rejects tested mismatches | Rejects | Rejects | Rejects |
| Server-omission form assigned to plain Col | Rejects | Rejects | Rejects | Rejects |
| Clock assigned to GenCol[str] or GenCol[None] | **Accepts** | Rejects in omission form | Rejects | Rejects |
| Wrong SQL literal/NULL/clock with required Python input (C1) | No C1 form | **Accepts** in tested signatures | No C1 form | No C1 form |
| Generation requested without a declared source | **Accepts** omission via default=PG and explicit PG via C3 | **Accepts** explicit PG via C3 | **Accepts** explicit PG via C3 | **Accepts** ordinary default=PG and explicit PG via C3 |
| No source in ServerInteger() / disabled generation | No such helper | No such helper | No such helper | Rejects tightened helper forms |
| Invalid selector / missing value / Python factory in server mode | No selector | No selector | Rejects | No selector |
| Default value plus factory in one declaration | Rejects | Rejects | Rejects | Ordinary Python constructor rejects |
| Backend-invalid storage/configuration/expression | Runtime checks still needed | Runtime checks still needed | Runtime checks still needed | Runtime checks still needed |

Current's accepted clock declarations include:

```python
wrong: db.GenCol[str] = db.Text(default=db.CurrentTimestamp)
null_only: db.GenCol[None] = db.Text(default=db.CurrentTimestamp)
```

Their constructor inputs and Row types accurately reflect those incorrect
annotations. That is not evidence the SQL expression can produce those values.
Production source contains a UTC-type guard in `snekql/storage.py`; this round
does not execute it. A type-checker false negative is not runtime acceptance.

Separate's accepted C1 mismatches include:

```python
wrong: db.Col[int] = db.Integer(server_default="wrong")
null: db.Col[str] = db.Text(server_default=None)
clock: db.Col[str] = db.Text(server_default=db.CurrentTimestamp)
```

These still have precise constructor input types. They need runtime declaration
validation in the tested signatures. No impossibility claim is made about
improving those signatures.

All four retain a route to requesting generation without a declared source,
including explicit sentinel inputs to required GenCol fields. That may rely on
external generation or lead to an INSERT failure. Do not silently redefine
GenCol, which describes lifecycle states, to claim source validation. The prefix
helper closes one shorthand hole; it does not close the complete interface.
Its literal-True identity overloads also support fewer configurations than the
current constructors; a restrictive prototype is not complete backend parity.

**Keep typing improvements separate from interface merits.** The prototypes'
stricter clock overloads or generation checks do not require their spellings to
be inherently sounder. Equivalent tightening might be possible without a public
syntax change. No such production improvement is implemented here.

## 6. Does it address the observed #473 mistake?

The mistaken declaration was:

```python
done: db.Col[bool] = db.Integer(default=False)
```

It was paired with separately authored SQL declaring DEFAULT 0. The current
verifier correctly found the mismatch. **This declaration is still a valid
Python-only default in every option under comparison.** No proposed option
makes the original misunderstanding impossible.

What changes is the server form the caller must discover:

- Current: `default=db.LiteralDefault(False)`.
- Separate: `default=db.PENDING_GENERATION, server_default=False`.
- Selector: `default=False, default_on="server"`.
- Prefix: `db.ServerInteger(False)`.

Separate/selector/prefix explicitly say server. Current requires marker
recognition. That is a concrete potential clarity benefit, not a static
prevention guarantee or an experimentally established preference. One observed
misunderstanding is evidence against assuming current is self-explanatory; it
is not by itself proof that any proposed replacement will prevent confusion.

## 7. Compatibility and change cost are part of the review

- **Current:** no implementation/migration required for keeping the interface;
  no pending/default semantics silently change. Typing/documentation improvements
  could be considered independently, but are not prerequisites to selecting it.
- **Separate / selector:** unimplemented replacements in these fixtures. Existing
  marker calls are not covered by their new overload sets. Compatibility would
  require an explicit retention/deprecation policy and additional branches/tests.
  "Adding a parameter" is not by itself a demonstrated compatible migration.
- **Prefix:** existing ordinary constructors remain unchanged in this prototype,
  so an additive introduction is plausible. Replacing/removing old marker forms
  would still require a policy. Helper count, exported namespace and backend
  coverage are genuine costs, even if implementation can be shared.

No compatibility policy is chosen. In particular, bare `default=False` must not
silently acquire an SQL default. Proposed runtime lowering, factory evaluation,
NULL binding, omission, DDL and verification agreement must be validated before
production implementation; existing behavior is not re-executed in this round.

## 8. Evidence and scope

Only the already agreed declaration/construction and consumer-typing seams are
used. The same baseline fixture covers R1–R11, exact Pending/Row types, explicit
overrides, frozen assignment, Pending-only construction and INSERT RETURNING.
Current uses real backend constructors and models, not substitute signatures.
Importing consumers, factory arity, required GenCol, accepted clock/source gaps,
and the plain Python False declaration have exact paired controls too.

This continuation adds **22 paired checks**, bringing the research suite to
**178 passing tests**: 168 static pairs and 10 historical parser rejection tests.
Current's accepted gaps are retained in clean controls alongside exact bad-input
rejections; they are not counted as rejected declarations. Older experiments
remain evidence only. CPython 3.15.0, ty 0.0.84, snekql 0.9.0.

```sh
uv run snektest tests/research
uv run ty check
uv run ruff check .
uv run ruff format --check .
git diff --check
```

No model template, factory, caller, SQL or database workflow is executed. The
initial values/SQL tables are current semantics or intended contracts, not new
runtime proof. No dependency/production changes, generated typing route,
comprehensive storage/foreign-key/inheritance certification or Actions wait.
