"""Searched CASE expressions through public compilation."""

from typing import TYPE_CHECKING, assert_type

from snektest import assert_eq, assert_raises, test

from snekql import mariadb, sqlite
from tests.query.test_arithmetic import Inventory, NumericValues
from tests.query.test_value_functions import Profile


@test(mark="fast")
def case_binds_condition_then_fallback_in_sql_order() -> None:
    """Both branches stay parameterized and the condition selects the owner."""
    compiled = (
        sqlite.select(
            sqlite.case(Inventory.quantity.gte(100), then="gold", otherwise="standard")
        )
        .all()
        .compile()
    )

    assert_eq(
        compiled.sql,
        'SELECT CASE WHEN "quantity" >= ? THEN ? ELSE ? END FROM "inventory"',
    )
    assert_eq(compiled.params, (100, "gold", "standard"))


@test(mark="fast")
def case_rejects_hidden_scalar_subquery_conditions() -> None:
    """Row-local CASE must not hide dependency reads inside a scalar SELECT."""
    condition = Inventory.id.eq_col(
        sqlite.scalar(sqlite.select(Inventory.version).all().limit(1))
    )

    with assert_raises(sqlite.QueryConstructionError):
        sqlite.case(condition, then=1, otherwise=0)


@test(mark="fast")
def case_condition_cannot_read_another_assigned_column() -> None:
    """Dependencies include the condition, not just values in THEN and ELSE."""
    query = (
        sqlite.update(Inventory)
        .set(
            Inventory.version.to(2),
            Inventory.quantity.to_expr(
                sqlite.case(
                    Inventory.version.gt(0),
                    then=Inventory.quantity.sub(1),
                    otherwise=Inventory.quantity,
                )
            ),
        )
        .all()
    )

    with assert_raises(sqlite.QueryCompilationError):
        query.compile()


@test(mark="fast")
def nested_case_preserves_parameter_order() -> None:
    """Nested branches bind immediately after their enclosing condition."""
    expression = sqlite.case(
        Inventory.quantity.gt(1),
        then=sqlite.case(Inventory.version.eq(2), then="yes", otherwise="no"),
        otherwise="empty",
    ).lower()
    compiled = sqlite.select(expression).all().compile()

    assert_eq(compiled.params, (1, 2, "yes", "no", "empty"))
    assert_eq(
        compiled.sql,
        'SELECT LOWER(CASE WHEN "quantity" > ? THEN CASE WHEN "version" = ? THEN ? ELSE ? END ELSE ? END) FROM "inventory"',
    )


@test(mark="fast")
def case_rejects_foreign_condition_column() -> None:
    """Both sides of a column comparison must belong to the same source."""
    condition = Inventory.id.eq_col(Profile.id)

    with assert_raises(sqlite.QueryConstructionError):
        sqlite.case(condition, then=1, otherwise=0)


@test(mark="fast")
def case_rejects_foreign_branch_owner() -> None:
    """Branches cannot smuggle another table into a single-source expression."""
    with assert_raises(sqlite.QueryConstructionError):
        sqlite.case(Inventory.id.eq(1), then=Profile.id, otherwise=0)  # ty: ignore[no-matching-overload]


@test(mark="fast")
def case_rejects_mixed_branch_domains() -> None:
    """Backend string/number coercion is not an inferred result contract."""
    with assert_raises(sqlite.QueryConstructionError):
        sqlite.case(Inventory.id.eq(1), then="yes", otherwise=0)  # ty: ignore[no-matching-overload]


@test(mark="fast")
def case_requires_a_typed_branch() -> None:
    """Two literal NULLs do not identify a native result domain."""
    with assert_raises(sqlite.QueryConstructionError):
        sqlite.case(Inventory.id.eq(1), then=None, otherwise=None)


@test(mark="fast")
def case_factory_rejects_another_backend() -> None:
    """Backend factories check predicate ownership before building a value."""
    with assert_raises(mariadb.QueryConstructionError):
        mariadb.case(Inventory.id.eq(1), then=1, otherwise=0)  # ty: ignore[no-matching-overload]


@test(mark="fast")
def case_preserves_alias_source() -> None:
    """A role-owned condition produces an expression owned by that role."""

    class Role:
        """Nominal query role."""

    profile = sqlite.alias(Profile, Role, name="display")
    compiled = (
        sqlite.select(
            sqlite.case(
                profile.column(Profile.id).eq(1),
                then=profile.column(Profile.nickname),
                otherwise=None,
            )
        )
        .all()
        .compile()
    )

    assert_eq(
        compiled.sql,
        'SELECT CASE WHEN "id" = ? THEN "nickname" ELSE ? END FROM "profile" AS "display"',
    )
    assert_eq(compiled.params, (1, None))


@test(mark="fast")
def joined_case_qualifies_predicate_columns() -> None:
    """CASE conditions use the same column qualification as their enclosing query."""
    query = (
        sqlite.select(
            sqlite.case(
                Profile.id.eq_col(Profile.id), then=Profile.nickname, otherwise=None
            )
        )
        .join(Inventory, on=Profile.id.eq_col(Inventory.id))
        .all()
    )
    compiled = query.compile()

    assert_eq(
        compiled.sql,
        'SELECT CASE WHEN "profile"."id" = "profile"."id" THEN "profile"."nickname" ELSE ? END FROM "profile" INNER JOIN "inventory" ON "profile"."id" = "inventory"."id"',
    )


@test(mark="fast")
def case_condition_respects_grouping_rules() -> None:
    """Literal branches do not remove the condition's column dependency."""
    query = sqlite.select(
        Inventory.id.count(), sqlite.case(Inventory.quantity.gt(0), then=1, otherwise=0)
    ).all()

    with assert_raises(sqlite.QueryCompilationError):
        query.compile()


if TYPE_CHECKING:

    async def check_case_result_contracts(transaction: sqlite.Transaction) -> None:
        """CASE tracks branch nullability without narrowing based on predicates."""
        assert_type(
            await transaction.fetch_all(
                sqlite.select(
                    sqlite.case(Inventory.id.eq(1), then=1, otherwise=2)
                ).all()
            ),
            list[int],
        )
        assert_type(
            await transaction.fetch_all(
                sqlite.select(
                    sqlite.case(Inventory.id.eq(1), then=1, otherwise=None)
                ).all()
            ),
            list[int | None],
        )
        assert_type(
            await transaction.fetch_all(
                sqlite.select(
                    sqlite.case(
                        Profile.id.eq(1), then=Profile.nickname, otherwise="fallback"
                    )
                ).all()
            ),
            list[str | None],
        )
        assert_type(
            await transaction.fetch_all(
                sqlite.select(
                    sqlite.case(Profile.id.eq(1), then="first", otherwise="second")
                ).all()
            ),
            list[str],
        )
        Inventory.quantity.to_expr(
            sqlite.case(Inventory.id.eq(1), then=1, otherwise=None)
        )  # ty: ignore[no-matching-overload]


@test(mark="fast")
def case_compares_computed_right_operand() -> None:
    """A computed comparison operand contributes its own ordered bindings."""
    expression = sqlite.case(
        Inventory.quantity.gt_col(Inventory.version.add(2)), then=1, otherwise=0
    )
    compiled = sqlite.select(expression).all().compile()

    assert_eq(
        compiled.sql,
        'SELECT CASE WHEN "quantity" > ("version" + ?) THEN ? ELSE ? END FROM "inventory"',
    )
    assert_eq(compiled.params, (2, 1, 0))


@test(mark="fast")
def case_comparison_cannot_reference_a_future_join() -> None:
    """A CASE on the right of a comparison still obeys the ON join prefix."""
    query = (
        sqlite.select(Profile)  # ty: ignore[no-matching-overload]
        .join(
            Inventory,
            on=Profile.id.eq_col(
                sqlite.case(
                    NumericValues.integer.gt(0), then=NumericValues.id, otherwise=0
                )
            ),
        )
        .join(NumericValues, on=Inventory.id.eq_col(NumericValues.id))
        .all()
    )

    with assert_raises(sqlite.QueryCompilationError):
        query.compile()
