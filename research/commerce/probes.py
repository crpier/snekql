"""SQL observations tied to commerce requirements, not a library oracle."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Probe:
    """Isolated mutation and optional raw readback with a stated business question."""

    name: str
    question: str
    statements: tuple[str, ...]
    query: str | None = None


PROBES = (
    Probe(
        "price_order",
        "Are exact decimal representations numerically sortable?",
        ("INSERT INTO products (price) VALUES ('2'),('10')",),
        "SELECT price FROM products ORDER BY price",
    ),
    Probe(
        "price_scale",
        "Does the database reject rather than round extra fractional digits?",
        ("INSERT INTO products (price) VALUES ('1.239')",),
        "SELECT price FROM products",
    ),
    Probe(
        "price_overflow",
        "Does DECIMAL(10,2)'s upper bound exist in installed storage?",
        ("INSERT INTO products (price) VALUES ('100000000.00')",),
        "SELECT price FROM products",
    ),
    Probe(
        "price_negative",
        "Does application nonnegativity reach the DDL?",
        ("INSERT INTO products (price) VALUES ('-1.00')",),
        "SELECT price FROM products",
    ),
    Probe(
        "price_invalid",
        "Can another SQL writer store nonnumeric money?",
        ("INSERT INTO products (price) VALUES ('banana')",),
        "SELECT price FROM products",
    ),
    Probe(
        "decimal_sum",
        "Is database arithmetic exact for 0.1 plus 0.2?",
        ("INSERT INTO products (price) VALUES ('0.1'),('0.2')",),
        "SELECT SUM(price), SUM(price) = 0.3 FROM products",
    ),
    Probe(
        "cents_sum",
        "Does integer-cent storage give exact arithmetic?",
        ("INSERT INTO cent_products (price_cents) VALUES (10),(20)",),
        "SELECT SUM(price_cents), SUM(price_cents) = 30 FROM cent_products",
    ),
    Probe(
        "cents_order",
        "Are integer-cent values numerically sortable?",
        ("INSERT INTO cent_products (price_cents) VALUES (200),(1000)",),
        "SELECT price_cents FROM cent_products ORDER BY price_cents",
    ),
    Probe(
        "cents_fraction",
        "Will fractional cents be rejected or coerced?",
        ("INSERT INTO cent_products (price_cents) VALUES (1.5)",),
        "SELECT price_cents FROM cent_products",
    ),
    Probe(
        "quantity_zero",
        "Does positive-quantity annotation constrain other writers?",
        ("INSERT INTO orders (quantity,status) VALUES (0,'pending')",),
        "SELECT quantity FROM orders",
    ),
    Probe(
        "timestamp_default",
        "Does omitting creation time get a database value, and in what format?",
        ("INSERT INTO orders (quantity,status) VALUES (1,'pending')",),
        "SELECT created_at FROM orders",
    ),
    Probe(
        "timestamp_null",
        "Does explicit NULL incorrectly invoke a default?",
        ("INSERT INTO orders (quantity,status,created_at) VALUES (1,'pending',NULL)",),
        "SELECT created_at FROM orders",
    ),
    Probe(
        "timestamp_precision",
        "What happens to six fractional digits from a raw SQL writer?",
        (
            "INSERT INTO orders (quantity,status,created_at) VALUES (1,'pending','2026-01-02 03:04:05.123456')",
        ),
        "SELECT created_at FROM orders",
    ),
    Probe(
        "timestamp_invalid",
        "Does physical storage validate a timestamp?",
        (
            "INSERT INTO orders (quantity,status,created_at) VALUES (1,'pending','not-a-date')",
        ),
        "SELECT created_at FROM orders",
    ),
    Probe(
        "timestamp_update",
        "Does an ordinary update leave creation time alone?",
        (
            "INSERT INTO orders (quantity,status,created_at) VALUES (1,'pending','2026-01-02 03:04:05')",
            "UPDATE orders SET status='paid'",
        ),
        "SELECT created_at FROM orders",
    ),
    Probe(
        "status_default",
        "Does a Python default fill omitted status in raw SQL?",
        ("INSERT INTO orders (quantity) VALUES (1)",),
        "SELECT status FROM orders",
    ),
)
