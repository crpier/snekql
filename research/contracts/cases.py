"""Independent input examples for the agreed order contract."""

from datetime import datetime
from decimal import Decimal
from typing import Any


def application_cases() -> dict[str, dict[str, Any]]:
    """None is intentionally explicit; absent keys request generated defaults."""
    overrides = {
        "offset": {
            "created_at": datetime.fromisoformat("2026-01-02T08:34:05.123456+05:30")
        },
        "defaults": {},
        "upper_bounds": {"price_cents": 9999999999, "quantity": 2147483647},
        "zero_cents": {"price_cents": 0},
        "fractional_cents": {"price_cents": Decimal("1.5")},
        "float_cents": {"price_cents": 1.0},
        "bool_quantity": {"quantity": True},
        "string_quantity": {"quantity": "1"},
        "zero_quantity": {"quantity": 0},
        "negative_cents": {"price_cents": -1},
        "overflow_cents": {"price_cents": 10000000000},
        "overflow_quantity": {"quantity": 2147483648},
        # Intentionally naive to test the boundary refusal.
        "naive_timestamp": {
            "created_at": datetime.fromisoformat("2026-01-02T03:04:05")
        },
        "null_timestamp": {"created_at": None},
        "null_status": {"status": None},
    }

    cases = {
        name: {"price_cents": 123, "quantity": 1, **supplied}
        for name, supplied in overrides.items()
    }
    cases["missing_quantity"] = {"price_cents": 123}
    return cases
