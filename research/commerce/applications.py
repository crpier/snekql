"""Construction and public encoder observations, separate from raw SQL guarantees."""

from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy.engine import Dialect

from research.commerce import mariadb_models, sqlalchemy_models, sqlite_models
from snekql.errors import ModelValidationError


def observe_construction(
    backend: str, library: str, track: str, dialect: Dialect
) -> dict[str, Any]:
    """Stop at the public encoder; this is not a full runtime/ORM round trip."""
    declarations = (
        (sqlite_models if backend == "sqlite" else mariadb_models).models()
        if library == "snekql"
        else sqlalchemy_models.models(backend, track)
    )
    cases = (
        ("price_valid", "products", "price", Decimal("1.2300")),
        ("price_extra_scale", "products", "price", Decimal("1.239")),
        ("price_overflow", "products", "price", Decimal("100000000.00")),
        ("price_negative", "products", "price", Decimal(-1)),
        ("price_invalid", "products", "price", "banana"),
        ("fractional_cents", "cent_products", "price_cents", Decimal("1.5")),
        ("quantity_zero", "orders", "quantity", 0),
        (
            "timestamp_offset",
            "orders",
            "created_at",
            datetime.fromisoformat("2026-01-02T08:34:05.123456+05:30"),
        ),
        # Deliberately naive input tests rejection, not an application recommendation.
        (
            "timestamp_naive",
            "orders",
            "created_at",
            datetime.fromisoformat("2026-01-02T03:04:05.123456"),
        ),
    )
    observations: dict[str, Any] = {}
    for name, table, field, supplied in cases:
        model = declarations[table]
        kwargs = {"quantity": 1} if table == "orders" else {}
        kwargs[field] = supplied
        outcome: dict[str, Any] = {
            "input": str(supplied),
            "input_type": type(supplied).__name__,
        }
        try:
            instance = model(**kwargs)
        except ModelValidationError as e:
            outcome.update(stage="construction", outcome="rejected", error=str(e))
        else:
            validated = getattr(instance, field)
            outcome.update(
                constructed=str(validated), constructed_type=type(validated).__name__
            )
            try:
                if library == "snekql":
                    encoded = getattr(model, field).encode(validated, backend=backend)
                else:
                    processor = (
                        model.__table__.c[field]
                        .type.dialect_impl(dialect)
                        .bind_processor(dialect)
                    )
                    encoded = processor(validated) if processor else validated
            except (ModelValidationError, ValueError, TypeError) as e:
                outcome.update(stage="encoding", outcome="rejected", error=str(e))
            else:
                outcome.update(
                    stage="encoding",
                    outcome="accepted",
                    encoded=str(encoded),
                    encoded_type=type(encoded).__name__,
                )
        observations[name] = outcome
    order = declarations["orders"](quantity=1)
    observations["unpersisted_defaults"] = {
        "status": str(order.status),
        "created_at": str(order.created_at),
        "created_at_type": type(order.created_at).__name__,
    }
    return observations
