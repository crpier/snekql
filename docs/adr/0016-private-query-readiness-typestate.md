# Carry query readiness as private typestate

Query Builder result carriers carry one private covariant readiness coordinate, while public `Select[Row]` and `Write[Result]` aliases describe only executable queries. Selects and deletes transition when row scope is chosen; updates use one four-state assignment × row-scope automaton. Joins, returning projections, and other fluent refinements preserve readiness. This keeps guaranteed compilation failures out of typed Query Runtime and nested-query seams without exposing another application generic or teaching Query Runtime concrete builder classes.

Nominal staged builders were rejected because readiness would multiply the existing select, update, delete, and generated returning class surfaces. Runtime completeness checks remain authoritative for `Any`, casts, untyped callers, and forged state; static readiness narrows ordinary typed paths rather than making Query Compilation trust query objects.
