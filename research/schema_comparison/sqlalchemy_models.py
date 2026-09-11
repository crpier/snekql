"""SQLAlchemy declarative equivalents, without ORM relationships or sessions."""

# SQLAlchemy mapped_column returns MappedColumn[Any] by design.

from typing import Any

from sqlalchemy import (
    BigInteger,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    create_mock_engine,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def ddl(backend: str, track: str) -> list[str]:
    """Capture every statement SQLAlchemy create_all emits."""
    matched = track == "matched"
    text_type = Text if backend == "sqlite" and matched else String(255)
    if backend == "mariadb" and matched:
        text_type = String(255, collation="utf8mb4_bin")

    integer_type = BigInteger if backend == "mariadb" and matched else Integer

    class Base(DeclarativeBase):
        pass

    class User(Base):
        __tablename__ = "users"
        __table_args__: Any = {  # noqa: RUF012 - SQLAlchemy declares this as an instance attribute.
            "sqlite_strict": matched,
            "sqlite_autoincrement": matched,
        }
        id: Mapped[int] = mapped_column(integer_type, primary_key=True)
        email: Mapped[str] = mapped_column(text_type, unique=True)
        nickname: Mapped[str | None] = mapped_column(text_type)
        status: Mapped[str] = mapped_column(text_type, default="active")

    class Profile(Base):
        __tablename__ = "profiles"
        __table_args__: Any = {  # noqa: RUF012 - SQLAlchemy declares this as an instance attribute.
            "sqlite_strict": matched
        }
        user_id: Mapped[int] = mapped_column(
            ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
        )
        bio: Mapped[str | None] = mapped_column(text_type)

    class Team(Base):
        __tablename__ = "teams"
        __table_args__: Any = {  # noqa: RUF012 - SQLAlchemy declares this as an instance attribute.
            "sqlite_strict": matched,
            "sqlite_autoincrement": matched,
        }
        id: Mapped[int] = mapped_column(integer_type, primary_key=True)
        name: Mapped[str] = mapped_column(text_type, unique=True)

    class Membership(Base):
        __tablename__ = "memberships"
        __table_args__: Any = (
            Index("ux_memberships_team_alias", "team_id", "alias", unique=True),
            Index("ix_memberships_user", "user_id"),
            {"sqlite_strict": matched},
        )
        team_id: Mapped[int] = mapped_column(
            ForeignKey("teams.id", ondelete="CASCADE"), primary_key=True
        )
        user_id: Mapped[int] = mapped_column(
            ForeignKey("users.id", ondelete="RESTRICT"), primary_key=True
        )
        alias: Mapped[str] = mapped_column(text_type)

    statements: list[str] = []

    def capture(statement: Any, *_args: Any, **_kwargs: Any) -> None:
        statements.append(str(statement.compile(dialect=engine.dialect)).strip())

    engine = create_mock_engine(
        "sqlite://" if backend == "sqlite" else "mariadb+pymysql://", capture
    )
    Base.metadata.create_all(engine, checkfirst=False)
    return statements
