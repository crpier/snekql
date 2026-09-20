"""Typed SQL value composition without changing column codecs."""

from __future__ import annotations

from dataclasses import dataclass, replace
from math import isfinite
from typing import Any, Literal, cast, overload

from snekql._dialect_expr import CompileCtx
from snekql._output_label import _NullExtendedLabel
from snekql.errors import (
    ModelValidationError,
    QueryCompilationError,
    QueryConstructionError,
)
from snekql.expressions import Comparable, Predicate


def _encode_native_literal(
    value_type: type[int | float | str], value: object
) -> int | float | str | None:
    """Validate native bindings without borrowing source-column validators."""
    allowed_types = (int, float) if value_type is float else (value_type,)
    if value is not None and type(value) not in allowed_types:
        msg = "expression literal does not match the value domain"
        raise QueryConstructionError(msg)
    if isinstance(value, int) and not -(2**63) <= value < 2**63:
        msg = "arithmetic literal exceeds the signed 64-bit integer range"
        raise QueryConstructionError(msg)
    if isinstance(value, float) and not isfinite(value):
        msg = "arithmetic requires finite floating literals"
        raise QueryConstructionError(msg)
    return cast("int | float | str | None", value)


def _compose[OwnerT, T](
    operand: ValueExpression[OwnerT, T],
    operator: Literal["+", "-", "*", "COALESCE"],
    value: object,
) -> ValueExpression[OwnerT, Any]:
    if isinstance(value, ExpressionMethods):
        right = value.__value_operand__()
        if right.owner is not operand.owner:
            msg = "expression operands must belong to the same query source"
            raise QueryConstructionError(msg)
        if right.value_type is not operand.value_type:
            msg = "expression operands require matching value domains"
            raise QueryConstructionError(msg)
    else:
        right = operand.__encode_comparison__(value)
        if (
            operator == "COALESCE"
            and operand.value_type is float
            and type(right) is int
        ):
            right = float(right)
    right_nullable = (
        right.nullable if isinstance(right, ValueExpression) else right is None
    )
    nullable = (
        (operand.nullable and right_nullable)
        if operator == "COALESCE"
        else (operand.nullable or right_nullable)
    )
    return ValueExpression(
        column=operand.column,
        owner=operand.owner,
        value_type=operand.value_type,
        nullable=nullable,
        operations=(*operand.operations, (operator, right)),
    )


class ExpressionMethods[OwnerT, T]:
    """Read-only SQL operations shared by columns and computed values."""

    def _value_identity(self, value: T) -> T:
        return value

    def __value_operand__(self) -> ValueExpression[OwnerT, T]:
        """Resolve a native column or an already computed value."""
        raise NotImplementedError

    def __numeric_operand__(self) -> ValueExpression[OwnerT, T]:
        """Reject arithmetic on non-numeric value expressions."""
        operand = self.__value_operand__()
        if operand.value_type not in (int, float):
            msg = "arithmetic requires a native numeric value"
            raise QueryConstructionError(msg)
        return operand

    @overload
    def add(
        self: ExpressionMethods[OwnerT, int],
        value: int | ExpressionMethods[OwnerT, int],
    ) -> ValueExpression[OwnerT, int]: ...

    @overload
    def add(
        self: ExpressionMethods[OwnerT, int],
        value: ExpressionMethods[OwnerT, int | None] | None,
    ) -> ValueExpression[OwnerT, int | None]: ...

    @overload
    def add(
        self: ExpressionMethods[OwnerT, int | None],
        value: int
        | ExpressionMethods[OwnerT, int]
        | ExpressionMethods[OwnerT, int | None]
        | None,
    ) -> ValueExpression[OwnerT, int | None]: ...

    @overload
    def add(
        self: ExpressionMethods[OwnerT, float],
        value: float | ExpressionMethods[OwnerT, float],
    ) -> ValueExpression[OwnerT, float]: ...

    @overload
    def add(
        self: ExpressionMethods[OwnerT, float],
        value: ExpressionMethods[OwnerT, float | None] | None,
    ) -> ValueExpression[OwnerT, float | None]: ...

    @overload
    def add(
        self: ExpressionMethods[OwnerT, float | None],
        value: float
        | ExpressionMethods[OwnerT, float]
        | ExpressionMethods[OwnerT, float | None]
        | None,
    ) -> ValueExpression[OwnerT, float | None]: ...

    def add(self, value: object) -> ValueExpression[OwnerT, Any]:
        """Add a literal or same-source expression, propagating SQL NULL."""
        return _compose(self.__numeric_operand__(), "+", value)

    @overload
    def sub(
        self: ExpressionMethods[OwnerT, int],
        value: int | ExpressionMethods[OwnerT, int],
    ) -> ValueExpression[OwnerT, int]: ...

    @overload
    def sub(
        self: ExpressionMethods[OwnerT, int],
        value: ExpressionMethods[OwnerT, int | None] | None,
    ) -> ValueExpression[OwnerT, int | None]: ...

    @overload
    def sub(
        self: ExpressionMethods[OwnerT, int | None],
        value: int
        | ExpressionMethods[OwnerT, int]
        | ExpressionMethods[OwnerT, int | None]
        | None,
    ) -> ValueExpression[OwnerT, int | None]: ...

    @overload
    def sub(
        self: ExpressionMethods[OwnerT, float],
        value: float | ExpressionMethods[OwnerT, float],
    ) -> ValueExpression[OwnerT, float]: ...

    @overload
    def sub(
        self: ExpressionMethods[OwnerT, float],
        value: ExpressionMethods[OwnerT, float | None] | None,
    ) -> ValueExpression[OwnerT, float | None]: ...

    @overload
    def sub(
        self: ExpressionMethods[OwnerT, float | None],
        value: float
        | ExpressionMethods[OwnerT, float]
        | ExpressionMethods[OwnerT, float | None]
        | None,
    ) -> ValueExpression[OwnerT, float | None]: ...

    def sub(self, value: object) -> ValueExpression[OwnerT, Any]:
        """Subtract a literal or same-source expression, propagating SQL NULL."""
        return _compose(self.__numeric_operand__(), "-", value)

    @overload
    def mul(
        self: ExpressionMethods[OwnerT, int],
        value: int | ExpressionMethods[OwnerT, int],
    ) -> ValueExpression[OwnerT, int]: ...

    @overload
    def mul(
        self: ExpressionMethods[OwnerT, int],
        value: ExpressionMethods[OwnerT, int | None] | None,
    ) -> ValueExpression[OwnerT, int | None]: ...

    @overload
    def mul(
        self: ExpressionMethods[OwnerT, int | None],
        value: int
        | ExpressionMethods[OwnerT, int]
        | ExpressionMethods[OwnerT, int | None]
        | None,
    ) -> ValueExpression[OwnerT, int | None]: ...

    @overload
    def mul(
        self: ExpressionMethods[OwnerT, float],
        value: float | ExpressionMethods[OwnerT, float],
    ) -> ValueExpression[OwnerT, float]: ...

    @overload
    def mul(
        self: ExpressionMethods[OwnerT, float],
        value: ExpressionMethods[OwnerT, float | None] | None,
    ) -> ValueExpression[OwnerT, float | None]: ...

    @overload
    def mul(
        self: ExpressionMethods[OwnerT, float | None],
        value: float
        | ExpressionMethods[OwnerT, float]
        | ExpressionMethods[OwnerT, float | None]
        | None,
    ) -> ValueExpression[OwnerT, float | None]: ...

    def mul(self, value: object) -> ValueExpression[OwnerT, Any]:
        """Multiply by a literal or same-source expression, propagating SQL NULL."""
        return _compose(self.__numeric_operand__(), "*", value)

    @overload
    def coalesce(
        self: ExpressionMethods[OwnerT, int],
        fallback: int
        | ExpressionMethods[OwnerT, int]
        | ExpressionMethods[OwnerT, int | None]
        | None,
    ) -> ValueExpression[OwnerT, int]: ...

    @overload
    def coalesce(
        self: ExpressionMethods[OwnerT, int | None],
        fallback: int | ExpressionMethods[OwnerT, int],
    ) -> ValueExpression[OwnerT, int]: ...

    @overload
    def coalesce(
        self: ExpressionMethods[OwnerT, int | None],
        fallback: ExpressionMethods[OwnerT, int | None] | None,
    ) -> ValueExpression[OwnerT, int | None]: ...

    @overload
    def coalesce(
        self: ExpressionMethods[OwnerT, float],
        fallback: float
        | ExpressionMethods[OwnerT, float]
        | ExpressionMethods[OwnerT, float | None]
        | None,
    ) -> ValueExpression[OwnerT, float]: ...

    @overload
    def coalesce(
        self: ExpressionMethods[OwnerT, float | None],
        fallback: float | ExpressionMethods[OwnerT, float],
    ) -> ValueExpression[OwnerT, float]: ...

    @overload
    def coalesce(
        self: ExpressionMethods[OwnerT, float | None],
        fallback: ExpressionMethods[OwnerT, float | None] | None,
    ) -> ValueExpression[OwnerT, float | None]: ...

    @overload
    def coalesce(
        self: ExpressionMethods[OwnerT, str],
        fallback: str
        | ExpressionMethods[OwnerT, str]
        | ExpressionMethods[OwnerT, str | None]
        | None,
    ) -> ValueExpression[OwnerT, str]: ...

    @overload
    def coalesce(
        self: ExpressionMethods[OwnerT, str | None],
        fallback: str | ExpressionMethods[OwnerT, str],
    ) -> ValueExpression[OwnerT, str]: ...

    @overload
    def coalesce(
        self: ExpressionMethods[OwnerT, str | None],
        fallback: ExpressionMethods[OwnerT, str | None] | None,
    ) -> ValueExpression[OwnerT, str | None]: ...

    def coalesce(self, fallback: object) -> ValueExpression[OwnerT, Any]:
        """Use the fallback only when SQL evaluates this value to NULL."""
        return _compose(self.__value_operand__(), "COALESCE", fallback)

    @overload
    def lower(self: ExpressionMethods[OwnerT, str]) -> ValueExpression[OwnerT, str]: ...

    @overload
    def lower(
        self: ExpressionMethods[OwnerT, str | None],
    ) -> ValueExpression[OwnerT, str | None]: ...

    def lower(self) -> ValueExpression[OwnerT, Any]:
        """Apply the backend's lower operation, preserving SQL NULL."""
        operand = self.__value_operand__()
        if operand.value_type is not str:
            msg = "lower() requires a native text expression"
            raise QueryConstructionError(msg)
        return replace(
            operand, value_type=str, operations=(*operand.operations, ("LOWER", None))
        )

    @overload
    def char_length(
        self: ExpressionMethods[OwnerT, str],
    ) -> ValueExpression[OwnerT, int]: ...

    @overload
    def char_length(
        self: ExpressionMethods[OwnerT, str | None],
    ) -> ValueExpression[OwnerT, int | None]: ...

    def char_length(self) -> ValueExpression[OwnerT, Any]:
        """Apply the backend's char_length operation, preserving SQL NULL."""
        operand = self.__value_operand__()
        if operand.value_type is not str:
            msg = "char_length() requires a native text expression"
            raise QueryConstructionError(msg)
        return replace(
            operand,
            value_type=int,
            operations=(*operand.operations, ("CHAR_LENGTH", None)),
        )


@dataclass(frozen=True)
class CaseRoot:
    """A searched condition with explicit branches and validated column reads."""

    condition: Predicate[Any]
    condition_columns: tuple[object, ...]
    otherwise: object
    then: object

    def __referenced_columns__(self) -> tuple[object, ...]:
        columns = self.condition_columns
        for branch in (self.then, self.otherwise):
            if isinstance(branch, ValueExpression):
                columns = (*columns, *branch.__referenced_columns__())
        return columns

    def __compile_sql__(self, ctx: CompileCtx) -> tuple[str, tuple[object, ...]]:
        if ctx.compile_predicate is None:
            msg = "CASE requires a predicate-aware compilation context"
            raise QueryCompilationError(msg)
        condition_sql, params = ctx.compile_predicate(self.condition)
        branches: list[str] = []
        for branch in (self.then, self.otherwise):
            if isinstance(branch, ValueExpression):
                sql, bindings = branch.__compile_sql__(ctx)
            else:
                sql, bindings = ctx.placeholder, (branch,)
            branches.append(sql)
            params = (*params, *bindings)
        return (
            f"CASE WHEN {condition_sql} THEN {branches[0]} ELSE {branches[1]} END",
            params,
        )


@dataclass(frozen=True)
class ValueExpression[OwnerT, T](
    ExpressionMethods[OwnerT, T], Comparable[OwnerT, T, T]
):
    """A private computed value, decoded independently from its source column."""

    column: object
    nullable: bool
    value_type: type[int | float | str]
    owner: type[OwnerT]
    operations: tuple[
        tuple[
            Literal["+", "-", "*", "COALESCE", "LOWER", "CHAR_LENGTH"],
            int | float | str | ValueExpression[OwnerT, Any] | None,
        ],
        ...,
    ] = ()

    def label(self, name: str) -> _NullExtendedLabel[OwnerT, T, T]:
        """Name the computed SQL value without evaluating it in Python."""
        return _NullExtendedLabel(name=name, operand=self)

    def __value_operand__(self) -> ValueExpression[OwnerT, T]:
        return self

    def __owner_model__(self) -> type[OwnerT]:
        return self.owner

    def __column_owner_type__(self) -> OwnerT:
        raise NotImplementedError

    def __column_value_type__(self) -> T:
        raise NotImplementedError

    def __referenced_columns__(self) -> tuple[object, ...]:
        """Expose all reads so SET dependencies cannot hide in nested operands."""
        columns = (
            self.column.__referenced_columns__()
            if isinstance(self.column, CaseRoot)
            else (self.column,)
        )
        for _, operand in self.operations:
            if isinstance(operand, ValueExpression):
                columns = (*columns, *operand.__referenced_columns__())
        return columns

    def __compile_sql__(self, ctx: CompileCtx) -> tuple[str, tuple[object, ...]]:
        if isinstance(self.column, CaseRoot):
            sql, params = self.column.__compile_sql__(ctx)
        else:
            sql, params = ctx.render_column(self.column), ()
        for operator, operand in self.operations:
            if operator in {"LOWER", "CHAR_LENGTH"}:
                function = "LOWER" if operator == "LOWER" else ctx.char_length_function
                if function is None:
                    msg = "this backend does not support character-length expressions"
                    raise QueryCompilationError(msg)
                sql = f"{function}({sql})"
                continue
            if isinstance(operand, ValueExpression):
                right_sql, right_params = operand.__compile_sql__(ctx)
            else:
                right_sql, right_params = ctx.placeholder, (operand,)
            sql = (
                f"COALESCE({sql}, {right_sql})"
                if operator == "COALESCE"
                else f"({sql} {operator} {right_sql})"
            )
            params = (*params, *right_params)
        return sql, params

    def __compile_select_sql__(self, ctx: CompileCtx) -> tuple[str, tuple[object, ...]]:
        return self.__compile_sql__(ctx)

    def __encode_comparison__(self, value: object) -> int | float | str | None:
        """Validate native value literals independently of column codecs."""
        return _encode_native_literal(self.value_type, value)

    def __decode__(self, raw: object) -> T:
        if raw is None and self.nullable:
            return cast("T", None)
        if type(raw) is not self.value_type:
            msg = "expression returned a result outside its value type contract"
            raise ModelValidationError(msg)
        # Construction tracks the native value domain and SQL nullability.
        return cast("T", raw)
