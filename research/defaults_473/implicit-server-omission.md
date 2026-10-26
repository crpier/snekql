# Can separate parameters avoid the explicit pending default?

Static-only follow-up for #473, 2026-10-26. No public interface is selected.

## Desired declaration, not a demonstrated capability

```python
value: db.GenCol[bool] = db.Integer(server_default=False)
```

For the common server-owned case, the desired contract is:

- Constructor omission is accepted, with intended initial PENDING_GENERATION.
- Pending access is exactly `bool | PENDING_GENERATION`; Row access is `bool`.
- Explicit bool and pending overrides remain accepted; None and wrong types fail.
- Defaultless required, required-nullable and required GenCol fields stay required.
- In the discussed annotation-sensitive rule, `Col[bool]` with only a server
  default can still require Python input; explicit Python defaults remain concrete.

The shorter spelling is a reasonable ergonomic goal within the existing separate
parameters family. The earlier explicit sentinel is a limitation of the tested
signatures, **not a proven requirement of every possible typing implementation**.
There is no generated-constructor work in this follow-up.

## Six native mechanisms probed

`tests/research/test_split_omission.py` reuses the existing native descriptor and
metaclass signatures, varying the Integer declaration machinery while preserving
the caller spelling. Both backends use their real lifecycle types. Prototype
bodies raise and are never executed.

| Mechanism | Omit server-default input? | Defaultless fields remain required? | Explicit server-field override? |
| --- | --- | --- | --- |
| Registered function, implicit `default: object = PENDING_GENERATION` | No | Yes | Yes |
| Registered function, implicit sentinel-typed default | No | Yes | Yes |
| Registered function, implicit sentinel-producing `default_factory` | No | Yes | Yes |
| Registered generic descriptor class with overloaded `__init__` and implicit default | Yes | **No** | Yes |
| Function removed from field-specifier registration | Yes | **No** | Yes |
| Registered server overload with implicit `init: Literal[False] = False` | Yes | Yes for calls without server defaults | **No** |

For the first three mechanisms, omitting the server field produces
`missing-argument`. Supplying an implicit default in the helper's own signature
is not enough in these probes.

For the class and unregistered-function mechanisms, required plain, nullable and
GenCol fields incorrectly accept omission. Merely observing `Server()` accepted
would have been a false positive. This records the tested class construction;
it does not rule out all descriptor/class implementations.

For `init=False`, concrete and pending overrides produce `unknown-argument`.
A plain Col with only a server default is also omitted from the constructor,
losing the required-input contrast. Excluding a field is not the desired optional
constructor argument.

All six retain the tested precise field-access and Row types and reject the
represented bad constructor values (or reject the keyword itself for excluded
fields). Accurate value types do not compensate for incorrect requiredness or
missing override support, and do not prove SQL-default compatibility.

## Controls and evidence

The initial desired-contract test failed on both backends solely because
`Server()` reported `missing-argument`. Adding a sentinel-typed implicit default
still failed on that line. The final observation tests deliberately record those
failures and the accepted gaps; **green observation tests do not mean the desired
shorter declaration has been implemented**.

Each mechanism has a clean independent control and exact challenge-line rules.
Controls cover constructor omission/requiredness, explicit None, bool/pending
and bad-value inputs, precise Pending/Row access, Python-only and combined
Python/server defaults, Pending-only construction, and assignment of INSERT
RETURNING to `Write[Server[Row]]`. The probes never execute INSERT.

There are 12 paired observations: six mechanisms on two backends, CPython 3.15.0
and ty 0.0.84. The shared signatures' existing SQL-validation gaps are not
repaired. This is a focused Integer/bool construction experiment, not a renewed
full scenario/backend/storage/configuration acceptance claim.

```sh
uv run snektest tests/research/test_split_omission.py
```

**Conclusion:** native omission inference for the desired shorter spelling remains
unresolved. These attempted mechanisms do not satisfy all the construction
controls. This is not an impossibility proof and does not eliminate the separate
parameters design. Runtime inference alone would not fix a required static
constructor parameter. A different native mechanism or additional checker support
would need its own evidence; the abandoned generated-typing route stays abandoned.
