"""Decode native SQLite plan steps without interpreting unstable detail prose."""

lazy from snekql._explain_types import ExplainFormat, SQLitePlanStep, SQLiteQueryPlan
lazy from snekql.errors import DatabaseRuntimeError


def decode_explain(
    columns: tuple[str, ...],
    rows: tuple[tuple[object, ...], ...],
    _format: ExplainFormat,
) -> SQLiteQueryPlan:
    """Preserve native step fields and reconstruct their parent relationships."""
    if columns != ("id", "parent", "notused", "detail"):
        msg = "unexpected SQLite query-plan columns"
        raise DatabaseRuntimeError(msg)
    steps: dict[int, tuple[int, int, str]] = {}
    for row in rows:
        if (
            len(row) != len(columns)
            or type(row[0]) is not int
            or type(row[1]) is not int
            or type(row[2]) is not int
            or not isinstance(row[3], str)
            or row[0] in steps
        ):
            msg = "unexpected SQLite query-plan step"
            raise DatabaseRuntimeError(msg)
        steps[row[0]] = (row[1], row[2], row[3])
    children: dict[int, list[int]] = {}
    roots: list[int] = []
    for identifier, (parent, _, _) in steps.items():
        if parent in steps:
            children.setdefault(parent, []).append(identifier)
        else:
            roots.append(identifier)

    visited: set[int] = set()

    def build(identifier: int) -> SQLitePlanStep:
        visited.add(identifier)
        parent, auxiliary, detail = steps[identifier]
        return SQLitePlanStep(
            id=identifier,
            parent=parent,
            auxiliary=auxiliary,
            detail=detail,
            children=tuple(build(child) for child in children.get(identifier, ())),
        )

    plan = SQLiteQueryPlan(roots=tuple(build(identifier) for identifier in roots))
    if len(visited) != len(steps):
        msg = "cyclic SQLite query-plan parent relationships"
        raise DatabaseRuntimeError(msg)
    return plan
