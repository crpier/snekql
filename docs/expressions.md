# Calculate values in SQL

Use expressions when the database should calculate a value rather than sending
it to Python first. A stock decrement, for example, can check availability and
update the quantity in one statement.

Start with [basic queries](queries.md). These operations work on supported native
numeric and text columns; a number stored as JSON or arbitrary text is not the
same thing.

## Arithmetic and atomic updates

Use `.add(...)`, `.sub(...)`, and `.mul(...)` for database arithmetic. Each
argument can be a number or another compatible column or expression from the
same query source, including an alias. Literal values become bound parameters.
You can select the calculated value or use it in a WHERE or ON condition.

`.to_expr(...)` assigns the computed value inside UPDATE. `.to(...)` retains its
existing Python-literal validation:

```python
from typing import ClassVar

from snekql import sqlite


class Inventory[State = sqlite.Pending](sqlite.Model[State]):
    __row_type__: ClassVar[sqlite.ReadType[Inventory[sqlite.Row]]]
    id: sqlite.Col[int] = sqlite.Integer(primary_key=True)
    quantity: sqlite.Col[int] = sqlite.Integer()
    version: sqlite.Col[int] = sqlite.Integer()


async def reserve_stock(
    database: sqlite.Database,
    *,
    item_id: int,
    amount: int,
    expected_version: int,
) -> int:
    query = (
        sqlite.update(Inventory)
        .set(
            Inventory.quantity.to_expr(Inventory.quantity.sub(amount)),
            Inventory.version.to_expr(Inventory.version.add(1)),
        )
        .where(
            Inventory.id.eq(item_id)
            & Inventory.quantity.gte(amount)
            & Inventory.version.eq(expected_version)
        )
    )
    async with database.transaction() as tx:
        return await tx.execute(query)
```

A result of `1` means the row had enough stock and the expected version. A result
of `0` means it did not, or the row was absent.


Validate application inputs such as a positive purchase amount separately. The
stock check, decrement, and version increment execute in one statement, without
an application-side read/modify/write. A stale version or insufficient stock
changes no rows.

Before using these expressions, check their limits:

- `int` requires native INTEGER storage; `float` requires native REAL storage.
  Text-encoded numbers, bool, Decimal, durations, and custom numeric types are
  rejected. Division and mixed integer/real column expressions are unsupported.
- Integer literals must fit signed 64 bits. Floating literals must be finite.
  Float expressions also accept integer literals, matching Python's float
  annotations. Boolean literals are rejected at runtime.
- Either nullable operand makes the result nullable. A literal `None` is SQL
  NULL, not zero. Assignments require matching numeric domains. A non-null
  expression may target nullable storage, but not the reverse.
- Arithmetic follows backend numeric behavior, not Python unlimited integers.
  SQLite may promote overflowing integer arithmetic to REAL; integer projection
  decoding rejects that result rather than truncating it. MariaDB integer
  overflow remains an execution error. Floating arithmetic uses backend
  precision and overflow behavior.
- Computed writes use database constraints, not Python field validators. Final
  storage validation cannot detect every overflowed or rounded intermediate
  expression. Guard operand ranges when exact integer arithmetic is required.
- Compilation rejects an expression reading another column assigned by the same
  UPDATE, even inside nested arithmetic. This avoids MariaDB's assignment-order
  behavior differing from SQLite. Independent stock/version updates are valid.
- Expression assignments currently support UPDATE only, not `DoUpdate` conflict
  actions. Aliases remain query-only, not mutation targets.

## COALESCE and text functions

Use `.coalesce(fallback)` to replace SQL NULL, `.lower()` to lowercase text, and
`.char_length()` to count characters. A fallback can be a compatible value or
another column or expression from the same query source. If both choices can be
NULL, the result can still be NULL.

```python
from snekql.sqlite import select, update


class Profile[State = sqlite.Pending](sqlite.Model[State]):
    __row_type__: ClassVar[sqlite.ReadType[Profile[sqlite.Row]]]
    id: sqlite.Col[int] = sqlite.Integer(primary_key=True)
    nickname: sqlite.Col[str | None] = sqlite.Text()
    score: sqlite.Col[int] = sqlite.Integer()


select(Profile.nickname.coalesce("anonymous").lower())  # str
select(Profile.nickname.char_length())  # int | None for nullable nickname
select(Profile.nickname.char_length().coalesce(0).add(1))  # int

update(Profile).set(
    Profile.nickname.to_expr(Profile.nickname.coalesce("anonymous").lower()),
).where(Profile.id.eq(7))
```

`lower()` preserves text nullability. `char_length()` returns `int` or
`int | None`. Both require native text storage, not JSON-encoded strings or
text-encoded non-string values. Text `.to_expr()` assignments follow the same
ownership, nullability, dependency, and database-validation rules as numeric
assignments. Grouped projections must group every column read by an expression.

These functions retain backend behavior. SQLite renders `LENGTH`, which counts
characters only up to the first NUL; MariaDB renders `CHAR_LENGTH`, which counts
all characters, not bytes. SQLite's built-in `LOWER` handles ASCII casing;
MariaDB casing depends on its character set and collation. Neither function
promises Python string semantics or identical Unicode casing across backends.

For floating COALESCE expressions, integer literal fallbacks are bound as floats
so a missing input still produces the promised float result. Integer and float
column/expression operands remain distinct. No caller-supplied function names
or result-type assertions are accepted.

## CASE expressions

Use `case(condition, then=..., otherwise=...)` to choose a value inside SQL.
For example, label a score as gold or standard:

```python
from snekql.sqlite import case, select

select(case(Profile.score.gte(100), then="gold", otherwise="standard"))
select(
    case(Profile.score.gte(100), then=Profile.nickname, otherwise=None)
    .coalesce("anonymous")
    .lower()
)
```

TRUE selects `then`; FALSE or SQL UNKNOWN selects `otherwise`. Branches accept
native integer, float, or text literals, columns, and expressions. They must
share a value domain and query source. Either nullable branch makes the result
nullable, even when the condition logically excludes NULL. Two literal NULL
branches are rejected because they do not identify a result domain. Integer
literals in a floating CASE are validated and bound as floats; integer and
floating column/expression branches cannot be mixed.

CASE results compose with arithmetic, COALESCE, text functions, comparisons,
and `.to_expr()` assignments. You can nest CASE expressions. The condition can
read plain columns and supported expressions from one query source, including
compound predicates. Subqueries, aggregates, and
multi-source conditions are excluded. Aliases retain their own source identity.

Grouping and UPDATE dependency checks include condition reads and both branches,
including nested expressions. A branch that would not execute for today's data
still counts as a dependency. Comparisons such as `.gt_col(expression)` preserve
bindings and check the right-hand expression against the current query scope.

Next: [named results](results.md) or [inspect the generated SQL](inspecting-queries.md).
[All guides](README.md)
