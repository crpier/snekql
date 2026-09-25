"""Matched application using direct dual columns; table/materialization adapters remain."""

from collections.abc import AsyncIterator
from typing import ClassVar

from snekql import sqlite

from scratchpad.dual_descriptors import sqlite as storage
from scratchpad.dual_descriptors.sqlite import (
    Row,
    Transaction,
    insert,
    insert_many,
    table,
)
from scratchpad.paired_advanced.contracts import (
    AccountSummary,
    BalanceGroup,
    FirstRole,
    PostId,
    ReferralStep,
    SecondRole,
    UserId,
)


class User(storage.Model):
    __row__: ClassVar[type[UserRow]]
    user_id: storage.Col[UserId | storage.Omitted] = storage.Integer(
        primary_key=True, auto_increment=True, default=storage.OMIT
    )
    email: storage.Col[str] = storage.Text(unique=True)
    balance: storage.Col[int] = storage.Integer()
    nickname: storage.Col[str | None] = storage.Text(default=None)
    inviter_id: storage.FKCol[UserRow, UserId | None] = storage.ForeignKey(
        lambda: UserRow.user_id, default=None
    )

    def label(self) -> str:
        return self.nickname or self.email


class UserRow(User, Row):
    table_name = "users"
    user_id: storage.Col[UserId]

    def identity(self) -> UserId:
        return self.user_id


class Post(storage.Model):
    __row__: ClassVar[type[PostRow]]
    post_id: storage.Col[PostId | storage.Omitted] = storage.Integer(
        primary_key=True, auto_increment=True, default=storage.OMIT
    )
    author_id: storage.FKCol[UserRow, UserId] = storage.ForeignKey(UserRow.user_id)
    title: storage.Col[str] = storage.Text()


class PostRow(Post, Row):
    table_name = "posts"
    post_id: storage.Col[PostId]


# 13. A feed containing both authors and posts.
async def author_posts(transaction: Transaction) -> list[tuple[UserRow, PostRow]]:
    users, posts = (table(UserRow), table(PostRow))
    return await transaction.fetch_all(
        sqlite.select(users)
        .join(posts, on=PostRow.author_id.references(UserRow.user_id))
        .all()
        .order_by(PostRow.post_id.asc())
    )


# 14. Keep accounts without posts.
async def optional_posts(
    transaction: Transaction,
) -> list[tuple[UserRow, PostRow | None]]:
    users = table(UserRow)
    posts = table(PostRow)
    return await transaction.fetch_all(
        sqlite.select(users)
        .left_join(posts, on=PostRow.author_id.references(UserRow.user_id))
        .all()
        .order_by(UserRow.user_id.asc(), PostRow.post_id.asc())
    )


# 15. Two occurrences of User, with distinct roles.
async def referrers(transaction: Transaction) -> list[tuple[UserRow, UserRow | None]]:
    users = table(UserRow)
    invitee = sqlite.alias(users, FirstRole, name="invitee")
    inviter = sqlite.alias(users, SecondRole, name="inviter")
    return await transaction.fetch_all(
        sqlite.select(invitee)
        .left_join(
            inviter,
            on=invitee.column(UserRow.inviter_id).eq_col(
                inviter.column(UserRow.user_id)
            ),
        )
        .all()
        .order_by(invitee.column(UserRow.user_id).asc())
    )


# 16. Aggregate a named application result.
async def balance_groups(transaction: Transaction) -> list[BalanceGroup]:
    users = table(UserRow)
    return await transaction.fetch_all(
        sqlite.select(users)
        .all()
        .project(BalanceGroup, balance=UserRow.balance, total=users.count_all())
        .group_by(UserRow.balance)
        .having(users.count_all().gt(1))
        .order_by(UserRow.balance.asc())
    )


# 17. Expressions and pagination without model materialization.
async def account_page(transaction: Transaction) -> list[tuple[str, int, str, str]]:
    return await transaction.fetch_all(
        sqlite.select(
            UserRow.email,
            UserRow.balance.add(3),
            UserRow.nickname.coalesce("anonymous"),
            sqlite.case(UserRow.balance.gte(10), then="regular", otherwise="new"),
        )
        .all()
        .distinct()
        .order_by(UserRow.email.asc())
        .offset(1)
        .limit(2)
    )


# 18. Correlated EXISTS keeps a model result.
async def active_authors(transaction: Transaction) -> list[UserRow]:
    users = table(UserRow)
    return await transaction.fetch_all(
        sqlite.select(users)
        .where(
            sqlite.exists(
                sqlite.select(PostRow.title).where(
                    PostRow.author_id.eq_col(UserRow.user_id)
                )
            )
        )
        .order_by(UserRow.user_id.asc())
    )


# 19. A scalar subquery has a nullable result slot.
async def balance_reference(transaction: Transaction) -> list[tuple[str, int | None]]:
    return await transaction.fetch_all(
        sqlite.select(
            UserRow.email,
            sqlite.scalar(
                sqlite.select(UserRow.balance)
                .all()
                .order_by(UserRow.user_id.asc())
                .limit(1)
            ),
        )
        .all()
        .order_by(UserRow.user_id.asc())
    )


# 20. A CTE exposes named result labels.
async def named_accounts(transaction: Transaction) -> list[AccountSummary]:
    users = table(UserRow)
    email = UserRow.email.label("email")
    accounts = (
        sqlite.select(users)
        .where(UserRow.balance.gte(10))
        .project(AccountSummary, email=email, balance=UserRow.balance)
        .cte(FirstRole, name="accounts")
    )
    return await transaction.fetch_all(
        sqlite.select(accounts).where(accounts.column(email).eq("Grace"))
    )


# 21. UNION ALL retains the named application contract.
async def account_union(transaction: Transaction) -> list[AccountSummary]:
    users = table(UserRow)
    email = UserRow.email.label("email")
    active = (
        sqlite.select(users)
        .where(UserRow.balance.gte(10))
        .project(AccountSummary, email=email, balance=UserRow.balance)
    )
    new = (
        sqlite.select(users)
        .where(UserRow.balance.lt(10))
        .project(AccountSummary, email=email, balance=UserRow.balance)
    )
    accounts = active.union_all(new).cte(FirstRole, name="accounts")
    return await transaction.fetch_all(
        sqlite.select(accounts).all().order_by(accounts.column(email).asc())
    )


# 22. Recursive traversal through stored referrals.
async def referral_chain(
    transaction: Transaction, start: UserId, max_depth: int = 8
) -> list[ReferralStep]:
    users = table(UserRow)
    identity = UserRow.user_id.label("user_id")
    parent = UserRow.inviter_id.label("inviter_id")
    depth = sqlite.literal(0).label("depth")
    anchor = (
        sqlite.select(users)
        .where(UserRow.user_id.eq(start))
        .project(ReferralStep, user_id=identity, inviter_id=parent, depth=depth)
    )
    walk = sqlite.recursive_cte(anchor, FirstRole, name="referrals").step(
        lambda previous: (
            sqlite.select(users)
            .join(previous, on=previous.column(parent).eq_col(UserRow.user_id))
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
) -> list[UserRow]:
    return await transaction.execute(
        insert_many(
            [User(email=email, balance=balance) for email, balance in accounts]
        ).returning()
    )


# 24. A typed expression assignment with returning rows.
async def award_bonus(
    transaction: Transaction, identity: UserId, amount: int
) -> list[UserRow]:
    users = table(UserRow)
    return await transaction.execute(
        sqlite.update(users)
        .set(UserRow.balance.to_expr(UserRow.balance.add(amount)))
        .where(UserRow.user_id.eq(identity))
        .returning()
    )


# 25. DELETE RETURNING uses the same complete value type.
async def remove_new_accounts(transaction: Transaction) -> list[UserRow]:
    users = table(UserRow)
    return await transaction.execute(
        sqlite.delete(users).where(UserRow.balance.lt(10)).returning()
    )


# 26. Conflict update preserves fields not assigned.
async def refresh_nickname(
    transaction: Transaction, email_value: str, nickname_value: str
) -> UserRow:
    return await transaction.execute(
        insert(User(email=email_value, balance=0, nickname=nickname_value))
        .on_conflict(
            UserRow.email, action=sqlite.DoUpdate(UserRow.nickname.to_inserted())
        )
        .returning()
    )


# 27. Optional lookup preserves the complete model result.
async def lookup_account(transaction: Transaction, email_value: str) -> UserRow | None:
    users = table(UserRow)
    return await transaction.fetch_one_or_none(
        sqlite.select(users).where(UserRow.email.eq(email_value))
    )


# 28. Stream complete values without collecting the whole result.
async def stream_accounts(transaction: Transaction) -> AsyncIterator[list[UserRow]]:
    users = table(UserRow)
    async with transaction.fetch_chunks(
        sqlite.select(users).all().order_by(UserRow.user_id.asc()), size=2
    ) as batches:
        async for batch in batches:
            yield batch
