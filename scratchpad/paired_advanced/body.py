"""Class-body application extension. Native queries and materialization unchanged."""

from collections.abc import AsyncIterator
from typing import ClassVar

from snekql import sqlite
from snekql.sqlite import Fetched, Pending, Transaction

from scratchpad.class_body_usage.sqlite import Model, ReadType
from scratchpad.paired_advanced.contracts import (
    AccountSummary,
    BalanceGroup,
    FirstRole,
    PostId,
    ReferralStep,
    SecondRole,
    UserId,
)


class User[State = Pending](Model[State]):
    __read_type__: ClassVar[ReadType[User[Fetched]]]
    __tablename__ = "users"
    user_id: sqlite.GenCol[UserId] = sqlite.Integer(
        primary_key=True, auto_increment=True, default=sqlite.PENDING_GENERATION
    )
    email: sqlite.Col[str] = sqlite.Text(unique=True)
    balance: sqlite.Col[int] = sqlite.Integer()
    nickname: sqlite.Col[str | None] = sqlite.Text(default=None)
    inviter_id: sqlite.FKCol[User, UserId | None] = sqlite.ForeignKey(
        lambda: User.user_id, default=None
    )

    def label(self: User[Pending] | User[Fetched]) -> str:
        return self.nickname or self.email

    def identity(self: User[Fetched]) -> UserId:
        return self.user_id


class Post[State = Pending](Model[State]):
    __read_type__: ClassVar[ReadType[Post[Fetched]]]
    __tablename__ = "posts"
    post_id: sqlite.GenCol[PostId] = sqlite.Integer(
        primary_key=True, auto_increment=True, default=sqlite.PENDING_GENERATION
    )
    author_id: sqlite.FKCol[User, UserId] = sqlite.ForeignKey(User.user_id)
    title: sqlite.Col[str] = sqlite.Text()


# 13. A feed containing both authors and posts.
async def author_posts(
    transaction: Transaction,
) -> list[tuple[User[Fetched], Post[Fetched]]]:
    return await transaction.fetch_all(
        sqlite.select(User)
        .join(Post, on=Post.author_id.references(User.user_id))
        .all()
        .order_by(Post.post_id.asc())
    )


# 14. Keep accounts without posts.
async def optional_posts(
    transaction: Transaction,
) -> list[tuple[User[Fetched], Post[Fetched] | None]]:
    return await transaction.fetch_all(
        sqlite.select(User)
        .left_join(Post, on=Post.author_id.references(User.user_id))
        .all()
        .order_by(User.user_id.asc(), Post.post_id.asc())
    )


# 15. Two occurrences of User, with distinct roles.
async def referrers(
    transaction: Transaction,
) -> list[tuple[User[Fetched], User[Fetched] | None]]:
    invitee = sqlite.alias(User, FirstRole, name="invitee")
    inviter = sqlite.alias(User, SecondRole, name="inviter")
    return await transaction.fetch_all(
        sqlite.select(invitee)
        .left_join(
            inviter,
            on=invitee.column(User.inviter_id).eq_col(inviter.column(User.user_id)),
        )
        .all()
        .order_by(invitee.column(User.user_id).asc())
    )


# 16. Aggregate a named application result.
async def balance_groups(transaction: Transaction) -> list[BalanceGroup]:
    return await transaction.fetch_all(
        sqlite.select(User)
        .all()
        .project(BalanceGroup, balance=User.balance, total=User.count_all())
        .group_by(User.balance)
        .having(User.count_all().gt(1))
        .order_by(User.balance.asc())
    )


# 17. Expressions and pagination without model materialization.
async def account_page(transaction: Transaction) -> list[tuple[str, int, str, str]]:
    return await transaction.fetch_all(
        sqlite.select(
            User.email,
            User.balance.add(3),
            User.nickname.coalesce("anonymous"),
            sqlite.case(User.balance.gte(10), then="regular", otherwise="new"),
        )
        .all()
        .distinct()
        .order_by(User.email.asc())
        .offset(1)
        .limit(2)
    )


# 18. Correlated EXISTS keeps a model result.
async def active_authors(transaction: Transaction) -> list[User[Fetched]]:
    return await transaction.fetch_all(
        sqlite.select(User)
        .where(
            sqlite.exists(
                sqlite.select(Post.title).where(Post.author_id.eq_col(User.user_id))
            )
        )
        .order_by(User.user_id.asc())
    )


# 19. A scalar subquery has a nullable result slot.
async def balance_reference(transaction: Transaction) -> list[tuple[str, int | None]]:
    return await transaction.fetch_all(
        sqlite.select(
            User.email,
            sqlite.scalar(
                sqlite.select(User.balance).all().order_by(User.user_id.asc()).limit(1)
            ),
        )
        .all()
        .order_by(User.user_id.asc())
    )


# 20. A CTE exposes named result labels.
async def named_accounts(transaction: Transaction) -> list[AccountSummary]:
    email = User.email.label("email")
    accounts = (
        sqlite.select(User)
        .where(User.balance.gte(10))
        .project(AccountSummary, email=email, balance=User.balance)
        .cte(FirstRole, name="accounts")
    )
    return await transaction.fetch_all(
        sqlite.select(accounts).where(accounts.column(email).eq("Grace"))
    )


# 21. UNION ALL retains the named application contract.
async def account_union(transaction: Transaction) -> list[AccountSummary]:
    email = User.email.label("email")
    active = (
        sqlite.select(User)
        .where(User.balance.gte(10))
        .project(AccountSummary, email=email, balance=User.balance)
    )
    new = (
        sqlite.select(User)
        .where(User.balance.lt(10))
        .project(AccountSummary, email=email, balance=User.balance)
    )
    accounts = active.union_all(new).cte(FirstRole, name="accounts")
    return await transaction.fetch_all(
        sqlite.select(accounts).all().order_by(accounts.column(email).asc())
    )


# 22. Recursive traversal through stored referrals.
async def referral_chain(
    transaction: Transaction, start: UserId, max_depth: int = 8
) -> list[ReferralStep]:
    identity = User.user_id.label("user_id")
    parent = User.inviter_id.label("inviter_id")
    depth = sqlite.literal(0).label("depth")
    anchor = (
        sqlite.select(User)
        .where(User.user_id.eq(start))
        .project(ReferralStep, user_id=identity, inviter_id=parent, depth=depth)
    )
    walk = sqlite.recursive_cte(anchor, FirstRole, name="referrals").step(
        lambda previous: (
            sqlite.select(User)
            .join(previous, on=previous.column(parent).eq_col(User.user_id))
            .where(previous.column(depth).lt(max_depth))
            .project(
                ReferralStep,
                user_id=identity,
                inviter_id=parent,
                depth=previous.column(depth).add(1),
            )
        )
    )
    return await transaction.fetch_all(
        sqlite.select(walk).all().order_by(walk.column(depth).asc())
    )


# 23. Bulk input produces complete rows.
async def import_accounts(
    transaction: Transaction, accounts: list[tuple[str, int]]
) -> list[User[Fetched]]:
    return await transaction.execute(
        sqlite.insert(
            [User(email=email, balance=balance) for email, balance in accounts]
        ).returning()
    )


# 24. A typed expression assignment with returning rows.
async def award_bonus(
    transaction: Transaction, identity: UserId, amount: int
) -> list[User[Fetched]]:
    return await transaction.execute(
        sqlite.update(User)
        .set(User.balance.to_expr(User.balance.add(amount)))
        .where(User.user_id.eq(identity))
        .returning()
    )


# 25. DELETE RETURNING uses the same complete value type.
async def remove_new_accounts(transaction: Transaction) -> list[User[Fetched]]:
    return await transaction.execute(
        sqlite.delete(User).where(User.balance.lt(10)).returning()
    )


# 26. Conflict update preserves fields not assigned.
async def refresh_nickname(
    transaction: Transaction, email_value: str, nickname_value: str
) -> User[Fetched]:
    return await transaction.execute(
        sqlite.insert(User(email=email_value, balance=0, nickname=nickname_value))
        .on_conflict(User.email, action=sqlite.DoUpdate(User.nickname.to_inserted()))
        .returning()
    )


# 27. Optional lookup preserves the complete model result.
async def lookup_account(
    transaction: Transaction, email_value: str
) -> User[Fetched] | None:
    return await transaction.fetch_one_or_none(
        sqlite.select(User).where(User.email.eq(email_value))
    )


# 28. Stream complete values without collecting the whole result.
async def stream_accounts(
    transaction: Transaction,
) -> AsyncIterator[list[User[Fetched]]]:
    async with transaction.fetch_chunks(
        sqlite.select(User).all().order_by(User.user_id.asc()), size=2
    ) as batches:
        async for batch in batches:
            yield batch
