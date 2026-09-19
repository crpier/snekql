"""The controlled matrix, shared by reproduction and regression checks."""

from typing import Any


def configurations() -> list[tuple[str, dict[str, Any]]]:
    """Keep transaction-mode and snapshot-isolation sensitivity separate."""
    cases: list[tuple[str, dict[str, Any]]] = [
        ("sqlite/snekql", {"backend": "sqlite", "library": "snekql"}),
        ("sqlite/sqlalchemy-explicit", {"backend": "sqlite", "library": "sqlalchemy"}),
        (
            "sqlite/sqlalchemy-legacy",
            {"backend": "sqlite", "library": "sqlalchemy", "sqlite_begin": "legacy"},
        ),
    ]
    cases.extend(
        (
            f"mariadb/{library}-snapshot-{'on' if snapshot else 'off'}",
            {"backend": "mariadb", "library": library, "snapshot_isolation": snapshot},
        )
        for library in ("snekql", "sqlalchemy")
        for snapshot in (True, False)
    )
    return cases
