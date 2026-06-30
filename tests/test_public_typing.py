"""Pyright-oriented public API prototypes."""

from __future__ import annotations

import uuid
from contextlib import AbstractAsyncContextManager
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, assert_type

from snekql import mariadb, sqlite
from snekql.sqlite import (
    PENDING_GENERATION,
    Aggregate,
    ChunkStream,
    CurrentTimestamp,
    Fetched,
    ForeignKey,
    Index,
    InsertManyQuery,
    InsertManyReturningQuery,
    InsertManyReturningTupleQuery,
    InsertManyReturningValueQuery,
    InsertQuery,
    InsertReturningQuery,
    InsertReturningTupleQuery,
    InsertReturningValueQuery,
    Integer,
    JoinModelQuery,
    Model,
    OrderBy,
    Pending,
    PendingGeneration,
    Predicate,
    Scalar,
    SelectModelQuery,
    SelectTupleQuery,
    SelectValueQuery,
    Text,
    Transaction,
    UpdateQuery,
    exists,
    insert,
    not_exists,
    scalar,
    select,
    update,
)
from snekql.testing import mariadb as testing_mariadb


class User[S = Pending](Model[S, "User[Fetched]"]):
    """Canonical table model used by public API typing examples."""

    id: User.GenCol[int] = Integer(
        primary_key=True,
        auto_increment=True,
        default=PENDING_GENERATION,
    )
    email: User.Col[str] = Text(nullable=False)
    status: User.Col[str] = Text(nullable=False, default="active")
    nickname: User.Col[str | None] = Text(nullable=True, default=None)
    created_at: User.GenCol[datetime] = Text(default=CurrentTimestamp)


class Order[S = Pending](Model[S, "Order[Fetched]"]):
    """Table with a foreign key to ``User`` for join typing examples."""

    id: Order.GenCol[int] = Integer(
        primary_key=True,
        auto_increment=True,
        default=PENDING_GENERATION,
    )
    user_id: Order.FKCol[User, int] = ForeignKey(User.id)
    # Nullable optional FK: ``default=None`` widens the value type and makes the
    # field omittable, parallel to the plain column constructors.
    reviewer_id: Order.FKCol[User, int | None] = ForeignKey(
        User.id, nullable=True, default=None
    )
    note: Order.Col[str] = Text(nullable=False)


class Region[S = Pending](Model[S, "Region[Fetched]"]):
    """Unjoined table used to probe out-of-scope rejections."""

    code: Region.Col[str] = Text(nullable=False)


class SqliteUser[S = Pending](sqlite.Model[S, "SqliteUser[Fetched]"]):
    """SQLite namespace table model used by public API typing examples."""

    id: SqliteUser.GenCol[int] = sqlite.Integer(
        primary_key=True,
        auto_increment=True,
        default=PENDING_GENERATION,
    )
    email: SqliteUser.Col[str] = sqlite.Text(nullable=False)
    # UUID logical type stored as TEXT on SQLite (no native UUID storage class).
    account_id: SqliteUser.Col[uuid.UUID] = sqlite.Text(
        nullable=False, default_factory=uuid.uuid4
    )


class MariadbUser[S = Pending](mariadb.Model[S, "MariadbUser[Fetched]"]):
    """MariaDB namespace table model used by public API typing examples."""

    id: MariadbUser.GenCol[int] = mariadb.Integer(
        primary_key=True,
        auto_increment=True,
        default=PENDING_GENERATION,
    )
    email: MariadbUser.Col[str] = mariadb.Text(nullable=False)
    # Native MariaDB UUID Column Type paired with the uuid.UUID logical type.
    account_id: MariadbUser.Col[uuid.UUID] = mariadb.Uuid(
        nullable=False, default_factory=uuid.uuid4
    )
    profile: MariadbUser.JsonCol[dict[str, object]] = mariadb.Json(nullable=False)
    # Nullable JSON: the ``default=None`` overload widens the value type to
    # optional and makes the field omittable, parallel to Integer/Real/Boolean.
    prefs: MariadbUser.JsonCol[dict[str, object] | None] = mariadb.Json(
        nullable=True, default=None
    )


if TYPE_CHECKING:

    class InvalidSqliteDefaults[S = Pending](
        Model[S, "InvalidSqliteDefaults[Fetched]"]
    ):
        """Invalid default declarations rejected by static typing."""

        text_default: InvalidSqliteDefaults.Col[int] = Text(default="nan")  # pyright: ignore[reportAssignmentType]
        factory_default: InvalidSqliteDefaults.Col[int] = Integer(
            default_factory=lambda: "nan"
        )  # pyright: ignore[reportAssignmentType]
        pending_generation_default: InvalidSqliteDefaults.Col[int] = Integer(  # pyright: ignore[reportAssignmentType, reportUnknownVariableType]
            default=PENDING_GENERATION
        )
        server_default: InvalidSqliteDefaults.Col[datetime] = Text(  # pyright: ignore[reportAssignmentType, reportUnknownVariableType]
            default=CurrentTimestamp
        )

    class InvalidOrderDefaults[S = Pending](Model[S, "InvalidOrderDefaults[Fetched]"]):
        """Invalid foreign-key default declarations rejected by static typing."""

        user_id: InvalidOrderDefaults.FKCol[User, int] = ForeignKey(  # pyright: ignore[reportAssignmentType, reportCallIssue]
            User.id,
            default="nan",  # pyright: ignore[reportArgumentType]
        )

    class InvalidMariadbDefaults[S = Pending](
        mariadb.Model[S, "InvalidMariadbDefaults[Fetched]"]
    ):
        """Invalid MariaDB default declarations rejected by static typing."""

        text_default: InvalidMariadbDefaults.Col[int] = mariadb.Text(default="nan")  # pyright: ignore[reportAssignmentType]
        factory_default: InvalidMariadbDefaults.Col[int] = mariadb.Uuid(
            default_factory=lambda: "nan"
        )  # pyright: ignore[reportAssignmentType]

    sqlite_config = sqlite.Config(database=Path("app.db"))
    _ = assert_type(sqlite_config, sqlite.Config)
    sqlite_index = sqlite.Index(SqliteUser.email)
    _ = assert_type(sqlite_index, Index[SqliteUser[Pending]])
    sqlite_user = SqliteUser(email="alice@example.com")
    _ = assert_type(sqlite_user, SqliteUser[Pending])
    _ = assert_type(sqlite_user.account_id, uuid.UUID)
    _ = assert_type(
        select(SqliteUser), SelectModelQuery[SqliteUser[Pending], SqliteUser[Fetched]]
    )

    _ = assert_type(mariadb.Model.__snekql_backend__, Literal["mariadb"])
    _ = assert_type(sqlite.Model.__snekql_backend__, Literal["sqlite"])

    mariadb_config = mariadb.Config(database="app", user="snekql")
    _ = assert_type(mariadb_config, mariadb.Config)
    test_server_context = testing_mariadb.temporary_mariadb_server(
        reset_database=True,
    )
    _ = assert_type(
        test_server_context,
        AbstractAsyncContextManager[testing_mariadb.TemporaryMariaDBServer],
    )
    test_server = testing_mariadb.TemporaryMariaDBServer(
        auth="insecure",
        database="test",
        data_directory=Path("data"),
        error_log_path=Path("mariadb.err"),
        host=None,
        password="",
        pid_path=Path("mariadb.pid"),
        port=None,
        socket_path=Path("mariadb.sock"),
        transports=frozenset({"unix_socket"}),
        user="root",
    )
    _ = assert_type(test_server.config(), mariadb.Config)

    async def check_test_server_sql_helper() -> None:
        """The public SQL helper is async and returns command output."""

        command_result = await test_server.run_sql("SELECT 1", check=False)
        _ = assert_type(command_result, testing_mariadb.MariaDBCommandResult)
        _ = assert_type(await test_server.reset_database(), None)

    mariadb_index = mariadb.Index(MariadbUser.email)
    _ = assert_type(mariadb_index, Index[MariadbUser[Pending]])
    mariadb_user = MariadbUser(email="alice@example.com")
    _ = assert_type(mariadb_user, MariadbUser[Pending])
    _ = assert_type(mariadb_user.account_id, uuid.UUID)
    # ``default=None`` makes the nullable JSON column omittable and optional.
    _ = assert_type(mariadb_user.prefs, dict[str, object] | None)
    _ = assert_type(
        select(MariadbUser),
        SelectModelQuery[MariadbUser[Pending], MariadbUser[Fetched]],
    )

    # Open-AST dialect operator (ADR 0004): the MariaDB JSON path operator is a
    # typed `int` operand and projection, and the result type flows through the
    # `select` overloads without the core naming the leaf expression.
    _ = assert_type(
        MariadbUser.profile.json_extract_int("$.age").gt(18),
        Predicate[MariadbUser[Pending]],
    )
    # A missing JSON path yields SQL NULL, so the projection is `int | None`.
    _ = assert_type(
        select(MariadbUser.profile.json_extract_int("$.age")),
        SelectValueQuery[Any, Any, int | None],
    )
    _ = assert_type(
        select(MariadbUser.email, MariadbUser.profile.json_extract_int("$.age")),
        SelectTupleQuery[MariadbUser[Pending], MariadbUser[Pending], str, int | None],
    )

    pending_user = User(email="alice@example.com")
    _ = assert_type(pending_user, User[Pending])
    _ = assert_type(pending_user.id, int | PendingGeneration)
    _ = assert_type(pending_user.email, str)
    _ = assert_type(pending_user.created_at, datetime | PendingGeneration)

    def check_fetched_user(fetched_user: User[Fetched]) -> None:
        """Fetched-state generated values are narrowed by descriptor overloads."""

        _ = assert_type(fetched_user.id, int)
        _ = assert_type(fetched_user.email, str)
        _ = assert_type(fetched_user.created_at, datetime)

    _ = assert_type(select(User), SelectModelQuery[User[Pending], User[Fetched]])
    _ = assert_type(
        select(User.email).where(User.email.eq("alice@example.com")).all(),
        SelectValueQuery[User[Pending], User[Pending], str],
    )
    _ = assert_type(
        select(User.email, User.status),
        SelectTupleQuery[User[Pending], User[Pending], str, str],
    )
    # Aggregates: column methods carry owner + result type; the star form lives
    # on the model. count is int; sum/min/max are nullable; avg is float | None.
    _ = assert_type(User.id.count(), Aggregate[User[Pending], int])
    _ = assert_type(User.count_all(), Aggregate[User[Pending], int])
    _ = assert_type(Order.id.sum(), Aggregate[Order[Pending], int | None])
    _ = assert_type(Order.id.min(), Aggregate[Order[Pending], int | None])
    _ = assert_type(Order.id.avg(), Aggregate[Order[Pending], float | None])
    _ = assert_type(
        select(User.id.count()).all(),
        SelectValueQuery[User[Pending], User[Pending], int],
    )
    _ = assert_type(
        select(Order.id.sum()).all(),
        SelectValueQuery[Order[Pending], Order[Pending], int | None],
    )
    # Grouped projection: a column and an aggregate land in a tuple select; the
    # aggregate carries its result type and an aggregate can drive order_by.
    _ = assert_type(
        select(User.status, User.id.count()).group_by(User.status).all(),
        SelectTupleQuery[User[Pending], User[Pending], str, int],
    )
    _ = assert_type(User.id.count().desc(), OrderBy[User[Pending]])
    _ = assert_type(
        select(User.status, Order.id.sum())
        .join(Order, on=Order.user_id.references(User.id))
        .group_by(User.status)
        .all(),
        SelectTupleQuery[
            User[Pending] | Order[Pending],
            User[Pending] | Order[Pending],
            str,
            int | None,
        ],
    )
    # HAVING: aggregates share the column comparison surface, so an aggregate
    # predicate carries its owner and having() widens the referenced-table union
    # exactly like where().
    _ = assert_type(User.id.count().gt(5), Predicate[User[Pending]])
    _ = assert_type(Order.id.sum().gt(5), Predicate[Order[Pending]])
    _ = assert_type(
        select(User.status, User.id.count())
        .group_by(User.status)
        .having(User.id.count().gt(5))
        .all(),
        SelectTupleQuery[User[Pending], User[Pending], str, int],
    )
    _ = assert_type(
        select(User.status, Order.id.sum())
        .join(Order, on=Order.user_id.references(User.id))
        .group_by(User.status)
        .having(Order.id.sum().gt(5))
        .all(),
        SelectTupleQuery[
            User[Pending] | Order[Pending],
            User[Pending] | Order[Pending],
            str,
            int | None,
        ],
    )
    _ = assert_type(User.email.eq("alice@example.com"), Predicate[User[Pending]])
    _ = assert_type(User.email.ne("alice@example.com"), Predicate[User[Pending]])
    _ = assert_type(User.email.is_null(), Predicate[User[Pending]])
    _ = assert_type(User.email.is_not_null(), Predicate[User[Pending]])
    _ = assert_type(User.email.in_("a@example.com"), Predicate[User[Pending]])
    _ = assert_type(
        User.email.not_in("a@example.com", "b@example.com"),
        Predicate[User[Pending]],
    )
    _ = assert_type(User.email.like("%@example.com"), Predicate[User[Pending]])
    _ = assert_type(User.email.not_like("%@example.com"), Predicate[User[Pending]])
    # Nullable column: comparing against None is invalid (the runtime rejects it);
    # the typed surface steers callers to is_null()/is_not_null() with a
    # deprecation diagnostic, while a real value still type-checks.
    _ = assert_type(User.nickname.eq("nick"), Predicate[User[Pending]])
    _ = assert_type(User.nickname.is_null(), Predicate[User[Pending]])
    _ = User.nickname.eq(None)  # pyright: ignore[reportDeprecated]
    _ = User.nickname.ne(None)  # pyright: ignore[reportDeprecated]
    _ = User.nickname.gt(None)  # pyright: ignore[reportDeprecated]
    _ = User.nickname.between(None, None)  # pyright: ignore[reportDeprecated]
    # Subqueries: a column-vs-column comparison keeps the left column's owner; a
    # single-column subquery types in_subquery; exists() carries no outer column;
    # scalar() carries the projected value type for projections and comparisons.
    _ = assert_type(Order.user_id.eq_col(User.id), Predicate[Order[Pending]])
    _ = assert_type(
        User.id.in_subquery(select(Order.user_id).where(Order.user_id.gt(0))),
        Predicate[User[Pending]],
    )
    _ = assert_type(exists(select(Order.id).all()), Predicate[Any])
    _ = assert_type(not_exists(select(Order.id).all()), Predicate[Any])
    _ = assert_type(
        scalar(select(Order.user_id).where(Order.user_id.eq_col(User.id))),
        Scalar[Any, int],
    )
    _ = assert_type(
        User.id.gt_col(scalar(select(Order.user_id).all())),
        Predicate[User[Pending]],
    )
    # A multi-column IN subquery is rejected: in_subquery wants a single column.
    _ = User.id.in_subquery(select(Order.id, Order.user_id))  # type: ignore[arg-type]
    _ = assert_type(
        User.email.eq("alice@example.com") & User.status.eq("active"),
        Predicate[User[Pending]],
    )
    # A single-table predicate flows into a wider union-owner slot: `Predicate`
    # is covariant in its owner type, which join queries rely on to accept a
    # predicate built from any one of the joined tables.
    _single_owner_predicate = User.email.eq("alice@example.com")
    _widened_owner_predicate: Predicate[User[Pending] | int] = _single_owner_predicate

    # Typed joins: the result tuple accumulates fetched models, the owner union
    # types where()/order_by(), and a left join makes the right model optional.
    _user_orders = select(User).join(Order, on=Order.user_id.references(User.id))
    _ = assert_type(
        _user_orders,
        JoinModelQuery[User[Pending] | Order[Pending], User[Fetched], Order[Fetched]],
    )
    _ = _user_orders.where(User.email.eq("a@b.c") & Order.note.eq("x"))
    _ = _user_orders.where(Order.note.eq("x"))
    _ = _user_orders.order_by(Order.note.asc(), User.id.asc())
    _ = assert_type(
        select(User).left_join(Order, on=Order.user_id.references(User.id)),
        JoinModelQuery[
            User[Pending] | Order[Pending],
            User[Fetched],
            Order[Fetched] | None,
        ],
    )
    # Rejection: right table, wrong-type key (int FK vs str column).
    _ = select(User).join(
        Order,
        on=Order.user_id.references(User.email),  # type: ignore[arg-type]
    )
    # Rejection: a plain (non-FK) column has no `references`.
    _ = select(User).join(
        Order,
        on=Order.note.references(User.id),  # type: ignore[attr-defined]
    )
    # Rejection: a predicate from a table not in the query is out of scope.
    _ = _user_orders.where(Region.code.eq("EU"))  # type: ignore[arg-type]

    # Projection joins: the result tuple is fixed by the selected columns, the
    # scope union grows with each join, and the referenced union grows with the
    # selected columns and where()/order_by(). A join only declares how tables
    # connect; it never changes the projected result shape.
    _email_notes = select(User.email, Order.note).join(
        Order,
        on=Order.user_id.references(User.id),
    )
    _ = assert_type(
        _email_notes,
        SelectTupleQuery[
            User[Pending] | Order[Pending],
            User[Pending] | Order[Pending],
            str,
            str,
        ],
    )
    _ = _email_notes.where(User.email.eq("a@b.c") & Order.note.eq("x"))
    _ = _email_notes.order_by(Order.note.asc())
    # A left join keeps the same projected result shape (its nullability is a
    # documented gap for projection selects).
    _ = assert_type(
        select(User.id, Order.note, Order.note).left_join(
            Order, on=Order.user_id.references(User.id)
        ),
        SelectTupleQuery[
            User[Pending] | Order[Pending],
            User[Pending] | Order[Pending],
            int,
            str,
            str,
        ],
    )
    # Single-column projection join: filter on a joined table you do not select.
    _ = assert_type(
        select(User.email)
        .join(Order, on=Order.user_id.references(User.id))
        .where(Order.note.eq("x")),
        SelectValueQuery[
            User[Pending] | Order[Pending],
            User[Pending] | Order[Pending],
            str,
        ],
    )
    # Rejection: a projection-join `on` with a wrong-type key.
    _ = select(User.email, Order.note).join(
        Order,
        on=Order.user_id.references(User.email),  # type: ignore[arg-type]
    )
    _ = assert_type(Index(User.email), Index[User[Pending]])
    _ = assert_type(Index(User.email, unique=True), Index[User[Pending]])
    _ = assert_type(
        insert(pending_user),
        InsertQuery[User[Pending], User[Fetched]],
    )
    _ = assert_type(
        insert([pending_user, pending_user]),
        InsertManyQuery[User[Pending], User[Fetched]],
    )
    _ = assert_type(
        insert(pending_user).returning(),
        InsertReturningQuery[User[Pending], User[Fetched]],
    )
    _ = assert_type(
        insert([pending_user]).returning(),
        InsertManyReturningQuery[User[Pending], User[Fetched]],
    )
    _ = assert_type(
        insert(pending_user).returning(User.id),
        InsertReturningValueQuery[User[Pending], int],
    )
    _ = assert_type(
        insert(pending_user).returning(User.id, User.email),
        InsertReturningTupleQuery[User[Pending], int, str],
    )
    _ = assert_type(
        insert([pending_user]).returning(User.id),
        InsertManyReturningValueQuery[User[Pending], int],
    )
    _ = assert_type(
        insert([pending_user]).returning(User.id, User.email),
        InsertManyReturningTupleQuery[User[Pending], int, str],
    )
    _ = assert_type(
        update(User).set(User.email.to("new@example.com")),
        UpdateQuery[User[Pending]],
    )
    # returning() is scoped to the written model: a column from another model is
    # rejected statically (the owner is pinned), matching the runtime guard.
    _ = insert(pending_user).returning(Order.note)  # pyright: ignore[reportArgumentType]
    _ = update(User).returning(Order.note)  # pyright: ignore[reportArgumentType]

    async def check_write_types(transaction: Transaction) -> None:
        """Runtime write overloads type returning inserts as Fetched models."""

        _ = assert_type(await transaction.execute(insert(pending_user)), None)
        _ = assert_type(
            await transaction.execute(insert([pending_user])),
            None,
        )
        _ = assert_type(
            await transaction.execute(insert(pending_user).returning()),
            User[Fetched],
        )
        _ = assert_type(
            await transaction.execute(insert([pending_user]).returning()),
            list[User[Fetched]],
        )
        _ = assert_type(
            await transaction.execute(insert(pending_user).returning(User.id)),
            int,
        )
        _ = assert_type(
            await transaction.execute(
                insert(pending_user).returning(User.id, User.email)
            ),
            tuple[int, str],
        )
        _ = assert_type(
            await transaction.execute(insert([pending_user]).returning(User.id)),
            list[int],
        )
        _ = assert_type(
            await transaction.execute(
                insert([pending_user]).returning(User.id, User.email)
            ),
            list[tuple[int, str]],
        )

    async def check_fetch_types(transaction: Transaction) -> None:
        """Runtime fetch overloads preserve selected result shapes."""

        _ = assert_type(
            await transaction.fetch_all(select(User).all()),
            list[User[Fetched]],
        )
        _ = assert_type(
            await transaction.fetch_all(select(User.email).all()),
            list[str],
        )
        _ = assert_type(
            await transaction.fetch_all(select(User.email, User.status).all()),
            list[tuple[str, str]],
        )
        # fetch_chunks preserves the same per-row shapes, wrapped in a
        # ChunkStream of row batches.
        _ = assert_type(
            transaction.fetch_chunks(select(User).all(), size=100),
            ChunkStream[User[Fetched]],
        )
        _ = assert_type(
            transaction.fetch_chunks(select(User.email).all(), size=100),
            ChunkStream[str],
        )
        _ = assert_type(
            transaction.fetch_chunks(select(User.email, User.status).all(), size=100),
            ChunkStream[tuple[str, str]],
        )
        # fetch_one is exactly-one: a returned value is never absent, so the
        # single-value result keeps the column read type without ``| None``.
        _ = assert_type(
            await transaction.fetch_one(select(User.email).all()),
            str,
        )
        _ = assert_type(
            await transaction.fetch_one(select(User).all()),
            User[Fetched],
        )
        # fetch_one_or_none is zero-or-one for model/tuple/join selects, where
        # ``None`` can only mean a missing row.
        _ = assert_type(
            await transaction.fetch_one_or_none(select(User).all()),
            User[Fetched] | None,
        )
        _ = assert_type(
            await transaction.fetch_one_or_none(select(User.email, User.status).all()),
            tuple[str, str] | None,
        )
        # Projection join: the result tuple comes from the projected columns.
        _ = assert_type(
            await transaction.fetch_all(
                select(User.email, Order.note).join(
                    Order,
                    on=Order.user_id.references(User.id),
                ),
            ),
            list[tuple[str, str]],
        )
        # Filtering a joined table you do not project is fine.
        _ = assert_type(
            await transaction.fetch_all(
                select(User.email)
                .join(Order, on=Order.user_id.references(User.id))
                .where(Order.note.eq("x")),
            ),
            list[str],
        )
        # Dual-union scope check: selecting a column whose table is never joined
        # is rejected at fetch because the referenced union escapes the scope.
        _unjoined_select = select(User.email, Region.code).join(
            Order,
            on=Order.user_id.references(User.id),
        )
        await transaction.fetch_all(_unjoined_select)  # type: ignore[type-var]
        # Same check for filtering an unjoined table.
        _unjoined_filter = (
            select(User.email)
            .join(Order, on=Order.user_id.references(User.id))
            .where(Region.code.eq("EU"))
        )
        await transaction.fetch_all(_unjoined_filter)  # type: ignore[type-var]
        # Projecting two tables but joining nothing is rejected too.
        _no_join = select(User.email, Order.note)
        await transaction.fetch_all(_no_join)  # type: ignore[type-var]
