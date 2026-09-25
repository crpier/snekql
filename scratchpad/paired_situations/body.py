"""Class-body result situations. Compare numbered sections with nested.py and dual.py.

Witness-only declaration change: native constructors and execution are untouched.
Counterexamples remain intentional. See README.md for evidence.
"""

from dataclasses import dataclass
from decimal import Decimal
from typing import Any, ClassVar, Literal, NewType, TypedDict
from uuid import UUID

from pydantic import Json
from snekql import mariadb, sqlite
from snekql.query import InsertableModel
from snekql.sqlite import Fetched, Pending

from scratchpad.class_body_usage.sqlite import Model, ReadType
from scratchpad.paired_situations.body_maria import Model as MariaModel

# 01. The smallest useful model
UserId = NewType("UserId", int)


class User[State = Pending](Model[State]):
    __read_type__: ClassVar[ReadType[User[Fetched]]]
    __tablename__ = "users"
    user_id: sqlite.GenCol[UserId] = sqlite.Integer(
        primary_key=True, auto_increment=True, default=sqlite.PENDING_GENERATION
    )
    email: sqlite.Col[str] = sqlite.Text(unique=True)
    display_name: sqlite.Col[str | None] = sqlite.Text(default=None)


@dataclass(frozen=True)
class PublicUser:
    """Explicit response selection, not automatic storage-model serialization."""

    email: str
    user_id: int


def public_user(user: User[Fetched]) -> PublicUser:
    return PublicUser(email=user.email, user_id=user.user_id)


async def create_user(transaction: sqlite.Transaction, email: str) -> User[Fetched]:
    return await transaction.execute(sqlite.insert(User(email=email)).returning())


async def fetch_user(
    transaction: sqlite.Transaction, user_id: UserId
) -> User[Fetched] | None:
    return await transaction.fetch_one_or_none(
        sqlite.select(User).where(User.user_id.eq(user_id))
    )


# 02. Constructing complete values directly
OMITTED = sqlite.PENDING_GENERATION


class Counter[State = Pending](Model[State]):
    __read_type__: ClassVar[ReadType[Counter[Fetched]]]
    __tablename__ = "counters"
    counter_id: sqlite.GenCol[int] = sqlite.Integer(
        primary_key=True, auto_increment=True, default=sqlite.PENDING_GENERATION
    )
    count: sqlite.GenCol[int] = sqlite.Integer(default=sqlite.LiteralDefault(0))


def complete_counter(counter_id: int, count: int) -> Counter[Fetched]:
    return Counter[Fetched](counter_id=counter_id, count=count)


def pending_counter() -> Counter[Pending]:
    return Counter()


# Counter[Fetched](count=3): accepted, but counter_id is PENDING_GENERATION.
# Counter[Fetched](counter_id=42): count is also PENDING_GENERATION, not zero.
# Counter[Fetched].construct(...) retains the native unchecked-construction hole.
# The result witness does not harden constructors.


# 03. Defaults, NULL, and omission
class Settings[State = Pending](Model[State]):
    __read_type__: ClassVar[ReadType[Settings[Fetched]]]
    __tablename__ = "settings"
    user_id: sqlite.Col[int] = sqlite.Integer(primary_key=True)
    timezone: sqlite.Col[str] = sqlite.Text()
    nickname: sqlite.Col[str | None] = sqlite.Text()
    enabled: sqlite.Col[bool] = sqlite.Integer(default=True)
    note: sqlite.Col[str | None] = sqlite.Text(default=None)
    digest_hour: sqlite.GenCol[int] = sqlite.Integer(default=sqlite.LiteralDefault(9))
    locale: sqlite.GenCol[str | None] = sqlite.Text(default=sqlite.LiteralDefault(None))
    created_at: sqlite.GenCol[sqlite.UtcDatetime] = sqlite.Text(
        default=sqlite.CurrentTimestamp
    )


async def create_settings(
    transaction: sqlite.Transaction, user_id: int, timezone: str, nickname: str | None
) -> Settings[Fetched]:
    return await transaction.execute(
        sqlite.insert(
            Settings(user_id=user_id, timezone=timezone, nickname=nickname)
        ).returning()
    )


# nickname is nullable AND required. note has a Python default of None.
# locale omitted means SQL supplies NULL; explicit None is also permitted.
# Settings[Fetched](...) applies Python defaults but can retain generated sentinels.


def nullable_datetime_default() -> str:
    """The original last_seen case rejects at declaration; locale isolates SQL NULL."""

    class LastSeen[State = Pending](Model[State]):
        __read_type__: ClassVar[ReadType[LastSeen[Fetched]]]
        __tablename__ = "last_seen"
        last_seen: sqlite.GenCol[sqlite.UtcDatetime | None] = sqlite.Text(
            default=sqlite.LiteralDefault(None)
        )

    return sqlite.scaffold([LastSeen])


# 04. Ordinary foreign keys
PostId = NewType("PostId", int)


class Post[State = Pending](Model[State]):
    __read_type__: ClassVar[ReadType[Post[Fetched]]]
    __tablename__ = "posts"
    post_id: sqlite.GenCol[PostId] = sqlite.Integer(
        primary_key=True, auto_increment=True, default=sqlite.PENDING_GENERATION
    )
    author_id: sqlite.FKCol[User, UserId] = sqlite.ForeignKey(User.user_id)
    title: sqlite.Col[str] = sqlite.Text()


async def create_post(
    transaction: sqlite.Transaction, author_id: UserId, title: str
) -> Post[Fetched]:
    return await transaction.execute(
        sqlite.insert(Post(author_id=author_id, title=title)).returning()
    )


async def author_emails(transaction: sqlite.Transaction) -> list[str]:
    return await transaction.fetch_all(
        sqlite.select(User.email)
        .join(Post, on=Post.author_id.references(User.user_id))
        .all()
    )


# Post(author_id=PostId(1), title="Wrong ID"): static rejection.
# The FK owner uses User, while fetched application results use User[Fetched].


# 05. Self-referencing foreign keys
class Comment[State = Pending](Model[State]):
    __read_type__: ClassVar[ReadType[Comment[Fetched]]]
    __tablename__ = "comments"
    comment_id: sqlite.Col[int] = sqlite.Integer(primary_key=True)
    parent_id: sqlite.FKCol[Comment, int | None] = sqlite.ForeignKey(
        lambda: Comment.comment_id, default=None, on_delete="SET NULL"
    )
    body: sqlite.Col[str] = sqlite.Text()


async def create_comment(
    transaction: sqlite.Transaction, comment_id: int, parent_id: int | None, body: str
) -> Comment[Fetched]:
    return await transaction.execute(
        sqlite.insert(
            Comment(comment_id=comment_id, parent_id=parent_id, body=body)
        ).returning()
    )


async def delete_comment(transaction: sqlite.Transaction, comment_id: int) -> None:
    await transaction.execute(
        sqlite.delete(Comment).where(Comment.comment_id.eq(comment_id))
    )


def local_comment_schema() -> str:
    """A self target also resolves when the model is local to a function."""

    class LocalComment[State = Pending](Model[State]):
        __read_type__: ClassVar[ReadType[LocalComment[Fetched]]]
        __tablename__ = "local_comments"
        comment_id: sqlite.Col[int] = sqlite.Integer(primary_key=True)
        parent_id: sqlite.FKCol[LocalComment, int | None] = sqlite.ForeignKey(
            lambda: LocalComment.comment_id, default=None
        )

    return sqlite.scaffold([LocalComment])


# 06. Mutually referencing models
async def mutual_foreign_keys() -> list[int | None]:
    """Intentionally fails at Department declaration with this native FKCol spelling.

    The rest shows the requested caller, not a claim it executed. No alternative
    table-level constraint or Any annotation is substituted to hide the failure.
    """

    class Department[State = Pending](Model[State]):
        __read_type__: ClassVar[ReadType[Department[Fetched]]]
        __tablename__ = "departments"
        department_id: sqlite.Col[int] = sqlite.Integer(primary_key=True)
        manager_id: sqlite.FKCol[Employee, int | None] = sqlite.ForeignKey(
            lambda: Employee.employee_id, default=None, on_update="CASCADE"
        )

    department = Department(department_id=1)

    class Employee[State = Pending](Model[State]):
        __read_type__: ClassVar[ReadType[Employee[Fetched]]]
        __tablename__ = "employees"
        employee_id: sqlite.Col[int] = sqlite.Integer(primary_key=True)
        department_id: sqlite.FKCol[Department, int] = sqlite.ForeignKey(
            Department.department_id
        )

    async with await sqlite.Database.initialize(database=":memory:") as database:
        await database.migrate({"001": sqlite.scaffold([Department, Employee])})
        async with database.transaction() as transaction:
            await transaction.execute(sqlite.insert(department))
            await transaction.execute(
                sqlite.insert(Employee(employee_id=2, department_id=1))
            )
            await transaction.execute(
                sqlite.update(Department).set(Department.manager_id.to(2)).all()
            )
            await transaction.execute(
                sqlite.update(Employee).set(Employee.employee_id.to(20)).all()
            )
        async with database.transaction() as transaction:
            return await transaction.fetch_all(
                sqlite.select(Department.manager_id).all()
            )


# 07. A large model undergoing a change

OrderId = NewType("OrderId", int)
TenantId = NewType("TenantId", int)
type Status = Literal["draft", "paid", "cancelled"]
type Currency = Literal["USD", "EUR"]


class Order[State = Pending](Model[State]):
    __read_type__: ClassVar[ReadType[Order[Fetched]]]
    __tablename__ = "orders"
    order_id: sqlite.GenCol[OrderId] = sqlite.Integer(
        primary_key=True, auto_increment=True, default=sqlite.PENDING_GENERATION
    )
    tenant_id: sqlite.Col[TenantId] = sqlite.Integer()
    customer_email: sqlite.Col[str] = sqlite.Text()
    status: sqlite.Col[Status] = sqlite.Text(default="draft")
    currency: sqlite.Col[Currency] = sqlite.Text(default="USD")
    subtotal: sqlite.Col[sqlite.CanonicalDecimal] = sqlite.Text()
    tax: sqlite.Col[sqlite.CanonicalDecimal] = sqlite.Text(default=Decimal(0))
    discount: sqlite.Col[sqlite.CanonicalDecimal] = sqlite.Text(default=Decimal(0))
    external_id: sqlite.Col[UUID] = sqlite.Text(unique=True)
    receipt: sqlite.Col[bytes] = sqlite.Blob()
    metadata: sqlite.Col[Json[dict[str, str]]] = sqlite.Text()
    note: sqlite.Col[str | None] = sqlite.Text(default=None)
    region: sqlite.Col[str] = sqlite.Text(default="US")
    active: sqlite.Col[bool] = sqlite.Integer(default=True)
    retry_count: sqlite.Col[int] = sqlite.Integer(default=0)
    item_count: sqlite.Col[int] = sqlite.Integer()
    shipping_days: sqlite.Col[int | None] = sqlite.Integer(default=None)
    paid_at: sqlite.Col[sqlite.UtcDatetime | None] = sqlite.Text(default=None)
    created_at: sqlite.GenCol[sqlite.UtcDatetime] = sqlite.Text(
        default=sqlite.CurrentTimestamp
    )
    revision: sqlite.GenCol[int] = sqlite.Integer(default=sqlite.LiteralDefault(1))

    def total(self: Order[Pending] | Order[Fetched]) -> Decimal:
        return invoice_total(self)

    def is_paid(self: Order[Pending] | Order[Fetched]) -> bool:
        return self.status == "paid"

    def receipt_key(self: Order[Fetched]) -> str:
        return f"{self.tenant_id}/{self.order_id}"


def sample_order() -> Order[Pending]:
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


async def create_order(transaction: sqlite.Transaction) -> Order[Fetched]:
    return await transaction.execute(sqlite.insert(sample_order()).returning())


# Evolution probes edit this actual declaration and its caller, independently:
# add cancellation_reason; str -> EmailAddress; draft -> queued default.
# See evolution.json for successful edits and deliberately stale contracts.


# 08. Models with behavior
def invoice_total(order: Order[Pending] | Order[Fetched]) -> Decimal:
    """Shared implementation; the two concrete contracts both supply these values."""
    return order.subtotal + order.tax - order.discount


def order_summary(order: Order[Fetched]) -> tuple[str, str, bool]:
    return order.receipt_key(), str(order.total()), order.is_paid()


# Shared method definitions are beside their fields in section 07.
# Pending may call total/is_paid, but must not call receipt_key.


# 09. Backend-specific fields and operators


class Product[State = Pending](MariaModel[State]):
    __read_type__: ClassVar[ReadType[Product[Fetched]]]
    __tablename__ = "products"
    product_id: mariadb.GenCol[int] = mariadb.Integer(
        primary_key=True, auto_increment=True, default=mariadb.PENDING_GENERATION
    )
    price: mariadb.Col[Decimal] = mariadb.Decimal(12, 2, unique=True)
    code: mariadb.Col[str] = mariadb.Text(
        length=32, unique=True, collation="utf8mb4_bin"
    )
    token: mariadb.Col[UUID] = mariadb.Uuid()
    created_at: mariadb.GenCol[mariadb.UtcDatetime] = mariadb.DateTime(
        default=mariadb.CurrentTimestamp
    )
    payload: mariadb.JsonCol[dict[str, int]] = mariadb.Json()
    active: mariadb.Col[bool] = mariadb.Boolean(default=True)
    description: mariadb.Col[str] = mariadb.LongText()
    image: mariadb.Col[bytes] = mariadb.Blob()
    __indexes__: ClassVar = [
        mariadb.Index(description, prefix_lengths=(16,), name="description_prefix")
    ]


async def create_product(transaction: mariadb.Transaction) -> Product[Fetched]:
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
        mariadb.select(Product.payload.json_extract_int("$.answer")).all()
    )


def decimal_fk_schema() -> str:
    """Native precision-metadata failure is retained, not repaired by the witness."""

    class PriceReference[State = Pending](MariaModel[State]):
        __read_type__: ClassVar[ReadType[PriceReference[Fetched]]]
        __tablename__ = "price_references"
        amount: mariadb.FKCol[Product, Decimal] = mariadb.ForeignKey(Product.price)

    return mariadb.scaffold([Product, PriceReference])


# 10. Reusable application helpers


def insert_generic[Read: sqlite.Model[Any, Any]](
    pending: sqlite.Model[Pending, Read],
) -> sqlite.Write[Read]:
    """Existing helper: this witness-only base erases Read to Any."""
    return sqlite.insert(pending).returning()


def insert_via_protocol[Owner: sqlite.Model[Any, Any], Read: sqlite.Model[Any, Any]](
    pending: InsertableModel[Literal["sqlite"], Owner, Read],
) -> sqlite.Write[Read]:
    """Result-aware alternative; this protocol lives in the native query module."""
    return sqlite.insert(pending).returning()


async def execute_write[Result](
    transaction: sqlite.Transaction, command: sqlite.Write[Result]
) -> Result:
    return await transaction.execute(command)


def users_query() -> sqlite.Select[User[Fetched]]:
    return sqlite.select(User).all()


# insert_generic(Counter()) yields Any after execution, despite the runtime Counter.
# execute_write(transaction, sqlite.insert(Counter()).returning()) stays exact.
# insert_via_protocol uses native InsertableModel instead of the erased base.
# It stays exact, but requires changing existing nominal-helper annotations.


# 11. Editing existing data


class ProfilePatch(TypedDict, total=False):
    """Omitted means preserve; None means SQL NULL. Not an insert contract."""

    display_name: str | None


async def patch_user(
    transaction: sqlite.Transaction, user_id: UserId, changes: ProfilePatch
) -> User[Fetched] | None:
    if "display_name" in changes:
        users = await transaction.execute(
            sqlite.update(User)
            .set(User.display_name.to(changes["display_name"]))
            .where(User.user_id.eq(user_id))
            .returning()
        )
        return users[0] if users else None
    return await fetch_user(transaction, user_id)


async def save_settings(
    transaction: sqlite.Transaction, user_id: int, timezone: str
) -> Settings[Fetched]:
    return await transaction.execute(
        sqlite.insert(Settings(user_id=user_id, timezone=timezone, nickname=None))
        .on_conflict(
            Settings.user_id, action=sqlite.DoUpdate(Settings.timezone.to_inserted())
        )
        .returning()
    )


# Existing digest_hour 18 remains 18; a fresh insert gets SQL default 9.
# Updating digest_hour.to_inserted() too would reset 18 to the attempted default 9.


# 12. Reading and navigating unfamiliar code
def receipt_destination(order: Order[Fetched]) -> str:
    """Follow Order or customer_email to the authoritative storage declaration."""
    return order.customer_email


# Complete values name Fetched. Bare Order is the default Pending specialization.
# Navigation requests and declaration-only lint run independently in navigation.py
# and evidence.py. No quoted result base, future import, or unused-import allowance.
