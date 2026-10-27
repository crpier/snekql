"""Immutable public query-plan evidence, separate from runtime Execution Plans."""

lazy from collections.abc import Iterator
lazy from dataclasses import dataclass
lazy from typing import Literal

type ExplainFormat = Literal["native", "json"]


@dataclass(frozen=True, slots=True, repr=False)
class SQLitePlanStep:
    """One native SQLite QUERY PLAN step; detail is intentionally unparsed.

    Parent/child links describe SQLite's plan tree, not execution order.
    The auxiliary integer is SQLite's currently unused third result column.
    Text formatting omits potentially sensitive plan details.
    """

    id: int
    parent: int
    auxiliary: int
    detail: str
    children: tuple[SQLitePlanStep, ...] = ()

    def __repr__(self) -> str:
        return f"SQLitePlanStep(children={len(self.children)})"


@dataclass(frozen=True, slots=True, repr=False)
class SQLiteQueryPlan:
    """SQLite's native plan forest, with preorder structural traversal."""

    roots: tuple[SQLitePlanStep, ...]

    def walk(self) -> Iterator[SQLitePlanStep]:
        """Visit every step in preorder; this is not an execution timeline."""
        pending = list(reversed(self.roots))
        while pending:
            step = pending.pop()
            yield step
            pending.extend(reversed(step.children))

    def __repr__(self) -> str:
        return f"SQLiteQueryPlan(roots={len(self.roots)})"


@dataclass(frozen=True, slots=True, repr=False)
class MariaDBPlanNode:
    """One JSON object in a MariaDB plan, identified by its native document path.

    Operation is the object's containing key, not a normalized physical operator.
    Children preserve JSON containment and array order, not execution order.
    Optional metrics are absent when not supplied; zero remains zero. Row counts
    are native estimates or observed averages, not application result counts.
    """

    operation: str
    path: tuple[str | int, ...]
    children: tuple[MariaDBPlanNode, ...] = ()
    table_name: str | None = None
    access_type: str | None = None
    key: str | None = None
    estimated_rows: float | None = None
    estimated_filtered_percent: float | None = None
    actual_rows: float | None = None
    actual_loops: int | None = None
    actual_filtered_percent: float | None = None
    total_time_ms: float | None = None
    table_time_ms: float | None = None

    def __repr__(self) -> str:
        return f"MariaDBPlanNode(children={len(self.children)})"


@dataclass(frozen=True, slots=True, repr=False)
class MariaDBQueryPlan:
    """A structural view of MariaDB JSON, retaining its complete original text."""

    roots: tuple[MariaDBPlanNode, ...]
    native_json: str

    def walk(self) -> Iterator[MariaDBPlanNode]:
        """Visit JSON objects in preorder, including unmodeled object shapes."""
        pending = list(reversed(self.roots))
        while pending:
            node = pending.pop()
            yield node
            pending.extend(reversed(node.children))

    def __repr__(self) -> str:
        return f"MariaDBQueryPlan(roots={len(self.roots)})"
