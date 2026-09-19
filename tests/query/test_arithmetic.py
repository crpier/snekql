"""Native numeric expressions through public query compilation."""

from typing import TYPE_CHECKING, assert_type

from snektest import Param, assert_eq, assert_raises, test

from snekql import sqlite


class Inventory[S = sqlite.Pending](sqlite.Model[S, "Inventory[sqlite.Fetched]"]):
    """Stock and optimistic version counters."""

    id: Inventory.Col[int] = sqlite.Integer(primary_key=True)
    quantity: Inventory.Col[int] = sqlite.Integer()
    version: Inventory.Col[int] = sqlite.Integer()


@test(mark="fast")
def arithmetic_projection_binds_literals() -> None:
    """An increment is performed in SQL, with its operand bound separately."""
    compiled = sqlite.select(Inventory.quantity.add(1)).all().compile()

    assert_eq(compiled.sql, 'SELECT ("quantity" + ?) FROM "inventory"')
    assert_eq(compiled.params, (1,))


@test(mark="fast")
def counter_assignment_uses_current_column() -> None:
    """An update sends the increment, not a previously fetched counter value."""
    compiled = (
        sqlite.update(Inventory)
        .set(Inventory.version.to_expr(Inventory.version.add(1)))
        .where(Inventory.id.eq(7))
        .compile()
    )

    assert_eq(
        compiled.sql,
        'UPDATE "inventory" SET "version" = ("version" + ?) WHERE ("id" = ?)',
    )
    assert_eq(compiled.params, (1, 7))


@test(mark="fast")
def arithmetic_composition_preserves_parentheses() -> None:
    """Chained methods retain their evaluation order instead of SQL precedence."""
    compiled = sqlite.select(Inventory.quantity.sub(2).mul(3).add(1)).all().compile()

    assert_eq(compiled.sql, 'SELECT ((("quantity" - ?) * ?) + ?) FROM "inventory"')
    assert_eq(compiled.params, (2, 3, 1))


@test(mark="fast")
def assignment_cannot_read_another_assigned_column() -> None:
    """SET order must not change results between SQLite and MariaDB."""
    query = (
        sqlite.update(Inventory)
        .set(
            Inventory.quantity.to(10),
            Inventory.version.to_expr(Inventory.quantity),
        )
        .all()
    )

    with assert_raises(sqlite.QueryCompilationError):
        query.compile()


@test(mark="fast")
def arithmetic_rejects_out_of_range_integer_bindings() -> None:
    """Oversized Python integers must fail before reaching a driver."""
    with assert_raises(sqlite.QueryConstructionError):
        Inventory.quantity.add(2**63)


@test(mark="fast")
def expression_assignments_are_update_only() -> None:
    """Conflict writes must not accidentally encode an expression as a literal."""
    query = sqlite.insert(Inventory(id=1, quantity=3, version=1)).on_conflict(
        Inventory.id,
        action=sqlite.DoUpdate(Inventory.version.to_expr(Inventory.version.add(1))),
    )

    with assert_raises(sqlite.QueryCompilationError):
        query.compile()


@test(mark="fast")
def arithmetic_accepts_nested_column_expressions() -> None:
    """Column operands retain their grouping inside another expression."""
    compiled = (
        sqlite.select(Inventory.quantity.add(Inventory.version.mul(2))).all().compile()
    )

    assert_eq(compiled.sql, 'SELECT ("quantity" + ("version" * ?)) FROM "inventory"')
    assert_eq(compiled.params, (2,))


@test(mark="fast")
def nested_assignment_dependency_is_rejected() -> None:
    """A changed column cannot hide inside the right side of arithmetic."""
    query = (
        sqlite.update(Inventory)
        .set(
            Inventory.quantity.to_expr(
                Inventory.quantity.add(Inventory.version.mul(2))
            ),
            Inventory.version.to(10),
        )
        .all()
    )

    with assert_raises(sqlite.QueryCompilationError):
        query.compile()


if TYPE_CHECKING:

    class Other[S = sqlite.Pending](sqlite.Model[S, "Other[sqlite.Fetched]"]):
        """An unrelated scope for negative typing cases."""

        id: Other.Col[int] = sqlite.Integer(primary_key=True)

    def check_arithmetic_scope() -> None:
        """Column and expression operands must keep the target model owner."""
        Inventory.quantity.add("wrong")  # ty: ignore[no-matching-overload]
        Inventory.quantity.add(Other.id)  # ty: ignore[no-matching-overload]
        Inventory.quantity.to_expr(Other.id.add(1))  # ty: ignore[no-matching-overload]


@test(mark="fast")
def arithmetic_rejects_text_encoded_numbers() -> None:
    """A numeric Logical Type does not authorize SQL arithmetic on its text codec."""

    class TextNumber[S = sqlite.Pending](sqlite.Model[S, "TextNumber[sqlite.Fetched]"]):
        value: TextNumber.Col[int] = sqlite.Text(primary_key=True)

    with assert_raises(sqlite.QueryConstructionError):
        TextNumber.value.add(1)


@test(mark="fast")
def arithmetic_preserves_alias_scope() -> None:
    """An expression over an alias selects that role, not the physical table."""

    class StockRole:
        pass

    stock = sqlite.alias(Inventory, StockRole, name="stock")
    compiled = sqlite.select(stock.column(Inventory.quantity).add(1)).all().compile()

    assert_eq(compiled.sql, 'SELECT ("quantity" + ?) FROM "inventory" AS "stock"')


class NumericValues[S = sqlite.Pending](
    sqlite.Model[S, "NumericValues[sqlite.Fetched]"]
):
    """Native numeric domains with independently nullable columns."""

    id: NumericValues.Col[int] = sqlite.Integer(primary_key=True)
    integer: NumericValues.Col[int] = sqlite.Integer()
    optional_integer: NumericValues.Col[int | None] = sqlite.Integer(nullable=True)
    real: NumericValues.Col[float] = sqlite.Real()
    optional_real: NumericValues.Col[float | None] = sqlite.Real(nullable=True)


@test(mark="fast")
def nullable_arithmetic_keeps_null_bindings() -> None:
    """NULL is a numeric operand, not a missing argument or Python default."""
    compiled = sqlite.select(NumericValues.optional_integer.add(None)).all().compile()

    assert_eq(compiled.sql, 'SELECT ("optional_integer" + ?) FROM "numeric_values"')
    assert_eq(compiled.params, (None,))


@test(mark="fast")
def floating_arithmetic_binds_native_values() -> None:
    """REAL expressions keep floating operands and nested column references."""
    compiled = (
        sqlite.select(NumericValues.real.mul(1.5).add(NumericValues.optional_real))
        .all()
        .compile()
    )

    assert_eq(
        compiled.sql, 'SELECT (("real" * ?) + "optional_real") FROM "numeric_values"'
    )
    assert_eq(compiled.params, (1.5,))


@test(mark="fast")
def nullable_expression_cannot_target_required_column() -> None:
    """Erased typing must not allow SQL NULL into a non-null assignment contract."""
    with assert_raises(sqlite.QueryConstructionError):
        NumericValues.integer.to_expr(NumericValues.optional_integer.add(1))  # ty: ignore[no-matching-overload]


@test(mark="fast")
def real_expression_cannot_target_integer_column() -> None:
    """Computed assignments do not ask the engine to narrow numeric types."""
    with assert_raises(sqlite.QueryConstructionError):
        NumericValues.integer.to_expr(NumericValues.real.add(1.0))  # ty: ignore[no-matching-overload]


if TYPE_CHECKING:

    def check_nullable_assignment() -> None:
        """Nullable storage can receive a non-null expression of the same domain."""
        NumericValues.optional_integer.to_expr(NumericValues.integer.add(1))
        NumericValues.optional_real.to_expr(NumericValues.real.mul(1.5))


@test(mark="fast")
def computed_predicate_rejects_oversized_binding() -> None:
    """Computed comparisons must validate bindings before the driver sees them."""
    query = sqlite.select(Inventory).where(Inventory.quantity.add(1).gte(2**63))

    with assert_raises(sqlite.QueryConstructionError):
        query.compile()


@test(
    [
        Param(value=True, name="boolean"),
        Param(value=float("inf"), name="infinity"),
        Param(value=float("nan"), name="nan"),
    ],
    mark="fast",
)
def floating_arithmetic_rejects_unsafe_literals(value: float) -> None:
    """Python's numeric subtyping does not authorize bool or non-finite bindings."""
    with assert_raises(sqlite.QueryConstructionError):
        NumericValues.real.add(value)


@test(mark="fast")
def mixed_numeric_columns_are_rejected() -> None:
    """Erased typing cannot request implicit conversion between numeric domains."""
    with assert_raises(sqlite.QueryConstructionError):
        NumericValues.real.add(NumericValues.integer)  # ty: ignore[no-matching-overload]


if TYPE_CHECKING:

    async def check_numeric_result_types(transaction: sqlite.Transaction) -> None:
        """Nullability follows both operands, including nested expressions."""
        assert_type(
            await transaction.fetch_all(
                sqlite.select(NumericValues.integer.add(1)).all()
            ),
            list[int],
        )
        assert_type(
            await transaction.fetch_all(
                sqlite.select(NumericValues.integer.add(None)).all()
            ),
            list[int | None],
        )
        assert_type(
            await transaction.fetch_all(
                sqlite.select(NumericValues.optional_integer.mul(2)).all()
            ),
            list[int | None],
        )
        assert_type(
            await transaction.fetch_all(
                sqlite.select(NumericValues.real.sub(1.5)).all()
            ),
            list[float],
        )
        assert_type(
            await transaction.fetch_all(
                sqlite.select(NumericValues.real.add(None)).all()
            ),
            list[float | None],
        )
        assert_type(
            await transaction.fetch_all(
                sqlite.select(
                    NumericValues.real.add(NumericValues.optional_real.mul(2.0))
                ).all()
            ),
            list[float | None],
        )
        NumericValues.integer.add(NumericValues.real)  # ty: ignore[no-matching-overload]
        NumericValues.real.to_expr(NumericValues.optional_real)  # ty: ignore[no-matching-overload]
        NumericValues.integer.to_expr(NumericValues.optional_integer.add(1))  # ty: ignore[no-matching-overload]
