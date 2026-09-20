"""Bind bounded CHECK predicates to immutable, parameter-free schema expressions."""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from snekql.constraints import CheckConstraint
from snekql.errors import ModelDeclarationError, SnekqlError
from snekql.expressions import (
    BetweenPredicate,
    ColumnComparisonPredicate,
    ComparisonPredicate,
    CompoundPredicate,
    MembershipPredicate,
    NegatedPredicate,
    NullPredicate,
)
from snekql.storage import (
    Attr,
    StorageBackend,
    _annotation_core_types,
    _extract_logical_type,
    _json_payload_annotation,
    _resolve_model_hint,
)


@dataclass(frozen=True)
class CheckExpression:
    """An ordered expression tree, independent of query scope and parameter state."""

    operator: str
    arguments: tuple[CheckExpression, ...] = ()
    value: str | int | None = None


@dataclass(frozen=True)
class BoundCheck:
    """One named constraint with its local descriptors resolved to column names."""

    name: str
    expression: CheckExpression


class _CheckBinder:
    """Validate every operand against the declaring table before freezing names."""

    def __init__(
        self,
        owner: type,
        columns: dict[str, Attr[Any, Any, Any, Any, Any]],
        backend: StorageBackend,
    ) -> None:
        self.backend: StorageBackend = backend
        self.owner: type = owner
        self.columns: dict[str, Attr[Any, Any, Any, Any, Any]] = columns

    def bind(self, predicate: object) -> CheckExpression:
        if isinstance(predicate, CompoundPredicate):
            return CheckExpression(
                predicate.operator,
                tuple(self.bind(child) for child in predicate.children),
            )
        if isinstance(predicate, NegatedPredicate):
            return CheckExpression("NOT", (self.bind(predicate.child),))
        if isinstance(
            predicate, (NullPredicate, MembershipPredicate, BetweenPredicate)
        ):
            column, logical = self._column(predicate.operand)
            left = CheckExpression("column", value=column.name)
            if isinstance(predicate, NullPredicate):
                return CheckExpression(
                    "IS NOT NULL" if predicate.negated else "IS NULL", (left,)
                )
            values = (
                predicate.values
                if isinstance(predicate, MembershipPredicate)
                else (predicate.low, predicate.high)
            )
            if not values or any(type(value) is not logical for value in values):
                msg = "unsupported CHECK literal"
                raise ModelDeclarationError(msg)
            arguments = tuple(self._literal(column, value, logical) for value in values)
            operator = (
                ("NOT IN" if predicate.negated else "IN")
                if isinstance(predicate, MembershipPredicate)
                else "BETWEEN"
            )
            return CheckExpression(operator, (left, *arguments))
        if isinstance(predicate, (ComparisonPredicate, ColumnComparisonPredicate)):
            column, logical = self._column(predicate.operand)
            left = CheckExpression("column", value=column.name)
            if isinstance(predicate, ColumnComparisonPredicate):
                other, other_logical = self._column(predicate.other)
                if other_logical is not logical or (
                    column.storage_type_name,
                    column.text_collation,
                ) != (other.storage_type_name, other.text_collation):
                    msg = "CHECK column comparison requires matching storage and logical types"
                    raise ModelDeclarationError(msg)
                right = CheckExpression("column", value=other.name)
            elif (
                isinstance(predicate.value, (int, str))
                and type(predicate.value) is logical
            ):
                right = self._literal(column, predicate.value, logical)
            else:
                msg = "unsupported CHECK literal"
                raise ModelDeclarationError(msg)
            return CheckExpression(predicate.operator, (left, right))
        msg = "unsupported CHECK predicate"
        raise ModelDeclarationError(msg)

    def _literal(
        self, column: Attr[Any, Any, Any, Any, Any], value: object, logical: type
    ) -> CheckExpression:
        if type(value) is not logical:
            msg = "unsupported CHECK literal"
            raise ModelDeclarationError(msg)
        try:
            encoded = column.encode(value, backend=self.backend)
            if isinstance(encoded, str):
                encoded.encode("utf-8")
        except (SnekqlError, UnicodeError) as e:
            msg = "invalid CHECK literal for column storage"
            raise ModelDeclarationError(msg) from e
        if not isinstance(encoded, (int, str)):
            msg = "unsupported CHECK wire literal"
            raise ModelDeclarationError(msg)
        return CheckExpression(
            "literal", value=int(encoded) if isinstance(encoded, bool) else encoded
        )

    def _column(self, operand: object) -> tuple[Attr[Any, Any, Any, Any, Any], type]:
        if (
            not isinstance(operand, Attr)
            or operand.owner is not self.owner
            or operand.name is None
            or self.columns.get(operand.name) is not operand
        ):
            msg = "CHECK requires local columns"
            raise ModelDeclarationError(msg)
        annotation = _extract_logical_type(
            _resolve_model_hint(self.owner, operand.name), operand.name
        )
        if _json_payload_annotation(annotation)[0]:
            msg = "CHECK requires ordinary, non-JSON storage"
            raise ModelDeclarationError(msg)
        logical_types = _annotation_core_types(annotation)
        if (
            len(logical_types) != 1
            or not isinstance(logical_types[0], type)
            or logical_types[0] not in (int, bool, str)
        ):
            msg = "CHECK requires integer, boolean, or ordinary text logical types"
            raise ModelDeclarationError(msg)
        logical = logical_types[0]
        if (
            logical in (int, bool)
            and operand.storage_type_name not in ("Integer", "Boolean")
        ) or (logical is str and operand.storage_type_name != "Text"):
            msg = "unsupported CHECK column storage"
            raise ModelDeclarationError(msg)
        return operand, logical


def bind_checks(
    declarations: object,
    owner: type,
    columns: dict[str, Attr[Any, Any, Any, Any, Any]],
    backend: StorageBackend,
) -> tuple[BoundCheck, ...]:
    """Snapshot table-level declarations after column ownership is assigned."""
    if not isinstance(declarations, list):
        msg = "__checks__ must be a list"
        raise ModelDeclarationError(msg)
    checks: list[BoundCheck] = []
    names: set[str] = set()
    binder = _CheckBinder(owner, columns, backend)
    for declaration in declarations:
        if not isinstance(declaration, CheckConstraint):
            msg = "__checks__ entries must be CheckConstraint declarations"
            raise ModelDeclarationError(msg)
        name = declaration.name
        if (
            not isinstance(name, str)
            or not name
            or not (name[0].isalpha() or name[0] == "_")
            or not all(character.isalnum() or character == "_" for character in name)
        ):
            msg = "CHECK name must be a SQL identifier"
            raise ModelDeclarationError(msg)
        if name.casefold() in names:
            msg = "CHECK names must be unique within a table"
            raise ModelDeclarationError(msg)
        names.add(name.casefold())
        checks.append(BoundCheck(name, binder.bind(declaration.predicate)))
    return tuple(checks)


def render_check(  # noqa: C901, PLR0911
    expression: CheckExpression, quote: Callable[[str], str], backend: StorageBackend
) -> str:
    """Render known nodes, never substitute literals into parameterized query SQL."""
    if expression.operator == "column":
        return quote(str(expression.value))
    if expression.operator == "literal":
        if isinstance(expression.value, str):
            encoded = expression.value.encode("utf-8").hex()
            if backend == "mariadb":
                return f"CONVERT(X'{encoded}' USING utf8mb4)"
            if "\0" in expression.value:
                return f"CAST(X'{encoded}' AS TEXT)"
            return "'" + expression.value.replace("'", "''") + "'"
        return str(expression.value)
    children = tuple(
        render_check(child, quote, backend) for child in expression.arguments
    )
    if expression.operator in {"IS NULL", "IS NOT NULL"}:
        return f"{children[0]} {expression.operator}"
    if expression.operator == "NOT":
        return f"NOT ({children[0]})"
    if expression.operator in {"IN", "NOT IN"}:
        return f"{children[0]} {expression.operator} ({', '.join(children[1:])})"
    if expression.operator == "BETWEEN":
        return f"{children[0]} BETWEEN {children[1]} AND {children[2]}"
    operators = {
        "eq": "=",
        "ne": "<>",
        "gt": ">",
        "gte": ">=",
        "lt": "<",
        "lte": "<=",
        "AND": "AND",
        "OR": "OR",
    }
    left, right = children
    if expression.operator in {"AND", "OR"}:
        left, right = f"({left})", f"({right})"
    return f"{left} {operators[expression.operator]} {right}"
