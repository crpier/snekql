"""Offline recorded-role authoring: explicit historical and desired declarations."""

from pathlib import Path
from typing import ClassVar

from snekql import mariadb, sqlite
from snekql.experimental import migrations as m


class SQLiteInitial[S = sqlite.Pending](sqlite.Model[S]):
    """Existing application contract."""

    __tablename__ = "accounts"
    __row_type__: ClassVar[sqlite.ReadType[SQLiteInitial[sqlite.Row]]]
    id: sqlite.Col[int] = sqlite.Integer(primary_key=True)
    is_admin: sqlite.Col[bool] = sqlite.Integer()


class SQLiteExpanded[S = sqlite.Pending](sqlite.Model[S]):
    """Intermediate schema while both representations exist."""

    __tablename__ = "accounts"
    __row_type__: ClassVar[sqlite.ReadType[SQLiteExpanded[sqlite.Row]]]
    id: sqlite.Col[int] = sqlite.Integer(primary_key=True)
    is_admin: sqlite.Col[bool] = sqlite.Integer()
    role: sqlite.Col[str | None] = sqlite.Text(nullable=True)


class SQLiteAccount[S = sqlite.Pending](sqlite.Model[S]):
    """Desired final contract, not the schema at every migration step."""

    __tablename__ = "accounts"
    __row_type__: ClassVar[sqlite.ReadType[SQLiteAccount[sqlite.Row]]]
    id: sqlite.Col[int] = sqlite.Integer(primary_key=True)
    role: sqlite.Col[str] = sqlite.Text()


class MariaDBInitial[S = mariadb.Pending](mariadb.Model[S]):
    """Existing application contract."""

    __tablename__ = "accounts"
    __row_type__: ClassVar[mariadb.ReadType[MariaDBInitial[mariadb.Row]]]
    id: mariadb.Col[int] = mariadb.Integer(primary_key=True)
    is_admin: mariadb.Col[bool] = mariadb.Integer()


class MariaDBExpanded[S = mariadb.Pending](mariadb.Model[S]):
    """Intermediate schema while both representations exist."""

    __tablename__ = "accounts"
    __row_type__: ClassVar[mariadb.ReadType[MariaDBExpanded[mariadb.Row]]]
    id: mariadb.Col[int] = mariadb.Integer(primary_key=True)
    is_admin: mariadb.Col[bool] = mariadb.Integer()
    role: mariadb.Col[str | None] = mariadb.Text(nullable=True)


class MariaDBAccount[S = mariadb.Pending](mariadb.Model[S]):
    """Desired final contract, not the schema at every migration step."""

    __tablename__ = "accounts"
    __row_type__: ClassVar[mariadb.ReadType[MariaDBAccount[mariadb.Row]]]
    id: mariadb.Col[int] = mariadb.Integer(primary_key=True)
    role: mariadb.Col[str] = mariadb.Text()


FIRST_SQLITE = m.compile(m.generate("001_accounts", [SQLiteInitial], backend="sqlite"))
FIRST_MARIADB = m.compile(
    m.generate("001_accounts", [MariaDBInitial], backend="mariadb")
)
EXPANDED_SQLITE = m.generate(
    "002_roles", [SQLiteExpanded], backend="sqlite", previous=FIRST_SQLITE
).then(m.Checkpoint(name="fill_roles"))
EXPANDED_MARIADB = m.generate(
    "002_roles", [MariaDBExpanded], backend="mariadb", previous=FIRST_MARIADB
).then(m.Checkpoint(name="fill_roles"))


def _write_once(path: Path, text: str) -> None:
    """Refuse to silently replace historical authoring inputs or frozen packages."""
    if path.exists():
        if path.read_text(encoding="utf-8") != text:
            msg = f"Historical input differs: {path}; review, do not overwrite"
            raise ValueError(msg)
        return
    with path.open("x", encoding="utf-8") as stream:
        stream.write(text)


def main() -> None:
    """Stage initial packages and real, importable intermediate typed bindings."""
    _write_once(Path("001_sqlite_accounts.json"), FIRST_SQLITE.dump())
    _write_once(Path("001_mariadb_accounts.json"), FIRST_MARIADB.dump())
    _write_once(
        Path("examples/recorded_sqlite_contract.py"),
        m.contract_source(EXPANDED_SQLITE, point="fill_roles", table="accounts"),
    )
    _write_once(
        Path("examples/recorded_mariadb_contract.py"),
        m.contract_source(EXPANDED_MARIADB, point="fill_roles", table="accounts"),
    )


if __name__ == "__main__":
    main()
