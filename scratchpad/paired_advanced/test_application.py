"""Matching application behavior, with independent expected business values."""

from typing import Literal, assert_type

from snekql import sqlite
from snektest import Param, assert_eq, load_fixture, test

from scratchpad.paired_advanced import body, dual
from scratchpad.paired_advanced.contracts import (
    AccountSummary,
    BalanceGroup,
    ReferralStep,
    UserId,
)
from scratchpad.paired_advanced.fixtures import cyclic_database, database


@test(
    [
        Param[Literal["body", "dual"]](value="body", name="body"),
        Param[Literal["body", "dual"]](value="dual", name="dual"),
    ],
    mark="medium",
)
async def author_posts_keep_both_model_slots(variant: Literal["body", "dual"]) -> None:
    connected = await load_fixture(database(variant))
    async with connected.transaction() as native:
        if variant == "body":
            rows = await body.author_posts(native)
            assert_type(
                rows, list[tuple[body.User[sqlite.Fetched], body.Post[sqlite.Fetched]]]
            )
            assert_eq(
                [(type(user), type(post)) for user, post in rows],
                [(body.User, body.Post)] * 3,
            )
        else:
            rows = await dual.author_posts(dual.Transaction(native))
            assert_type(rows, list[tuple[dual.UserRow, dual.PostRow]])
            assert_eq(
                [(type(user), type(post)) for user, post in rows],
                [(dual.UserRow, dual.PostRow)] * 3,
            )
    assert_eq(
        [(user.email, post.title) for user, post in rows],
        [("Ada", "Notes"), ("Ada", "SQL"), ("Grace", "Compilers")],
    )


@test(
    [
        Param[Literal["body", "dual"]](value="body", name="body"),
        Param[Literal["body", "dual"]](value="dual", name="dual"),
    ],
    mark="medium",
)
async def optional_posts_has_matching_results(variant: Literal["body", "dual"]) -> None:
    connected = await load_fixture(database(variant))
    async with connected.transaction() as native:
        if variant == "body":
            rows = await body.optional_posts(native)
            assert_type(
                rows,
                list[
                    tuple[body.User[sqlite.Fetched], body.Post[sqlite.Fetched] | None]
                ],
            )
        else:
            rows = await dual.optional_posts(dual.Transaction(native))
            assert_type(rows, list[tuple[dual.UserRow, dual.PostRow | None]])
    assert_eq(
        [(user.email, None if post is None else post.title) for user, post in rows],
        [("Ada", "Notes"), ("Ada", "SQL"), ("Grace", "Compilers"), ("Linus", None)],
    )


@test(
    [
        Param[Literal["body", "dual"]](value="body", name="body"),
        Param[Literal["body", "dual"]](value="dual", name="dual"),
    ],
    mark="medium",
)
async def referrers_has_matching_results(variant: Literal["body", "dual"]) -> None:
    connected = await load_fixture(database(variant))
    async with connected.transaction() as native:
        if variant == "body":
            rows = await body.referrers(native)
            assert_type(
                rows,
                list[
                    tuple[body.User[sqlite.Fetched], body.User[sqlite.Fetched] | None]
                ],
            )
        else:
            rows = await dual.referrers(dual.Transaction(native))
            assert_type(rows, list[tuple[dual.UserRow, dual.UserRow | None]])
    assert_eq(
        [
            (user.email, None if inviter is None else inviter.email)
            for user, inviter in rows
        ],
        [("Ada", None), ("Grace", "Ada"), ("Linus", "Grace")],
    )


@test(
    [
        Param[Literal["body", "dual"]](value="body", name="body"),
        Param[Literal["body", "dual"]](value="dual", name="dual"),
    ],
    mark="medium",
)
async def balance_groups_has_matching_results(variant: Literal["body", "dual"]) -> None:
    connected = await load_fixture(database(variant))
    async with connected.transaction() as native:
        if variant == "body":
            rows = await body.balance_groups(native)
            assert_type(rows, list[BalanceGroup])
        else:
            rows = await dual.balance_groups(dual.Transaction(native))
            assert_type(rows, list[BalanceGroup])
    assert_eq(rows, [BalanceGroup(balance=12, total=2)])


@test(
    [
        Param[Literal["body", "dual"]](value="body", name="body"),
        Param[Literal["body", "dual"]](value="dual", name="dual"),
    ],
    mark="medium",
)
async def account_page_has_matching_results(variant: Literal["body", "dual"]) -> None:
    connected = await load_fixture(database(variant))
    async with connected.transaction() as native:
        if variant == "body":
            rows = await body.account_page(native)
            assert_type(rows, list[tuple[str, int, str, str]])
        else:
            rows = await dual.account_page(dual.Transaction(native))
            assert_type(rows, list[tuple[str, int, str, str]])
    assert_eq(
        rows, [("Grace", 15, "Amazing", "regular"), ("Linus", 8, "anonymous", "new")]
    )


@test(
    [
        Param[Literal["body", "dual"]](value="body", name="body"),
        Param[Literal["body", "dual"]](value="dual", name="dual"),
    ],
    mark="medium",
)
async def active_authors_has_matching_results(variant: Literal["body", "dual"]) -> None:
    connected = await load_fixture(database(variant))
    async with connected.transaction() as native:
        if variant == "body":
            rows = await body.active_authors(native)
            assert_type(rows, list[body.User[sqlite.Fetched]])
        else:
            rows = await dual.active_authors(dual.Transaction(native))
            assert_type(rows, list[dual.UserRow])
    assert_eq([user.email for user in rows], ["Ada", "Grace"])


@test(
    [
        Param[Literal["body", "dual"]](value="body", name="body"),
        Param[Literal["body", "dual"]](value="dual", name="dual"),
    ],
    mark="medium",
)
async def balance_reference_has_matching_results(
    variant: Literal["body", "dual"],
) -> None:
    connected = await load_fixture(database(variant))
    async with connected.transaction() as native:
        if variant == "body":
            rows = await body.balance_reference(native)
            assert_type(rows, list[tuple[str, int | None]])
        else:
            rows = await dual.balance_reference(dual.Transaction(native))
            assert_type(rows, list[tuple[str, int | None]])
    assert_eq(rows, [("Ada", 12), ("Grace", 12), ("Linus", 12)])


@test(
    [
        Param[Literal["body", "dual"]](value="body", name="body"),
        Param[Literal["body", "dual"]](value="dual", name="dual"),
    ],
    mark="medium",
)
async def named_accounts_has_matching_results(variant: Literal["body", "dual"]) -> None:
    connected = await load_fixture(database(variant))
    async with connected.transaction() as native:
        if variant == "body":
            rows = await body.named_accounts(native)
            assert_type(rows, list[AccountSummary])
        else:
            rows = await dual.named_accounts(dual.Transaction(native))
            assert_type(rows, list[AccountSummary])
    assert_eq(rows, [AccountSummary(email="Grace", balance=12)])


@test(
    [
        Param[Literal["body", "dual"]](value="body", name="body"),
        Param[Literal["body", "dual"]](value="dual", name="dual"),
    ],
    mark="medium",
)
async def account_union_has_matching_results(variant: Literal["body", "dual"]) -> None:
    connected = await load_fixture(database(variant))
    async with connected.transaction() as native:
        if variant == "body":
            rows = await body.account_union(native)
            assert_type(rows, list[AccountSummary])
        else:
            rows = await dual.account_union(dual.Transaction(native))
            assert_type(rows, list[AccountSummary])
    assert_eq(
        rows,
        [
            AccountSummary(email="Ada", balance=12),
            AccountSummary(email="Grace", balance=12),
            AccountSummary(email="Linus", balance=5),
        ],
    )


@test(
    [
        Param[Literal["body", "dual"]](value="body", name="body"),
        Param[Literal["body", "dual"]](value="dual", name="dual"),
    ],
    mark="medium",
)
async def referral_chain_has_matching_results(variant: Literal["body", "dual"]) -> None:
    connected = await load_fixture(database(variant))
    async with connected.transaction() as native:
        if variant == "body":
            rows = await body.referral_chain(native, UserId(3))
            assert_type(rows, list[ReferralStep])
        else:
            rows = await dual.referral_chain(dual.Transaction(native), UserId(3))
            assert_type(rows, list[ReferralStep])
    assert_eq(
        [(step.user_id, step.inviter_id, step.depth) for step in rows],
        [(3, 2, 0), (2, 1, 1), (1, None, 2)],
    )


@test(
    [
        Param[Literal["body", "dual"]](value="body", name="body"),
        Param[Literal["body", "dual"]](value="dual", name="dual"),
    ],
    mark="medium",
)
async def import_accounts_has_matching_results(
    variant: Literal["body", "dual"],
) -> None:
    connected = await load_fixture(database(variant))
    async with connected.transaction() as native:
        if variant == "body":
            rows = await body.import_accounts(native, [("Barbara", 7), ("Margaret", 9)])
            assert_type(rows, list[body.User[sqlite.Fetched]])
        else:
            rows = await dual.import_accounts(
                dual.Transaction(native), [("Barbara", 7), ("Margaret", 9)]
            )
            assert_type(rows, list[dual.UserRow])
    assert_eq(
        [(user.email, user.balance) for user in rows], [("Barbara", 7), ("Margaret", 9)]
    )


@test(
    [
        Param[Literal["body", "dual"]](value="body", name="body"),
        Param[Literal["body", "dual"]](value="dual", name="dual"),
    ],
    mark="medium",
)
async def award_bonus_has_matching_results(variant: Literal["body", "dual"]) -> None:
    connected = await load_fixture(database(variant))
    async with connected.transaction() as native:
        if variant == "body":
            rows = await body.award_bonus(native, UserId(2), 5)
            assert_type(rows, list[body.User[sqlite.Fetched]])
        else:
            rows = await dual.award_bonus(dual.Transaction(native), UserId(2), 5)
            assert_type(rows, list[dual.UserRow])
    assert_eq([(user.email, user.balance) for user in rows], [("Grace", 17)])


@test(
    [
        Param[Literal["body", "dual"]](value="body", name="body"),
        Param[Literal["body", "dual"]](value="dual", name="dual"),
    ],
    mark="medium",
)
async def remove_new_accounts_has_matching_results(
    variant: Literal["body", "dual"],
) -> None:
    connected = await load_fixture(database(variant))
    async with connected.transaction() as native:
        if variant == "body":
            rows = await body.remove_new_accounts(native)
            assert_type(rows, list[body.User[sqlite.Fetched]])
        else:
            rows = await dual.remove_new_accounts(dual.Transaction(native))
            assert_type(rows, list[dual.UserRow])
    assert_eq([user.email for user in rows], ["Linus"])


@test(
    [
        Param[Literal["body", "dual"]](value="body", name="body"),
        Param[Literal["body", "dual"]](value="dual", name="dual"),
    ],
    mark="medium",
)
async def refresh_nickname_has_matching_results(
    variant: Literal["body", "dual"],
) -> None:
    connected = await load_fixture(database(variant))
    async with connected.transaction() as native:
        if variant == "body":
            rows = await body.refresh_nickname(native, "Ada", "A")
            assert_type(rows, body.User[sqlite.Fetched])
        else:
            rows = await dual.refresh_nickname(dual.Transaction(native), "Ada", "A")
            assert_type(rows, dual.UserRow)
    assert_eq((rows.email, rows.nickname, rows.balance), ("Ada", "A", 12))


@test(
    [
        Param[Literal["body", "dual"]](value="body", name="body"),
        Param[Literal["body", "dual"]](value="dual", name="dual"),
    ],
    mark="medium",
)
async def lookup_account_has_matching_results(variant: Literal["body", "dual"]) -> None:
    connected = await load_fixture(database(variant))
    async with connected.transaction() as native:
        if variant == "body":
            rows = await body.lookup_account(native, "Missing")
            assert_type(rows, body.User[sqlite.Fetched] | None)
        else:
            rows = await dual.lookup_account(dual.Transaction(native), "Missing")
            assert_type(rows, dual.UserRow | None)
    assert_eq(rows, None)


@test(
    [
        Param[Literal["body", "dual"]](value="body", name="body"),
        Param[Literal["body", "dual"]](value="dual", name="dual"),
    ],
    mark="medium",
)
async def streaming_keeps_complete_values_in_batches(
    variant: Literal["body", "dual"],
) -> None:
    connected = await load_fixture(database(variant))
    async with connected.transaction() as native:
        if variant == "body":
            batches = [batch async for batch in body.stream_accounts(native)]
            assert_type(batches, list[list[body.User[sqlite.Fetched]]])
        else:
            batches = [
                batch async for batch in dual.stream_accounts(dual.Transaction(native))
            ]
            assert_type(batches, list[list[dual.UserRow]])
    assert_eq(
        [[user.email for user in batch] for batch in batches],
        [["Ada", "Grace"], ["Linus"]],
    )


@test(
    [
        Param[Literal["body", "dual"]](value="body", name="body"),
        Param[Literal["body", "dual"]](value="dual", name="dual"),
    ],
    mark="medium",
)
async def referral_depth_limit_stops_before_the_root(
    variant: Literal["body", "dual"],
) -> None:
    connected = await load_fixture(database(variant))
    async with connected.transaction() as native:
        if variant == "body":
            rows = await body.referral_chain(native, UserId(3), max_depth=1)
        else:
            rows = await dual.referral_chain(
                dual.Transaction(native), UserId(3), max_depth=1
            )
    assert_eq([(step.user_id, step.depth) for step in rows], [(3, 0), (2, 1)])


@test(
    [
        Param[Literal["body", "dual"]](value="body", name="body"),
        Param[Literal["body", "dual"]](value="dual", name="dual"),
    ],
    mark="medium",
)
async def missing_referral_seed_returns_no_steps(
    variant: Literal["body", "dual"],
) -> None:
    connected = await load_fixture(database(variant))
    async with connected.transaction() as native:
        if variant == "body":
            rows = await body.referral_chain(native, UserId(42))
        else:
            rows = await dual.referral_chain(dual.Transaction(native), UserId(42))
    assert_eq(rows, [])


@test(
    [
        Param[Literal["body", "dual"]](value="body", name="body"),
        Param[Literal["body", "dual"]](value="dual", name="dual"),
    ],
    mark="medium",
)
async def optional_lookup_materializes_the_declared_class(
    variant: Literal["body", "dual"],
) -> None:
    connected = await load_fixture(database(variant))
    async with connected.transaction() as native:
        if variant == "body":
            row = await body.lookup_account(native, "Ada")
            assert_eq(type(row), body.User)
        else:
            row = await dual.lookup_account(dual.Transaction(native), "Ada")
            assert_eq(type(row), dual.UserRow)
    assert_eq(None if row is None else row.email, "Ada")


@test(
    [
        Param[Literal["body", "dual"]](value="body", name="body"),
        Param[Literal["body", "dual"]](value="dual", name="dual"),
    ],
    mark="medium",
)
async def returning_update_is_visible_after_commit(
    variant: Literal["body", "dual"],
) -> None:
    connected = await load_fixture(database(variant))
    async with connected.transaction() as native:
        if variant == "body":
            await body.award_bonus(native, UserId(2), 5)
        else:
            await dual.award_bonus(dual.Transaction(native), UserId(2), 5)
    async with connected.transaction() as native:
        row = (
            await body.lookup_account(native, "Grace")
            if variant == "body"
            else await dual.lookup_account(dual.Transaction(native), "Grace")
        )
    assert_eq(None if row is None else row.balance, 17)


@test(
    [
        Param[Literal["body", "dual"]](value="body", name="body"),
        Param[Literal["body", "dual"]](value="dual", name="dual"),
    ],
    mark="medium",
)
async def referral_cycle_is_bounded_by_explicit_depth(
    variant: Literal["body", "dual"],
) -> None:
    connected = await load_fixture(cyclic_database(variant))
    async with connected.transaction() as native:
        if variant == "body":
            rows = await body.referral_chain(native, UserId(3), max_depth=4)
        else:
            rows = await dual.referral_chain(
                dual.Transaction(native), UserId(3), max_depth=4
            )
    assert_eq(
        [(step.user_id, step.depth) for step in rows],
        [(3, 0), (2, 1), (1, 2), (3, 3), (2, 4)],
    )
