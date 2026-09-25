"""Input-first dual models, with one authoritative storage declaration."""

from typing import ClassVar

from scratchpad.dual_typing_parity.bridge import Row
from scratchpad.dual_typing_parity.domain import PostId, UserId
from scratchpad.paired_situations import dual_sqlite as sqlite


class User(sqlite.Model):
    __row__: ClassVar[type[UserRow]]
    user_id: sqlite.Col[UserId | sqlite.Omitted] = sqlite.Integer(
        primary_key=True, auto_increment=True, default=sqlite.OMIT
    )
    email: sqlite.Col[str] = sqlite.Text(unique=True)
    balance: sqlite.Col[int] = sqlite.Integer()
    nickname: sqlite.Col[str | None] = sqlite.Text(default=None)

    def label(self) -> str:
        return self.nickname or self.email


class UserRow(User, Row):
    table_name = "users"
    user_id: sqlite.Col[UserId]

    def identity(self) -> UserId:
        return self.user_id


class Post(sqlite.Model):
    __row__: ClassVar[type[PostRow]]
    post_id: sqlite.Col[PostId | sqlite.Omitted] = sqlite.Integer(
        primary_key=True, auto_increment=True, default=sqlite.OMIT
    )
    author_id: sqlite.FKCol[UserRow, UserId] = sqlite.ForeignKey(UserRow.user_id)
    title: sqlite.Col[str] = sqlite.Text()


class PostRow(Post, Row):
    table_name = "posts"
    post_id: sqlite.Col[PostId]
