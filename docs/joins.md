# Join tables and reuse queries

Joins are explicit. snekql does not load relationships when you access an
attribute, and a join does not require a declared foreign key.

These examples build queries without running them. Pass the final query to a
transaction's fetch method to read its results.

## Tables used below

```python
from typing import ClassVar

from snekql import sqlite


class User[State = sqlite.Pending](sqlite.Model[State]):
    __row_type__: ClassVar[sqlite.ReadType[User[sqlite.Row]]]
    id: sqlite.Col[int] = sqlite.Integer(primary_key=True)
    email: sqlite.Col[str] = sqlite.Text()
    manager_id: sqlite.Col[int | None] = sqlite.Integer()


class Order[State = sqlite.Pending](sqlite.Model[State]):
    __row_type__: ClassVar[sqlite.ReadType[Order[sqlite.Row]]]
    id: sqlite.Col[int] = sqlite.Integer(primary_key=True)
    user_id: sqlite.Col[int] = sqlite.Integer()
    amount: sqlite.Col[int] = sqlite.Integer()
    status: sqlite.Col[str] = sqlite.Text()
```

## Keep matching rows, or keep every left row

```python
matched = (
    sqlite.select(User)
    .join(
        Order,
        on=Order.user_id.eq_col(User.id),
    )
    .all()
)
# fetch_all: list[tuple[User[sqlite.Row], Order[sqlite.Row]]]

with_or_without_orders = (
    sqlite.select(User)
    .left_join(
        Order,
        on=Order.user_id.eq_col(User.id) & Order.status.ne("cancelled"),
    )
    .all()
)
# fetch_all: list[tuple[User[sqlite.Row], Order[sqlite.Row] | None]]
```

The inner join keeps only matching pairs. The left join keeps users even when
they have no qualifying order; the second tuple item is then `None`. A matched
row whose declared fields are all NULL is still a Row Model, not `None`. snekql
adds a private presence field when no declared non-null column can distinguish
the two cases.

Putting the status condition in ON is important here. Moving it into WHERE can
remove unmatched users. The database applies ordinary SQL join semantics.

Compare two columns with `.eq_col(...)`, `.gt_col(...)`, and the related methods.
Use `.eq(value)` and `.gt(value)` for Python values. Column comparisons retain
both source types so the checker can catch references to tables you have not
joined.

Each ON clause can reference the starting table, earlier joins, and the table
being added. It cannot reference a later join. Compilation also checks those
references. Some valid enclosing-table correlations inside nested JOIN ON need
a typing escape; see [typing limits](typing-compatibility.md#remaining-limits).

You still need `.all()` or `.where(...)` before execution. A projected inner join
keeps the selected columns' result types. Projected left joins are not supported;
use whole-model joins or a supported [named projection](results.md).

## Join a table to itself

Use an alias when the same table plays two roles:

```python
class ManagerRole:
    pass


manager = sqlite.alias(User, ManagerRole, name="manager")
query = (
    sqlite.select(User)
    .left_join(
        manager,
        on=User.manager_id.eq_col(manager.column(User.id)),
    )
    .all()
)
# fetch_all: list[tuple[User[sqlite.Row], User[sqlite.Row] | None]]
```

The marker class distinguishes the role for the type checker. `name` is the SQL
alias. `manager.column(User.email)` refers to the manager's email and keeps its
Python type and value conversion.

Pass an original column from the aliased model to `.column(...)`. A different
model's column, or another alias's column, is rejected.

Give each repeated role a distinct marker class and SQL name. Names must be ASCII
SQL identifiers and cannot collide, ignoring case, with another visible source.
That includes sources in an enclosing query, even when distinct model classes
name the same physical table. Reusing an alias in a separate query
is fine; using the same model/role pair twice in one query is not.

Aliases do not create tables. You cannot insert into, update, delete from, or
migrate an alias. Selecting an alias returns instances of the original model.

## Ask whether another row exists

```python
has_order = sqlite.select(User).where(
    sqlite.exists(
        sqlite.select(Order.id).where(Order.user_id.eq_col(User.id)),
    ),
)

no_order = sqlite.select(User).where(
    sqlite.not_exists(
        sqlite.select(Order.id).where(Order.user_id.eq_col(User.id)),
    ),
)
```

The inner query refers to the outer user's ID. This is a correlated subquery:
it answers the question for each outer row. A reference to a table in neither
the inner query nor an enclosing query fails compilation.

## Compare with another query's results

```python
large_orders = sqlite.select(Order.user_id).where(Order.amount.gt(100))
users_with_large_orders = sqlite.select(User).where(
    User.id.in_subquery(large_orders),
)
```

`in_subquery` and `not_in_subquery` require one selected column. `exists` and
`not_exists` can use a SELECT with any result shape.

For one value from a subquery, use `scalar`:

```python
order_totals = sqlite.select(
    User.id,
    sqlite.scalar(
        sqlite.select(Order.amount.sum()).where(Order.user_id.eq_col(User.id)),
    ),
).all()
```

`scalar` requires a single-column query. Its SQL must produce a suitable scalar
result; the wrapper does not turn an arbitrary multi-row query into one value.
Aggregate NULL behavior is preserved. No orders may mean a NULL sum, not zero.

For a larger reusable query with named output fields, use a [CTE](ctes.md).
[All guides](README.md)
