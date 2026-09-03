# Execution plans own query runtime policy

Query Compilation produces private typed Execution Plans carrying SQL, parameters, backend identity, result cardinality, and validation-aware Materialization. Query Runtime executes those plans without inspecting concrete Query Builder classes; this keeps new query shapes local to compilation and turns cardinality failures into package errors.

The tracer moves `fetch_one` and every write through plans. Remaining select paths migrate incrementally by adding `many`, optional-one, and streaming plan policies; until then, the existing Query Codec methods remain beside the plan factories. Empty bulk inserts use a no-SQL plan bound to the active adapter because an empty batch has no model from which to recover backend identity.
