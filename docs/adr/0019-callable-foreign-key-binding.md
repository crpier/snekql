# Bind callable foreign-key targets once on first metadata use

Scalar `ForeignKey` declarations may accept a synchronous zero-argument callback
when an explicit Python default is provided. Class-qualified callback results
retain target/value typing; inferring a self target from an unbound class-body
column would accept unrelated targets. Callable overloads without defaults are
excluded because ty currently misses some wrong-target declarations in that form.

For callback-bearing models, declaration options and resolvable annotations are
captured at creation, while physical target binding and target-dependent hooks
wait for first metadata use. Eager callback execution cannot reliably resolve a
class name before Python assigns it and may silently select an older definition.
Rewriting application namespaces and adding an explicit public finalization verb
were rejected. Models without callable FKs retain their eager checks.

Binding preserves descriptor identity, publishes immutable derived storage, and
memoizes both success and failure. A synchronous reentrant coordinator prevents
concurrent duplicate evaluation without a model registry or IO. Storage dependency
cycles and model-level reentry fail closed. Callbacks must remain side-effect-free;
no schema, query plan or encoded value may consume a failed binding. Table-level
`ForeignKeyConstraint` remains the alternative for eager checks and required
self-reference fields.
