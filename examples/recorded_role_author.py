"""Typed role backfills: review before freezing, check freshness without rewriting."""

import sys
from pathlib import Path

from examples.recorded_mariadb_contract import (
    CONTRACT_DIGEST as MARIADB_CONTRACT,
)
from examples.recorded_mariadb_contract import (
    Historical as MariaDBHistorical,
)
from examples.recorded_role_stage import (
    EXPANDED_MARIADB,
    EXPANDED_SQLITE,
    FIRST_MARIADB,
    FIRST_SQLITE,
    MariaDBAccount,
    SQLiteAccount,
)
from examples.recorded_sqlite_contract import (
    CONTRACT_DIGEST as SQLITE_CONTRACT,
)
from examples.recorded_sqlite_contract import (
    Historical as SQLiteHistorical,
)
from snekql import mariadb, sqlite
from snekql.experimental import migrations as m


def sqlite_route() -> m.Draft:
    """Initialize roles, classify administrators, then remove the old flag."""
    accounts = SQLiteHistorical
    return (
        EXPANDED_SQLITE.then(
            m.DataChange.from_query(
                sqlite.update(accounts).set(accounts.role.to("user")).all(),
                checkpoint="fill_roles",
                contract_digest=SQLITE_CONTRACT,
            ),
            m.DataChange.from_query(
                sqlite.update(accounts)
                .set(accounts.role.to("admin"))
                .where(accounts.is_admin.eq(value=True)),
                checkpoint="fill_roles",
                contract_digest=SQLITE_CONTRACT,
            ),
        )
        .advance(
            [SQLiteAccount],
            removals=(m.DropColumn(table_name="accounts", column_name="is_admin"),),
        )
        .then(m.Checkpoint(name="final"))
    )


def mariadb_route() -> m.Draft:
    """Author the same business intent with independent native historical bindings."""
    accounts = MariaDBHistorical
    return (
        EXPANDED_MARIADB.then(
            m.DataChange.from_query(
                mariadb.update(accounts).set(accounts.role.to("user")).all(),
                checkpoint="fill_roles",
                contract_digest=MARIADB_CONTRACT,
            ),
            m.DataChange.from_query(
                mariadb.update(accounts)
                .set(accounts.role.to("admin"))
                .where(accounts.is_admin.eq(value=True)),
                checkpoint="fill_roles",
                contract_digest=MARIADB_CONTRACT,
            ),
        )
        .advance(
            [MariaDBAccount],
            removals=(m.DropColumn(table_name="accounts", column_name="is_admin"),),
        )
        .then(m.Checkpoint(name="final"))
    )


def main() -> None:
    """Compile during initial authoring; --check never rewrites a frozen artifact."""
    if sys.argv[1:] == ["--check"]:
        for path, draft in (
            ("001_sqlite_accounts.json", FIRST_SQLITE.draft),
            ("001_mariadb_accounts.json", FIRST_MARIADB.draft),
            ("002_sqlite_roles.json", sqlite_route()),
            ("002_mariadb_roles.json", mariadb_route()),
        ):
            m.Package.load(Path(path).read_text(encoding="utf-8")).check(draft)
    elif not sys.argv[1:]:
        for path, route in (
            ("002_sqlite_roles.json", sqlite_route()),
            ("002_mariadb_roles.json", mariadb_route()),
        ):
            Path(path).write_text(m.compile(route).dump(), encoding="utf-8")
    else:
        msg = "Use no arguments to compile, or --check to verify freshness"
        raise ValueError(msg)


if __name__ == "__main__":
    main()
