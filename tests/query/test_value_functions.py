"""Typed SQL value functions through query compilation."""

from typing import TYPE_CHECKING, ClassVar, assert_type

from pydantic import Json
from snektest import assert_eq, assert_raises, test

from snekql import sqlite


class Profile[S = sqlite.Pending](sqlite.Model[S]):
    """Optional display data with a native text representation."""

    __row_type__: ClassVar[sqlite.ReadType[Profile[sqlite.Row]]]

    id: Profile.Col[int] = sqlite.Integer(primary_key=True)
    nickname: Profile.Col[str | None] = sqlite.Text(nullable=True)


@test(mark="fast")
def coalesce_binds_its_fallback() -> None:
    """The fallback remains a bound value rather than SQL text."""
    compiled = sqlite.select(Profile.nickname.coalesce("anonymous")).compile()

    assert_eq(compiled.sql, 'SELECT COALESCE("nickname", ?) FROM "profile"')
    assert_eq(compiled.params, ("anonymous",))


@test(mark="fast")
def text_functions_compose_with_arithmetic() -> None:
    """Character count has an integer domain even when its input is text."""
    compiled = sqlite.select(Profile.nickname.lower().char_length().add(1)).compile()

    assert_eq(compiled.sql, 'SELECT (LENGTH(LOWER("nickname")) + ?) FROM "profile"')
    assert_eq(compiled.params, (1,))


@test(mark="fast")
def text_functions_reject_json_encoded_strings() -> None:
    """A JSON string's wire representation is not native text content."""

    class Document[S = sqlite.Pending](sqlite.Model[S]):
        __row_type__: ClassVar[sqlite.ReadType[Document[sqlite.Row]]]
        payload: Document.Col[Json[str]] = sqlite.Text()

    with assert_raises(sqlite.QueryConstructionError):
        Document.payload.lower()


@test(mark="fast")
def coalesce_rejects_incompatible_fallback() -> None:
    """SQL's implicit text/number conversion is not part of this contract."""
    with assert_raises(sqlite.QueryConstructionError):
        Profile.nickname.coalesce(1)  # ty: ignore[no-matching-overload]


@test(mark="fast")
def text_function_assignment_preserves_dependency_checks() -> None:
    """A character-count dependency cannot hide behind a function call."""
    query = (
        sqlite.update(Profile)
        .set(
            Profile.id.to_expr(Profile.nickname.char_length().coalesce(0)),
            Profile.nickname.to("changed"),
        )
        .all()
    )

    with assert_raises(sqlite.QueryCompilationError):
        query.compile()


@test(mark="fast")
def text_function_predicate_binds_its_comparison() -> None:
    """Function operands use their result domain for predicate bindings."""
    compiled = (
        sqlite.select(Profile).where(Profile.nickname.lower().eq("ada")).compile()
    )

    assert_eq(compiled.params, ("ada",))
    assert_eq(
        compiled.sql,
        'SELECT "id", "nickname" FROM "profile" WHERE (LOWER("nickname") = ?)',
    )


@test(mark="fast")
def text_function_preserves_alias_owner() -> None:
    """Composed functions resolve the alias, not its original physical table."""

    class Role:
        """Nominal display role."""

    profile = sqlite.alias(Profile, Role, name="display_profile")
    compiled = sqlite.select(profile.column(Profile.nickname).lower()).compile()

    assert_eq(
        compiled.sql, 'SELECT LOWER("nickname") FROM "profile" AS "display_profile"'
    )


if TYPE_CHECKING:

    async def check_function_result_types(transaction: sqlite.Transaction) -> None:
        """Both fallback and input nullability affect the inferred result."""
        assert_type(
            await transaction.fetch_all(sqlite.select(Profile.nickname.coalesce(None))),
            list[str | None],
        )
        assert_type(
            await transaction.fetch_all(
                sqlite.select(Profile.nickname.coalesce(Profile.nickname))
            ),
            list[str | None],
        )
        assert_type(
            await transaction.fetch_all(
                sqlite.select(Profile.nickname.coalesce("fallback").coalesce(None))
            ),
            list[str],
        )
        assert_type(
            await transaction.fetch_all(
                sqlite.select(Profile.nickname.coalesce("fallback").char_length())
            ),
            list[int],
        )
        Profile.nickname.to_expr(Profile.id.add(1))  # ty: ignore[no-matching-overload]
        Profile.nickname.coalesce(Profile.id)  # ty: ignore[no-matching-overload]


@test(mark="fast")
def grouped_projection_rejects_ungrouped_expression_inputs() -> None:
    """A function must not bypass grouping rules for its source column."""
    query = sqlite.select(Profile.id.count(), Profile.nickname.lower())

    with assert_raises(sqlite.QueryCompilationError):
        query.compile()
