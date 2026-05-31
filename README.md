# snekql

snekql is a Python-only, async-first query builder and query runtime for SQLite `STRICT` tables. It is not an ORM.

## Current v1 API direction

```python
from datetime import datetime
from pathlib import Path

from snekql import (
    MISSING,
    CurrentTimestamp,
    Database,
    DateTime,
    Fetched,
    Integer,
    Model,
    Pending,
    Text,
    insert,
    select,
)

class User[S = Pending](Model[S, "User[Fetched]"]):
    id: User.GenCol[int] = Integer(primary_key=True, auto_increment=True, default=MISSING)
    email: User.Col[str] = Text(nullable=False)
    created_at: User.GenCol[datetime] = DateTime(
        server_default=CurrentTimestamp(),
        default=MISSING,
    )

async def main() -> None:
    db = await Database.initialize(
        database=Path("app.db"),
        models=[User],
        schema_policy="strict",
        pool_size=5,
        acquire_timeout=30.0,
    )
    try:
        async with db.transaction(timeout=5.0) as tx:
            await tx.execute(insert(User(email="alice@example.com")))
            user = await tx.fetch_one(select(User).where(User.email.eq("alice@example.com")))
    finally:
        await db.close()
```

## Locked design choices

- Query builder + query runtime, not an ORM.
- Async runtime only.
- SQLite v1 only; generated tables are always `STRICT`.
- No raw SQL API in v1.
- No joins in v1.
- Models are immutable value objects after construction/materialization.
- Fetched objects come from database reads; no public materialization helper in v1.
- `Database.initialize(...)` is the only public database construction path.
- `db.transaction(...)` is the only public transaction-starting API.
- `tx.fetch_all(...)`, `tx.fetch_one(...)`, and `tx.execute(...)` are the runtime methods.
- `tx.execute(...)` accepts write statements only and returns `None`.
- All snekql-originated raises use `SnekqlError` subclasses.

## SQLite storage classes

V1 storage classes:

- `Integer`
- `Real`
- `Text`
- `Blob`
- `Json`
- `Boolean`
- `DateTime`

No `Varchar` in v1. `Text` has no length option.

Logical encodings:

- `Json` stores JSON text.
- `Boolean` stores `0` / `1` in an `INTEGER` column.
- `DateTime` stores UTC text as `YYYY-MM-DDTHH:MM:SS.SSSZ`.
- `DateTime` accepts timezone-aware datetimes only, normalizes to UTC, and truncates to milliseconds.
- `CurrentTimestamp()` is the only v1 server default and is valid only on `DateTime` `GenCol` fields.

## Schema verification v1

Keep verification simple and deterministic:

1. Generate the expected SQLite `CREATE TABLE` SQL for each model.
2. Read the existing table SQL from SQLite metadata.
3. Normalize only formatting that snekql itself controls.
4. Treat mismatch as schema drift.

`strict` raises `SchemaVerificationError`; `warn` logs and continues.

## Validation

Pydantic integration should follow the obvious boundary:

- model construction validates/coerces pending values;
- fetched row materialization validates/coerces database values;
- JSON and DateTime decoding happen before final model validation;
- Pydantic/external validation errors are wrapped in `SnekqlError` subclasses.
