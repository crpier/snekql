# Review-sheet investigation: promising native designs for #473

2026-10-26. CPython 3.15.0, ty 0.0.84, snekql 0.9.0.
Continuing from `6718fe5`; this round changes research and static tests only.

Read this with the [agreed review sheet](review-sheet.md). The maintainer's
shortlist has **three families**, none selected. This round tests those three,
an explicit-Python variant within the prefix family, and a policy-wrapper
challenger. It does not reopen the abandoned annotation split or its generator.

## Findings and recommendation

The strongest comparison to put in front of the reviewer is:

1. **Separate parameters:** most literal correspondence between a Python initial
   value and `default=`, with a separate SQL fact. More verbose for omission in
   favor of SQL. Native ty has a declaration-validation gap on server-only calls.
2. **Prefixed constructors:** flat, coherent server-supplied declarations. The
   missing-generation-source hole can be closed for the represented forms.
   Within this family, consider explicit **Python/Server prefixes on both
   owners**: they remove implicit ownership without nesting, at the cost of many
   more names. This variation is newly prototyped, not newly approved.
3. **Ownership selector:** compact and natively typed, but the reviewer must
   interpret `default=` through another argument. The conversation already
   exposed this explanatory cost; passing ty does not remove it.

Symmetric value policies remain technically viable but do not earn promotion:
they make both owners explicit while adding `default=PythonDefault(...)` /
`default=ServerDefault(...)` nesting and retaining the existing identity spelling.
The new symmetric-prefix variation offers explicit ownership without that
nesting, though its expanded constructor vocabulary is a different real cost.
These are design judgments for review, not measured fresh-reader preferences.

All five variants pass the eleven core static scenarios, nullable clock
extensions, required GenCol construction, factory arity checks, declaration
negative controls and importing-consumer checks. That does **not** mean all
incoherent declarations are statically rejected, or that runtime behavior works.
The new signatures cover representative Integer/Text declarations, not complete
constructor/storage-option parity, every MariaDB native type, foreign keys,
inheritance/decorator combinations, or every SQL expression/codec pairing.

## Shared meaning of the examples

Each block below gives all eleven declarations. Names are hypothetical public
spellings. Tests use local `Twin*`, `Choice*`, `Policy*` helpers and actual backend
model/descriptor types; no real constructor is changed. Model lifecycle and
`__row_type__` boilerplate is omitted here but present in the fixture.
`UUID`, `uuid4`, and the `db` namespace are assumed imported.

| Field / scenario | Omitted argument: intended initial value | Intended INSERT | Intended SQL |
| --- | --- | --- | --- |
| `required` / R1 | Rejected | Explicit string | NOT NULL, no default |
| `required_nullable` / R2 | Rejected; explicit None accepted | Explicit string or NULL | Allows NULL, no default |
| `python_value` / R3 | `7` | Supplies value | NOT NULL, no default |
| `python_none` / R4 | `None` | Supplies NULL | Allows NULL, no default |
| `python_nullable` / R5 | `"guest"` | Supplies value, including explicit NULL override | Allows NULL, no default |
| `python_factory` / R6 | Factory-produced UUID | Supplies value | NOT NULL, no default |
| `server_value` / R7 | Pending sentinel | Omits column | NOT NULL, literal SQL default False |
| `server_clock` / R8 | Pending sentinel | Omits column | NOT NULL, backend UTC clock default |
| `server_nullable` / R9 | Pending sentinel | Omits column; explicit None supplies NULL | Allows NULL, default `"fallback"` |
| `server_null` / R10 | Pending sentinel | Omits column; explicit None supplies NULL | Allows NULL, DEFAULT NULL |
| `identity` / R11 | Pending sentinel | Omits column; explicit ID supplies value | Primary key + identity, not SQL DEFAULT |

For every declaration, `Col[T]` means Pending/Row both read as T. `GenCol[T]`
means Pending reads as `T | PENDING_GENERATION`, Row as T. All explicit values
must fit that constructor input; None is accepted only for nullable inputs.
For non-nullable server fields, None is rejected rather than interpreted as a
request for the SQL default. Defaults can be overridden with concrete values.

Both the types and constructor acceptance/rejection above are checked. Actual
initial values, per-instance factory evaluation, binding NULL versus omitting,
DDL, SQL execution and schema verification are intended contracts only. No
model module, factory, caller or database workflow is executed. INSERT RETURNING
is checked as an exact `Write[Review[Row]]` type, not run. Pending objects would
not be filled in place; completed Rows would contain concrete values.

## A. Separate Python and SQL parameters — shortlisted

```python
required: db.Col[str] = db.Text()
required_nullable: db.Col[str | None] = db.Text()
python_value: db.Col[int] = db.Integer(default=7)
python_none: db.Col[str | None] = db.Text(default=None)
python_nullable: db.Col[str | None] = db.Text(default="guest")
python_factory: db.Col[UUID] = db.Text(default_factory=uuid4)
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
identity: db.GenCol[int] = db.Integer(
    default=db.PENDING_GENERATION, primary_key=True, auto_increment=True
)
```

Here `default` always describes the Python initial value, including the pending
marker. `server_default` only describes SQL. Omitting `default` makes the Python
input required; it is not a failure of ty to do so.

Both contrast cases naturally work in this round's signatures:

```python
# C1: required in Python; SQL default available to other writers.
value: db.Col[bool] = db.Integer(server_default=False)

# C2: Python supplies False; SQL default True applies if another writer omits it.
value: db.Col[bool] = db.Integer(default=False, server_default=True)
label: db.Col[str] = db.Text(default_factory=lambda: "client", server_default="server")
```

The input/read parameters must remain independent: an initial attempt to
select different return states solely by an overloaded `default` parameter
rejected C2. A red test caught this; explicit typed input/read descriptor
parameters preserve C2 and the negative controls, without Any constructor inputs.
This is signature work, not generation of constructors or caller annotations.

### Static gap: server-only declaration validation

The same native checker accepts all of these:

```python
value: db.Col[int] = db.Integer(server_default="wrong")
name: db.Col[str] = db.Text(server_default=None)
clock: db.Col[str] = db.Text(server_default=db.CurrentTimestamp)
```

Constructor inputs still follow the annotation: the first accepts an int and
rejects a string. That does not validate its SQL default. Registered calls with
no recognized default argument do not provide the same contextual declaration
checks in these experiments. Runtime validation would need to check these
mismatches. No claim is made that all possible native signatures must have this
limitation; the probes establish it for the tested design.

With explicit Python defaults present, the tested signatures reject mismatched
Python and SQL default types, incompatible NULL, and wrong clock types.

## B. Ownership selector — shortlisted

```python
required: db.Col[str] = db.Text()
required_nullable: db.Col[str | None] = db.Text()
python_value: db.Col[int] = db.Integer(default=7)
python_none: db.Col[str | None] = db.Text(default=None)
python_nullable: db.Col[str | None] = db.Text(default="guest")
python_factory: db.Col[UUID] = db.Text(default_factory=uuid4)
server_value: db.GenCol[bool] = db.Integer(default=False, default_on="server")
server_clock: db.GenCol[db.UtcDatetime] = db.Text(
    default=db.CurrentTimestamp, default_on="server"
)
server_nullable: db.GenCol[str | None] = db.Text(
    default="fallback", default_on="server"
)
server_null: db.GenCol[str | None] = db.Text(default=None, default_on="server")
identity: db.GenCol[int] = db.Integer(
    default=db.PENDING_GENERATION, primary_key=True, auto_increment=True
)
```

The default mode is Python; writing `default_on="python"` is also supported.
The new prototype uses `"server"`, not the historical `"database"` spelling.
In server mode, the value after `default=` is a SQL default, **not** the Python
initial value. Omission still leaves the sentinel, and ty still sees the Pending
union. Identity retains Python pending-default syntax; the selector must not
make an identity into a SQL DEFAULT.

Invalid selector strings, server mode without a value, Python factories in
server mode, and simultaneous value/factory declarations are statically rejected.
Wrong field states and default types are also rejected in the typed examples.

C1/C2 are not expressed by these signatures: there is one selected default
owner, and server mode makes construction omittable. This is a limitation of
this prototype, not a decision to prohibit coexistence or proof of impossibility.

## C. Prefixed server constructors — shortlisted

```python
required: db.Col[str] = db.Text()
required_nullable: db.Col[str | None] = db.Text()
python_value: db.Col[int] = db.Integer(default=7)
python_none: db.Col[str | None] = db.Text(default=None)
python_nullable: db.Col[str | None] = db.Text(default="guest")
python_factory: db.Col[UUID] = db.Text(default_factory=uuid4)
server_value: db.GenCol[bool] = db.ServerInteger(False)
server_clock: db.GenCol[db.UtcDatetime] = db.ServerText(db.CurrentTimestamp)
server_nullable: db.GenCol[str | None] = db.ServerText("fallback")
server_null: db.GenCol[str | None] = db.ServerText(None)
identity: db.GenCol[int] = db.ServerInteger(primary_key=True, auto_increment=True)
```

Server helpers are deliberately **not registered field specifiers**. Ordinary
constructors stay registered so their no-default forms stay required. Native ty
recognizes the server descriptor assignments as defaults; no generated typing
information is required.

### Improvement: close the missing-source hole

A red test first reproduced acceptance of `ServerInteger()` and
`ServerInteger(auto_increment=False)` by the older overloads. The new signatures
reject both. A server integer declaration must provide a value or select the
represented identity form with literal True primary-key/auto-increment flags.
An identity returns an integer generated column, not arbitrary logical T.

This is a **narrow prototype**, not complete storage-option parity. It does not
cover external generators, dynamic boolean identity flags, non-primary-key
MariaDB identity/index configurations or all SQLite implicit-rowid forms. It
also does not introduce a policy on all SQL-default/identity combinations.
These would need deliberate extensions, not a broad catch-all overload.

C1/C2 are not expressed by this server helper. They would need extensions.

### Promising variation: explicitly prefix both owners

Keep required declarations and all server declarations exactly as above, but
replace the four optional Python declarations:

```python
python_value: db.Col[int] = db.PythonInteger(7)
python_none: db.Col[str | None] = db.PythonText(None)
python_nullable: db.Col[str | None] = db.PythonText("guest")
python_factory: db.Col[UUID] = db.PythonText(factory=uuid4)
```

Now every defaulted declaration names its owner, without value-wrapper nesting
or a selector changing the meaning of `default`. Unlike the earlier blocked
**registered** `PythonInteger(python_default=...)`, these are **unregistered**
functions returning typed ordinary descriptors. Required ordinary constructors
remain registered. This new variant passes all the same review tests.

`PythonInteger()` and `PythonText()` are rejected: there must be a value or
factory. A value plus factory is also rejected. The names are provisional;
`DefaultInteger` without an owner remains ambiguous between Python and SQL.

Trade-off: roughly two additional constructor families per storage primitive,
including the larger MariaDB namespace. Shared implementation can avoid code
duplication, but cannot remove the public vocabulary cost. This variation is
not a fourth maintainer-approved shortlist item or an accepted design.

## D. Explicit value policies — challenger only

```python
required: db.Col[str] = db.Text()
required_nullable: db.Col[str | None] = db.Text()
python_value: db.Col[int] = db.Integer(default=db.PythonDefault(7))
python_none: db.Col[str | None] = db.Text(default=db.PythonDefault(None))
python_nullable: db.Col[str | None] = db.Text(default=db.PythonDefault("guest"))
python_factory: db.Col[UUID] = db.Text(default=db.PythonDefault(factory=uuid4))
server_value: db.GenCol[bool] = db.Integer(default=db.ServerDefault(False))
server_clock: db.GenCol[db.UtcDatetime] = db.Text(
    default=db.ServerDefault(db.CurrentTimestamp)
)
server_nullable: db.GenCol[str | None] = db.Text(default=db.ServerDefault("fallback"))
server_null: db.GenCol[str | None] = db.Text(default=db.ServerDefault(None))
identity: db.GenCol[int] = db.Integer(
    default=db.PENDING_GENERATION, primary_key=True, auto_increment=True
)
```

Both owners are explicit and the policy helpers are shared across storage types.
Raw values/clock markers are rejected by the earlier policy-only signatures.
The identity is an existing-constructor control, not a new policy shorthand;
that deliberate exception limits the claim that every default is uniformly a
policy. No new generation policy or coexistence machinery is added.

## Cross-cutting nonsense, constraints and false positives

| Case | Observed result |
| --- | --- |
| Wrong Python value or factory result type | Rejected in all five variants |
| Factory requires an argument | Rejected in all five variants |
| Non-nullable field with a None default | Rejected in tested defaulted forms |
| Server-defaulted Pending field incorrectly annotated plain Col | Rejected in tested server-omission forms |
| Wrong SQL literal or clock type with server omission | Rejected in all five variants |
| Nullable clock accepts explicit None but must not claim None-only Rows | Accepted/rejected correctly in all five variants |
| Wrong SQL default type with **required** Python input | Accepted gap in split variant; other variants do not express C1 |
| No generation source in `ServerInteger()` | Rejected by tightened prefix, previously accepted |
| Server selector without a default, invalid selector, Python factory in server mode | Rejected |
| Required `GenCol` without a construction default | Required in all five; explicit value/sentinel accepted |
| Backend-invalid storage/expression/configuration | Not generally certified; runtime validation remains necessary |

The nullable clock extension initially failed for split/selector/prefix and was
fixed under red tests without adding another caller-visible nullable flag. Its
clock overloads allow the optional None component while retaining UTC in the
result. A None-only Row and a str Row are rejected. The policy wrapper already
supported this case through contextual inference. These results do not certify
all SQL expression types or every logical/storage combination.

A remaining generation gap must not be hidden: preserving existing required
`GenCol` behavior permits a caller to pass the sentinel without a source of
generation declared in that field. Existing ordinary
`GenCol[int] = Integer(default=PENDING_GENERATION)` can likewise request omission
without declaring a generator. C3 is about requiredness/type truthfulness, not a
proof that SQL can fill the value. The prefix-source fix does not eliminate
these routes or certify INSERT success. Define validation of declared/external
generation before production implementation, rather than silently changing
GenCol's current meaning.

## Compatibility and behavioral acceptance

No existing source changes meaning in this branch. Any eventual design needs
an explicit migration policy; current raw `default=False` must never silently
become SQL DEFAULT False. The selector's omitted mode is Python in this
prototype. Whether to require explicit modes or explicit Python prefixes is
open, not a compatibility decision hidden in the test signatures.

Before production work, specify evaluation timing, factory frequency, strict
None semantics, pending omission, overrides, Row retrieval, DDL and verification
agreement. The review table records intended behavior, not runtime proof. The
maintainer excluded database runtime tests from this research.

## Reproduction and evidence

```sh
uv run snektest tests/research
uv run ty check
uv run ruff check .
uv run ruff format --check .
git diff --check
```

This round adds **66 paired native-ty checks**, across both namespaces. Each
valid control is independently clean; challenges must have exactly the marked
rules/lines. Importing consumers explicitly check their model modules too.
Accepted-gap observations retain wrong-constructor-input negative controls so
precise construction cannot be confused with SQL-default validation.

The complete research suite has **156 passing tests**: 146 static pairs and
10 historical parser rejection cases. Some historical tests intentionally
record blocked approaches. No SQL/runtime suite, dependency changes, production
changes, generated typing workflow or GitHub Actions wait.

Files: `review_baseline.py.txt`, `review_misuse.py.txt`,
`review_split_contrasts.py.txt`, `review_declarations.py.txt`, the existing
`policy_declarations.py.txt`, and `tests/research/test_defaults_review.py`.
