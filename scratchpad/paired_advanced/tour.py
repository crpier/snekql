"""Print matching application results. Run with python -m scratchpad.paired_advanced.tour."""

from anyio import run

from scratchpad.paired_advanced import body, dual
from scratchpad.paired_advanced.contracts import UserId
from scratchpad.paired_advanced.fixtures import database


async def main() -> None:
    async with database("body") as connected, connected.transaction() as transaction:
        print("CLASS-BODY")
        print(
            "optional posts:",
            [
                (user.email, None if post is None else post.title)
                for user, post in await body.optional_posts(transaction)
            ],
        )
        print(
            "referrers:",
            [
                (user.email, None if inviter is None else inviter.email)
                for user, inviter in await body.referrers(transaction)
            ],
        )
        print("groups:", await body.balance_groups(transaction))
        print("page:", await body.account_page(transaction))
        print("referral chain:", await body.referral_chain(transaction, UserId(3)))
        print(
            "bonus:",
            [
                (type(user).__name__, user.email, user.balance)
                for user in await body.award_bonus(transaction, UserId(2), 5)
            ],
        )
    async with database("dual") as connected, connected.transaction() as native:
        transaction = dual.Transaction(native)
        print("DUAL")
        print(
            "optional posts:",
            [
                (user.email, None if post is None else post.title)
                for user, post in await dual.optional_posts(transaction)
            ],
        )
        print(
            "referrers:",
            [
                (user.email, None if inviter is None else inviter.email)
                for user, inviter in await dual.referrers(transaction)
            ],
        )
        print("groups:", await dual.balance_groups(transaction))
        print("page:", await dual.account_page(transaction))
        print("referral chain:", await dual.referral_chain(transaction, UserId(3)))
        print(
            "bonus:",
            [
                (type(user).__name__, user.email, user.balance)
                for user in await dual.award_bonus(transaction, UserId(2), 5)
            ],
        )


if __name__ == "__main__":
    run(main)
