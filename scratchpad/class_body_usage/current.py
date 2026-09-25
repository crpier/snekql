"""Current native declarations and ordinary application operations."""

from dataclasses import dataclass

from snekql import sqlite
from snekql.sqlite import Fetched, Model, Pending


class User[State = Pending](Model[State, "User[Fetched]"]):
    __tablename__ = "users"

    user_id: sqlite.GenCol[int] = sqlite.Integer(
        primary_key=True, auto_increment=True, default=sqlite.PENDING_GENERATION
    )
    email: sqlite.Col[str] = sqlite.Text(unique=True)
    display_name: sqlite.Col[str | None] = sqlite.Text(default=None)
    active: sqlite.Col[bool] = sqlite.Integer(default=True)
    created_at: sqlite.GenCol[sqlite.UtcDatetime] = sqlite.Text(
        default=sqlite.CurrentTimestamp
    )

    def label(self: User[Pending] | User[Fetched]) -> str:
        """Available before and after insertion; only uses ordinary fields."""
        return self.display_name or self.email

    def identity(self: User[Fetched]) -> int:
        """Only a complete specialization promises a generated identifier."""
        return self.user_id


class Post[State = Pending](Model[State, "Post[Fetched]"]):
    __tablename__ = "posts"

    post_id: sqlite.GenCol[int] = sqlite.Integer(
        primary_key=True, auto_increment=True, default=sqlite.PENDING_GENERATION
    )
    author_id: sqlite.FKCol[User, int] = sqlite.ForeignKey(User.user_id)
    title: sqlite.Col[str] = sqlite.Text()


class UserSettings[State = Pending](Model[State, "UserSettings[Fetched]"]):
    __tablename__ = "user_settings"

    user_id: sqlite.FKCol[User, int] = sqlite.ForeignKey(User.user_id, primary_key=True)
    timezone: sqlite.Col[str] = sqlite.Text()
    digest_hour: sqlite.GenCol[int] = sqlite.Integer(default=sqlite.LiteralDefault(9))


@dataclass(frozen=True)
class PublicUser:
    """An explicitly selected response contract, separate from the storage model."""

    email: str
    user_id: int


def public_user(user: User[Fetched]) -> PublicUser:
    return PublicUser(email=user.email, user_id=user.user_id)


def active_users() -> sqlite.Select[User[Fetched]]:
    """Return a ready query with its exact result type, not mutable scope state."""
    return sqlite.select(User).where(User.active.eq(True)).order_by(User.user_id.asc())


async def create_user(transaction: sqlite.Transaction, email: str) -> User[Fetched]:
    """Execution stays in the caller's native transaction."""
    return await transaction.execute(sqlite.insert(User(email=email)).returning())


async def fetch_user(
    transaction: sqlite.Transaction, user_id: int
) -> User[Fetched] | None:
    return await transaction.fetch_one_or_none(
        sqlite.select(User).where(User.user_id.eq(user_id))
    )


async def list_users(transaction: sqlite.Transaction) -> list[User[Fetched]]:
    return await transaction.fetch_all(active_users())


async def user_summaries(transaction: sqlite.Transaction) -> list[tuple[int, str]]:
    return await transaction.fetch_all(
        sqlite.select(User.user_id, User.email).all().order_by(User.user_id.asc())
    )


async def author_emails(transaction: sqlite.Transaction) -> list[str]:
    return await transaction.fetch_all(
        sqlite.select(User.email)
        .join(Post, on=Post.author_id.references(User.user_id))
        .all()
    )


async def rename_user(
    transaction: sqlite.Transaction, user_id: int, display_name: str | None
) -> list[User[Fetched]]:
    return await transaction.execute(
        sqlite.update(User)
        .set(User.display_name.to(display_name))
        .where(User.user_id.eq(user_id))
        .returning()
    )


async def remove_posts(
    transaction: sqlite.Transaction, author_id: int
) -> list[Post[Fetched]]:
    return await transaction.execute(
        sqlite.delete(Post).where(Post.author_id.eq(author_id)).returning()
    )


async def save_settings(
    transaction: sqlite.Transaction, user_id: int, timezone: str
) -> UserSettings[Fetched]:
    return await transaction.execute(
        sqlite.insert(UserSettings(user_id=user_id, timezone=timezone))
        .on_conflict(
            UserSettings.user_id,
            action=sqlite.DoUpdate(UserSettings.timezone.to_inserted()),
        )
        .returning()
    )


async def create_users(
    transaction: sqlite.Transaction, emails: list[str]
) -> list[User[Fetched]]:
    return await transaction.execute(
        sqlite.insert([User(email=email) for email in emails]).returning()
    )
