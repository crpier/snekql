"""snekql: an async typed query builder and runtime for SQLite and MariaDB.

snekql has no flat top-level API. Pick a backend namespace and import the whole
surface -- the dialect-neutral verbs and builders as well as the backend's
``Model`` base and column constructors -- from it::

    from snekql.sqlite import Model, Text, select
    from snekql.mariadb import Model, Json, select

This keeps SQLite-only and MariaDB-only symbols from colliding in one namespace
and stops auto-imports from landing on the wrong backend (see ADR 0004).
"""

from __future__ import annotations

import logging

from snekql import mariadb as mariadb
from snekql import sqlite as sqlite

# Library logging hygiene: attach a do-nothing handler to the package's
# top-level logger so snekql emits nothing unless the application configures
# logging. Apps silence or route every snekql submodule via this one logger
# (e.g. ``logging.getLogger("snekql").setLevel(...)``).
logging.getLogger("snekql").addHandler(logging.NullHandler())

__all__ = ["mariadb", "sqlite"]
