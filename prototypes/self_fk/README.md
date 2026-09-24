# Throwaway self-FK typing research

For #410. Do not merge these probes into production. Baseline is main at
580c9b697347f6ee6282dad0d045e0d321c9ff83. No production changes are proposed here.

## Findings

1. `standalone-default.py` reduces the owner problem without snekql. A bare
   class-body descriptor retains `Unbound`; class-qualified access binds the
   declaring model. Both ty 0.0.83 and Pyright 1.1.414 reject the direct self
   assignment with and without dataclass transforms. The retained-unbound and
   external-reference controls pass. Pyright also reports a return-only generic
   warning on the no-default factory overload; this is separate from the two
   owner errors.
2. `field-erasure.py` isolates a separate ty false negative. A custom field
   specifier called without an explicit default becomes unspecialized
   `dataclasses.Field` in its class body. A wrong argument then passes. ty
   0.0.77 and 0.0.83 reject the explicit-default and ordinary-class controls but
   miss the no-default call. Pyright 1.1.414 rejects all three wrong calls.
   This is not evidence that removing defaults safely supports self-FKs.
3. `contextual.pyi` is a rejected signature experiment. It accepts an unbound
   column and chooses the target only from the annotated FKCol. Both ty and
   strict Pyright accept `contextual-counterexample.py`, including the wrong
   target. No extra Any is needed to produce this unsoundness. Do not add such
   an overload to ForeignKey.
4. `deferred.pyi` is a signature-only proposal, not a runtime implementation.
   `deferred_fk(lambda: Account.key, default=None)` supplies a class-qualified
   target. Both backend positive consumers pass ty 0.0.77 and strict Pyright
   1.1.414. Both checkers reject all six wrong-owner/value/backend consumers,
   one initializer error each. Constructor omittability and typed references
   are included in the positives. Only the nullable-default signature is
   explored; this does not prove the full ForeignKey overload matrix.

## Decision still needed

Keep the existing typed FKCol plus table-level ForeignKeyConstraint spelling,
which is already supported, or approve design work on a deferred target such as
`ForeignKey(lambda: Account.key, default=None)`.

The latter changes the public interface. Runtime design must address deferred
name lookup, when storage is derived, one-time resolution, declaration metadata
freezing, cycles, and invalid targets. The callback cannot simply run inside
ModelMeta.__new__: the class name is not yet bound. No claim of native execution
or declaration-lifecycle compatibility is made by these signature probes.

The ty false negative has a standalone upstream-ready reproducer. No upstream
issue has been filed by this research. Fixing that false negative alone would
not solve the separate missing-owner problem.

## Reproduce

From this worktree root, with the locked development environment:

```sh
uv run ty check prototypes/self_fk/field-erasure.py
uvx --from ty==0.0.83 ty check prototypes/self_fk/field-erasure.py
uvx --from pyright==1.1.414 pyright --pythonversion 3.14 prototypes/self_fk/field-erasure.py
uv run ty check prototypes/self_fk/standalone-default.py
uv run ty check --extra-search-path prototypes/self_fk prototypes/self_fk/contextual-counterexample.py
uv run ty check --extra-search-path prototypes/self_fk prototypes/self_fk/deferred-*-positive.py
uv run ty check --extra-search-path prototypes/self_fk prototypes/self_fk/deferred-*-owner.py prototypes/self_fk/deferred-*-value.py prototypes/self_fk/deferred-*-backend.py
```

Nonzero results are intentional for negative probes. The contextual counterexample
returning zero is evidence against its proposed signature, not a successful fix.
The .pyi helpers exist only for checking and cannot be imported for execution.
For strict Pyright, configure this directory and the worktree root as extraPaths,
Python 3.14, reportMissingModuleSource=false for stub-only helpers, and the project
interpreter. Raw checker outputs are under results/.
