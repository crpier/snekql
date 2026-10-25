# Explicit default policies — native typing, no left/right split

Research for #473, 2026-10-26. Supersedes the left/right split as the active
investigation, not as an accepted interface. Static-only; no production change.

## Maintainer direction

Stop pursuing the annotation-left / SQL-right split, including its generated
typing route. Native constructor optionality did not work, and independent
settings admitted declarations the maintainer found unhelpful, such as an
ordinary required `Col[bool]` with a SQL default.

Do not optimize for expressing every independent combination. Optimize for a
small set of useful, understandable declarations with honest lifecycle types.
Existing experiments remain historical evidence, not active recommendations.

## Candidate: make both default owners explicit

Illustrative public spellings, not existing exports:

```python
# Required field.
quantity: db.Col[int] = db.Integer()

# Python supplies the value when the constructor argument is omitted.
done: db.Col[bool] = db.Integer(default=db.PythonDefault(False))
token: db.Col[str] = db.Text(default=db.PythonDefault(factory=make_token))

# Python leaves a pending value; SQL supplies it on insertion.
server_done: db.GenCol[bool] = db.Integer(default=db.ServerDefault(False))
created_at: db.GenCol[db.UtcDatetime] = db.Text(
    default=db.ServerDefault(db.CurrentTimestamp)
)

# SQL NULL is distinct from a Python construction default of None.
python_null: db.Col[str | None] = db.Text(default=db.PythonDefault(None))
server_null: db.GenCol[str | None] = db.Text(default=db.ServerDefault(None))
```

This is a **symmetric tagged-default design**, not a new typing mechanism. Its
value over the existing design must come from removing implicit ownership:

| Today | Candidate |
| --- | --- |
| `default=False` implicitly means Python | `default=PythonDefault(False)` names Python |
| `default=LiteralDefault(False)` means SQL | `default=ServerDefault(False)` names the server |
| Bare `default=CurrentTimestamp` is a special SQL case | Clock also goes inside `ServerDefault(...)` |
| `default_factory=make_token` is a separate Python channel | `default=PythonDefault(factory=make_token)` keeps the owner explicit |

Simply adding a `ServerDefault` alias while continuing to recommend bare
`default=False` would **not** deliver this property. In the candidate policy-only
channel, bare values and bare clock markers are rejected. This is a research
contract, not a change to today's constructors or an approved migration policy.

The public helper names are provisional. `default=Python(...)` and
`default=Server(...)` could shorten the same structure, but shorter names must
still tell a reader where the default runs. No extra typing result is claimed
for those hypothetical exports.

## Native typing result

Ten positive/challenge pairs pass on ty 0.0.84 across SQLite and MariaDB, using
ordinary dataclass-transform field specifiers and concrete descriptor types.
No source projection, generated constructor, checker suppression or loose
constructor `**kwargs` is used.

The fixtures use local `PolicyInteger`/`PolicyText` functions and a metaclass
registering them. An implemented version would extend the actual constructors;
consumers would not introduce a new model base. Typed overload implementations
use Any internally, but their public overloads expose typed descriptors and
policy values. Required declarations have independently inferred input/read
parameters so required `GenCol` remains supported.

Verified:

- Defaulted construction is omittable, with explicit typed overrides retained.
- Required ordinary, required nullable, and required `GenCol` inputs stay required.
- Python default values and factory results retain concrete Pending types.
- Server-default Pending types include the sentinel; Row types do not.
- A `ServerDefault` declaration assigned to an ordinary `Col` is rejected.
- Wrong Python/SQL value types, wrong clock types, incompatible None defaults,
  wrong factory result types and factories requiring arguments are rejected.
- Bare values, bare clock markers and old literal markers do not enter the
  candidate policy-only channel without an explicit owner.
- Constructed UUID defaults, UUID factories, nullable literals, SQL NULL,
  frozen fields, Pending-only construction and exact INSERT RETURNING types.

No policy is added to permit a server default on a required plain `Col`. This
is different from pursuing maximal independence of Python and SQL settings.
The type distinction expresses an actual useful difference in the resulting
Pending object, rather than two unrelated settings a caller must coordinate.

## Comparison with the earlier candidates

### Versus today's markers

The typing mechanism is intentionally close to the accepted marker design.
What changes is the consistency of the human rule: *every default declaration
names its owner*. This directly targets #473's bare-False misunderstanding,
but it is a hypothesis about readability, not fresh-reader evidence.

### Versus `ServerInteger(...)`

A server prefix keeps a declaration flatter and was already viable in earlier
static probes. But ordinary `Integer(default=False)` still asks readers to know
that unqualified defaults belong to Python. Explicit policies put both choices
at the same place in every storage constructor, without a server constructor
variant for every storage type.

Cost: nesting and repeated `default=...Default(...)`. A server-prefixed
constructor may still read better in whole models. That alternative remains
in contention; it is not eliminated by this prototype.

### Versus the flat ownership selector

`Integer(default=False, default_on="database")` was also statically viable.
It is flatter, but the value and ownership are separate arguments. A policy
keeps the value/factory together with its owner and makes the two ordinary
value declarations structurally symmetric.

Neither layout is proven more intuitive by passing ty. Whole-declaration
readability, not another clever typing workaround, should decide between them.

## Limits and open questions

- No new identity shorthand is proposed. The server consumer retains today's
  `Integer(primary_key=True, auto_increment=True, default=PENDING_GENERATION)`
  as a control. An identity is not a SQL DEFAULT and must not be disguised as
  one by writing `ServerDefault(...)`. The policy design is not yet complete
  for a friendlier generated-ID declaration.
- The prototype does not certify all storage options, foreign keys, complete
  overload parity, backend-specific expressions, or importing consumers for
  the new policy helpers.
- This single-default prototype does not settle a policy on applications that
  need Python and server defaults together. No extra machinery is designed to
  support or prohibit that case up front.
- Mandatory ownership markers would affect existing source. Whether to offer
  migration, compatibility aliases, deprecation, or an explicit break is open.
  Existing raw values must not silently become SQL defaults.
- No runtime lowering, factory invocation timing, INSERT omission, SQL NULL
  binding, DDL or schema verification is tested. These remain eventual
  behavioral acceptance criteria, not claims established here.

## Files and validation

- `policy_declarations.py.txt`: native typed policy and column signatures.
- `policy_basic.py.txt`: ownership, overrides, shape rejection and query types.
- `policy_factories.py.txt`: factories, constructed values and nullable inputs.
- `policy_server.py.txt`: SQL clocks/NULL, identity and required-generation controls.
- `policy_required.py.txt`: new constructors without defaults remain required.
- `tests/research/test_policy_defaults.py`: paired static checks; no model is run.

```sh
uv run snektest tests/research
uv run ty check
uv run ruff check .
uv run ruff format --check .
```

At the end of this round: **90 tests pass**, including 80 static
positive/challenge pairs and 10 historical parser rejection tests. Ten pairs
belong to this policy experiment. Historical failures/abandoned strategies are
preserved as observations; passing research tests does not make them viable.
No database runtime tests or production code changes.
