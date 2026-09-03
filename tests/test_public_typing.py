"""ty-oriented public API conformance probes."""

from __future__ import annotations

import uuid
from contextlib import AbstractAsyncContextManager
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, assert_type
from zoneinfo import ZoneInfo

from snekql import mariadb, sqlite
from snekql.query import (
    DeleteQuery,
    DeleteReturningQuery,
    DeleteReturningTupleQuery,
    InsertManyQuery,
    InsertManyReturningQuery,
    InsertManyReturningTupleQuery,
    InsertManyReturningValueQuery,
    InsertQuery,
    InsertReturningQuery,
    InsertReturningTupleQuery,
    InsertReturningValueQuery,
    JoinModelQuery,
    SelectModelQuery,
    SelectTupleQuery,
    SelectValueQuery,
    UpdateQuery,
    UpdateReturningQuery,
    UpdateReturningTupleQuery,
)
from snekql.sqlite import (
    PENDING_GENERATION,
    Aggregate,
    CanonicalDecimal,
    ChunkStream,
    Col,
    ColumnRef,
    CurrentTimestamp,
    DoNothing,
    DoUpdate,
    Duration,
    Fetched,
    FKCol,
    ForeignKey,
    GenCol,
    Index,
    Integer,
    JoinOn,
    Model,
    OrderBy,
    Pending,
    PendingGeneration,
    Predicate,
    Scalar,
    Select,
    Text,
    Transaction,
    UtcDatetime,
    Write,
    ZonedDatetime,
    delete,
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

    id: GenCol[int] = Integer(
        primary_key=True,
        auto_increment=True,
        default=PENDING_GENERATION,
    )
    email: Col[str] = Text(nullable=False)
    status: Col[str] = Text(nullable=False, default="active")
    nickname: Col[str | None] = Text(nullable=True, default=None)
    created_at: GenCol[UtcDatetime] = Text(default=CurrentTimestamp)
    balance: Col[CanonicalDecimal] = Text(nullable=False, default=Decimal(0))
    elapsed: Col[Duration] = Integer(nullable=False, default=timedelta(0))


class ZonedEvent[S = Pending](Model[S, "ZonedEvent[Fetched]"]):
    """Table carrying a timezone-preserving datetime."""

    happened_at: Col[ZonedDatetime] = Text(nullable=False)


class Order[S = Pending](Model[S, "Order[Fetched]"]):
    """Table with a foreign key to ``User`` for join typing examples."""

    id: GenCol[int] = Integer(
        primary_key=True,
        auto_increment=True,
        default=PENDING_GENERATION,
    )
    user_id: FKCol[User, int] = ForeignKey(User.id)
    # Nullable optional FK: ``default=None`` widens the value type and makes the
    # field omittable, parallel to the plain column constructors.
    reviewer_id: FKCol[User, int | None] = ForeignKey(
        User.id, nullable=True, default=None
    )
    note: Col[str] = Text(nullable=False)


class Region[S = Pending](Model[S, "Region[Fetched]"]):
    """Unjoined table used to probe out-of-scope rejections."""

    code: Col[str] = Text(nullable=False)


class SqliteUser[S = Pending](sqlite.Model[S, "SqliteUser[Fetched]"]):
    """SQLite namespace table model used by public API typing examples."""

    id: GenCol[int] = sqlite.Integer(
        primary_key=True,
        auto_increment=True,
        default=PENDING_GENERATION,
    )
    email: Col[str] = sqlite.Text(nullable=False)
    # UUID logical type stored as TEXT on SQLite (no native UUID storage class).
    account_id: Col[uuid.UUID] = sqlite.Text(nullable=False, default_factory=uuid.uuid4)


class MariadbUser[S = Pending](mariadb.Model[S, "MariadbUser[Fetched]"]):
    """MariaDB namespace table model used by public API typing examples."""

    id: mariadb.GenCol[int] = mariadb.Integer(
        primary_key=True,
        auto_increment=True,
        default=PENDING_GENERATION,
    )
    email: mariadb.Col[str] = mariadb.Text(nullable=False)
    balance: mariadb.Col[Decimal] = mariadb.Decimal(9, 2, nullable=False)
    # Native MariaDB UUID Column Type paired with the uuid.UUID logical type.
    account_id: mariadb.Col[uuid.UUID] = mariadb.Uuid(
        nullable=False, default_factory=uuid.uuid4
    )
    profile: mariadb.JsonCol[dict[str, object]] = mariadb.Json(nullable=False)
    # Nullable JSON: the ``default=None`` overload widens the value type to
    # optional and makes the field omittable, parallel to Integer/Real/Boolean.
    prefs: mariadb.JsonCol[dict[str, object] | None] = mariadb.Json(
        nullable=True, default=None
    )


if TYPE_CHECKING:

    def _sqlite_predicate_from_column[OwnerT: sqlite.Model[Any, Any], ValueT](
        column: sqlite.ColumnRef[OwnerT, ValueT],
        value: ValueT,
    ) -> sqlite.Predicate[OwnerT]:
        return column.eq(value)

    def _sqlite_projection_from_column[OwnerT: sqlite.Model[Any, Any], ValueT](
        column: sqlite.ColumnRef[OwnerT, ValueT],
    ) -> sqlite.Select[ValueT]:
        return sqlite.select(column).all()

    def _sqlite_pair_projection_from_columns[
        OwnerT: sqlite.Model[Any, Any],
        FirstT,
        SecondT,
    ](
        first: sqlite.ColumnRef[OwnerT, FirstT],
        second: sqlite.ColumnRef[OwnerT, SecondT],
    ) -> sqlite.Select[tuple[FirstT, SecondT]]:
        return sqlite.select(first, second).all()

    def _column_ref_cannot_build_assignments[OwnerT, ValueT](
        column: sqlite.ColumnRef[OwnerT, ValueT],
        value: ValueT,
    ) -> None:
        _ = column.to(value)  # ty: ignore[unresolved-attribute]

    def _mariadb_predicate_from_column[OwnerT: mariadb.Model[Any, Any], ValueT](
        column: mariadb.ColumnRef[OwnerT, ValueT],
        value: ValueT,
    ) -> mariadb.Predicate[OwnerT]:
        return column.eq(value)

    def _mariadb_projection_from_column[OwnerT: mariadb.Model[Any, Any], ValueT](
        column: mariadb.ColumnRef[OwnerT, ValueT],
    ) -> mariadb.Select[ValueT]:
        return mariadb.select(column).all()

    class ValidForeignKeyDeclarations[S = Pending](
        Model[S, "ValidForeignKeyDeclarations[Fetched]"]
    ):
        """Valid required-nullable and defaulted foreign-key declarations."""

        required_nullable_user_id: FKCol[User, int | None] = ForeignKey(
            User.id,
            nullable=True,
        )
        defaulted_user_id: FKCol[User, int] = ForeignKey(User.id, default=1)
        nullable_defaulted_user_id: FKCol[User, int | None] = ForeignKey(
            User.id,
            nullable=True,
            default=1,
        )

    class ValidMariadbForeignKeyDeclarations[S = Pending](
        mariadb.Model[S, "ValidMariadbForeignKeyDeclarations[Fetched]"]
    ):
        """The shared foreign-key field specifier works in MariaDB models."""

        required_nullable_user_id: mariadb.FKCol[MariadbUser, int | None] = (
            mariadb.ForeignKey(MariadbUser.id, nullable=True)
        )
        defaulted_user_id: mariadb.FKCol[MariadbUser, int] = mariadb.ForeignKey(
            MariadbUser.id,
            default=1,
        )

    required_nullable_foreign_key = ValidForeignKeyDeclarations(
        required_nullable_user_id=None,
    )
    _ = assert_type(
        required_nullable_foreign_key.required_nullable_user_id,
        int | None,
    )
    _ = ValidForeignKeyDeclarations(required_nullable_user_id=1)
    _ = ValidForeignKeyDeclarations()  # ty: ignore[missing-argument]

    omittable_nullable_foreign_key = Order(user_id=1, note="review pending")
    _ = assert_type(omittable_nullable_foreign_key.reviewer_id, int | None)
    _ = assert_type(omittable_nullable_foreign_key.user_id, int)
    _ = Order(note="missing user")  # ty: ignore[missing-argument]
    _ = Order(
        user_id=None,  # ty: ignore[invalid-argument-type]
        note="invalid user",
    )

    def check_required_nullable_fetched(
        row: ValidForeignKeyDeclarations[Fetched],
    ) -> None:
        """Fetched required-nullable foreign keys retain their optional value."""

        _ = assert_type(row.required_nullable_user_id, int | None)

    class InvalidSqliteDefaults[S = Pending](
        Model[S, "InvalidSqliteDefaults[Fetched]"]
    ):
        """Invalid default declarations rejected by static typing."""

        text_default: Col[int] = Text(default="nan")  # ty: ignore[invalid-assignment]
        factory_default: Col[int] = Integer(default_factory=lambda: "nan")  # ty: ignore[invalid-assignment]
        pending_generation_default: Col[int] = Integer(  # ty: ignore[invalid-assignment]
            default=PENDING_GENERATION
        )
        server_default: Col[datetime] = Text(  # ty: ignore[invalid-assignment]
            default=CurrentTimestamp
        )
        conflicting_default: Col[int] = Integer(  # ty: ignore[no-matching-overload]
            default=1,
            default_factory=lambda: 2,
        )

    class InvalidOrderDefaults[S = Pending](Model[S, "InvalidOrderDefaults[Fetched]"]):
        """Invalid foreign-key default declarations rejected by static typing."""

        user_id: FKCol[User, int] = ForeignKey(  # ty: ignore[no-matching-overload]
            User.id,
            default="nan",
        )

    class InvalidMariadbDefaults[S = Pending](
        mariadb.Model[S, "InvalidMariadbDefaults[Fetched]"]
    ):
        """Invalid MariaDB default declarations rejected by static typing."""

        text_default: mariadb.Col[int] = mariadb.Text(default="nan")  # ty: ignore[invalid-assignment]
        factory_default: mariadb.Col[int] = mariadb.Uuid(default_factory=lambda: "nan")  # ty: ignore[invalid-assignment]

    _ = User()  # ty: ignore[missing-argument]
    _ = MariadbUser(email="alice@example.com")  # ty: ignore[missing-argument]
    public_email: ColumnRef[User[Pending], str] = User.email
    public_select: Select[User[Fetched]] = select(User)
    public_insert: Write[None] = insert(User(email="alice@example.com"))
    public_update: Write[int] = update(User).all()
    _laundered_order_column: Col[str] = Order.note  # ty: ignore[invalid-assignment]
    _ = update(User).set(
        _laundered_order_column.to("wrong model")  # ty: ignore[invalid-argument-type]
    )
    _raw_column = Text(default="raw")
    _ = update(User).set(
        _raw_column.to("wrong model")  # ty: ignore[invalid-argument-type]
    )

    sqlite_config = sqlite.Config(database=Path("app.db"))
    _ = assert_type(sqlite_config, sqlite.Config)
    sqlite_index = sqlite.Index(SqliteUser.email)
    _ = assert_type(sqlite_index, Index[SqliteUser[Pending]])
    sqlite_user = SqliteUser(email="alice@example.com")
    _ = assert_type(sqlite_user, SqliteUser[Pending])
    _ = assert_type(sqlite_user.account_id, uuid.UUID)
    _ = assert_type(
        select(SqliteUser),
        SelectModelQuery[Literal["sqlite"], SqliteUser[Pending], SqliteUser[Fetched]],
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
    mariadb_user = MariadbUser(
        email="alice@example.com",
        balance=Decimal(0),
        profile={},
    )
    _ = assert_type(mariadb_user, MariadbUser[Pending])
    _ = assert_type(mariadb_user.account_id, uuid.UUID)
    # ``default=None`` makes the nullable JSON column omittable and optional.
    _ = assert_type(mariadb_user.prefs, dict[str, object] | None)
    _ = assert_type(
        mariadb.select(MariadbUser),
        SelectModelQuery[
            Literal["mariadb"], MariadbUser[Pending], MariadbUser[Fetched]
        ],
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
        mariadb.select(MariadbUser.profile.json_extract_int("$.age")),
        SelectValueQuery[
            Literal["mariadb"],
            MariadbUser[Pending],
            MariadbUser[Pending],
            int | None,
            int,
        ],
    )
    _ = assert_type(
        mariadb.select(
            MariadbUser.email, MariadbUser.profile.json_extract_int("$.age")
        ),
        SelectTupleQuery[
            Literal["mariadb"],
            MariadbUser[Pending],
            MariadbUser[Pending],
            str,
            int | None,
        ],
    )

    zoned_datetime = ZonedDatetime(
        datetime(2026, 7, 1, 8, tzinfo=ZoneInfo("America/New_York"))
    )
    pending_zoned_event = ZonedEvent(happened_at=zoned_datetime)
    _ = assert_type(pending_zoned_event.happened_at, ZonedDatetime)
    _ = assert_type(pending_zoned_event.happened_at.datetime, datetime)
    _ = assert_type(
        ZonedEvent.happened_at.eq(zoned_datetime),
        Predicate[ZonedEvent[Pending]],
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
        _ = insert(fetched_user)  # ty: ignore[no-matching-overload]

    _ = assert_type(
        select(User), SelectModelQuery[Literal["sqlite"], User[Pending], User[Fetched]]
    )
    _ = assert_type(
        select(User.email).where(User.email.eq("alice@example.com")).all(),
        SelectValueQuery[Literal["sqlite"], User[Pending], User[Pending], str],
    )
    _ = assert_type(
        select(User)
        .where(User.email.eq("alice@example.com"), User.status.eq("active"))
        .order_by(User.email.asc(), User.id.desc()),
        SelectModelQuery[Literal["sqlite"], User[Pending], User[Fetched]],
    )
    _ = assert_type(
        select(User.email, User.status),
        SelectTupleQuery[Literal["sqlite"], User[Pending], User[Pending], str, str],
    )
    _ = assert_type(
        select(
            User.id,
            User.email,
            User.status,
            User.nickname,
            User.created_at,
            User.balance,
            User.elapsed,
            User.id,
        ),
        SelectTupleQuery[
            Literal["sqlite"],
            User[Pending],
            User[Pending],
            int,
            str,
            str,
            str | None,
            UtcDatetime,
            CanonicalDecimal,
            Duration,
            int,
        ],
    )
    _ = select(  # ty: ignore[no-matching-overload]
        User.id,
        User.email,
        User.status,
        User.nickname,
        User.created_at,
        User.balance,
        User.elapsed,
        User.id,
        User.email,
    )
    # Expression names are annotation-only; supported factories produce their
    # values, while direct construction is rejected by the public interface.
    _ = Aggregate[User[Pending], int]()  # ty: ignore[missing-argument]
    _ = Scalar[User[Pending], int]()  # ty: ignore[missing-argument]
    _ = JoinOn[Order[Pending], User[Pending]]()  # ty: ignore[missing-argument]
    _ = OrderBy[User[Pending]]()  # ty: ignore[missing-argument]
    _ = Predicate[User[Pending]]()  # ty: ignore[missing-argument]
    _ = sqlite.Assignment[User[Pending]]()  # ty: ignore[missing-argument]

    # Aggregates: column methods carry owner + result type; the star form lives
    # on the model. count is int; sum/min/max are nullable; avg is float | None.
    _ = assert_type(User.id.count(), Aggregate[User[Pending], int])
    _ = Aggregate[User[Pending], int](  # ty: ignore[missing-argument]
        func="UNSAFE",  # ty: ignore[unknown-argument]
        owner=User,  # ty: ignore[unknown-argument]
    )
    _ = assert_type(User.count_all(), Aggregate[User[Pending], int])
    _ = assert_type(Order.id.sum(), Aggregate[Order[Pending], int | None, int])
    _ = assert_type(Order.id.min(), Aggregate[Order[Pending], int | None, int])
    _ = assert_type(Order.id.avg(), Aggregate[Order[Pending], float | None, float])
    _ = assert_type(
        select(User.id.count()).all(),
        SelectValueQuery[Literal["sqlite"], User[Pending], User[Pending], int],
    )
    _ = assert_type(
        select(Order.id.sum()).all(),
        SelectValueQuery[
            Literal["sqlite"], Order[Pending], Order[Pending], int | None, int
        ],
    )
    # Grouped projection: a column and an aggregate land in a tuple select; the
    # aggregate carries its result type and an aggregate can drive order_by.
    _ = assert_type(
        select(User.status, User.id.count()).group_by(User.status).all(),
        SelectTupleQuery[Literal["sqlite"], User[Pending], User[Pending], str, int],
    )
    _ = assert_type(
        select(User.id.count())
        .group_by(User.status)
        .having(User.id.count().gt(0))
        .all(),
        SelectValueQuery[Literal["sqlite"], User[Pending], User[Pending], int],
    )
    _ = assert_type(User.id.count().desc(), OrderBy[User[Pending]])
    _ = assert_type(
        select(User.status, Order.id.sum())
        .join(Order, on=Order.user_id.references(User.id))
        .group_by(User.status)
        .all(),
        SelectTupleQuery[
            Literal["sqlite"],
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
        SelectTupleQuery[Literal["sqlite"], User[Pending], User[Pending], str, int],
    )
    _ = assert_type(
        select(User.status, Order.id.sum())
        .join(Order, on=Order.user_id.references(User.id))
        .group_by(User.status)
        .having(Order.id.sum().gt(5))
        .all(),
        SelectTupleQuery[
            Literal["sqlite"],
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
    _ = User.id.like("1")  # ty: ignore[no-matching-overload]
    # Nullable columns retain nullable projection types while their literal
    # comparison domain excludes None. SQL NULL checks stay explicit.
    _ = assert_type(User.nickname.eq("nick"), Predicate[User[Pending]])
    _ = assert_type(User.nickname.is_null(), Predicate[User[Pending]])
    _ = assert_type(
        select(User.nickname),
        SelectValueQuery[
            Literal["sqlite"], User[Pending], User[Pending], str | None, str
        ],
    )
    _ = assert_type(
        User.nickname.between("a", "z"),
        Predicate[User[Pending]],
    )
    _ = assert_type(
        Order.reviewer_id.eq_col(Order.reviewer_id),
        Predicate[Order[Pending]],
    )
    _ = assert_type(
        Order.reviewer_id.in_subquery(select(Order.reviewer_id)),
        Predicate[Order[Pending]],
    )
    _ = assert_type(
        User.nickname.eq_col(scalar(select(User.nickname))),
        Predicate[User[Pending]],
    )
    _ = User.nickname.eq(None)  # ty: ignore[invalid-argument-type]
    _ = User.nickname.ne(None)  # ty: ignore[invalid-argument-type]
    _ = User.nickname.gt(None)  # ty: ignore[invalid-argument-type]
    _ = User.nickname.gte(None)  # ty: ignore[invalid-argument-type]
    _ = User.nickname.lt(None)  # ty: ignore[invalid-argument-type]
    _ = User.nickname.lte(None)  # ty: ignore[invalid-argument-type]
    _ = User.nickname.between(None, "z")  # ty: ignore[invalid-argument-type]
    _ = User.nickname.between("a", None)  # ty: ignore[invalid-argument-type]
    _ = assert_type(User.nickname.in_("nick"), Predicate[User[Pending]])
    _ = User.nickname.in_(None)  # ty: ignore[invalid-argument-type]
    _ = User.nickname.in_("nick", None)  # ty: ignore[invalid-argument-type]
    _ = User.nickname.not_in(None)  # ty: ignore[invalid-argument-type]
    _ = User.nickname.not_in("nick", None)  # ty: ignore[invalid-argument-type]
    _ = Order.id.sum().eq(None)  # ty: ignore[invalid-argument-type]
    _ = MariadbUser.profile.json_extract_int("$.age").eq(
        None  # ty: ignore[invalid-argument-type]
    )

    # Non-empty fluent APIs reject calls that Query Construction always rejects.
    _ = select(User).where()  # ty: ignore[no-matching-overload]
    _ = select(User).order_by()  # ty: ignore[no-matching-overload]
    _ = select(User.email).where()  # ty: ignore[no-matching-overload]
    _ = select(User.email).order_by()  # ty: ignore[no-matching-overload]
    _ = select(User.email).group_by()  # ty: ignore[no-matching-overload]
    _ = select(User.email).having()  # ty: ignore[no-matching-overload]
    _ = select(User.email, User.status).where()  # ty: ignore[no-matching-overload]
    _ = select(User.email, User.status).order_by()  # ty: ignore[no-matching-overload]
    _ = select(User.email, User.status).group_by()  # ty: ignore[no-matching-overload]
    _ = select(User.email, User.status).having()  # ty: ignore[no-matching-overload]
    _ = User.email.in_()  # ty: ignore[no-matching-overload]
    _ = User.email.not_in()  # ty: ignore[no-matching-overload]
    _ = DoUpdate[User[Pending]]()  # ty: ignore[no-matching-overload]
    _ = insert(pending_user).on_conflict(  # ty: ignore[no-matching-overload]
        action=DoNothing
    )
    _ = update(User).set()  # ty: ignore[no-matching-overload]
    _ = update(User).where()  # ty: ignore[no-matching-overload]
    _ = delete(User).where()  # ty: ignore[no-matching-overload]
    # Subqueries: a column-vs-column comparison keeps the left column's owner; a
    # single-column subquery types in_subquery; exists() carries no outer column;
    # scalar() carries the projected value type for projections and comparisons.
    _ = assert_type(Order.user_id.eq_col(User.id), Predicate[Order[Pending]])
    _ = assert_type(
        Order.reviewer_id.references(User.id),
        JoinOn[Order[Pending], User[Pending]],
    )
    _ = assert_type(
        User.id.in_subquery(select(Order.user_id).where(Order.user_id.gt(0))),
        Predicate[User[Pending]],
    )
    _ = assert_type(exists(select(Order.id).all()), Predicate[Any])
    _ = assert_type(not_exists(select(Order.id).all()), Predicate[Any])
    # A scalar subquery evaluates to NULL on an empty match, so its projected
    # value type is always optional even over a NOT NULL inner column (#203 F10).
    _ = assert_type(
        scalar(select(Order.user_id).where(Order.user_id.eq_col(User.id))),
        Scalar[Any, int | None, int],
    )
    _ = select(
        scalar(select(Order.id).all()),  # ty: ignore[invalid-argument-type]
        User.id,
        Region.code,
    )
    _ = select(  # ty: ignore[no-matching-overload]
        scalar(select(Order.id).all())
    )
    _ = assert_type(
        User.id.gt_col(scalar(select(Order.user_id).all())),
        Predicate[User[Pending]],
    )
    _ = assert_type(
        User.id.gt_col(scalar(select(Order.id.avg()).all())),
        Predicate[User[Pending]],
    )
    _ = User.id.gt_col(
        scalar(select(Order.note).all())  # ty: ignore[invalid-argument-type]
    )
    # A multi-column IN subquery is rejected: in_subquery wants a single column.
    _ = User.id.in_subquery(
        select(Order.id, Order.user_id)  # ty: ignore[invalid-argument-type]
    )
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
        JoinModelQuery[
            Literal["sqlite"],
            User[Pending] | Order[Pending],
            User[Fetched],
            Order[Fetched],
        ],
    )
    _ = _user_orders.where(User.email.eq("a@b.c") & Order.note.eq("x"))
    _ = _user_orders.where(Order.note.eq("x"))
    _ = _user_orders.order_by(Order.note.asc(), User.id.asc())
    _ = assert_type(
        select(User).left_join(Order, on=Order.user_id.references(User.id)),
        JoinModelQuery[
            Literal["sqlite"],
            User[Pending] | Order[Pending],
            User[Fetched],
            Order[Fetched] | None,
        ],
    )
    _ = select(User).join(  # ty: ignore[no-matching-overload]
        Order,
        on=JoinOn[Region[Pending], User[Pending]](),  # ty: ignore[missing-argument]
    )
    _ = select(User.email).join(  # ty: ignore[no-matching-overload]
        Order,
        on=JoinOn[Region[Pending], User[Pending]](),  # ty: ignore[missing-argument]
    )
    # Rejection: right table, wrong-type key (int FK vs str column).
    _ = select(User).join(
        Order,
        on=Order.user_id.references(User.email),  # ty: ignore[no-matching-overload]
    )
    # Rejection: a plain (non-FK) column has no `references`.
    _ = select(User).join(
        Order,
        on=Order.note.references(User.id),  # ty: ignore[unresolved-attribute]
    )
    # Rejection: a predicate from a table not in the query is out of scope.
    _ = _user_orders.where(
        Region.code.eq("EU")  # ty: ignore[invalid-argument-type]
    )

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
            Literal["sqlite"],
            User[Pending] | Order[Pending],
            User[Pending] | Order[Pending],
            str,
            str,
        ],
    )
    _ = _email_notes.where(User.email.eq("a@b.c") & Order.note.eq("x"))
    _ = _email_notes.order_by(Order.note.asc())
    # Projection left joins are rejected because the current query shape cannot
    # make only the nullable-side result slots optional.
    _ = select(User.id, Order.note, Order.note).left_join(
        Order,  # ty: ignore[invalid-argument-type]
        on=Order.user_id.references(User.id),  # ty: ignore[invalid-argument-type]
    )
    # Single-column projection join: filter on a joined table you do not select.
    _ = assert_type(
        select(User.email)
        .join(Order, on=Order.user_id.references(User.id))
        .where(Order.note.eq("x")),
        SelectValueQuery[
            Literal["sqlite"],
            User[Pending] | Order[Pending],
            User[Pending] | Order[Pending],
            str,
        ],
    )
    # Rejection: a projection-join `on` with a wrong-type key.
    _ = select(User.email, Order.note).join(
        Order,
        on=Order.user_id.references(User.email),  # ty: ignore[no-matching-overload]
    )
    _ = assert_type(Index(User.email), Index[User[Pending]])
    _ = assert_type(Index(User.email, unique=True), Index[User[Pending]])
    _ = Index("email")  # ty: ignore[invalid-argument-type]
    _ = assert_type(
        insert(pending_user),
        InsertQuery[Literal["sqlite"], User[Pending], User[Fetched]],
    )
    _ = assert_type(
        insert([pending_user, pending_user]),
        InsertManyQuery[Literal["sqlite"], User[Pending], User[Fetched]],
    )
    _ = assert_type(
        DoUpdate(User.email.to_inserted(), User.status.to("active")),
        DoUpdate[User[Pending]],
    )
    _ = assert_type(
        insert(pending_user).on_conflict(
            User.email,
            action=DoUpdate(User.status.to_inserted()),
        ),
        InsertQuery[Literal["sqlite"], User[Pending], User[Fetched]],
    )
    _ = assert_type(
        insert([pending_user]).on_conflict(User.email, action=DoNothing),
        InsertManyQuery[Literal["sqlite"], User[Pending], User[Fetched]],
    )
    _ = assert_type(
        insert(pending_user).returning(),
        InsertReturningQuery[Literal["sqlite"], User[Pending], User[Fetched]],
    )
    _ = assert_type(
        insert([pending_user]).returning(),
        InsertManyReturningQuery[Literal["sqlite"], User[Pending], User[Fetched]],
    )
    _ = assert_type(
        insert(pending_user).returning(User.id),
        InsertReturningValueQuery[Literal["sqlite"], User[Pending], int],
    )
    _ = assert_type(
        insert(pending_user).returning(User.id, User.email),
        InsertReturningTupleQuery[Literal["sqlite"], User[Pending], int, str],
    )
    _ = assert_type(
        insert([pending_user]).returning(User.id),
        InsertManyReturningValueQuery[Literal["sqlite"], User[Pending], int],
    )
    _ = assert_type(
        insert([pending_user]).returning(User.id, User.email),
        InsertManyReturningTupleQuery[Literal["sqlite"], User[Pending], int, str],
    )
    _ = assert_type(
        insert(pending_user).returning(
            User.id,
            User.email,
            User.status,
            User.nickname,
            User.created_at,
            User.balance,
            User.elapsed,
            User.id,
        ),
        InsertReturningTupleQuery[
            Literal["sqlite"],
            User[Pending],
            int,
            str,
            str,
            str | None,
            UtcDatetime,
            CanonicalDecimal,
            Duration,
            int,
        ],
    )
    _ = assert_type(
        insert([pending_user]).returning(
            User.id,
            User.email,
            User.status,
            User.nickname,
            User.created_at,
            User.balance,
            User.elapsed,
            User.id,
        ),
        InsertManyReturningTupleQuery[
            Literal["sqlite"],
            User[Pending],
            int,
            str,
            str,
            str | None,
            UtcDatetime,
            CanonicalDecimal,
            Duration,
            int,
        ],
    )
    _ = assert_type(
        update(User).set(User.email.to("new@example.com")),
        UpdateQuery[Literal["sqlite"], User[Pending], User[Fetched]],
    )
    _ = assert_type(
        update(User)
        .set(User.email.to("new@example.com"), User.status.to("active"))
        .where(User.id.gt(0), User.nickname.is_not_null()),
        UpdateQuery[Literal["sqlite"], User[Pending], User[Fetched]],
    )
    _ = assert_type(
        delete(User).where(User.id.eq(1)),
        DeleteQuery[Literal["sqlite"], User[Pending], User[Fetched]],
    )
    _ = assert_type(
        update(User).returning(),
        UpdateReturningQuery[Literal["sqlite"], User[Pending], User[Fetched]],
    )
    _ = assert_type(
        delete(User).returning(),
        DeleteReturningQuery[Literal["sqlite"], User[Pending], User[Fetched]],
    )
    _ = assert_type(
        update(User).returning(
            User.id,
            User.email,
            User.status,
            User.nickname,
        ),
        UpdateReturningTupleQuery[
            Literal["sqlite"], User[Pending], User[Fetched], int, str, str, str | None
        ],
    )
    _ = assert_type(
        delete(User).returning(
            User.id,
            User.email,
            User.status,
            User.nickname,
        ),
        DeleteReturningTupleQuery[
            Literal["sqlite"], User[Pending], User[Fetched], int, str, str, str | None
        ],
    )
    _ = insert(pending_user).returning(  # ty: ignore[no-matching-overload]
        User.id,
        User.email,
        User.status,
        User.nickname,
        User.created_at,
        User.balance,
        User.elapsed,
        User.id,
        User.email,
    )
    # returning() is scoped to the written model: a column from another model is
    # rejected statically (the owner is pinned), matching the runtime guard.
    _ = insert(pending_user).returning(
        Order.note  # ty: ignore[invalid-argument-type]
    )
    _ = insert(pending_user).on_conflict(
        Order.note,  # ty: ignore[invalid-argument-type]
        action=DoNothing,
    )
    _ = insert(pending_user).on_conflict(
        User.email,
        action=DoUpdate(Order.note.to_inserted()),  # ty: ignore[invalid-argument-type]
    )
    _ = update(User).returning(
        Order.note  # ty: ignore[invalid-argument-type]
    )

    async def check_write_types(transaction: Transaction) -> None:
        """Runtime write overloads type returning inserts as Fetched models."""

        _ = assert_type(await transaction.execute(insert(pending_user)), None)
        _ = assert_type(
            await transaction.execute(insert(pending_user), validate=False),
            None,
        )
        _ = assert_type(
            await transaction.execute(insert([pending_user])),
            None,
        )
        _ = assert_type(
            await transaction.execute(update(User).all(), validate=False),
            int,
        )
        _ = assert_type(
            await transaction.execute(delete(User).all(), validate=False),
            int,
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
            await transaction.execute(update(User).all().returning()),
            list[User[Fetched]],
        )
        _ = assert_type(
            await transaction.execute(delete(User).all().returning()),
            list[User[Fetched]],
        )
        _ = assert_type(
            await transaction.execute(insert(pending_user).returning(User.id)),
            int,
        )
        _ = assert_type(
            await transaction.execute(
                insert(pending_user).returning(User.balance),
                validate=False,
            ),
            object,
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

    async def check_migration_types(database: sqlite.Database) -> None:
        """Migration verbs expose one immutable result and a read-only check."""

        migrations = {"001_users": 'CREATE TABLE "user" ("id" INTEGER) STRICT'}
        migration_result = assert_type(
            await database.migrate(migrations),
            sqlite.MigrationResult,
        )
        _ = assert_type(migration_result.applied, tuple[str, ...])
        _ = assert_type(migration_result.already_applied, tuple[str, ...])
        _ = assert_type(migration_result.legacy_adopted, bool)
        _ = assert_type(await database.verify_migrations(migrations), None)
        _ = await database.migrate(
            [("001_users", "SELECT 1")]  # ty: ignore[invalid-argument-type]
        )
        _ = await database.migrate(
            migrations,
            True,  # ty: ignore[too-many-positional-arguments]
        )

    async def execute_public_query_annotations(
        transaction: Transaction,
        read_query: Select[User[Fetched]],
        write_query: Write[int],
    ) -> None:
        """Result-oriented annotations remain executable after type erasure."""

        _ = assert_type(
            await transaction.fetch_all(read_query),
            list[User[Fetched]],
        )
        _ = assert_type(await transaction.execute(write_query), int)

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
        _ = assert_type(
            await transaction.fetch_all(
                select(User.balance).all(),
                validate=False,
            ),
            list[object],
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
        _ = assert_type(
            transaction.fetch_chunks(
                select(User.balance).all(),
                size=100,
                validate=False,
            ),
            ChunkStream[object],
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
        _ = assert_type(
            await transaction.fetch_one(
                select(User.balance).all(),
                validate=False,
            ),
            object,
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
        _ = assert_type(
            await transaction.fetch_one_or_none(
                select(User.email, User.status).all(),
                validate=False,
            ),
            object,
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
        await transaction.fetch_all(
            _unjoined_select  # ty: ignore[invalid-argument-type]
        )
        # Same check for filtering an unjoined table.
        _unjoined_filter = (
            select(User.email)
            .join(Order, on=Order.user_id.references(User.id))
            .where(Region.code.eq("EU"))
        )
        await transaction.fetch_all(
            _unjoined_filter  # ty: ignore[invalid-argument-type]
        )
        # Projecting two tables but joining nothing is rejected too.
        _no_join = select(User.email, Order.note)
        await transaction.fetch_all(
            _no_join  # ty: ignore[invalid-argument-type]
        )
