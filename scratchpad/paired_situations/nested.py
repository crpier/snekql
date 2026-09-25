"""Fetched-first nested situations. Compare numbered sections with body.py.

Research imports are intentional. Independent complete and input constructors;
no production interface or general inheritance claim. See README.md for evidence.
"""

from dataclasses import dataclass
from decimal import Decimal
from typing import ClassVar, Literal, NewType, TypedDict
from uuid import UUID

from pydantic import Json
from snekql import mariadb as native_maria
from snekql import sqlite as native

from scratchpad.dual_backends.core import Returning
from scratchpad.dual_backends.sqlite import Select
from scratchpad.fetched_stress.contracts import Paired
from scratchpad.paired_situations import nested_mariadb as mariadb
from scratchpad.paired_situations import nested_sqlite as sqlite
from scratchpad.paired_situations.gaps import native_delete, native_update

# 01. The smallest useful model
UserId = NewType("UserId", int)


class User(sqlite.Row):
    table_name = "users"
    user_id: sqlite.Col[UserId] = sqlite.Integer(primary_key=True, auto_increment=True)
    email: sqlite.Col[str] = sqlite.Text(unique=True)
    display_name: sqlite.Col[str | None] = sqlite.Text()

    class Pending(sqlite.Pending):
        __row__: ClassVar[type[User]]
        user_id: sqlite.Col[UserId | sqlite.Omitted] = sqlite.omitted()
        email: sqlite.Col[str]
        display_name: sqlite.Col[str | None] = sqlite.default(None)


@dataclass(frozen=True)
class PublicUser:
    """Explicit response selection, not automatic storage-model serialization."""

    email: str
    user_id: int


def public_user(user: User) -> PublicUser:
    return PublicUser(email=user.email, user_id=user.user_id)


async def create_user(transaction: sqlite.Transaction, email: str) -> User:
    return await transaction.execute(
        sqlite.insert(User.Pending(email=email)).returning()
    )


async def fetch_user(transaction: sqlite.Transaction, user_id: UserId) -> User | None:
    # The adapter has fetch_all only; the primary-key predicate bounds cardinality.
    users = await transaction.fetch_all(
        sqlite.select(User).where(User.user_id.eq(user_id))
    )
    return users[0] if users else None


# 02. Constructing complete values directly

OMITTED = sqlite.OMIT


class Counter(sqlite.Row):
    table_name = "counters"
    counter_id: sqlite.Col[int] = sqlite.Integer(primary_key=True, auto_increment=True)
    count: sqlite.Col[int] = sqlite.Integer(server_default=native.LiteralDefault(0))

    class Pending(sqlite.Pending):
        __row__: ClassVar[type[Counter]]
        counter_id: sqlite.Col[int | sqlite.Omitted] = sqlite.omitted()
        count: sqlite.Col[int | sqlite.Omitted] = sqlite.omitted()


def complete_counter(counter_id: int, count: int) -> Counter:
    return Counter(counter_id=counter_id, count=count)


def pending_counter() -> Counter.Pending:
    return Counter.Pending()


# Counter(count=3): static rejection and runtime validation error.
# Counter(counter_id=42): SQL default does not relax complete construction.
# Counter(counter_id=OMITTED, count=3): static and runtime rejection.
# Fully populated Counter.Pending still is not a Counter.


# 03. Defaults, NULL, and omission
class Settings(sqlite.Row):
    table_name = "settings"
    user_id: sqlite.Col[int] = sqlite.Integer(primary_key=True)
    timezone: sqlite.Col[str] = sqlite.Text()
    nickname: sqlite.Col[str | None] = sqlite.Text()
    enabled: sqlite.Col[bool] = sqlite.Integer()
    note: sqlite.Col[str | None] = sqlite.Text()
    digest_hour: sqlite.Col[int] = sqlite.Integer(
        server_default=native.LiteralDefault(9)
    )
    locale: sqlite.Col[str | None] = sqlite.Text(
        server_default=native.LiteralDefault(None)
    )
    created_at: sqlite.Col[native.UtcDatetime] = sqlite.Text(
        server_default=native.CurrentTimestamp
    )

    class Pending(sqlite.Pending):
        __row__: ClassVar[type[Settings]]
        user_id: sqlite.Col[int]
        timezone: sqlite.Col[str]
        nickname: sqlite.Col[str | None]
        enabled: sqlite.Col[bool] = sqlite.default(True)
        note: sqlite.Col[str | None] = sqlite.default(None)
        digest_hour: sqlite.Col[int | sqlite.Omitted] = sqlite.omitted()
        locale: sqlite.Col[str | sqlite.Omitted | None] = sqlite.omitted()
        created_at: sqlite.Col[native.UtcDatetime | sqlite.Omitted] = sqlite.omitted()


async def create_settings(
    transaction: sqlite.Transaction, user_id: int, timezone: str, nickname: str | None
) -> Settings:
    return await transaction.execute(
        sqlite.insert(
            Settings.Pending(user_id=user_id, timezone=timezone, nickname=nickname)
        ).returning()
    )


# nickname is nullable AND required. note has a Python default of None.
# locale omitted means SQL supplies NULL; explicit None is also permitted.
# Settings itself requires every field, including enabled and created_at.


def nullable_datetime_default() -> str:
    """Declaration succeeds, but native SQL-default binding rejects this codec."""

    class LastSeen(sqlite.Row):
        table_name = "last_seen"
        last_seen: sqlite.Col[native.UtcDatetime | None] = sqlite.Text(
            server_default=native.LiteralDefault(None)
        )

        class Pending(sqlite.Pending):
            __row__: ClassVar[type[LastSeen]]
            last_seen: sqlite.Col[native.UtcDatetime | sqlite.Omitted | None] = (
                sqlite.omitted()
            )

    return sqlite.scaffold(LastSeen)


# 04. Ordinary foreign keys
PostId = NewType("PostId", int)


class Post(sqlite.Row):
    table_name = "posts"
    post_id: sqlite.Col[PostId] = sqlite.Integer(primary_key=True, auto_increment=True)
    author_id: sqlite.FKCol[User, UserId] = sqlite.ForeignKey(User.user_id)
    title: sqlite.Col[str] = sqlite.Text()

    class Pending(sqlite.Pending):
        __row__: ClassVar[type[Post]]
        post_id: sqlite.Col[PostId | sqlite.Omitted] = sqlite.omitted()
        author_id: sqlite.FKCol[User, UserId]
        title: sqlite.Col[str]


async def create_post(
    transaction: sqlite.Transaction, author_id: UserId, title: str
) -> Post:
    return await transaction.execute(
        sqlite.insert(Post.Pending(author_id=author_id, title=title)).returning()
    )


async def author_emails(transaction: sqlite.Transaction) -> list[str]:
    return await transaction.fetch_all(
        sqlite.select(User.email)
        .join(Post, on=Post.author_id.references(User.user_id))
        .all()
    )


# Post.Pending(author_id=PostId(1), title="Wrong ID"): static rejection.
# A wrong target in Pending's FKCol is checked at schema binding.


# 05. Self-referencing foreign keys


class Comment(sqlite.Row):
    table_name = "comments"
    comment_id: sqlite.Col[int] = sqlite.Integer(primary_key=True)
    parent_id: sqlite.FKCol[Comment, int | None] = sqlite.ForeignKey(
        lambda: Comment.comment_id, on_delete="SET NULL"
    )
    body: sqlite.Col[str] = sqlite.Text()

    class Pending(sqlite.Pending):
        __row__: ClassVar[type[Comment]]
        comment_id: sqlite.Col[int]
        parent_id: sqlite.FKCol[Comment, int | None] = sqlite.default(None)
        body: sqlite.Col[str]


async def create_comment(
    transaction: sqlite.Transaction, comment_id: int, parent_id: int | None, body: str
) -> Comment:
    return await transaction.execute(
        sqlite.insert(
            Comment.Pending(comment_id=comment_id, parent_id=parent_id, body=body)
        ).returning()
    )


async def delete_comment(transaction: sqlite.Transaction, comment_id: int) -> None:
    # Adapter gap: explicit native bridge, not a typed nested DELETE implementation.
    await native_delete(transaction, Comment, key=("comment_id", comment_id))


def local_comment_schema() -> str:
    """A self target also resolves when the model is local to a function."""

    class LocalComment(sqlite.Row):
        table_name = "local_comments"
        comment_id: sqlite.Col[int] = sqlite.Integer(primary_key=True)
        parent_id: sqlite.FKCol[LocalComment, int | None] = sqlite.ForeignKey(
            lambda: LocalComment.comment_id
        )

        class Pending(sqlite.Pending):
            __row__: ClassVar[type[LocalComment]]
            comment_id: sqlite.Col[int]
            parent_id: sqlite.FKCol[LocalComment, int | None] = sqlite.default(None)

    return sqlite.scaffold(LocalComment)


# 06. Mutually referencing models
async def mutual_foreign_keys() -> list[int | None]:
    """Local declarations allow construction before the other table is defined."""

    class Department(sqlite.Row):
        table_name = "departments"
        department_id: sqlite.Col[int] = sqlite.Integer(primary_key=True)
        manager_id: sqlite.FKCol[Employee, int | None] = sqlite.ForeignKey(
            lambda: Employee.employee_id, on_update="CASCADE"
        )

        class Pending(sqlite.Pending):
            __row__: ClassVar[type[Department]]
            department_id: sqlite.Col[int]
            manager_id: sqlite.FKCol[Employee, int | None] = sqlite.default(None)

    department = Department.Pending(department_id=1)
    # Calling scaffold here instead would memoize a missing-Employee binding failure.

    class Employee(sqlite.Row):
        table_name = "employees"
        employee_id: sqlite.Col[int] = sqlite.Integer(primary_key=True)
        department_id: sqlite.FKCol[Department, int] = sqlite.ForeignKey(
            Department.department_id
        )

        class Pending(sqlite.Pending):
            __row__: ClassVar[type[Employee]]
            employee_id: sqlite.Col[int]
            department_id: sqlite.FKCol[Department, int]

    async with await sqlite.Database.initialize(database=":memory:") as database:
        await database.migrate({"001": sqlite.scaffold(Department)})
        async with database.transaction() as transaction:
            await transaction.execute(sqlite.insert(department))
            await transaction.execute(
                sqlite.insert(Employee.Pending(employee_id=2, department_id=1))
            )
            await native_update(transaction, Department, values={"manager_id": 2})
            await native_update(transaction, Employee, values={"employee_id": 20})
        async with database.transaction() as transaction:
            return await transaction.fetch_all(
                sqlite.select(Department.manager_id).all()
            )


# 07. A large model undergoing a change

OrderId = NewType("OrderId", int)
TenantId = NewType("TenantId", int)
type Status = Literal["draft", "paid", "cancelled"]
type Currency = Literal["USD", "EUR"]


class Order(sqlite.Row):
    table_name = "orders"
    order_id: sqlite.Col[OrderId] = sqlite.Integer(
        primary_key=True, auto_increment=True
    )
    tenant_id: sqlite.Col[TenantId] = sqlite.Integer()
    customer_email: sqlite.Col[str] = sqlite.Text()
    status: sqlite.Col[Status] = sqlite.Text()
    currency: sqlite.Col[Currency] = sqlite.Text()
    subtotal: sqlite.Col[native.CanonicalDecimal] = sqlite.Text()
    tax: sqlite.Col[native.CanonicalDecimal] = sqlite.Text()
    discount: sqlite.Col[native.CanonicalDecimal] = sqlite.Text()
    external_id: sqlite.Col[UUID] = sqlite.Text(unique=True)
    receipt: sqlite.Col[bytes] = sqlite.Blob()
    metadata: sqlite.Col[Json[dict[str, str]]] = sqlite.Text()
    note: sqlite.Col[str | None] = sqlite.Text()
    region: sqlite.Col[str] = sqlite.Text()
    active: sqlite.Col[bool] = sqlite.Integer()
    retry_count: sqlite.Col[int] = sqlite.Integer()
    item_count: sqlite.Col[int] = sqlite.Integer()
    shipping_days: sqlite.Col[int | None] = sqlite.Integer()
    paid_at: sqlite.Col[native.UtcDatetime | None] = sqlite.Text()
    created_at: sqlite.Col[native.UtcDatetime] = sqlite.Text(
        server_default=native.CurrentTimestamp
    )
    revision: sqlite.Col[int] = sqlite.Integer(server_default=native.LiteralDefault(1))

    def total(self) -> Decimal:
        return invoice_total(self)

    def is_paid(self) -> bool:
        return self.status == "paid"

    def receipt_key(self) -> str:
        return f"{self.tenant_id}/{self.order_id}"

    class Pending(sqlite.Pending):
        __row__: ClassVar[type[Order]]
        order_id: sqlite.Col[OrderId | sqlite.Omitted] = sqlite.omitted()
        tenant_id: sqlite.Col[TenantId]
        customer_email: sqlite.Col[str]
        status: sqlite.Col[Status] = sqlite.default("draft")
        currency: sqlite.Col[Currency] = sqlite.default("USD")
        subtotal: sqlite.Col[native.CanonicalDecimal]
        tax: sqlite.Col[native.CanonicalDecimal] = sqlite.default(Decimal(0))
        discount: sqlite.Col[native.CanonicalDecimal] = sqlite.default(Decimal(0))
        external_id: sqlite.Col[UUID]
        receipt: sqlite.Col[bytes]
        metadata: sqlite.Col[Json[dict[str, str]]]
        note: sqlite.Col[str | None] = sqlite.default(None)
        region: sqlite.Col[str] = sqlite.default("US")
        active: sqlite.Col[bool] = sqlite.default(True)
        retry_count: sqlite.Col[int] = sqlite.default(0)
        item_count: sqlite.Col[int]
        shipping_days: sqlite.Col[int | None] = sqlite.default(None)
        paid_at: sqlite.Col[native.UtcDatetime | None] = sqlite.default(None)
        created_at: sqlite.Col[native.UtcDatetime | sqlite.Omitted] = sqlite.omitted()
        revision: sqlite.Col[int | sqlite.Omitted] = sqlite.omitted()

        def total(self) -> Decimal:
            return invoice_total(self)

        def is_paid(self) -> bool:
            return self.status == "paid"


def sample_order() -> Order.Pending:
    """Fixed caller data makes the runnable comparisons reproducible."""
    return Order.Pending(
        tenant_id=TenantId(7),
        customer_email="ada@example.com",
        subtotal=Decimal("12.50"),
        tax=Decimal("2.50"),
        external_id=UUID(int=7),
        receipt=b"invoice",
        metadata={"channel": "web"},
        item_count=2,
    )


async def create_order(transaction: sqlite.Transaction) -> Order:
    return await transaction.execute(sqlite.insert(sample_order()).returning())


# Evolution probes edit this actual declaration and its caller, independently:
# add cancellation_reason; str -> EmailAddress; draft -> queued default.
# See evolution.json for successful edits and deliberately stale contracts.


# 08. Models with behavior
def invoice_total(order: Order | Order.Pending) -> Decimal:
    """Shared implementation; the two concrete contracts both supply these values."""
    return order.subtotal + order.tax - order.discount


def order_summary(order: Order) -> tuple[str, str, bool]:
    return order.receipt_key(), str(order.total()), order.is_paid()


# Shared method definitions are beside their fields in section 07.
# Pending may call total/is_paid, but must not call receipt_key.


# 09. Backend-specific fields and operators


class Product(mariadb.Row):
    table_name = "products"
    product_id: mariadb.Col[int] = mariadb.Integer(
        primary_key=True, auto_increment=True
    )
    price: mariadb.Col[Decimal] = mariadb.Decimal(12, 2, unique=True)
    code: mariadb.Col[str] = mariadb.Text(
        length=32, unique=True, collation="utf8mb4_bin"
    )
    token: mariadb.Col[UUID] = mariadb.Uuid()
    created_at: mariadb.Col[native_maria.UtcDatetime] = mariadb.DateTime(
        server_default=native_maria.CurrentTimestamp
    )
    payload: mariadb.JsonCol[dict[str, int]] = mariadb.Json()
    active: mariadb.Col[bool] = mariadb.Boolean()
    description: mariadb.Col[str] = mariadb.LongText()
    image: mariadb.Col[bytes] = mariadb.Blob()
    __indexes__ = (
        mariadb.Index(description, prefix_lengths=(16,), name="description_prefix"),
    )

    class Pending(mariadb.Pending):
        __row__: ClassVar[type[Product]]
        product_id: mariadb.Col[int | mariadb.Omitted] = mariadb.omitted()
        price: mariadb.Col[Decimal]
        code: mariadb.Col[str]
        token: mariadb.Col[UUID]
        created_at: mariadb.Col[native_maria.UtcDatetime | mariadb.Omitted] = (
            mariadb.omitted()
        )
        payload: mariadb.JsonCol[dict[str, int]]
        active: mariadb.Col[bool] = mariadb.default(True)
        description: mariadb.Col[str]
        image: mariadb.Col[bytes]


async def create_product(transaction: mariadb.Transaction) -> Product:
    return await transaction.execute(
        mariadb.insert(
            Product.Pending(
                price=Decimal("12.50"),
                code="SKU-7",
                token=UUID(int=7),
                payload={"answer": 42},
                description="long description",
                image=b"image",
            )
        ).returning()
    )


async def product_answers(transaction: mariadb.Transaction) -> list[int | None]:
    return await transaction.fetch_all(
        mariadb.select(Product.payload.json_extract_int("$.answer")).all()
    )


def decimal_fk_schema() -> str:
    """Existing adapter preserves the referenced Decimal precision."""

    class PriceReference(mariadb.Row):
        table_name = "price_references"
        amount: mariadb.FKCol[Product, Decimal] = mariadb.ForeignKey(Product.price)

        class Pending(mariadb.Pending):
            __row__: ClassVar[type[PriceReference]]
            amount: mariadb.FKCol[Product, Decimal]

    return mariadb.scaffold(PriceReference)


# 10. Reusable application helpers

# This prototype's Write contract covers INSERT RETURNING, not every native verb.
type Write[Result] = Returning[Literal["sqlite"], Result]


def insert_generic[Read: sqlite.Row](pending: Paired[Read]) -> Write[Read]:
    return sqlite.insert(pending).returning()


async def execute_write[Result](
    transaction: sqlite.Transaction, command: Write[Result]
) -> Result:
    return await transaction.execute(command)


def users_query() -> Select[User]:
    return sqlite.select(User).all()


# insert_generic(Counter.Pending()) preserves Counter exactly.
# The old native Model[State, Result] helper cannot accept independent Pending.


# 11. Editing existing data


class ProfilePatch(TypedDict, total=False):
    """Omitted means preserve; None means SQL NULL. Not an insert contract."""

    display_name: str | None


async def patch_user(
    transaction: sqlite.Transaction, user_id: UserId, changes: ProfilePatch
) -> User | None:
    if "display_name" in changes:
        # Explicit adapter gap: field-name strings are not checked assignments.
        await native_update(
            transaction,
            User,
            values={"display_name": changes["display_name"]},
            key=("user_id", user_id),
        )
    return await fetch_user(transaction, user_id)


async def save_settings(
    transaction: sqlite.Transaction, user_id: int, timezone: str
) -> Settings:
    return await transaction.execute(
        sqlite.insert(
            Settings.Pending(user_id=user_id, timezone=timezone, nickname=None)
        )
        .on_conflict(
            Settings.user_id, action=sqlite.DoUpdate(Settings.timezone.to_inserted())
        )
        .returning()
    )


# Existing digest_hour 18 remains 18; a fresh insert gets SQL default 9.
# Updating digest_hour.to_inserted() too would reset 18 to the attempted default 9.


# 12. Reading and navigating unfamiliar code
def receipt_destination(order: Order) -> str:
    """Follow Order or customer_email to the authoritative storage declaration."""
    return order.customer_email


# Complete values use the short name. Input annotations use Order.Pending.
# Navigation requests and declaration-only lint run independently in navigation.py
# and evidence.py. No quoted result base, future import, or unused-import allowance.
