"""Reachable CTE definitions, dependency ordering and shared WITH name scope."""

from typing import Any

from snekql._aliases import _AliasRelation
from snekql._cte import _CteDefinition, _CteRelation
from snekql._query_state import SelectState, require_subquery_state
from snekql.errors import QueryCompilationError
from snekql.expressions import _PredicateNode, _require_predicate_node, _Scalar
from snekql.model import Table, require_model_table_name


class _DefinitionGraph:
    """Walk SQL scopes without executing definitions or inspecting bound values."""

    def __init__(self) -> None:
        self._definitions: list[_CteDefinition] = []
        self._emitted: set[_CteDefinition] = set()
        self._names: dict[str, _CteDefinition] = {}
        self._physical_names: set[str] = set()
        self._visiting: set[_CteDefinition] = set()

    def collect(self, query: SelectState) -> None:
        for source in query.result_models():
            self._source(source)
        for field in query.fields:
            if isinstance(field, _Scalar):
                self.collect(require_subquery_state(field.subquery))
        for predicate in (*query.predicates, *query.having):
            self._predicate(predicate)
        for join in query.joins:
            self._predicate(join.predicate)

    def finish(self) -> tuple[_CteDefinition, ...]:
        if self._names.keys() & self._physical_names:
            msg = "CTE name collides with a visible query source"
            raise QueryCompilationError(msg)
        return tuple(self._definitions)

    def _predicate(self, predicate: _PredicateNode[Any]) -> None:
        for nested in predicate.__predicate_nested_selects__():
            self.collect(require_subquery_state(nested))
        for child in predicate.__predicate_children__():
            self._predicate(_require_predicate_node(child))

    def _source(self, source: type[Table[Any]]) -> None:
        if not issubclass(source, _CteRelation):
            self._physical_names.add(require_model_table_name(source).casefold())
            if issubclass(source, _AliasRelation):
                self._physical_names.add(
                    require_model_table_name(source.source_model).casefold()
                )
            return
        definition = source.definition
        name = definition.name.casefold()
        if name in self._names and self._names[name] is not definition:
            msg = "CTE names must be unique ignoring case"
            raise QueryCompilationError(msg)
        self._names[name] = definition
        if definition in self._visiting:
            msg = "CTE dependency cycle"
            raise QueryCompilationError(msg)
        if definition in self._emitted:
            return
        self._visiting.add(definition)
        self.collect(definition.state)
        self._visiting.remove(definition)
        self._emitted.add(definition)
        self._definitions.append(definition)


def collect_cte_definitions(state: SelectState) -> tuple[_CteDefinition, ...]:
    """Resolve one statement's reachable definitions in dependency order."""
    graph = _DefinitionGraph()
    graph.collect(state)
    return graph.finish()
