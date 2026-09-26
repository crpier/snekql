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


def _compose[OwnerT, T, FamilyT](
    operand: ValueExpression[OwnerT, T, T, FamilyT],
    operator: Literal["+", "-", "*", "COALESCE"],
    value: object,
) -> ValueExpression[OwnerT, Any, Any, FamilyT]:
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


class ExpressionMethods[OwnerT, T, FamilyT = Any]:
    """Read-only SQL operations shared by columns and computed values."""

    def _value_identity(self, value: T) -> T:
        return value

    def __value_operand__(self) -> ValueExpression[OwnerT, T, Any, FamilyT]:
        """Resolve a native column or an already computed value."""
        raise NotImplementedError

    def __numeric_operand__(self) -> ValueExpression[OwnerT, T, Any, FamilyT]:
        """Reject arithmetic on non-numeric value expressions."""
        operand = self.__value_operand__()
        if operand.value_type not in (int, float):
            msg = "arithmetic requires a native numeric value"
            raise QueryConstructionError(msg)
        return operand

    @overload
    def add(
        self: ExpressionMethods[OwnerT, int, FamilyT],
        value: int | ExpressionMethods[OwnerT, int, FamilyT],
    ) -> ValueExpression[OwnerT, int, int, FamilyT]: ...

    @overload
    def add(
        self: ExpressionMethods[OwnerT, int, FamilyT],
        value: ExpressionMethods[OwnerT, int | None, FamilyT] | None,
    ) -> ValueExpression[OwnerT, int | None, int, FamilyT]: ...

    @overload
    def add(
        self: ExpressionMethods[OwnerT, int | None, FamilyT],
        value: int
        | ExpressionMethods[OwnerT, int, FamilyT]
        | ExpressionMethods[OwnerT, int | None, FamilyT]
        | None,
    ) -> ValueExpression[OwnerT, int | None, int, FamilyT]: ...

    @overload
    def add(
        self: ExpressionMethods[OwnerT, float, FamilyT],
        value: float | ExpressionMethods[OwnerT, float, FamilyT],
    ) -> ValueExpression[OwnerT, float, float, FamilyT]: ...

    @overload
    def add(
        self: ExpressionMethods[OwnerT, float, FamilyT],
        value: ExpressionMethods[OwnerT, float | None, FamilyT] | None,
    ) -> ValueExpression[OwnerT, float | None, float, FamilyT]: ...

    @overload
    def add(
        self: ExpressionMethods[OwnerT, float | None, FamilyT],
        value: float
        | ExpressionMethods[OwnerT, float, FamilyT]
        | ExpressionMethods[OwnerT, float | None, FamilyT]
        | None,
    ) -> ValueExpression[OwnerT, float | None, float, FamilyT]: ...

    def add(self, value: object) -> ValueExpression[OwnerT, Any, Any, FamilyT]:
        """Add a literal or same-source expression, propagating SQL NULL."""
        return _compose(self.__numeric_operand__(), "+", value)

    @overload
    def sub(
        self: ExpressionMethods[OwnerT, int, FamilyT],
        value: int | ExpressionMethods[OwnerT, int, FamilyT],
    ) -> ValueExpression[OwnerT, int, int, FamilyT]: ...

    @overload
    def sub(
        self: ExpressionMethods[OwnerT, int, FamilyT],
        value: ExpressionMethods[OwnerT, int | None, FamilyT] | None,
    ) -> ValueExpression[OwnerT, int | None, int, FamilyT]: ...

    @overload
    def sub(
        self: ExpressionMethods[OwnerT, int | None, FamilyT],
        value: int
        | ExpressionMethods[OwnerT, int, FamilyT]
        | ExpressionMethods[OwnerT, int | None, FamilyT]
        | None,
    ) -> ValueExpression[OwnerT, int | None, int, FamilyT]: ...

    @overload
    def sub(
        self: ExpressionMethods[OwnerT, float, FamilyT],
        value: float | ExpressionMethods[OwnerT, float, FamilyT],
    ) -> ValueExpression[OwnerT, float, float, FamilyT]: ...

    @overload
    def sub(
        self: ExpressionMethods[OwnerT, float, FamilyT],
        value: ExpressionMethods[OwnerT, float | None, FamilyT] | None,
    ) -> ValueExpression[OwnerT, float | None, float, FamilyT]: ...

    @overload
    def sub(
        self: ExpressionMethods[OwnerT, float | None, FamilyT],
        value: float
        | ExpressionMethods[OwnerT, float, FamilyT]
        | ExpressionMethods[OwnerT, float | None, FamilyT]
        | None,
    ) -> ValueExpression[OwnerT, float | None, float, FamilyT]: ...

    def sub(self, value: object) -> ValueExpression[OwnerT, Any, Any, FamilyT]:
        """Subtract a literal or same-source expression, propagating SQL NULL."""
        return _compose(self.__numeric_operand__(), "-", value)

    @overload
    def mul(
        self: ExpressionMethods[OwnerT, int, FamilyT],
        value: int | ExpressionMethods[OwnerT, int, FamilyT],
    ) -> ValueExpression[OwnerT, int, int, FamilyT]: ...

    @overload
    def mul(
        self: ExpressionMethods[OwnerT, int, FamilyT],
        value: ExpressionMethods[OwnerT, int | None, FamilyT] | None,
    ) -> ValueExpression[OwnerT, int | None, int, FamilyT]: ...

    @overload
    def mul(
        self: ExpressionMethods[OwnerT, int | None, FamilyT],
        value: int
        | ExpressionMethods[OwnerT, int, FamilyT]
        | ExpressionMethods[OwnerT, int | None, FamilyT]
        | None,
    ) -> ValueExpression[OwnerT, int | None, int, FamilyT]: ...

    @overload
    def mul(
        self: ExpressionMethods[OwnerT, float, FamilyT],
        value: float | ExpressionMethods[OwnerT, float, FamilyT],
    ) -> ValueExpression[OwnerT, float, float, FamilyT]: ...

    @overload
    def mul(
        self: ExpressionMethods[OwnerT, float, FamilyT],
        value: ExpressionMethods[OwnerT, float | None, FamilyT] | None,
    ) -> ValueExpression[OwnerT, float | None, float, FamilyT]: ...

    @overload
    def mul(
        self: ExpressionMethods[OwnerT, float | None, FamilyT],
        value: float
        | ExpressionMethods[OwnerT, float, FamilyT]
        | ExpressionMethods[OwnerT, float | None, FamilyT]
        | None,
    ) -> ValueExpression[OwnerT, float | None, float, FamilyT]: ...

    def mul(self, value: object) -> ValueExpression[OwnerT, Any, Any, FamilyT]:
        """Multiply by a literal or same-source expression, propagating SQL NULL."""
        return _compose(self.__numeric_operand__(), "*", value)

    @overload
    def coalesce(
        self: ExpressionMethods[OwnerT, int, FamilyT],
        fallback: int
        | ExpressionMethods[OwnerT, int, FamilyT]
        | ExpressionMethods[OwnerT, int | None, FamilyT]
        | None,
    ) -> ValueExpression[OwnerT, int, int, FamilyT]: ...

    @overload
    def coalesce(
        self: ExpressionMethods[OwnerT, int | None, FamilyT],
        fallback: int | ExpressionMethods[OwnerT, int, FamilyT],
    ) -> ValueExpression[OwnerT, int, int, FamilyT]: ...

    @overload
    def coalesce(
        self: ExpressionMethods[OwnerT, int | None, FamilyT],
        fallback: ExpressionMethods[OwnerT, int | None, FamilyT] | None,
    ) -> ValueExpression[OwnerT, int | None, int, FamilyT]: ...

    @overload
    def coalesce(
        self: ExpressionMethods[OwnerT, float, FamilyT],
        fallback: float
        | ExpressionMethods[OwnerT, float, FamilyT]
        | ExpressionMethods[OwnerT, float | None, FamilyT]
        | None,
    ) -> ValueExpression[OwnerT, float, float, FamilyT]: ...

    @overload
    def coalesce(
        self: ExpressionMethods[OwnerT, float | None, FamilyT],
        fallback: float | ExpressionMethods[OwnerT, float, FamilyT],
    ) -> ValueExpression[OwnerT, float, float, FamilyT]: ...

    @overload
    def coalesce(
        self: ExpressionMethods[OwnerT, float | None, FamilyT],
        fallback: ExpressionMethods[OwnerT, float | None, FamilyT] | None,
    ) -> ValueExpression[OwnerT, float | None, float, FamilyT]: ...

    @overload
    def coalesce(
        self: ExpressionMethods[OwnerT, str, FamilyT],
        fallback: str
        | ExpressionMethods[OwnerT, str, FamilyT]
        | ExpressionMethods[OwnerT, str | None, FamilyT]
        | None,
    ) -> ValueExpression[OwnerT, str, str, FamilyT]: ...

    @overload
    def coalesce(
        self: ExpressionMethods[OwnerT, str | None, FamilyT],
        fallback: str | ExpressionMethods[OwnerT, str, FamilyT],
    ) -> ValueExpression[OwnerT, str, str, FamilyT]: ...

    @overload
    def coalesce(
        self: ExpressionMethods[OwnerT, str | None, FamilyT],
        fallback: ExpressionMethods[OwnerT, str | None, FamilyT] | None,
    ) -> ValueExpression[OwnerT, str | None, str, FamilyT]: ...

    def coalesce(self, fallback: object) -> ValueExpression[OwnerT, Any, Any, FamilyT]:
        """Use the fallback only when SQL evaluates this value to NULL."""
        return _compose(self.__value_operand__(), "COALESCE", fallback)

    @overload
    def lower(
        self: ExpressionMethods[OwnerT, str, FamilyT],
    ) -> ValueExpression[OwnerT, str, str, FamilyT]: ...

    @overload
    def lower(
        self: ExpressionMethods[OwnerT, str | None, FamilyT],
    ) -> ValueExpression[OwnerT, str | None, str, FamilyT]: ...

    def lower(self) -> ValueExpression[OwnerT, Any, Any, FamilyT]:
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
        self: ExpressionMethods[OwnerT, str, FamilyT],
    ) -> ValueExpression[OwnerT, int, int, FamilyT]: ...

    @overload
    def char_length(
        self: ExpressionMethods[OwnerT, str | None, FamilyT],
    ) -> ValueExpression[OwnerT, int | None, int, FamilyT]: ...

    def char_length(self) -> ValueExpression[OwnerT, Any, Any, FamilyT]:
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
class ValueExpression[OwnerT, T, CompareT = T, FamilyT = Any](
    ExpressionMethods[OwnerT, T, FamilyT], Comparable[OwnerT, CompareT, T, FamilyT]
):
    """A computed value with independent read and literal-comparison domains.

    SQL NULL propagates through nullable expressions, but comparison literals
    remain non-null. Use is_null()/is_not_null() to test a missing value.
    """

    column: object
    nullable: bool
    value_type: type[int | float | str]
    owner: type[OwnerT]
    operations: tuple[
        tuple[
            Literal["+", "-", "*", "COALESCE", "LOWER", "CHAR_LENGTH"],
            int | float | str | ValueExpression[OwnerT, Any, Any, FamilyT] | None,
        ],
        ...,
    ] = ()

    def label(self, name: str) -> _NullExtendedLabel[OwnerT, T, CompareT, FamilyT]:
        """Name the computed SQL value without evaluating it in Python."""
        return _NullExtendedLabel(name=name, operand=self)

    def __value_operand__(self) -> ValueExpression[OwnerT, T, CompareT, FamilyT]:
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

    def __nullable_when_extended__(self) -> bool:
        """Compute possible NULL output when this expression's row is absent.

        Row absence nulls column reads, not literal CASE branches or COALESCE
        fallbacks. Fold the SQL operations instead of nulling every expression
        that happens to read a LEFT-joined owner.
        """
        if isinstance(self.column, CaseRoot):
            nullable = any(
                branch.__nullable_when_extended__()
                if isinstance(branch, ValueExpression)
                else branch is None
                for branch in (self.column.then, self.column.otherwise)
            )
        else:
            nullable = True
        for operator, operand in self.operations:
            if operator in {"LOWER", "CHAR_LENGTH"}:
                continue
            right_nullable = (
                operand.__nullable_when_extended__()
                if isinstance(operand, ValueExpression)
                else operand is None
            )
            nullable = (
                nullable and right_nullable
                if operator == "COALESCE"
                else nullable or right_nullable
            )
        return nullable

    def __decode__(self, raw: object) -> T:
        if raw is None and self.nullable:
            return cast("T", None)
        if type(raw) is not self.value_type:
            msg = "expression returned a result outside its value type contract"
            raise ModelValidationError(msg)
        # Construction tracks the native value domain and SQL nullability.
        return cast("T", raw)
