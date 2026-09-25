"""Current native lifecycle generics, without the class-body witness shim."""

from snekql import sqlite

from scratchpad.dual_typing_parity.domain import PostId, UserId


class User[State = sqlite.Pending](sqlite.Model[State, "User[sqlite.Fetched]"]):
    __tablename__ = "users"
    user_id: sqlite.GenCol[UserId] = sqlite.Integer(
        primary_key=True, auto_increment=True, default=sqlite.PENDING_GENERATION
    )
    email: sqlite.Col[str] = sqlite.Text(unique=True)
    balance: sqlite.Col[int] = sqlite.Integer()
    nickname: sqlite.Col[str | None] = sqlite.Text(default=None)

    def label(self: User[sqlite.Pending] | User[sqlite.Fetched]) -> str:
        return self.nickname or self.email

    def identity(self: User[sqlite.Fetched]) -> UserId:
        return self.user_id


class Post[State = sqlite.Pending](sqlite.Model[State, "Post[sqlite.Fetched]"]):
    __tablename__ = "posts"
    post_id: sqlite.GenCol[PostId] = sqlite.Integer(
        primary_key=True, auto_increment=True, default=sqlite.PENDING_GENERATION
    )
    author_id: sqlite.FKCol[User, UserId] = sqlite.ForeignKey(User.user_id)
    title: sqlite.Col[str] = sqlite.Text()
