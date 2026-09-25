"""Input-first application extension. Explicit native-query translation is temporary."""

from collections.abc import AsyncIterator
from typing import ClassVar

from snekql import sqlite

from scratchpad.dual_typing_parity.bridge import (
    Row,
    Transaction,
    column,
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
from scratchpad.paired_situations import dual_sqlite as storage


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
    users, posts = table(UserRow), table(PostRow)
    author, identity = column(PostRow.author_id), column(UserRow.user_id)
    post_id = column(PostRow.post_id)
    return await transaction.fetch_all(
        sqlite.select(users)
        .join(posts, on=author.references(identity))
        .all()
        .order_by(post_id.asc())
    )


# 14. Keep accounts without posts.
async def optional_posts(
    transaction: Transaction,
) -> list[tuple[UserRow, PostRow | None]]:
    author = column(PostRow.author_id)
    identity = column(UserRow.user_id)
    post_id = column(PostRow.post_id)
    users = table(UserRow)
    posts = table(PostRow)
    return await transaction.fetch_all(
        sqlite.select(users)
        .left_join(posts, on=author.references(identity))
        .all()
        .order_by(identity.asc(), post_id.asc())
    )


# 15. Two occurrences of User, with distinct roles.
async def referrers(transaction: Transaction) -> list[tuple[UserRow, UserRow | None]]:
    inviter_id = column(UserRow.inviter_id)
    identity = column(UserRow.user_id)
    users = table(UserRow)
    invitee = sqlite.alias(users, FirstRole, name="invitee")
    inviter = sqlite.alias(users, SecondRole, name="inviter")
    return await transaction.fetch_all(
        sqlite.select(invitee)
        .left_join(
            inviter, on=invitee.column(inviter_id).eq_col(inviter.column(identity))
        )
        .all()
        .order_by(invitee.column(identity).asc())
    )


# 16. Aggregate a named application result.
async def balance_groups(transaction: Transaction) -> list[BalanceGroup]:
    balance = column(UserRow.balance)
    users = table(UserRow)
    return await transaction.fetch_all(
        sqlite.select(users)
        .all()
        .project(BalanceGroup, balance=balance, total=users.count_all())
        .group_by(balance)
        .having(users.count_all().gt(1))
        .order_by(balance.asc())
    )


# 17. Expressions and pagination without model materialization.
async def account_page(transaction: Transaction) -> list[tuple[str, int, str, str]]:
    email = column(UserRow.email)
    balance = column(UserRow.balance)
    nickname = column(UserRow.nickname)
    return await transaction.fetch_all(
        sqlite.select(
            email,
            balance.add(3),
            nickname.coalesce("anonymous"),
            sqlite.case(balance.gte(10), then="regular", otherwise="new"),
        )
        .all()
        .distinct()
        .order_by(email.asc())
        .offset(1)
        .limit(2)
    )


# 18. Correlated EXISTS keeps a model result.
async def active_authors(transaction: Transaction) -> list[UserRow]:
    title = column(PostRow.title)
    author = column(PostRow.author_id)
    identity = column(UserRow.user_id)
    users = table(UserRow)
    return await transaction.fetch_all(
        sqlite.select(users)
        .where(sqlite.exists(sqlite.select(title).where(author.eq_col(identity))))
        .order_by(identity.asc())
    )


# 19. A scalar subquery has a nullable result slot.
async def balance_reference(transaction: Transaction) -> list[tuple[str, int | None]]:
    email = column(UserRow.email)
    balance = column(UserRow.balance)
    identity = column(UserRow.user_id)
    return await transaction.fetch_all(
        sqlite.select(
            email,
            sqlite.scalar(
                sqlite.select(balance).all().order_by(identity.asc()).limit(1)
            ),
        )
        .all()
        .order_by(identity.asc())
    )


# 20. A CTE exposes named result labels.
async def named_accounts(transaction: Transaction) -> list[AccountSummary]:
    email_column = column(UserRow.email)
    balance = column(UserRow.balance)
    users = table(UserRow)
    email = email_column.label("email")
    accounts = (
        sqlite.select(users)
        .where(balance.gte(10))
        .project(AccountSummary, email=email, balance=balance)
        .cte(FirstRole, name="accounts")
    )
    return await transaction.fetch_all(
        sqlite.select(accounts).where(accounts.column(email).eq("Grace"))
    )


# 21. UNION ALL retains the named application contract.
async def account_union(transaction: Transaction) -> list[AccountSummary]:
    email_column = column(UserRow.email)
    balance = column(UserRow.balance)
    users = table(UserRow)
    email = email_column.label("email")
    active = (
        sqlite.select(users)
        .where(balance.gte(10))
        .project(AccountSummary, email=email, balance=balance)
    )
    new = (
        sqlite.select(users)
        .where(balance.lt(10))
        .project(AccountSummary, email=email, balance=balance)
    )
    accounts = active.union_all(new).cte(FirstRole, name="accounts")
    return await transaction.fetch_all(
        sqlite.select(accounts).all().order_by(accounts.column(email).asc())
    )


# 22. Recursive traversal through stored referrals.
async def referral_chain(
    transaction: Transaction, start: UserId, max_depth: int = 8
) -> list[ReferralStep]:
    user_id = column(UserRow.user_id)
    inviter_id = column(UserRow.inviter_id)
    users = table(UserRow)
    identity = user_id.label("user_id")
    parent = inviter_id.label("inviter_id")
    depth = sqlite.literal(0).label("depth")
    anchor = (
        sqlite.select(users)
        .where(user_id.eq(start))
        .project(ReferralStep, user_id=identity, inviter_id=parent, depth=depth)
    )
    walk = sqlite.recursive_cte(anchor, FirstRole, name="referrals").step(
        lambda previous: (
            sqlite.select(users)
            .join(previous, on=previous.column(parent).eq_col(user_id))
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
    balance = column(UserRow.balance)
    user_id = column(UserRow.user_id)
    users = table(UserRow)
    return await transaction.execute(
        sqlite.update(users)
        .set(balance.to_expr(balance.add(amount)))
        .where(user_id.eq(identity))
        .returning()
    )


# 25. DELETE RETURNING uses the same complete value type.
async def remove_new_accounts(transaction: Transaction) -> list[UserRow]:
    balance = column(UserRow.balance)
    users = table(UserRow)
    return await transaction.execute(
        sqlite.delete(users).where(balance.lt(10)).returning()
    )


# 26. Conflict update preserves fields not assigned.
async def refresh_nickname(
    transaction: Transaction, email_value: str, nickname_value: str
) -> UserRow:
    email = column(UserRow.email)
    nickname = column(UserRow.nickname)
    return await transaction.execute(
        insert(User(email=email_value, balance=0, nickname=nickname_value))
        .on_conflict(email, action=sqlite.DoUpdate(nickname.to_inserted()))
        .returning()
    )


# 27. Optional lookup preserves the complete model result.
async def lookup_account(transaction: Transaction, email_value: str) -> UserRow | None:
    email = column(UserRow.email)
    users = table(UserRow)
    return await transaction.fetch_one_or_none(
        sqlite.select(users).where(email.eq(email_value))
    )


# 28. Stream complete values without collecting the whole result.
async def stream_accounts(transaction: Transaction) -> AsyncIterator[list[UserRow]]:
    users = table(UserRow)
    identity = column(UserRow.user_id)
    async with transaction.fetch_chunks(
        sqlite.select(users).all().order_by(identity.asc()), size=2
    ) as batches:
        async for batch in batches:
            yield batch
