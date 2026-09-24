# Callable FK targets: proposed runtime contract

Status: design for #410, not implementation. The user approved exploring the
callable interface. The lifecycle change and initial limitations below still need
agreement. Production files and dependencies are unchanged.

## Typing result changed the proposed scope

Broadening all five ForeignKey overloads to accept a column or a zero-argument
callback does not preserve all expected target checks in ty. Both backend valid
consumers pass. However, ty 0.0.77 and 0.0.83 reject only six of ten wrong-target
consumers: both required forms without an explicit default are missed. Pyright
rejects all ten. These are distinct from the earlier class-body argument-erasure
reproducer; the field-specifier initializer check also loses information without
an explicit default. This is a checker limitation, not proof of supported typing.

Proposed first release: permit callbacks only with an explicit Python default,
including None. Keep all existing bound-column overloads unchanged. Do not add
callable overloads for omitted defaults, default_factory, server defaults or
pending-generation sentinels.

```python
manager_id: sqlite.FKCol[Account, int | None] = sqlite.ForeignKey(
    lambda: Account.key, default=None,
)
```

The narrow signature experiment passes both backend positive consumers. ty and
strict Pyright reject all ten negative consumers: six wrong-target cases and four
unsupported required callback declarations. Ty emits ten diagnostics; Pyright
emits sixteen, including cascaded unknown-type diagnostics on the four unsupported
calls. This is signature evidence only, not native implementation evidence. The
prior nullable-only probes also rejected wrong logical types and backend owners.

## Lifecycle findings

Current ModelMeta binds columns, validates backends/nullability/defaults, freezes
column metadata, then evaluates index and check declarations. Some Index
validation also reads storage in the class body itself.

`lifecycle_probe.py` uses current snekql unchanged. It confirms:

- A local class name is not bound when __indexes__ executes.
- Columns are already frozen inside that hook.
- During class redefinition, resolving a callback can silently return the old
  class's column instead of raising NameError.
- The same callback returns the correct column after the class statement ends.

Calling the callback during class creation is therefore not a safe implementation.
Neither is retrying only after NameError. Decorators also run before the class
name is assigned. Rewriting callback globals/closure cells or parsing its bytecode
would change normal Python semantics and is rejected.

## Options

1. Resolve automatically on first use requiring bound model metadata. This keeps
   the proposed spelling, but moves target-dependent validation for callback-bearing
   models out of class creation.
2. Require a new explicit model-binding call after declaration. Timing is explicit,
   but this adds another public verb and an easy-to-forget prerequisite to queries.
3. Keep the existing FKCol plus ForeignKeyConstraint spelling. No lifecycle change;
   the callable interface is not added.

Recommendation: option 1 if delayed target-dependent errors are acceptable. This
is a real change to the current rule that all model declaration facts are fixed
when the class is created. It should get an ADR if accepted, not be hidden as an
annotation-only patch.

## Recommended contract

- Freeze declaration options at class creation. Capture the expected FK target
  and logical contract from the annotation. Initially require that annotation to
  resolve to self or an already-defined model; do not promise new cross-model
  forward-reference support.
- Invoke the original synchronous, side-effect-free target callback once, after
  the class statement has finished, when model construction, schema/query work,
  or metadata inspection first needs the binding. Ordinary column lookup inside
  a resolver must not recursively finalize an entire model.
- Validate canonical descriptor membership, annotated target identity, backend
  and supported key storage before publishing the binding. Preserve existing
  schema-level candidate-key and referential-action validation.
- Copy derived storage into one immutable resolved record, preserving descriptor
  identity. Do not invent temporary INTEGER/BLOB storage, return None for an
  unresolved physical FK, or unfreeze a published descriptor.
- Delay target-dependent checks and relevant declaration hooks for models with
  callable FKs. Existing models without callbacks keep their current timing.
  Index construction must retain a pending declaration rather than incorrectly
  validating against fake storage. No statement, schema output or encoded value
  may consume a partially bound model.
- Use explicit Unresolved/Resolving/Resolved/Failed states. Cache success and
  failure; do not silently retry after names or globals change. Raise a fresh
  domain error on repeated failed access rather than accumulating traceback
  frames on a reused exception. Invalid/non-column/async results and resolution
  cycles fail closed. Do not mistake ordinary self-relationships for cycles.
- Ensure concurrent first use does not execute a callback twice or deadlock
  across dependent bindings. A synchronous reentrant resolution coordinator is
  one candidate; it must not become a global model registry or perform IO.
- Cache the resolved identity so later global rebinding cannot redirect an
  established FK. Do not modify the application's globals or closures.

Implementation still needs to prove these behaviors. In particular, dependency
resolution must distinguish column storage dependencies from cycles in the table
relationship graph. The design should not claim mutual forward-model support as
a side effect of accepting Callable.

## Reviewable implementation parts if approved

1. Public declaration/default and wrong-target typing controls, plus one real
   SQLite self-reference whose target resolves after declaration. First failing
   public-seam test before any production change.
2. Complete the binding lifecycle with once-only resolution, failures, reentry,
   concurrency, immutable metadata, indexes/checks and eager-model regressions.
3. Symmetric native MariaDB/SQLite defaults, generated-key inserts, aliased joins,
   physical orphan rejection and storage derivation. Expand wrong-domain/backend
   controls alongside supported defaults, without accepting omitted defaults.
4. Document timing and limits, then installed-wheel consumers, artifacts, static
   checks, frozen full discovery and CI. Only then open the implementation PR.

No production or full-suite validation has been run for this proposal because no
production implementation exists. No upstream checker issue has been filed.
