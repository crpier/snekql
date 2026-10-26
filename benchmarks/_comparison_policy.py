"""Declared policy shared by comparison planning and native verification."""

POLICY = {
    "autocommit": 0,
    "read_only": 0,
    "charset": "utf8mb4",
    "isolation": "REPEATABLE-READ",
    "sql_mode": "STRICT_ALL_TABLES,NO_ENGINE_SUBSTITUTION,NO_ZERO_DATE,NO_ZERO_IN_DATE,ERROR_FOR_DIVISION_BY_ZERO",
    "time_zone": "+00:00",
    "foreign_key_checks": 1,
    "check_constraint_checks": 1,
    "unique_checks": 1,
    "transport": "tcp-loopback",
}
