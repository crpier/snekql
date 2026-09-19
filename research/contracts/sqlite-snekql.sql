CREATE TABLE orders (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        price_cents INTEGER NOT NULL CHECK (price_cents BETWEEN 0 AND 9999999999),
        quantity INTEGER NOT NULL CHECK (quantity BETWEEN 1 AND 2147483647),
        status TEXT NOT NULL DEFAULT 'pending',
        created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
    ) STRICT;
