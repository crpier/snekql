# Native omission hooks: source-informed follow-up for #473

2026-10-26. Research only; no production, dependency, or checker changes.

## Current goal and priorities

The maintainer now considers a defaults interface change worthwhile and favors
separate Python/SQL parameters because brownfield databases have other writers.
Different Python and SQL defaults are valid independent policies when their
values fit the logical domain. Final public names, compatibility, and full
implementation are not selected.

We want the common generated field to need no repeated pending default:

```python
value: db.GenCol[bool] = db.Integer(server_default=False)
```

The desired controls still include required defaultless Col, nullable Col and
GenCol inputs, optional generated server defaults, explicit overrides, exact
Pending/Row types, and independent Python/SQL policies. In particular, a plain
Col with a server default can still require input, and a Python False default
can coexist with SQL True. Preserving those controls matters more than getting
one omitted constructor call past the checker.

## Release-pinned implementation evidence

The installed checker reports ty 0.0.84, with `commit_info: null`. The published
[0.0.84 release](https://github.com/astral-sh/ty/releases/tag/0.0.84) points through
its `ruff` submodule to commit `11aaa39f84c0c44bdfb4c9cc21e4038c6f74c00a`.
The source links below were obtained through `gh api` at that commit, not current
main. Local black-box tests remain the evidence for the installed executable.

1. **Field metadata:** [`types/call/bind.rs`](https://github.com/astral-sh/ruff/blob/11aaa39f84c0c44bdfb4c9cc21e4038c6f74c00a/crates/ty_python_semantic/src/types/call/bind.rs), lines 1986–2050.
   The relevant branch matches a registered `FunctionLiteral`. It asks for
   `default`, `default_factory`, and `factory` with `fallback_to_default=false`.
   It does not ask for `server_default`, and helper-signature default values
   therefore do not supply the omission signal. In contrast, options such as
   `init` are read with signature-default fallback enabled. The hook creates
   field default metadata only if a recognized argument is bound.
2. **Constructor synthesis:** [`types/class/static_literal.rs`](https://github.com/astral-sh/ruff/blob/11aaa39f84c0c44bdfb4c9cc21e4038c6f74c00a/crates/ty_python_semantic/src/types/class/static_literal.rs), lines 2698–2745 and 1749–1885.
   Recognized field metadata replaces the ordinary RHS default. Descriptor
   `__set__` contributes the constructor input type; `__get__` transforms an
   existing default type, but does not create a default where metadata has none.
   The synthesized parameter receives the resulting optional default metadata.
3. **Requiredness:** [`types/class.rs`](https://github.com/astral-sh/ruff/blob/11aaa39f84c0c44bdfb4c9cc21e4038c6f74c00a/crates/ty_python_semantic/src/types/class.rs), lines 2852–2868.
   The dataclass-field requiredness rule depends on default metadata and `init`;
   it is not based on the GenCol annotation's value domain.

**Bounded conclusion:** an ordinary registered function call with only
`server_default=` cannot acquire omission through this hook by changing just its
return annotation or implicit parameter defaults. This is a causal explanation
of the observed failures, not a theorem about every possible Python typing
architecture. It also does not say every GenCol must always permit omission.

## Additional native probes

`tests/research/test_split_omission_hooks.py` retains the constructor, Pending/Row,
independent-default, bad-input and INSERT RETURNING controls from the previous
round. Only source strings are checked; models and factories are never executed.

| Mechanism | Observed result on both backends |
| --- | --- |
| Export a registered staticmethod under the normal constructor name | Requiredness is retained; server omission still gets `missing-argument` |
| Callable instance, registering both the instance and its `__call__` | Omission accepted, but defaultless fields and the schema-only contrast incorrectly become optional |
| Constructor class, registering its underlying `__new__` as well as the class | Requiredness is retained; server omission still gets `missing-argument` |
| Optional typed `**kwargs` with a `NotRequired` pending-default entry | Merely permitting the option does not bind it; server omission still gets `missing-argument` |
| Actually pass a typed `**kwargs` value containing `default=PENDING_GENERATION` | Omission, required-input, override, independent-default and exact type controls pass |

The `__new__` result refines the preceding generic-class observation: the earlier
class registration failure was not proof that classes cannot preserve required
inputs. Registering the underlying function can preserve them. It still does not
infer a missing Python default from a server parameter.

### Why the passing pack is not our solution

The passing control effectively has this shape:

```python
# Declared once as a TypedDict with a required, sentinel-typed default entry:
_generation = {"default": db.PENDING_GENERATION}

value: db.GenCol[bool] = db.Integer(server_default=False, **_generation)
```

The tests use the precise TypedDict annotation, not an untyped/dynamic dictionary.
The checker sees a bound `default` argument even though the call does not spell
that keyword literally. This demonstrates the difference between an implicit
signature default and an argument supplied through unpacking.

It avoids repeating the sentinel's full name, but **still repeats a Python
omission marker on each generated field**. It is a diagnostic control, not a
proposed public shorthand or a newly promoted design. It does not meet the goal
of deriving the common omission policy without duplicate field syntax.

## Identity control: not just server defaults

Four more pairs check the identity declaration with and without the explicit pack:

```python
value: db.GenCol[int] = db.Integer(primary_key=True, auto_increment=True)
```

Both backends retain exact int/pending and Row-int types, explicit overrides,
wrong-value rejections and Pending-only construction. Without a bound default,
omitting the constructor input still produces `missing-argument`; supplying the
same typed pack permits omission. Auto-increment is a generation source, not a
SQL DEFAULT, and neither the flag nor GenCol creates Python default metadata.
This is a representative primary-key identity control, not complete backend
identity-option or explicit-ID runtime validation.

## Outcome of the hook-only probes

There are fourteen additional paired observations: five mechanisms on each
backend plus two identity controls on each backend. The desired raw shorter
server and identity declarations failed first, with `missing-argument` on both
backends. The final green observation tests record the limitations and the
explicit-pack controls; they do not implement zero-duplication inference.

These probes did not demonstrate a zero-duplication solution. A subsequent
[callable-intersection prototype](callable-intersections.md) **does change the
substantive mechanism**: it combines registered-function and unregistered-protocol
views, passing the eleven common scenarios without explicit pending defaults.
It needs an explicit override for required-input SQL-default cases and remains
checker-sensitive, static-only research. The single-function hook analysis above
still explains why merely varying implicit defaults did not work.

No checker patch or plug-in is implemented or authorized for adoption. Generated
constructors remain abandoned.

This focused follow-up uses Integer/bool fields plus representative int identity
fields. Full clock, factory, identity-option, codec, inheritance and backend
configuration acceptance would still be needed before promoting a route. SQL-default compatibility and runtime
lowering are not proven by the precise constructor types.

```sh
uv run snektest tests/research/test_split_omission_hooks.py
```
