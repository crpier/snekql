"""Independent mariadb table declarations for the pilot."""

from typing import Any, ClassVar

from snekql import mariadb as db


def ddl() -> list[str]:
    """Scaffold users/profiles and teams/memberships through the public API."""

    class User[S = db.Pending](db.Model[S, "User[db.Fetched]"]):
        __tablename__ = "users"
        id: db.GenCol[int] = db.Integer(
            primary_key=True, auto_increment=True, default=db.PENDING_GENERATION
        )
        email: db.Col[str] = db.Text(unique=True)
        nickname: db.Col[str | None] = db.Text(nullable=True)
        status: db.Col[str] = db.Text(default="active")

    class Profile[S = db.Pending](db.Model[S, "Profile[db.Fetched]"]):
        __tablename__ = "profiles"
        user_id: db.FKCol[User, int] = db.ForeignKey(
            User.id, primary_key=True, on_delete="CASCADE"
        )
        bio: db.Col[str | None] = db.Text(nullable=True)

    class Team[S = db.Pending](db.Model[S, "Team[db.Fetched]"]):
        __tablename__ = "teams"
        id: db.GenCol[int] = db.Integer(
            primary_key=True, auto_increment=True, default=db.PENDING_GENERATION
        )
        name: db.Col[str] = db.Text(unique=True)

    class Membership[S = db.Pending](db.Model[S, "Membership[db.Fetched]"]):
        __tablename__ = "memberships"
        team_id: db.FKCol[Team, int] = db.ForeignKey(
            Team.id, primary_key=True, on_delete="CASCADE"
        )
        user_id: db.FKCol[User, int] = db.ForeignKey(
            User.id, primary_key=True, on_delete="RESTRICT"
        )
        alias: db.Col[str] = db.Text()
        __indexes__: ClassVar[list[db.Index[Any]]] = [
            db.Index(team_id, alias, unique=True),
            db.Index(user_id),
        ]

    # Fixed fixtures contain no semicolons inside identifiers or literals.
    return [
        statement.strip()
        for statement in db.scaffold([User, Profile, Team, Membership]).split(";")
        if statement.strip()
    ]
