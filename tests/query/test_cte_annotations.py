"""Backend-owned annotations for reusable named query helpers."""

from typing import ClassVar, get_type_hints

from snektest import Param, assert_eq, assert_raises, test

from snekql import mariadb, sqlite
from tests.query.test_recursive_ctes import Category, Visit, WalkRole


@test(mark="fast")
def named_recursive_callback_preserves_its_contract() -> None:
    """Public helper annotations retain the named row through recursion."""
    identifier = Category.id.label("id")
    depth = sqlite.literal(0).label("depth")
    anchor = sqlite.select(Category).all().project(Visit, id=identifier, depth=depth)

    def advance(
        previous: sqlite.Cte[Category, Visit, WalkRole],
    ) -> sqlite.NamedOperand[Visit]:
        return (
            sqlite.select(previous)
            .where(previous.column(depth).lt(2))
            .project(
                Visit,
                id=previous.column(identifier),
                depth=previous.column(depth).add(1),
            )
        )

    walk = sqlite.recursive_cte(anchor, WalkRole, name="walk").step(advance)
    compiled = sqlite.select(walk).all().compile()

    assert_eq(compiled.params, (0, 1, 2))
    assert_eq(
        get_type_hints(advance),
        {
            "previous": sqlite.Cte[Category, Visit, WalkRole],
            "return": sqlite.NamedOperand[Visit],
        },
    )


class NativeCategory[S = mariadb.Pending](mariadb.Model[S]):
    __row_type__: ClassVar[mariadb.ReadType[NativeCategory[mariadb.Row]]]
    id: mariadb.Col[int] = mariadb.Integer(primary_key=True)


@test(mark="fast")
def native_named_recursive_callback_preserves_its_contract() -> None:
    """Public helper annotations retain the named row through recursion."""
    identifier = NativeCategory.id.label("id")
    depth = mariadb.literal(0).label("depth")
    anchor = (
        mariadb.select(NativeCategory).all().project(Visit, id=identifier, depth=depth)
    )

    def advance(
        previous: mariadb.Cte[NativeCategory, Visit, WalkRole],
    ) -> mariadb.NamedOperand[Visit]:
        return (
            mariadb.select(previous)
            .where(previous.column(depth).lt(2))
            .project(
                Visit,
                id=previous.column(identifier),
                depth=previous.column(depth).add(1),
            )
        )

    walk = mariadb.recursive_cte(anchor, WalkRole, name="walk").step(advance)
    compiled = mariadb.select(walk).all().compile()

    assert_eq(compiled.params, (0, 1, 2))
    assert_eq(
        get_type_hints(advance),
        {
            "previous": mariadb.Cte[NativeCategory, Visit, WalkRole],
            "return": mariadb.NamedOperand[Visit],
        },
    )


@test(
    [
        Param(sqlite.Cte, name="sqlite_relation"),
        Param(sqlite.Cte[Category, Visit, WalkRole], name="sqlite_bound_relation"),
        Param(sqlite.NamedOperand, name="sqlite_operand"),
        Param(sqlite.NamedOperand[Visit], name="sqlite_bound_operand"),
        Param(mariadb.Cte, name="mariadb_relation"),
        Param(
            mariadb.Cte[NativeCategory, Visit, WalkRole], name="mariadb_bound_relation"
        ),
        Param(mariadb.NamedOperand, name="mariadb_operand"),
        Param(mariadb.NamedOperand[Visit], name="mariadb_bound_operand"),
    ],
    mark="fast",
)
def composition_annotations_are_not_factories(annotation: object) -> None:
    """Neither annotation can manufacture a query source or executable member."""
    with assert_raises(TypeError):
        annotation()  # ty: ignore[call-non-callable]
    with assert_raises(TypeError):
        annotation(_relation=object())  # ty: ignore[call-non-callable]
