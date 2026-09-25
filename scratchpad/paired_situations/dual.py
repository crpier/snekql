"""Input-first dual classes. Compare numbered sections with body.py and nested.py.

Research imports are intentional. Complete rows inherit input fields and methods;
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
from scratchpad.dual_pairing.sqlite import Paired
from scratchpad.paired_situations import dual_mariadb as mariadb
from scratchpad.paired_situations import dual_sqlite as sqlite
from scratchpad.paired_situations.dual_gaps import native_delete, native_update

# 01. The smallest useful model
UserId = NewType("UserId", int)


class User(sqlite.Model):
    __row__: ClassVar[type[UserRow]]
    user_id: sqlite.Col[UserId | sqlite.Omitted] = sqlite.Integer(
        primary_key=True, auto_increment=True, default=sqlite.OMIT
    )
    email: sqlite.Col[str] = sqlite.Text(unique=True)
    display_name: sqlite.Col[str | None] = sqlite.Text(default=None)


class UserRow(User, sqlite.Row):
    table_name = "users"
    user_id: sqlite.Col[UserId]


@dataclass(frozen=True)
class PublicUser:
    """Explicit response selection, not automatic storage-model serialization."""

    email: str
    user_id: int


def public_user(user: UserRow) -> PublicUser:
    return PublicUser(email=user.email, user_id=user.user_id)


async def create_user(transaction: sqlite.Transaction, email: str) -> UserRow:
    return await transaction.execute(sqlite.insert(User(email=email)).returning())


async def fetch_user(
    transaction: sqlite.Transaction, user_id: UserId
) -> UserRow | None:
    # The adapter has fetch_all only; the primary-key predicate bounds cardinality.
    users = await transaction.fetch_all(
        sqlite.select(UserRow).where(UserRow.user_id.eq(user_id))
    )
    return users[0] if users else None


# 02. Constructing complete values directly

OMITTED = sqlite.OMIT


class Counter(sqlite.Model):
    __row__: ClassVar[type[CounterRow]]
    counter_id: sqlite.Col[int | sqlite.Omitted] = sqlite.Integer(
        primary_key=True, auto_increment=True, default=sqlite.OMIT
    )
    count: sqlite.Col[int | sqlite.Omitted] = sqlite.Integer(
        default=native.LiteralDefault(0)
    )


class CounterRow(Counter, sqlite.Row):
    table_name = "counters"
    counter_id: sqlite.Col[int]
    count: sqlite.Col[int]


def complete_counter(counter_id: int, count: int) -> CounterRow:
    return CounterRow(counter_id=counter_id, count=count)


def pending_counter() -> Counter:
    return Counter()


# CounterRow(count=3): static rejection and runtime validation error.
# CounterRow(counter_id=42): SQL default does not relax complete construction.
# CounterRow(counter_id=OMITTED, count=3): static and runtime rejection.
# A Counter input is not a CounterRow; CounterRow is a subtype of Counter.


# 03. Defaults, NULL, and omission
class Settings(sqlite.Model):
    __row__: ClassVar[type[SettingsRow]]
    user_id: sqlite.Col[int] = sqlite.Integer(primary_key=True)
    timezone: sqlite.Col[str] = sqlite.Text()
    nickname: sqlite.Col[str | None] = sqlite.Text()
    enabled: sqlite.Col[bool] = sqlite.Integer(default=True)
    note: sqlite.Col[str | None] = sqlite.Text(default=None)
    digest_hour: sqlite.Col[int | sqlite.Omitted] = sqlite.Integer(
        default=native.LiteralDefault(9)
    )
    locale: sqlite.Col[str | sqlite.Omitted | None] = sqlite.Text(
        default=native.LiteralDefault(None)
    )
    created_at: sqlite.Col[native.UtcDatetime | sqlite.Omitted] = sqlite.Text(
        default=native.CurrentTimestamp
    )


class SettingsRow(Settings, sqlite.Row):
    table_name = "settings"
    digest_hour: sqlite.Col[int]
    locale: sqlite.Col[str | None]
    created_at: sqlite.Col[native.UtcDatetime]


async def create_settings(
    transaction: sqlite.Transaction, user_id: int, timezone: str, nickname: str | None
) -> SettingsRow:
    return await transaction.execute(
        sqlite.insert(
            Settings(user_id=user_id, timezone=timezone, nickname=nickname)
        ).returning()
    )


# nickname is nullable AND required. note has a Python default of None.
# locale omitted means SQL supplies NULL; explicit None is also permitted.
# SettingsRow requires generated values; inherited Python defaults still apply.


def nullable_datetime_default() -> str:
    """Declaration succeeds, but native SQL-default binding rejects this codec."""

    class LastSeen(sqlite.Model):
        __row__ = sqlite.paired(lambda: LastSeenRow)
        last_seen: sqlite.Col[native.UtcDatetime | sqlite.Omitted | None] = sqlite.Text(
            default=native.LiteralDefault(None)
        )

    class LastSeenRow(LastSeen, sqlite.Row):
        table_name = "last_seen"
        last_seen: sqlite.Col[native.UtcDatetime | None]

    return sqlite.scaffold(LastSeenRow)


# 04. Ordinary foreign keys
PostId = NewType("PostId", int)


class Post(sqlite.Model):
    __row__: ClassVar[type[PostRow]]
    post_id: sqlite.Col[PostId | sqlite.Omitted] = sqlite.Integer(
        primary_key=True, auto_increment=True, default=sqlite.OMIT
    )
    author_id: sqlite.FKCol[UserRow, UserId] = sqlite.ForeignKey(UserRow.user_id)
    title: sqlite.Col[str] = sqlite.Text()


class PostRow(Post, sqlite.Row):
    table_name = "posts"
    post_id: sqlite.Col[PostId]


async def create_post(
    transaction: sqlite.Transaction, author_id: UserId, title: str
) -> PostRow:
    return await transaction.execute(
        sqlite.insert(Post(author_id=author_id, title=title)).returning()
    )


async def author_emails(transaction: sqlite.Transaction) -> list[str]:
    return await transaction.fetch_all(
        sqlite.select(UserRow.email)
        .join(PostRow, on=PostRow.author_id.references(UserRow.user_id))
        .all()
    )


# Post(author_id=PostId(1), title="Wrong ID"): static rejection.
# The FK is declared once on Post and inherited by PostRow.


# 05. Self-referencing foreign keys


class Comment(sqlite.Model):
    __row__: ClassVar[type[CommentRow]]
    comment_id: sqlite.Col[int] = sqlite.Integer(primary_key=True)
    parent_id: sqlite.FKCol[CommentRow, int | None] = sqlite.ForeignKey(
        lambda: CommentRow.comment_id, on_delete="SET NULL", default=None
    )
    body: sqlite.Col[str] = sqlite.Text()


class CommentRow(Comment, sqlite.Row):
    table_name = "comments"


async def create_comment(
    transaction: sqlite.Transaction, comment_id: int, parent_id: int | None, body: str
) -> CommentRow:
    return await transaction.execute(
        sqlite.insert(
            Comment(comment_id=comment_id, parent_id=parent_id, body=body)
        ).returning()
    )


async def delete_comment(transaction: sqlite.Transaction, comment_id: int) -> None:
    # Adapter gap: explicit native bridge, not a typed dual DELETE implementation.
    await native_delete(transaction, CommentRow, key=("comment_id", comment_id))


def local_comment_schema() -> str:
    """A self target also resolves when the model is local to a function."""

    class LocalComment(sqlite.Model):
        __row__ = sqlite.paired(lambda: LocalCommentRow)
        comment_id: sqlite.Col[int] = sqlite.Integer(primary_key=True)
        parent_id: sqlite.FKCol[LocalCommentRow, int | None] = sqlite.ForeignKey(
            lambda: LocalCommentRow.comment_id, default=None
        )

    class LocalCommentRow(LocalComment, sqlite.Row):
        table_name = "local_comments"

    return sqlite.scaffold(LocalCommentRow)


# 06. Mutually referencing models
async def mutual_foreign_keys() -> list[int | None]:
    """Local declarations allow construction before the other table is defined."""

    class Department(sqlite.Model):
        __row__ = sqlite.paired(lambda: DepartmentRow)
        department_id: sqlite.Col[int] = sqlite.Integer(primary_key=True)
        manager_id: sqlite.FKCol[EmployeeRow, int | None] = sqlite.ForeignKey(
            lambda: EmployeeRow.employee_id, on_update="CASCADE", default=None
        )

    class DepartmentRow(Department, sqlite.Row):
        table_name = "departments"

    department = Department(department_id=1)
    # Calling scaffold here instead would memoize a missing-EmployeeRow binding failure.

    class Employee(sqlite.Model):
        __row__ = sqlite.paired(lambda: EmployeeRow)
        employee_id: sqlite.Col[int] = sqlite.Integer(primary_key=True)
        department_id: sqlite.FKCol[DepartmentRow, int] = sqlite.ForeignKey(
            DepartmentRow.department_id
        )

    class EmployeeRow(Employee, sqlite.Row):
        table_name = "employees"

    async with await sqlite.Database.initialize(database=":memory:") as database:
        await database.migrate({"001": sqlite.scaffold(DepartmentRow)})
        async with database.transaction() as transaction:
            await transaction.execute(sqlite.insert(department))
            await transaction.execute(
                sqlite.insert(Employee(employee_id=2, department_id=1))
            )
            await native_update(transaction, DepartmentRow, values={"manager_id": 2})
            await native_update(transaction, EmployeeRow, values={"employee_id": 20})
        async with database.transaction() as transaction:
            return await transaction.fetch_all(
                sqlite.select(DepartmentRow.manager_id).all()
            )


# 07. A large model undergoing a change

OrderId = NewType("OrderId", int)
TenantId = NewType("TenantId", int)
type Status = Literal["draft", "paid", "cancelled"]
type Currency = Literal["USD", "EUR"]


class Order(sqlite.Model):
    __row__: ClassVar[type[OrderRow]]
    order_id: sqlite.Col[OrderId | sqlite.Omitted] = sqlite.Integer(
        primary_key=True, auto_increment=True, default=sqlite.OMIT
    )
    tenant_id: sqlite.Col[TenantId] = sqlite.Integer()
    customer_email: sqlite.Col[str] = sqlite.Text()
    status: sqlite.Col[Status] = sqlite.Text(default="draft")
    currency: sqlite.Col[Currency] = sqlite.Text(default="USD")
    subtotal: sqlite.Col[native.CanonicalDecimal] = sqlite.Text()
    tax: sqlite.Col[native.CanonicalDecimal] = sqlite.Text(default=Decimal(0))
    discount: sqlite.Col[native.CanonicalDecimal] = sqlite.Text(default=Decimal(0))
    external_id: sqlite.Col[UUID] = sqlite.Text(unique=True)
    receipt: sqlite.Col[bytes] = sqlite.Blob()
    metadata: sqlite.Col[Json[dict[str, str]]] = sqlite.Text()
    note: sqlite.Col[str | None] = sqlite.Text(default=None)
    region: sqlite.Col[str] = sqlite.Text(default="US")
    active: sqlite.Col[bool] = sqlite.Integer(default=True)
    retry_count: sqlite.Col[int] = sqlite.Integer(default=0)
    item_count: sqlite.Col[int] = sqlite.Integer()
    shipping_days: sqlite.Col[int | None] = sqlite.Integer(default=None)
    paid_at: sqlite.Col[native.UtcDatetime | None] = sqlite.Text(default=None)
    created_at: sqlite.Col[native.UtcDatetime | sqlite.Omitted] = sqlite.Text(
        default=native.CurrentTimestamp
    )
    revision: sqlite.Col[int | sqlite.Omitted] = sqlite.Integer(
        default=native.LiteralDefault(1)
    )

    def total(self) -> Decimal:
        return invoice_total(self)

    def is_paid(self) -> bool:
        return self.status == "paid"


class OrderRow(Order, sqlite.Row):
    table_name = "orders"
    order_id: sqlite.Col[OrderId]
    created_at: sqlite.Col[native.UtcDatetime]
    revision: sqlite.Col[int]

    def receipt_key(self) -> str:
        return f"{self.tenant_id}/{self.order_id}"


def sample_order() -> Order:
    """Fixed caller data makes the runnable comparisons reproducible."""
    return Order(
        tenant_id=TenantId(7),
        customer_email="ada@example.com",
        subtotal=Decimal("12.50"),
        tax=Decimal("2.50"),
        external_id=UUID(int=7),
        receipt=b"invoice",
        metadata={"channel": "web"},
        item_count=2,
    )


async def create_order(transaction: sqlite.Transaction) -> OrderRow:
    return await transaction.execute(sqlite.insert(sample_order()).returning())


# Evolution probes edit this actual declaration and its caller, independently:
# add cancellation_reason; str -> EmailAddress; draft -> queued default.
# See evolution.json for successful edits and deliberately stale refinements.


# 08. Models with behavior
def invoice_total(order: Order) -> Decimal:
    """Shared implementation; rows inherit these available input values."""
    return order.subtotal + order.tax - order.discount


def order_summary(order: OrderRow) -> tuple[str, str, bool]:
    return order.receipt_key(), str(order.total()), order.is_paid()


# Order defines total/is_paid once; OrderRow inherits them.
# receipt_key exists only on OrderRow.


# 09. Backend-specific fields and operators


class Product(mariadb.Model):
    __row__: ClassVar[type[ProductRow]]
    product_id: mariadb.Col[int | mariadb.Omitted] = mariadb.Integer(
        primary_key=True, auto_increment=True, default=mariadb.OMIT
    )
    price: mariadb.Col[Decimal] = mariadb.Decimal(12, 2, unique=True)
    code: mariadb.Col[str] = mariadb.Text(
        length=32, unique=True, collation="utf8mb4_bin"
    )
    token: mariadb.Col[UUID] = mariadb.Uuid()
    created_at: mariadb.Col[native_maria.UtcDatetime | mariadb.Omitted] = (
        mariadb.DateTime(default=native_maria.CurrentTimestamp)
    )
    payload: mariadb.JsonCol[dict[str, int]] = mariadb.Json()
    active: mariadb.Col[bool] = mariadb.Boolean(default=True)
    description: mariadb.Col[str] = mariadb.LongText()
    image: mariadb.Col[bytes] = mariadb.Blob()
    __indexes__ = (
        mariadb.Index(description, prefix_lengths=(16,), name="description_prefix"),
    )


class ProductRow(Product, mariadb.Row):
    table_name = "products"
    product_id: mariadb.Col[int]
    created_at: mariadb.Col[native_maria.UtcDatetime]


async def create_product(transaction: mariadb.Transaction) -> ProductRow:
    return await transaction.execute(
        mariadb.insert(
            Product(
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
        mariadb.select(ProductRow.payload.json_extract_int("$.answer")).all()
    )


class PriceReference(mariadb.Model):
    __row__: ClassVar[type[PriceReferenceRow]]
    amount: mariadb.FKCol[ProductRow, Decimal] = mariadb.ForeignKey(ProductRow.price)


class PriceReferenceRow(PriceReference, mariadb.Row):
    table_name = "price_references"


def decimal_fk_schema() -> str:
    """Existing adapter preserves the referenced Decimal precision."""
    return mariadb.scaffold(PriceReferenceRow)


# 10. Reusable application helpers

# This prototype's Write contract covers INSERT RETURNING, not every native verb.
type Write[Result] = Returning[Literal["sqlite"], Result]


def insert_generic[Read: sqlite.Row](pending: Paired[Read]) -> Write[Read]:
    return sqlite.insert(pending).returning()


async def execute_write[Result](
    transaction: sqlite.Transaction, command: Write[Result]
) -> Result:
    return await transaction.execute(command)


def users_query() -> Select[UserRow]:
    return sqlite.select(UserRow).all()


# insert_generic(Counter()) preserves CounterRow exactly.
# The old native Model[State, Result] helper cannot accept these input classes.


# 11. Editing existing data


class ProfilePatch(TypedDict, total=False):
    """Omitted means preserve; None means SQL NULL. Not an insert contract."""

    display_name: str | None


async def patch_user(
    transaction: sqlite.Transaction, user_id: UserId, changes: ProfilePatch
) -> UserRow | None:
    if "display_name" in changes:
        # Explicit adapter gap: field-name strings are not checked assignments.
        await native_update(
            transaction,
            UserRow,
            values={"display_name": changes["display_name"]},
            key=("user_id", user_id),
        )
    return await fetch_user(transaction, user_id)


async def save_settings(
    transaction: sqlite.Transaction, user_id: int, timezone: str
) -> SettingsRow:
    return await transaction.execute(
        sqlite.insert(Settings(user_id=user_id, timezone=timezone, nickname=None))
        .on_conflict(
            SettingsRow.user_id,
            action=sqlite.DoUpdate(SettingsRow.timezone.to_inserted()),
        )
        .returning()
    )


# Existing digest_hour 18 remains 18; a fresh insert gets SQL default 9.
# Updating digest_hour.to_inserted() too would reset 18 to the attempted default 9.


# 12. Reading and navigating unfamiliar code
def receipt_destination(order: OrderRow) -> str:
    """OrderRow holds refinements; inherited customer_email leads to storage on Order."""
    return order.customer_email


# Complete values use OrderRow. Input annotations use Order.
# Navigation requests and declaration-only lint run independently in navigation.py
# and evidence.py. No quoted result base, future import, or unused-import allowance.
